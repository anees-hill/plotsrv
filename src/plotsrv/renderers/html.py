# src/plotsrv/renderers/html.py
from __future__ import annotations

from typing import Any
import re

from .base import RenderResult, Renderer
from .limits import DEFAULT_TEXT_LIMITS, truncate_text

_STYLE_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def strip_style_and_script_blocks(html: str) -> str:
    return _STYLE_SCRIPT_RE.sub("", html)


def _sanitize_html(html: str) -> tuple[str, bool]:
    """
    Best-effort sanitization.
    Returns (sanitized_html, used_bleach?).
    """
    try:
        import bleach  # type: ignore

        # Conservative default: allow basic formatting + links + tables + code.
        allowed_tags = [
            "p",
            "br",
            "hr",
            "b",
            "strong",
            "i",
            "em",
            "u",
            "blockquote",
            "pre",
            "code",
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
            "a",
            "span",
            "div",
            "img",
        ]
        allowed_attrs = {
            "a": ["href", "title", "target", "rel"],
            "img": ["src", "alt", "title", "width", "height"],
            "*": ["class"],
        }
        allowed_protocols = ["http", "https", "mailto", "data"]

        html = strip_style_and_script_blocks(html)

        cleaned = bleach.clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=allowed_protocols,
            strip=True,
        )

        # Also “linkify” plain URLs, and force rel attributes on <a>
        cleaned = bleach.linkify(cleaned, callbacks=[bleach.callbacks.nofollow])
        return cleaned, True
    except Exception:
        return _escape_html(html), False


def _iframe_html(
    raw_html: str,
    *,
    sandbox: str,
) -> str:
    # Use srcdoc so we don't need any new routes.
    srcdoc = raw_html.replace("&", "&amp;").replace('"', "&quot;")
    return f"""
    <div class="plotsrv-html-iframe-wrap">
      <iframe class="plotsrv-html-iframe"
              sandbox="{_escape_html(sandbox)}"
              srcdoc="{srcdoc}">
      </iframe>
    </div>
    """.strip()


class HtmlRenderer(Renderer):
    kind = "html"

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, (str, dict))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        """
        Supports:
          - obj: str => treated as raw HTML
          - obj: {"html": "<...>", "unsafe": bool, "sandbox": "..."} (optional)
        """
        unsafe = False
        sandbox = (
            "allow-forms allow-modals allow-popups allow-downloads"  # conservative
        )
        raw_html = ""

        if isinstance(obj, dict):
            raw_html = str(obj.get("html") or "")
            unsafe = bool(obj.get("unsafe") or False)
            if obj.get("sandbox"):
                sandbox = str(obj.get("sandbox") or sandbox)
        else:
            raw_html = str(obj)

        raw_html2, truncation = truncate_text(raw_html, limits=DEFAULT_TEXT_LIMITS)

        if unsafe:
            # Unsafe mode: do not sanitize; isolate in sandboxed iframe.
            # Note: scripts are NOT allowed unless sandbox includes "allow-scripts".
            html = _iframe_html(raw_html2, sandbox=sandbox)
            return RenderResult(
                kind="html",
                html=html,
                mime="text/html",
                truncation=truncation,
                meta={
                    "view_id": view_id,
                    "mode": "unsafe_iframe",
                    "sandbox": sandbox,
                },
            )

        # Safe mode: sanitize if possible, otherwise escape.
        sanitized, used_bleach = _sanitize_html(raw_html2)

        if used_bleach:
            html = (
                f"<div class='plotsrv-html plotsrv-html--sanitized'>{sanitized}</div>"
            )
            note = None
        else:
            # No bleach => show escaped HTML as code (safe preview)
            html = (
                "<div class='plotsrv-html plotsrv-html--escaped'>"
                "<div class='note'>Install <code>bleach</code> to sanitize and render HTML safely. Showing escaped preview.</div>"
                f"<pre class='plotsrv-pre plotsrv-pre--wrap'>{sanitized}</pre>"
                "</div>"
            )
            note = "bleach not installed; rendered escaped preview"

        return RenderResult(
            kind="html",
            html=html,
            mime="text/html",
            truncation=truncation,
            meta={
                "view_id": view_id,
                "mode": "sanitized" if used_bleach else "escaped_preview",
                "note": note,
            },
        )
