# src/plotsrv/renderers/text.py
from __future__ import annotations

from typing import Any

from .base import RenderResult
from .limits import DEFAULT_TEXT_LIMITS, TextLimits, truncate_text
from ..artifacts import Truncation


class TextRenderer:
    kind = "text"

    def __init__(self, *, limits: TextLimits | None = None) -> None:
        self._limits = limits or DEFAULT_TEXT_LIMITS

    def can_render(self, obj: Any) -> bool:
        # Render plain text-like things. (Everything else can fall back to repr in registry.py)
        return isinstance(obj, (str, bytes, bytearray))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text = _to_text(obj)
        out, truncation = truncate_text(text, limits=self._limits)

        html = (
            f'<pre class="plotsrv-pre" data-plotsrv-pre="1">{_escape_html(out)}</pre>'
        )
        return RenderResult(
            kind="text",
            html=html,
            truncation=truncation,
            meta={"view_id": view_id, "length": len(text)},
        )


def _to_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        try:
            return bytes(obj).decode("utf-8")
        except Exception:
            # best-effort fallback
            return bytes(obj).decode("utf-8", errors="replace")
    return repr(obj)


def _truncate_text(text: str, *, limits: TextLimits) -> dict[str, Any]:
    original_len = len(text)
    max_chars = max(1, int(limits.max_chars))

    if original_len <= max_chars:
        return {"text": text, "truncation": Truncation(truncated=False)}

    head = text[:max_chars]
    truncation = Truncation(
        truncated=True,
        reason="text exceeded max_chars",
        details={"max_chars": max_chars, "original_chars": original_len},
    )
    # Add a tiny suffix so it's obvious it's cut.
    head = head + "\n…"
    return {"text": head, "truncation": truncation}


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
