# src/plotsrv/renderers/text.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .. import config
from .base import RenderResult
from .limits import TextLimits, truncate_text

ANCHOR_PREFIX = "\ufeffPLOTSRV_ANCHOR="  # BOM + prefix


@dataclass(frozen=True, slots=True)
class TextPayload:
    text: str
    anchor: Literal["head", "tail"] = "head"


class TextRenderer:
    kind = "text"

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, (str, bytes, bytearray, TextPayload))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text, anchor = _to_text_and_anchor(obj)

        max_chars = config.get_truncation_max_chars("text")
        if max_chars is None:
            out = text
            from ..artifacts import Truncation

            truncation = Truncation(truncated=False)
        else:
            out, truncation = truncate_text(
                text,
                limits=TextLimits(max_chars=max_chars),
                anchor=anchor,
            )

        toolbar = """
        <div class="ps-text-shell">
          <div class="artifact-toolbar ps-text-toolbar" data-plotsrv-toolbar="text">
            <div class="artifact-toolbar-group ps-text-toolbar__group">
              <button type="button" class="artifact-btn" data-plotsrv-action="copy" title="Copy to clipboard">Copy</button>
              <button type="button" class="artifact-btn" data-plotsrv-action="wrap" title="Toggle word wrap" aria-pressed="false">Wrap</button>
              <button type="button" class="artifact-btn" data-plotsrv-action="reverse" title="Reverse line order" aria-pressed="false">Reverse lines</button>
              <button type="button" class="artifact-btn" data-plotsrv-action="colour" title="Toggle lightweight log colouring" aria-pressed="true">Colour logs</button>
            </div>
            <div class="artifact-toolbar-group ps-text-toolbar__group">
              <span class="ps-text-reverse-indicator"
                    data-plotsrv-text-reverse-indicator="1"
                    title="Line order is reversed, so the newest lines are shown first."
                    hidden>↕ Reversed</span>
            </div>
          </div>
        """.strip()

        pre = (
            f'<pre class="plotsrv-pre ps-text-pre" '
            f'data-plotsrv-pre="1" '
            f'data-plotsrv-text-anchor="{anchor}">{_escape_html(out)}</pre>'
        )
        html = f"{toolbar}\n{pre}\n</div>"

        return RenderResult(
            kind="text",
            html=html,
            truncation=truncation,
            meta={"view_id": view_id, "length": len(text), "anchor": anchor},
        )


def _strip_anchor_header(text: str) -> tuple[str, Literal["head", "tail"]]:
    if not text.startswith(ANCHOR_PREFIX):
        return text, "head"

    nl = text.find("\n")
    header = text if nl == -1 else text[:nl]
    rest = "" if nl == -1 else text[nl + 1 :]

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


def _escape_attr(s: str) -> str:
    return _escape_html(s).replace("\n", " ").replace("\r", " ")
