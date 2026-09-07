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

    def _get_max_chars(self, *, view_id: str) -> int | None:
        return config.get_truncation_max_chars("text", view_id=view_id)

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text, anchor = _to_text_and_anchor(obj)

        max_chars = self._get_max_chars(view_id=view_id)
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
              <div class="ps-text-style-control">
                <button type="button"
                        class="artifact-btn ps-text-style-trigger"
                        data-plotsrv-action="style-menu"
                        title="Choose lightweight text highlighting"
                        aria-haspopup="menu"
                        aria-expanded="false">Styling <span class="ps-text-style-trigger__choice" data-plotsrv-text-style-choice="1">Auto</span><span aria-hidden="true">▾</span></button>
                <div class="ps-text-style-menu"
                     data-plotsrv-text-style-menu="1"
                     role="menu"
                     aria-label="Text highlighting style"
                     hidden>
                  <span class="ps-text-style-menu__heading">Highlighting</span>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="auto" aria-checked="false"><span>Auto</span><small>Detect a useful style</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="plain" aria-checked="false"><span>None / Plain</span><small>Show unstyled text</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="http" aria-checked="false"><span>HTTP / access log</span><small>Methods, paths and statuses</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="application" aria-checked="false"><span>Application log</span><small>Levels and logger names</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="timestamp" aria-checked="false"><span>Timestamp + severity</span><small>Times and log levels</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="syslog" aria-checked="false"><span>Syslog / system log</span><small>System log prefixes</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="container" aria-checked="false"><span>Container / Docker</span><small>Streams and timestamps</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="test" aria-checked="false"><span>Test output</span><small>Results and test names</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="traceback" aria-checked="false"><span>Traceback / error</span><small>Frames and exceptions</small></button>
                  <button type="button" role="menuitemradio" data-plotsrv-text-style="keyvalue" aria-checked="false"><span>Key / value</span><small>Config-like entries</small></button>
                </div>
              </div>
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
            kind=self.kind,
            html=html,
            truncation=truncation,
            meta={"view_id": view_id, "length": len(text), "anchor": anchor},
        )


class ErrorTextRenderer(TextRenderer):
    """
    Text-like renderer for plotsrv-generated error artifacts.

    These must not obey limits.truncate_after.text because low text truncation
    can hide the useful config/actionability message itself.
    """

    def __init__(self, *, kind: Literal["watch_error", "publish_error"]) -> None:
        self.kind = kind

    def _get_max_chars(self, *, view_id: str) -> int | None:
        return None

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        if self.kind != "watch_error":
            return super().render(obj, view_id=view_id)

        text, _ = _to_text_and_anchor(obj)
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        body = "\n".join(
            f"<p>{_escape_html(paragraph).replace(chr(10), '<br>')}</p>"
            for paragraph in paragraphs
        )
        if not body:
            body = "<p>This watched view could not be updated.</p>"

        html = (
            '<section class="ps-watch-error" role="alert">'
            '<span class="ps-watch-error__eyebrow">Source problem</span>'
            "<h2>Couldn\u2019t update this view</h2>"
            f"{body}"
            "</section>"
        )

        from ..artifacts import Truncation

        return RenderResult(
            kind=self.kind,
            html=html,
            truncation=Truncation(truncated=False),
            meta={"view_id": view_id, "length": len(text), "presentation": "error_card"},
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
