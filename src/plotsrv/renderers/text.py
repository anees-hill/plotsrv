# src/plotsrv/renderers/text.py
from __future__ import annotations

from typing import Any
from dataclasses import dataclass
from typing import Literal

from .base import RenderResult
from .limits import DEFAULT_TEXT_LIMITS, TextLimits, truncate_text

ANCHOR_PREFIX = "\ufeffPLOTSRV_ANCHOR="  # BOM + prefix


@dataclass(frozen=True, slots=True)
class TextPayload:
    text: str
    anchor: Literal["head", "tail"] = "head"


class TextRenderer:
    kind = "text"

    def __init__(self, *, limits: TextLimits | None = None) -> None:
        self._limits = limits or DEFAULT_TEXT_LIMITS

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, (str, bytes, bytearray, TextPayload))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text, anchor = _to_text_and_anchor(obj)
        out, truncation = truncate_text(text, limits=self._limits, anchor=anchor)

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


def _strip_anchor_header(text: str) -> tuple[str, Literal["head", "tail"]]:
    if not text.startswith(ANCHOR_PREFIX):
        return text, "head"

    nl = text.find("\n")
    header = text if nl == -1 else text[:nl]
    rest = "" if nl == -1 else text[nl + 1 :]

    # header looks like "\ufeffPLOTSRV_ANCHOR=tail"
    val = header[len(ANCHOR_PREFIX) :].strip().lower()
    anchor: Literal["head", "tail"] = "tail" if val == "tail" else "head"
    return rest, anchor


def _to_text_and_anchor(obj: Any) -> tuple[str, Literal["head", "tail"]]:
    if isinstance(obj, TextPayload):
        return obj.text, obj.anchor

    if isinstance(obj, str):
        return _strip_anchor_header(obj)

    if isinstance(obj, (bytes, bytearray)):
        try:
            s = bytes(obj).decode("utf-8")
        except Exception:
            s = bytes(obj).decode("utf-8", errors="replace")
        return _strip_anchor_header(s)

    return repr(obj), "head"


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
