# src/plotsrv/renderers/python.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import Renderer, RenderResult


@dataclass(slots=True)
class PythonRenderer(Renderer):
    kind: str = "python"

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, str)

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        code = obj if isinstance(obj, str) else repr(obj)

        toolbar = """
        <div class="artifact-toolbar ps-code-toolbar" data-plotsrv-toolbar="code">
          <div class="artifact-toolbar-group ps-code-toolbar__group">
            <button type="button" class="artifact-btn" data-plotsrv-code-action="copy" title="Copy code to clipboard">Copy</button>
            <button type="button" class="artifact-btn" data-plotsrv-code-action="wrap" aria-pressed="false" title="Toggle word wrap">Wrap</button>
            <button type="button" class="artifact-btn" data-plotsrv-code-action="highlight" aria-pressed="true" title="Toggle syntax highlighting">Highlight</button>
            <button type="button" class="artifact-btn" data-plotsrv-code-action="lines" aria-pressed="true" title="Toggle line numbers">Lines</button>
          </div>
          <div class="ps-code-toolbar__meta" title="Lightweight browser-side Python highlighting; no extra dependency or LSP required.">
            Python
          </div>
        </div>
        """.strip()

        html = f"""
        <div class="ps-code-shell">
          {toolbar}
          <pre class="ps-code ps-code-pre"
               data-plotsrv-code-pre="1"
               data-plotsrv-code-language="python"><code class="language-python"
               data-plotsrv-code-content="1">{_escape_html(code)}</code></pre>
        </div>
        """.strip()

        return RenderResult(
            kind="python",
            html=html,
            mime="text/html",
            meta={"view_id": view_id},
        )


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
