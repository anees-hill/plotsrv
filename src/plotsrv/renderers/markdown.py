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


def _coerce_markdown_obj(obj: Any) -> tuple[str, bool]:
    """
    Supported forms:
      - str -> markdown text (safe mode)
      - {"text": "...", "unsafe_html": true|false} -> explicit unsafe toggle
    """
    if isinstance(obj, str):
        return obj, False

    if isinstance(obj, dict):
        text = obj.get("text")
        if isinstance(text, str):
            unsafe = bool(obj.get("unsafe_html") or False)
            return text, unsafe

    # fallback
    return str(obj), False


def _sanitize_html(html: str) -> tuple[str, bool, str | None]:
    """
    Returns (sanitized_html, sanitized?, note_if_any)
    """
    try:
        import bleach  # type: ignore
    except Exception:
        return html, False, "install 'bleach' to enable safe markdown sanitization"

    # Reasonable default allowlist (markdown-ish)
    allowed_tags = [
        "a",
        "p",
        "br",
        "hr",
        "blockquote",
        "strong",
        "em",
        "code",
        "pre",
        "kbd",
        "samp",
        "var",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "span",
        "div",
    ]

    allowed_attrs: dict[str, list[str]] = {
        "a": ["href", "title", "rel", "target"],
        "th": ["colspan", "rowspan"],
        "td": ["colspan", "rowspan"],
        "span": ["class"],
        "div": ["class"],
        "code": ["class"],
        "pre": ["class"],
        "table": ["class"],
    }

    # Restrict protocols on href
    allowed_protocols = ["http", "https", "mailto"]

    cleaned = bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        protocols=allowed_protocols,
        strip=True,  # strips disallowed tags entirely
    )

    # Also linkify plain URLs that appear in text (optional nice-to-have)
    try:
        cleaned = bleach.linkify(cleaned)
    except Exception:
        pass

    return cleaned, True, None


class MarkdownRenderer(Renderer):
    kind = "markdown"

    def can_render(self, obj: Any) -> bool:
        # Accept str and our dict wrapper
        if isinstance(obj, str):
            return True
        return isinstance(obj, dict) and isinstance(obj.get("text"), str)

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text, unsafe_html = _coerce_markdown_obj(obj)

        # optional truncation (keep UI responsive)
        text2, truncation = truncate_text(text, limits=DEFAULT_TEXT_LIMITS)

        # Render markdown -> HTML body
        try:
            import markdown  # type: ignore

            html_body = markdown.markdown(text2, extensions=["fenced_code", "tables"])
        except Exception as e:
            # If markdown lib breaks, fall back to escaped text
            html = f"<pre style='white-space:pre-wrap'>{_escape_html(text2)}</pre>"
            return RenderResult(
                kind="markdown",
                html=html,
                mime="text/html",
                truncation=truncation,
                meta={
                    "view_id": view_id,
                    "rendered": False,
                    "unsafe_html": unsafe_html,
                    "note": f"markdown render failed: {type(e).__name__}: {e}",
                },
            )

        # Safe-by-default: sanitize unless explicitly unsafe
        if unsafe_html:
            out_body = html_body
            meta_note = None
            sanitized = False
        else:
            out_body, sanitized, meta_note = _sanitize_html(html_body)

            # Fail closed if bleach missing: do NOT show unsanitized HTML
            if not sanitized and meta_note:
                html = (
                    "<div class='artifact-warn'>"
                    "Markdown sanitization is not available. "
                    "Showing raw markdown (escaped). "
                    f"{_escape_html(meta_note)}"
                    "</div>"
                    f"<pre style='white-space:pre-wrap'>{_escape_html(text2)}</pre>"
                )
                return RenderResult(
                    kind="markdown",
                    html=html,
                    mime="text/html",
                    truncation=truncation,
                    meta={
                        "view_id": view_id,
                        "rendered": False,
                        "unsafe_html": False,
                        "note": meta_note,
                    },
                )

        html = f"<div class='plotsrv-markdown'>{out_body}</div>"
        meta: dict[str, Any] = {
            "view_id": view_id,
            "rendered": True,
            "unsafe_html": unsafe_html,
            "sanitized": (not unsafe_html),
        }
        if meta_note:
            meta["note"] = meta_note

        return RenderResult(
            kind="markdown",
            html=html,
            mime="text/html",
            truncation=truncation,
            meta=meta,
        )
