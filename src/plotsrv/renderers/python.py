# src/plotsrv/renderers/python.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from html import escape
import json

from .. import config
from .limits import TextLimits, truncate_text
from .syntax import highlight, presentation

from .base import Renderer, RenderResult


@dataclass(slots=True)
class PythonRenderer(Renderer):
    kind: str = "python"
    supports_source_info = True

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, str)

    def render(self, obj: Any, *, view_id: str, source_info=None) -> RenderResult:
        from .text import _to_text_and_anchor

        code, anchor = _to_text_and_anchor(obj)
        info = source_info or {}
        anchor = info.get("anchor", anchor)
        limit = config.get_truncation_max_chars("text", view_id=view_id)
        code, truncation = truncate_text(
            code, limits=TextLimits(max_chars=min(limit or 65536, 65536)), anchor=anchor
        )
        # Bound browser line wrappers after the character prefix/tail admission.
        code, line_truncation = truncate_text(
            code, limits=TextLimits(max_chars=65536, max_lines=2000), anchor=anchor
        )
        if line_truncation.truncated:
            truncation = line_truncation
        language, style = presentation(view_id, info, default_language="python")
        coloured = highlight(
            code,
            language,
            partial_tail=anchor == "tail"
            and (info.get("partial", False) or truncation.truncated),
        )
        markup = coloured.html if coloured.html is not None else escape(code)
        note = (
            '<div class="note">' + escape(coloured.reason) + "</div>"
            if coloured.reason
            else ""
        )

        toolbar = f"""
        <div class="artifact-toolbar ps-code-toolbar" data-plotsrv-toolbar="code">
          <div class="artifact-toolbar-group ps-code-toolbar__group">
            <button type="button" class="artifact-btn" data-plotsrv-code-action="copy" title="Copy code to clipboard">Copy</button>
            <button type="button" class="artifact-btn" data-plotsrv-code-action="wrap" aria-pressed="false" title="Toggle word wrap">Wrap</button>
            <button type="button" class="artifact-btn" data-plotsrv-code-action="highlight" aria-pressed="true" title="Toggle syntax highlighting">Highlight</button>
            <button type="button" class="artifact-btn" data-plotsrv-code-action="lines" aria-pressed="true" title="Toggle line numbers">Lines</button>
          </div>
          <div class="ps-code-toolbar__meta" title="Bounded server-side syntax highlighting.">
            {escape(language or "Plain text")}
          </div>
        </div>
        """.strip()

        html = f"""
        <div class="ps-code-shell">
          {toolbar}
          {note}
          <pre class="ps-code ps-code-pre"
               data-plotsrv-code-pre="1"
               data-plotsrv-code-language="{escape(language or "text")}"><code class="language-python"
               data-plotsrv-code-content="1"
               data-plotsrv-code-highlighted="{int(coloured.html is not None)}"
               data-plotsrv-code-default="{int(style != "plain")}"
               data-plotsrv-code-raw="{escape(json.dumps(code), quote=True)}">{markup}</code></pre>
        </div>
        """.strip()

        return RenderResult(
            kind="python",
            html=html,
            mime="text/html",
            truncation=truncation,
            meta={
                "view_id": view_id,
                "language": coloured.language,
                "syntax_limited": coloured.reason,
            },
        )


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
