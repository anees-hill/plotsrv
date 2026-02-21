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
        html = (
            '<pre class="ps-code"><code class="language-python">'
            + _escape_html(code)
            + "</code></pre>"
        )
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
