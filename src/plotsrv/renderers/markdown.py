# src/plotsrv/renderers/markdown.py
from __future__ import annotations

from typing import Any

from .. import config
from ..artifacts import Truncation
from .base import RenderResult, Renderer
from .limits import TextLimits, truncate_text


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_srcdoc(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;")


def _coerce_markdown_obj(obj: Any) -> tuple[str, bool, str | None]:
    """
    Supported forms:
      - str -> markdown text (safe mode)
      - {"text": "...", "unsafe_html": true|false} -> explicit unsafe toggle
      - {"text": "...", "unsafe_html": true, "sandbox": "..."} -> optional sandbox override
    """
    if isinstance(obj, str):
        return obj, False, None

    if isinstance(obj, dict):
        text = obj.get("text")
        if isinstance(text, str):
            unsafe = bool(obj.get("unsafe_html") or False)
            sandbox = str(obj.get("sandbox")) if obj.get("sandbox") else None
            return text, unsafe, sandbox

    return str(obj), False, None


def _render_markdown_to_html(text: str) -> str:
    try:
        import markdown  # type: ignore

        return markdown.markdown(text, extensions=["fenced_code", "tables"])
    except Exception:
        raise


def _sanitize_html(html: str) -> tuple[str, bool, str | None]:
    """
    Returns (sanitized_html, sanitized?, note_if_any)
    """
    try:
        import bleach  # type: ignore
    except Exception:
        return html, False, "install 'bleach' to enable safe markdown sanitization"

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
        "img",
    ]

    allowed_attrs: dict[str, list[str]] = {
        "a": ["href", "title", "rel", "target"],
        "img": ["src", "alt", "title", "width", "height"],
        "th": ["colspan", "rowspan"],
        "td": ["colspan", "rowspan"],
        "span": ["class"],
        "div": ["class"],
        "code": ["class"],
        "pre": ["class"],
        "table": ["class"],
    }

    allowed_protocols = ["http", "https", "mailto", "data"]

    cleaned = bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        protocols=allowed_protocols,
        strip=True,
    )

    try:
        cleaned = bleach.linkify(cleaned, callbacks=[bleach.callbacks.nofollow])
    except Exception:
        pass

    return cleaned, True, None


def _iframe_html(
    html_body: str,
    *,
    sandbox: str,
) -> str:
    srcdoc = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        html, body {{
          margin: 0;
          padding: 0;
          background: #ffffff;
          color: #222222;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          line-height: 1.55;
        }}

        body {{
          padding: 1.25rem;
        }}

        img {{
          max-width: 100%;
          height: auto;
        }}

        pre {{
          overflow: auto;
          padding: 0.75rem;
          border: 1px solid #eeeeee;
          border-radius: 6px;
          background: #fafafa;
        }}

        code {{
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }}

        table {{
          border-collapse: collapse;
          width: 100%;
        }}

        th, td {{
          border: 1px solid #e8e8e8;
          padding: 0.45rem 0.55rem;
          text-align: left;
          vertical-align: top;
        }}
      </style>
    </head>
    <body>
      {html_body}
    </body>
    </html>
    """.strip()

    return f"""
    <div class="plotsrv-markdown plotsrv-markdown--iframe">
      <div class="plotsrv-markdown__sandbox-note" title="This markdown allowed raw HTML, so plotsrv is displaying it inside a restricted iframe.">
        Sandboxed markdown HTML
      </div>
      <div class="plotsrv-markdown-iframe-wrap">
        <iframe class="plotsrv-markdown-iframe"
                sandbox="{_escape_html(sandbox)}"
                srcdoc="{_escape_srcdoc(srcdoc)}">
        </iframe>
      </div>
    </div>
    """.strip()


class MarkdownRenderer(Renderer):
    kind = "markdown"

    def can_render(self, obj: Any) -> bool:
        if isinstance(obj, str):
            return True
        return isinstance(obj, dict) and isinstance(obj.get("text"), str)

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        text, unsafe_html, sandbox_override = _coerce_markdown_obj(obj)

        max_chars = config.get_truncation_max_chars("markdown", view_id=view_id)
        if max_chars is None:
            text2 = text
            truncation = Truncation(truncated=False)
        else:
            text2, truncation = truncate_text(
                text,
                limits=TextLimits(max_chars=max_chars),
            )

        try:
            html_body = _render_markdown_to_html(text2)
        except Exception as e:
            html = (
                "<div class='plotsrv-markdown plotsrv-markdown--fallback'>"
                f"<div class='artifact-warn'>Markdown render failed: "
                f"{_escape_html(type(e).__name__)}: {_escape_html(str(e))}</div>"
                f"<pre class='plotsrv-markdown__raw'>{_escape_html(text2)}</pre>"
                "</div>"
            )
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

        configured_sanitize = config.get_markdown_sanitize()
        configured_sandbox = config.get_markdown_sandbox()

        # Explicit payload unsafe_html=True wins over config.
        # Otherwise markdown_sanitize=False means "render raw markdown HTML in a sandbox".
        should_use_iframe = unsafe_html or not configured_sanitize

        if should_use_iframe:
            sandbox = (
                sandbox_override if sandbox_override is not None else configured_sandbox
            )
            html = _iframe_html(html_body, sandbox=sandbox)

            return RenderResult(
                kind="markdown",
                html=html,
                mime="text/html",
                truncation=truncation,
                meta={
                    "view_id": view_id,
                    "rendered": True,
                    "unsafe_html": bool(unsafe_html),
                    "sanitized": False,
                    "mode": "unsafe_iframe",
                    "sandbox": sandbox,
                    "markdown_sanitize": configured_sanitize,
                },
            )

        out_body, sanitized, meta_note = _sanitize_html(html_body)

        if not sanitized and meta_note:
            html = (
                "<div class='plotsrv-markdown plotsrv-markdown--fallback'>"
                "<div class='artifact-warn'>"
                "Markdown sanitization is not available. "
                "Showing raw markdown escaped. "
                f"{_escape_html(meta_note)}"
                "</div>"
                f"<pre class='plotsrv-markdown__raw'>{_escape_html(text2)}</pre>"
                "</div>"
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
                    "sanitized": False,
                    "markdown_sanitize": configured_sanitize,
                    "note": meta_note,
                },
            )

        html = f"<div class='plotsrv-markdown plotsrv-markdown--sanitized'>{out_body}</div>"
        meta: dict[str, Any] = {
            "view_id": view_id,
            "rendered": True,
            "unsafe_html": False,
            "sanitized": True,
            "mode": "sanitized_inline",
            "markdown_sanitize": configured_sanitize,
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

        if unsafe_html:
            sandbox = sandbox_override if sandbox_override is not None else ""
            html = _iframe_html(html_body, sandbox=sandbox)

            return RenderResult(
                kind="markdown",
                html=html,
                mime="text/html",
                truncation=truncation,
                meta={
                    "view_id": view_id,
                    "rendered": True,
                    "unsafe_html": True,
                    "sanitized": False,
                    "mode": "unsafe_iframe",
                    "sandbox": sandbox,
                },
            )

        out_body, sanitized, meta_note = _sanitize_html(html_body)

        if not sanitized and meta_note:
            html = (
                "<div class='plotsrv-markdown plotsrv-markdown--fallback'>"
                "<div class='artifact-warn'>"
                "Markdown sanitization is not available. "
                "Showing raw markdown escaped. "
                f"{_escape_html(meta_note)}"
                "</div>"
                f"<pre class='plotsrv-markdown__raw'>{_escape_html(text2)}</pre>"
                "</div>"
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

        html = f"<div class='plotsrv-markdown plotsrv-markdown--sanitized'>{out_body}</div>"
        meta: dict[str, Any] = {
            "view_id": view_id,
            "rendered": True,
            "unsafe_html": False,
            "sanitized": True,
            "mode": "sanitized_inline",
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
