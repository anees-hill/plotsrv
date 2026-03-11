from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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


DEFAULT_TEXT_LIMITS = TextLimits(max_chars=50_000)
DEFAULT_JSON_LIMITS = JsonLimits()


def truncate_text(
    text: str,
    *,
    limits: TextLimits,
    anchor: Literal["head", "tail"] = "head",
) -> tuple[str, Truncation]:
    original_chars = len(text)
    out = text
    details: dict[str, Any] = {"original_chars": original_chars, "anchor": anchor}

    # max_lines first (so max_chars applies to the resulting text)
    if limits.max_lines is not None:
        max_lines = max(1, int(limits.max_lines))
        lines = out.splitlines(True)  # keepends
        if len(lines) > max_lines:
            if anchor == "tail":
                out = "".join(lines[-max_lines:])
                details["truncated_side_lines"] = "head"
            else:
                out = "".join(lines[:max_lines])
                details["truncated_side_lines"] = "tail"

            details["max_lines"] = max_lines
            details["original_lines"] = len(lines)
            details["truncated_by"] = "max_lines"

    max_chars = max(1, int(limits.max_chars))
    if len(out) > max_chars:
        if anchor == "tail":
            out = out[-max_chars:]
            details["truncated_side_chars"] = "head"
        else:
            out = out[:max_chars]
            details["truncated_side_chars"] = "tail"

        details["max_chars"] = max_chars
        details["truncated_by"] = details.get("truncated_by") or "max_chars"

    if out is text:
        return out, Truncation(truncated=False)

    if anchor == "tail":
        out = ("…\n" if not out.startswith("\n") else "…") + out
    else:
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
