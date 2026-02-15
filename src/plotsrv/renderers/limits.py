from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..artifacts import Truncation


@dataclass(frozen=True, slots=True)
class TextLimits:
    max_chars: int = 50_000
    max_lines: int | None = None  # optional


@dataclass(frozen=True, slots=True)
class JsonLimits:
    max_depth: int = 10
    max_nodes: int = 5_000
    max_string_chars: int = 1_000
    max_list_items: int = 200
    max_dict_items: int = 200


DEFAULT_TEXT_LIMITS = TextLimits()
DEFAULT_JSON_LIMITS = JsonLimits()


def truncate_text(text: str, *, limits: TextLimits) -> tuple[str, Truncation]:
    original_chars = len(text)
    out = text
    details: dict[str, Any] = {"original_chars": original_chars}

    # max_lines first (so max_chars applies to the resulting text)
    if limits.max_lines is not None:
        max_lines = max(1, int(limits.max_lines))
        lines = out.splitlines(True)  # keepends
        if len(lines) > max_lines:
            out = "".join(lines[:max_lines])
            details["max_lines"] = max_lines
            details["original_lines"] = len(lines)
            details["truncated_by"] = "max_lines"

    max_chars = max(1, int(limits.max_chars))
    if len(out) > max_chars:
        out = out[:max_chars]
        details["max_chars"] = max_chars
        details["truncated_by"] = details.get("truncated_by") or "max_chars"

    if out is text:
        return out, Truncation(truncated=False)

    # make it obvious it’s cut
    out = out + ("\n…" if not out.endswith("\n") else "…")
    return (
        out,
        Truncation(
            truncated=True,
            reason="text truncated by limits",
            details=details,
        ),
    )


def safe_scalar_text(x: Any, *, max_chars: int) -> tuple[str, bool]:
    """
    Best-effort scalar to string with a hard cap.
    Returns (string, truncated?).
    """
    try:
        s = str(x)
    except Exception:
        try:
            s = repr(x)
        except Exception:
            s = "<unprintable>"

    if len(s) <= max_chars:
        return s, False
    return s[:max_chars] + "…", True
