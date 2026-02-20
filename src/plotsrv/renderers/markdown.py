# src/plotsrv/renderers/markdown.py
from __future__ import annotations

from typing import Any

from .registry import RenderResult, Renderer


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class MarkdownRenderer(Renderer):
    kind = "markdown"

    def can_render(self, obj: Any, *, kind_hint: str | None = None) -> bool:
        return (kind_hint or "").lower() == "markdown" and isinstance(obj, str)

    def render(
        self, obj: Any, *, view_id: str, kind_hint: str | None = None
    ) -> RenderResult:
        text = obj if isinstance(obj, str) else str(obj)

        try:
            import markdown  # type: ignore

            html = markdown.markdown(text, extensions=["fenced_code", "tables"])
            return RenderResult(
                kind="markdown", html=html, mime="text/html", truncation=None, meta={}
            )
        except Exception:
            html = f"<pre style='white-space:pre-wrap'>{_escape_html(text)}</pre>"
            return RenderResult(
                kind="markdown",
                html=html,
                mime="text/html",
                truncation=None,
                meta={"note": "install 'markdown' to render"},
            )
