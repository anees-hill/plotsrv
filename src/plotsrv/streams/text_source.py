"""Mixed-text framing on the existing file lifecycle and ordered stream path."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import time
from uuid import uuid4

from .file_source import JsonlBatch, JsonlFollower, JsonlRecord
from .http_adapter import adapt_frame
from .models import (
    MAX_STREAM_BATCH_BYTES,
    MAX_STREAM_BATCH_RECORDS,
    stream_record_size,
    validate_stream_record,
)
from .text_framing import ReadBudget, TextFramer


def resolve_text_source(source: str | Path) -> Path:
    path = Path(source).expanduser().resolve(strict=False)
    if path.exists() and not path.is_file():
        raise ValueError("stream source must be a regular file")
    return path


class TextFollower(JsonlFollower):
    """Reuse descriptor handover, retry IDs, acknowledgement and close semantics.

    Only candidate construction differs from JSONL. At most one transport batch
    plus one bounded lookahead record is retained. Framer partial state contains
    offsets/times only, so truncation cannot splice old bytes onto a new source.
    """

    _resolve_source = staticmethod(resolve_text_source)

    def __init__(self, source, *, adapter: str = "uvicorn", **kwargs):
        if adapter not in ("uvicorn", "text"):
            raise ValueError("unsupported text adapter")
        if kwargs.get("on_batch") is None or kwargs.get("on_record") is not None:
            raise ValueError("text following requires an ordered batch callback")
        self.adapter = adapter
        self._framer = TextFramer()
        self._lookahead_record: JsonlRecord | None = None
        self._finalize_text = False
        self._text_budget = ReadBudget()
        super().__init__(source, **kwargs)
        if self.initial_offset and self._continuity_probe:
            self._framer.continuation = not self._continuity_probe[1].endswith(b"\n")

    def _reset_source_offsets(self) -> None:
        self._framer = TextFramer()
        self._lookahead_record = None
        super()._reset_source_offsets()

    def drain(self, **kwargs) -> bool:
        self._finalize_text = True
        try:
            return super().drain(**kwargs)
        finally:
            self._finalize_text = False

    def _deliver_candidate_batch(self, **kwargs) -> bool:
        self._text_budget = ReadBudget()
        return super()._deliver_candidate_batch(**kwargs)

    def _build_candidate_batch(self) -> JsonlBatch | None:
        active = self._active_source
        if active is None:
            return None
        with self._source_offset_lock:
            start = self._accounted_source_offset
        cursor = start
        records = []
        batch_bytes = 0
        while len(records) < MAX_STREAM_BATCH_RECORDS:
            record = self._lookahead_record
            if record is not None:
                self._lookahead_record = None
            else:
                frame, end = self._framer.read(
                    active.file,
                    cursor,
                    now=time.monotonic(),
                    budget=self._text_budget,
                    finalize=self._finalize_text or self._rotation_pending,
                )
                if frame is None:
                    if end > cursor:
                        # A previously emitted truncation notice accounts for
                        # these discarded suffix bytes; never retain the suffix.
                        cursor = end
                        continue
                    break
                observed = datetime.now(UTC)
                data = adapt_frame(frame, observed_at=observed, adapter=self.adapter)
                validate_stream_record(data)
                record = JsonlRecord(data, frame.start, frame.end, observed)
                if frame.partial and self._rotation_pending:
                    # Preserve the existing protocol's warning vocabulary; no
                    # server-side adapter or new text transport is required.
                    self._record_continuity_warning(
                        "The JSONL source changed during rotation; record continuity is uncertain."
                    )
            size = stream_record_size(record.data)
            if records and batch_bytes + size > MAX_STREAM_BATCH_BYTES:
                self._lookahead_record = record
                break
            records.append(record)
            batch_bytes += size
            cursor = record.source_end_offset
        if not records:
            if cursor > start:
                self._advance_accounted_source_offset(cursor)
            return None
        self.records_seen += len(records)
        return JsonlBatch(uuid4().hex, tuple(records), start, cursor)
