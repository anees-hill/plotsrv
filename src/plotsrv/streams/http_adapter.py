"""Conservative Uvicorn access-line adaptation; never executes log content."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import math
import re

from .text_framing import MAX_FRAME_BYTES, TextFrame

# Every input is already bounded by the physical framer. Patterns have no
# nested variable-length repetition or backtracking over arbitrary log tails.
_CSI = re.compile(r"\x1b\[[0-?]{0,64}[ -/]{0,16}[@-~]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]{0,8192}(?:\x07|\x1b\\|$)")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
_QUERY = re.compile(r"[?#][^\s\"'<>]*")
_AUTH = re.compile(
    r"(?im)\b(?:authorization|proxy-authorization|cookie|set-cookie)[\"']?\s*[:=][^\n]*"
)
_SECRET = re.compile(
    r"(?i)\b(password|passwd|token|access_token|api_key|secret)[\"']?\s*[:=]\s*(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,;]+)"
)
_FILE = re.compile(r'File "([^"\n]{1,4096})"')
_LOCAL_PATH = re.compile(
    r"(?:/(?:home|Users|tmp|var|srv|opt)/|[A-Za-z]:\\)[^\s\"'<>]{1,4096}"
)
_TIMESTAMP = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)\]?\s+"
)
_ACCESS = re.compile(
    r'^(?:INFO:\s+)?[^\s"]{1,128}:\d{1,5} - "'
    r'([A-Z]{1,16}) (/[^\s"]{0,2047}) HTTP/[0-9.]{1,8}" ([1-5]\d{2})'
    r"(?:\s+(?:duration=)?(\d{1,10}(?:\.\d{1,6})?)\s*(ns|us|µs|ms|s))?\s*$"
)


def _basename(value: str) -> str:
    return value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def clean_controls(text: str) -> str:
    return _CONTROL.sub("", _CSI.sub("", _OSC.sub("", text)))


def sanitize(text: str) -> tuple[str, list[str]]:
    transformations = []
    for name, transform in (
        ("terminal_controls_removed", clean_controls),
        ("query_and_fragment_redacted", lambda s: _QUERY.sub("?[redacted]", s)),
        (
            "credential_fields_redacted",
            lambda s: _SECRET.sub(
                r"\1=[redacted]", _AUTH.sub("[credential header redacted]", s)
            ),
        ),
        (
            "local_paths_shortened",
            lambda s: _LOCAL_PATH.sub(
                lambda m: "<path>/" + _basename(m[0]),
                _FILE.sub(lambda m: 'File "' + _basename(m[1]) + '"', s),
            ),
        ),
    ):
        updated = transform(text)
        if updated != text:
            transformations.append(name)
        text = updated
    return text, transformations


def adapt_frame(frame: TextFrame, *, observed_at: datetime, adapter: str) -> dict:
    if len(frame.raw) > MAX_FRAME_BYTES:
        frame = replace(frame, raw=frame.raw[:MAX_FRAME_BYTES], truncated=True)
    decoded = frame.raw.decode("utf-8", errors="replace")
    raw_text, transformations = sanitize(decoded)
    if "\ufffd" in decoded:
        transformations.append("invalid_utf8_replaced")
    event = {
        "kind": frame.kind,
        "adapter": adapter,
        "publisher_observed_at": observed_at.isoformat(),
    }
    result = {
        "log_schema_version": 1,
        "event": event,
        "raw": {
            "text": raw_text,
            "partial": frame.partial,
            "truncated": frame.truncated,
            "ambiguous": frame.ambiguous,
            "transformations": transformations,
        },
    }
    if frame.truncated:
        result["raw"][
            "notice"
        ] = "Frame limit reached; content omitted. An oversized line is discarded through its next newline."
    if frame.kind == "traceback":
        result["raw"][
            "notice"
        ] = "Unattributed traceback block; interleaving is possible. No request association is inferred."
        if frame.truncated:
            result["raw"]["notice"] += " Frame limit reached; continuation is separate."
    terminal_free = _CSI.sub("", _OSC.sub("", decoded)).strip("\r\n")
    invalid_controls = _CONTROL.search(terminal_free) is not None
    line = clean_controls(decoded).strip()
    prefix = _TIMESTAMP.match(line)
    if prefix:
        stamp = prefix[1].replace(",", ".")
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            event["source_timestamp"] = parsed.isoformat()
            event["source_timezone_known"] = parsed.tzinfo is not None
            line = line[prefix.end() :]
    match = (
        _ACCESS.fullmatch(line)
        if adapter != "text"
        and not frame.ambiguous
        and not frame.truncated
        and not invalid_controls
        else None
    )
    if match:
        method, target, status, duration, unit = match.groups()
        path = target.split("?", 1)[0].split("#", 1)[0]
        if len(path) > 1024:
            return result
        http = {"method": method, "path": path, "status": int(status)}
        if duration is not None:
            value = (
                float(duration)
                * {"ns": 1e-6, "us": 0.001, "µs": 0.001, "ms": 1, "s": 1000}[unit]
            )
            if math.isfinite(value):
                http["duration_ms"] = value
        event["kind"] = "http_request"
        result["http"] = http
    return result
