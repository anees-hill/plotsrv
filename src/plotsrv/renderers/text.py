# src/plotsrv/renderers/text.py
from __future__ import annotations

from typing import Any

from .base import RenderResult
from .limits import DEFAULT_TEXT_LIMITS, TextLimits, truncate_text


class TextRenderer:
    kind = "text"

    def __init__(self, *, limits: TextLimits | None = None) -> None:
        self._limits = limits or DEFAULT_TEXT_LIMITS

    def can_render(self, obj: Any) -> bool:
        # Render plain text-like things. (Everything else can fall back to repr elsewhere.)
        return isinstance(obj, (str, bytes, bytearray))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text = _to_text(obj)
        out, truncation = truncate_text(text, limits=self._limits)

        # Phase 1.1:
        # - word wrap toggle
        # - copy button
        #
        # Phase 1.2:
        # - truncation UX stays primarily in the global artifact truncation line
        #   (but we keep obvious "…" suffix from truncate_text)
        toolbar = """
        <div class="artifact-toolbar" data-plotsrv-toolbar="text">
          <div class="artifact-toolbar-group">
            <button type="button" class="artifact-btn" data-plotsrv-action="copy" title="Copy to clipboard">Copy</button>
            <button type="button" class="artifact-btn" data-plotsrv-action="wrap" title="Toggle word wrap">Wrap</button>
          </div>
        </div>
        """.strip()

        pre = f'<pre class="plotsrv-pre" data-plotsrv-pre="1">{_escape_html(out)}</pre>'
        html = f"{toolbar}\n{pre}"

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
            return bytes(obj).decode("utf-8", errors="replace")
    return repr(obj)


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
