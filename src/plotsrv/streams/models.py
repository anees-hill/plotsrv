"""Versioned wire-model primitives for the dedicated stream protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from collections.abc import Sequence
from typing import Any


# v4 carries bounded, sanitised source-observation state alongside transport
# lifecycle messages. A receiver must not infer source continuity from a
# legacy producer that cannot report it.
STREAM_PROTOCOL_VERSION = 4
MAX_STREAM_JSON_NESTING = 100
MAX_STREAM_RECORD_BYTES = 64 * 1024
MAX_STREAM_BATCH_RECORDS = 100
MAX_STREAM_BATCH_BYTES = 512 * 1024
# Includes protocol metadata around a maximally-sized records payload.
MAX_STREAM_REQUEST_BYTES = 640 * 1024
SOURCE_TRANSITIONS = frozenset(
    ("unknown", "initial", "continuing", "replaced", "truncated", "missing", "appeared")
)
MAX_SOURCE_CONTINUITY_WARNING_CHARS = 256
MAX_SOURCE_HEALTH_COUNTER = (2**53) - 1
SOURCE_CONTINUITY_WARNINGS = frozenset(
    (
        "The JSONL source was truncated; record continuity is uncertain.",
        "The JSONL source was replaced; record continuity is uncertain.",
        "The JSONL source identity could not be verified during rotation; record continuity is uncertain.",
        "The JSONL source changed during rotation; record continuity is uncertain.",
        "The JSONL source changed near the observed offset; record continuity is uncertain.",
        "The JSONL source changed during observer start; record continuity is uncertain.",
    )
)


class StreamRecordValidationError(ValueError):
    """A record cannot safely cross the strict JSON stream boundary."""


class StreamBatchValidationError(StreamRecordValidationError):
    """A stream append exceeds an explicit record or batch resource bound."""


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """Bounded, browser-safe source-observation facts known to a producer."""

    source_available: bool | None = None
    source_transition: str = "unknown"
    continuity_warning: str | None = None


@dataclass(frozen=True, slots=True)
class SourceHealth:
    """Bounded source progress counters safe to show in the stream browser.

    These are observational producer telemetry, not server accounting.  The
    optional values keep a legacy or custom producer distinguishable from a
    source that has truthfully reported a zero backlog.
    """

    unread_source_bytes: int | None = None
    unacknowledged_source_bytes: int | None = None
    in_flight_records: int | None = None
    records_seen: int | None = None
    records_rejected: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        """Return only the fixed browser-facing telemetry schema."""
        return {
            "unread_source_bytes": self.unread_source_bytes,
            "unacknowledged_source_bytes": self.unacknowledged_source_bytes,
            "in_flight_records": self.in_flight_records,
            "records_seen": self.records_seen,
            "records_rejected": self.records_rejected,
        }


def validate_source_status(status: SourceStatus) -> None:
    """Keep browser-visible source state small and free of raw OS details."""
    if status.source_available is not None and not isinstance(status.source_available, bool):
        raise StreamRecordValidationError("source availability must be a boolean or null")
    if status.source_transition not in SOURCE_TRANSITIONS:
        raise StreamRecordValidationError("source transition is not supported")
    if status.continuity_warning is not None:
        if not isinstance(status.continuity_warning, str):
            raise StreamRecordValidationError("source continuity warning must be a string or null")
        if len(status.continuity_warning) > MAX_SOURCE_CONTINUITY_WARNING_CHARS:
            raise StreamRecordValidationError("source continuity warning is too long")
        if status.continuity_warning not in SOURCE_CONTINUITY_WARNINGS:
            raise StreamRecordValidationError("source continuity warning is not supported")


def validate_source_health(health: SourceHealth) -> None:
    """Keep producer telemetry finite, non-negative, and JS-safe."""
    for field_name, value in health.as_dict().items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise StreamRecordValidationError(
                f"source health {field_name} must be an integer or null"
            )
        if not 0 <= value <= MAX_SOURCE_HEALTH_COUNTER:
            raise StreamRecordValidationError(
                f"source health {field_name} is outside the supported range"
            )


def validate_stream_record(record: object) -> None:
    """Require a JSON object that FastAPI can safely return to the browser.

    The HTTP request decoder and Python's :mod:`json` module are deliberately
    permissive in a few places that Starlette's JSON response encoder is not:
    non-finite floats and escaped lone surrogates are the important examples.
    Validate iteratively so direct protocol callers cannot introduce a cyclic
    or excessively nested value that would later poison ``/stream/data``.
    """
    if type(record) is not dict:
        raise StreamRecordValidationError("stream records must be JSON objects")

    pending: list[tuple[object, int]] = [(record, 1)]
    seen_containers: set[int] = set()
    while pending:
        value, depth = pending.pop()
        if depth > MAX_STREAM_JSON_NESTING:
            raise StreamRecordValidationError(
                "stream records exceed the supported JSON nesting depth"
            )

        value_type = type(value)
        if value_type is dict:
            value_id = id(value)
            if value_id in seen_containers:
                raise StreamRecordValidationError(
                    "stream records must not contain shared or cyclic containers"
                )
            seen_containers.add(value_id)
            for key, nested_value in value.items():
                if type(key) is not str:
                    raise StreamRecordValidationError(
                        "stream record field names must be strings"
                    )
                _validate_stream_string(key)
                pending.append((nested_value, depth + 1))
            continue

        if value_type is list:
            value_id = id(value)
            if value_id in seen_containers:
                raise StreamRecordValidationError(
                    "stream records must not contain shared or cyclic containers"
                )
            seen_containers.add(value_id)
            pending.extend((item, depth + 1) for item in value)
            continue

        if value_type is str:
            _validate_stream_string(value)
            continue
        if value_type is float:
            if not math.isfinite(value):
                raise StreamRecordValidationError(
                    "stream record floats must be finite JSON numbers"
                )
            continue
        if value_type is int:
            # JSONResponse ultimately converts ints through ``str``. Python
            # intentionally limits that conversion for hostile huge integers,
            # so check it before the value can enter retained stream state.
            try:
                str(value)
            except ValueError as error:
                raise StreamRecordValidationError(
                    "stream record integer cannot be safely JSON-serialized"
                ) from error
            continue
        if value is None or value_type is bool:
            continue

        raise StreamRecordValidationError(
            "stream record values must be JSON strings, numbers, booleans, "
            "null, arrays, or objects"
        )


def _validate_stream_string(value: str) -> None:
    if any("\ud800" <= character <= "\udfff" for character in value):
        raise StreamRecordValidationError(
            "stream record strings must not contain lone Unicode surrogates"
        )


def stream_record_size(record: dict[str, Any]) -> int:
    """Return the canonical wire size of one already-validated record."""
    return len(_canonical_json(record))


def validate_stream_batch(records: Sequence[object]) -> None:
    """Validate bounded append contents before either client or server retains it."""
    record_count = len(records)
    if not 1 <= record_count <= MAX_STREAM_BATCH_RECORDS:
        raise StreamBatchValidationError(
            "stream batches must contain from 1 through "
            f"{MAX_STREAM_BATCH_RECORDS} records"
        )

    batch_bytes = 0
    for record in records:
        validate_stream_record(record)
        # The validator above establishes this cast without accepting a
        # dict subclass or a generic mapping as a wire record.
        assert type(record) is dict
        record_bytes = stream_record_size(record)
        if record_bytes > MAX_STREAM_RECORD_BYTES:
            raise StreamBatchValidationError(
                "stream record exceeds the "
                f"{MAX_STREAM_RECORD_BYTES}-byte wire limit"
            )
        batch_bytes += record_bytes
        if batch_bytes > MAX_STREAM_BATCH_BYTES:
            raise StreamBatchValidationError(
                "stream batch exceeds the "
                f"{MAX_STREAM_BATCH_BYTES}-byte wire limit"
            )


def stream_batch_fingerprint(records: Sequence[dict[str, Any]]) -> str:
    """Return a bounded canonical content fingerprint for idempotent retries."""
    return hashlib.sha256(_canonical_json(records)).hexdigest()


def _canonical_json(value: object) -> bytes:
    """Encode validated values once, consistently, and without non-JSON forms."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class StreamRegistration:
    """One producer's explicit ownership claim for a logical stream.

    ``view_id`` names the logical stream visible in the plotsrv catalogue.
    ``client_id`` identifies the producer client across the sessions it may
    create, while ``session_id`` identifies this one active ownership epoch.
    The pair is repeated on every batch so a batch cannot be attributed to a
    different producer merely by sharing its logical stream ID.
    """

    view_id: str
    label: str
    section: str
    client_id: str
    session_id: str
    protocol_version: int = STREAM_PROTOCOL_VERSION
    source_status: SourceStatus = field(default_factory=SourceStatus, compare=False)
    source_health: SourceHealth = field(default_factory=SourceHealth, compare=False)


@dataclass(frozen=True, slots=True)
class StreamAppend:
    """One ordered batch owned by a registered producer session.

    ``batch_id`` identifies a retryable source batch within the producer
    session, and ``batch_sequence`` orders those batches.  Browser-facing
    record sequences are assigned by the server after acceptance; producer
    batches never get to claim them.
    """

    view_id: str
    client_id: str
    session_id: str
    batch_id: str
    batch_sequence: int
    records: tuple[dict[str, Any], ...]
    protocol_version: int = STREAM_PROTOCOL_VERSION
    source_status: SourceStatus = field(default_factory=SourceStatus, compare=False)
    source_health: SourceHealth = field(default_factory=SourceHealth, compare=False)


@dataclass(frozen=True, slots=True)
class StreamHeartbeat:
    """A producer's bounded liveness observation for its active session.

    ``delivery_state`` is intentionally limited to what the producer knows:
    it is either currently delivering normally or retrying a transport
    operation.  It never asserts application-process exit state.  A pending
    delivery lets the server report an expired observer as incomplete instead
    of implying the retained source batch was delivered.
    """

    view_id: str
    client_id: str
    session_id: str
    delivery_state: str
    pending_delivery: bool
    protocol_version: int = STREAM_PROTOCOL_VERSION
    source_status: SourceStatus = field(default_factory=SourceStatus, compare=False)
    source_health: SourceHealth = field(default_factory=SourceHealth, compare=False)


@dataclass(frozen=True, slots=True)
class StreamClose:
    """An explicit stop outcome after one bounded local final-drain attempt."""

    view_id: str
    client_id: str
    session_id: str
    drain_completed: bool
    protocol_version: int = STREAM_PROTOCOL_VERSION
