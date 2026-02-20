# src/plotsrv/renderers/markdown.py
from __future__ import annotations

from typing import Any

from .base import RenderResult, Renderer
from .limits import DEFAULT_TEXT_LIMITS, truncate_text


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


class MarkdownRenderer(Renderer):
    kind = "markdown"

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, str)

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text = obj if isinstance(obj, str) else str(obj)

        # optional truncation (keep UI responsive for larger md files)
        text2, truncation = truncate_text(text, limits=DEFAULT_TEXT_LIMITS)

        # Try render if markdown lib available; else show raw
        try:
            import markdown  # type: ignore

            html_body = markdown.markdown(text2, extensions=["fenced_code", "tables"])
            html = f"<div class='plotsrv-markdown'>{html_body}</div>"
            return RenderResult(
                kind="markdown",
                html=html,
                mime="text/html",
                truncation=truncation,
                meta={"view_id": view_id, "rendered": True},
            )
        except Exception:
            html = f"<pre style='white-space:pre-wrap'>{_escape_html(text2)}</pre>"
            return RenderResult(
                kind="markdown",
                html=html,
                mime="text/html",
                truncation=truncation,
                meta={
                    "view_id": view_id,
                    "rendered": False,
                    "note": "install 'markdown' to render",
                },
            )
