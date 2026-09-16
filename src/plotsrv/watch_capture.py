"""Bounded, read-only watch capture and path-free format preparation.

Shared by publisher and receiver. No caller can disable the transfer or decoded
limits. CSV tail windows with ambiguous quote context remain text previews.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
from pathlib import Path
import stat
from dataclasses import dataclass
from typing import NamedTuple
import configparser
import tomllib

from .file_kinds import infer_file_kind, coerce_file_to_publishable
from .runtime import _coerce_csv_rows, default_watch_read_mode

MAX_SOURCE_BYTES = 256 * 1024
MAX_HEADER_BYTES = 16 * 1024
MAX_ROWS = 200
MAX_COLUMNS = 64
MAX_TEXT_CHARS = 64 * 1024
MAX_PIXELS = 4_000_000
MAX_PREPARED_BYTES = 1024 * 1024
MAX_WATCH_REQUEST_BYTES = 384 * 1024
MAX_WATCHES = 64
SESSION_LEASE_S = 60.0
WATCH_FEATURE = "watch-v2"


@dataclass(frozen=True)
class Capture:
    raw: bytes
    source: dict
    signature: tuple
    bytes_read: int


def signature(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def capture(
    path: Path,
    *,
    maximum=MAX_SOURCE_BYTES,
    read_mode=None,
    encoding="utf-8",
    kind="auto",
) -> Capture:
    maximum = min(
        MAX_SOURCE_BYTES,
        maximum if isinstance(maximum, int) and maximum > 0 else MAX_SOURCE_BYTES,
    )
    mode = read_mode or default_watch_read_mode(path)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb", buffering=0) as file:
        before = os.fstat(file.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise OSError("source is not a regular file")
        size = before.st_size
        complete = size <= maximum
        start = 0 if complete or mode == "head" else size - maximum
        header = b""
        header_read = 0
        if start and infer_file_kind(path) == "csv" and kind == "auto":
            # No unbounded readline or scan to discover the end of a huge header.
            header = file.read(min(MAX_HEADER_BYTES, maximum))
            header_read = len(header)
            end = header.find(b"\n")
            header = header[: end + 1] if end >= 0 else header
            start = max(header_read, size - (maximum - header_read))
        file.seek(start)
        raw = file.read(min(size - start, maximum - header_read))
        read_bytes = len(raw) + header_read
        after = os.fstat(file.fileno())
        # A rename during reading is also a changed source, even if the old fd is stable.
        if signature(before) != signature(after) or signature(
            path.lstat()
        ) != signature(after):
            raise BlockingIOError("source changed during capture")
        if not complete and start and header:
            # Drop a physical partial line; quoted tails are handled conservatively below.
            newline = raw.find(b"\n")
            raw = raw[newline + 1 :] if newline >= 0 else b""
            raw = header + raw
        source = dict(
            basename=path.name,
            source_type="watch",
            size_bytes=size,
            mtime_ns=before.st_mtime_ns,
            read_scope="full" if complete else mode,
            read_mode=mode,
            complete=complete,
            encoding=encoding,
            kind=kind,
        )
        return Capture(raw, source, signature(before), read_bytes)


def _bounded_object(obj):
    stack = [(obj, 0)]
    count = 0
    seen = set()
    while stack:
        value, depth = stack.pop()
        count += 1
        if count > 10_000 or depth > 32:
            raise ValueError("structured preview limit")
        if isinstance(value, (dict, list)):
            if id(value) in seen:
                raise ValueError("aliased structured content")
            seen.add(id(value))
            stack.extend(
                (v, depth + 1)
                for v in (value.values() if isinstance(value, dict) else value)
            )


class Preparation(NamedTuple):
    payload: dict
    limitation: str | None
    invalid_structured: bool = False


def prepare(raw: bytes, source: dict) -> Preparation:
    """Convert bounded bytes without paths; distinguish syntax errors from limits."""
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source byte limit")
    path = Path(source["basename"])
    fk = infer_file_kind(path) if source["kind"] == "auto" else source["kind"]
    complete = source["complete"]
    limitation = None
    invalid_structured = False
    mode = source.get("read_mode", source["read_scope"])
    text = None
    if fk == "image":
        if not complete or path.suffix.lower() == ".svg":
            raise ValueError("image must be complete supported raster data")
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > MAX_PIXELS or getattr(im, "n_frames", 1) != 1:
                raise ValueError("decoded image limit")
            mime = Image.MIME.get(im.format)
            if mime not in (
                "image/png",
                "image/jpeg",
                "image/gif",
                "image/webp",
                "image/bmp",
            ):
                raise ValueError("unsupported image")
            im.verify()
        payload = dict(
            kind="artifact",
            artifact_kind="image",
            artifact={
                "mime": mime,
                "data_b64": base64.b64encode(raw).decode(),
                "filename": path.name,
            },
        )
    else:
        text = raw.decode(source["encoding"], errors="replace")
        if "\x00" in text:
            raise ValueError("binary source is unsupported")
        payload = dict(kind="artifact", artifact_kind="text", artifact=text)
        if fk == "csv":
            try:
                if (
                    not complete
                    and source["read_scope"] == "head"
                    and not text.endswith("\n")
                ):
                    end = text.rfind("\n")
                    if end < 0:
                        raise ValueError("incomplete CSV header")
                    text = text[: end + 1]
                if not complete and source["read_scope"] == "tail" and '"' in text:
                    raise ValueError("quoted CSV tail has unknown record boundary")
                reader = csv.reader(io.StringIO(text), strict=True)
                header = next(reader, [])
                if (
                    not header
                    or len(header) > MAX_COLUMNS
                    or any(len(v) > 8192 for v in header)
                ):
                    raise ValueError("CSV header limit")
                from collections import deque

                rows = deque(maxlen=MAX_ROWS)
                omitted = False
                for row in reader:
                    if len(row) != len(header) or any(len(v) > 8192 for v in row):
                        raise ValueError("partial or oversized CSV record")
                    if len(rows) == MAX_ROWS:
                        omitted = True
                        if mode != "tail":
                            break
                    rows.append(row)
                columns, values, _, _ = _coerce_csv_rows(
                    header=header, rows=list(rows), max_columns=MAX_COLUMNS
                )
                payload = dict(
                    kind="table",
                    table=dict(
                        columns=columns,
                        rows=values,
                        total_rows=len(values) if complete and not omitted else None,
                        returned_rows=len(values),
                    ),
                )
                if omitted or not complete:
                    limitation = "Bounded CSV preview; total row count is unknown."
            except (ValueError, csv.Error):
                limitation = "CSV record/header limit or ambiguous tail; showing bounded raw text."
        elif fk in ("json", "ini", "toml", "yaml"):
            try:
                if not complete or len(raw) > 64 * 1024:
                    raise ValueError("structured source preview")
                if fk == "json":
                    # Reuse the ingress pre-expansion depth/token guard.
                    from .ingestion import _decode_payload

                    obj = _decode_payload(bytearray(b'{"value":' + raw + b"}"))["value"]
                    _bounded_object(obj)
                    payload = dict(kind="artifact", artifact_kind="json", artifact=obj)
                else:
                    if fk == "yaml":
                        import yaml

                        for i, token in enumerate(yaml.scan(text)):
                            if i > 10_000 or isinstance(
                                token, (yaml.AliasToken, yaml.AnchorToken)
                            ):
                                raise ValueError("YAML alias/token limit")
                    coerced = coerce_file_to_publishable(
                        path, raw=raw, encoding=source["encoding"]
                    )
                    _bounded_object(coerced.obj)
                    payload = dict(
                        kind="artifact",
                        artifact_kind=coerced.artifact_kind,
                        artifact=coerced.obj,
                    )
            except Exception as error:
                # Syntax failures may be partial writes; resource limits are a
                # valid preview outcome and must replace an older small object.
                invalid_structured = (
                    isinstance(error, (configparser.Error, tomllib.TOMLDecodeError))
                    or getattr(error, "reason", None) == "invalid_json"
                )
                if fk == "yaml":
                    import yaml

                    invalid_structured = isinstance(error, yaml.YAMLError)
                limitation = "Structured parsing unavailable or limited; showing bounded raw text."
        elif fk in ("html", "markdown"):
            if complete and len(text) <= MAX_TEXT_CHARS:
                payload = dict(kind="artifact", artifact_kind=fk, artifact=text)
                if fk == "html":
                    limitation = "Isolated HTML; relative assets are not uploaded."
            else:
                limitation = "Incomplete or oversized markup; showing bounded raw text."
        if fk == "code":
            payload["artifact_kind"] = "code"
        if payload.get("artifact_kind") in ("text", "python", "code"):
            from .runtime import get_watch_render_limit

            configured = get_watch_render_limit("text")
            limit = (
                min(MAX_TEXT_CHARS, configured)
                if configured is not None
                else MAX_TEXT_CHARS
            )
            if len(payload["artifact"]) > limit:
                preview = payload["artifact"]
                payload["artifact"] = (
                    preview[-limit:] if mode == "tail" else preview[:limit]
                )
                limitation = limitation or "Text presentation is a bounded preview."
    if payload["kind"] == "artifact":
        from .source_info import for_file

        payload["source_info"] = for_file(
            path.name,
            anchor=mode if mode in ("head", "tail") else "head",
            partial=not complete or bool(limitation),
        )
    if (
        len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
        > MAX_PREPARED_BYTES
    ):
        raise ValueError("decoded output limit")
    return Preparation(payload, limitation, invalid_structured)
