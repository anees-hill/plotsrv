# src/plotsrv/renderers/html.py
from __future__ import annotations

from typing import Any
import re

from .. import config
from ..artifacts import Truncation
from .base import RenderResult, Renderer
from .limits import truncate_text

_STYLE_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_HEAD_CLOSE_RE = re.compile(r"(?is)</head\s*>")
_BODY_OPEN_RE = re.compile(r"(?is)<body\b[^>]*>")
_HTML_OPEN_RE = re.compile(r"(?is)<html\b[^>]*>")


_DISPLAY_ONLY_SCRIPT = r"""
<script>
(function () {
  "use strict";

  function isBlockedTarget(target) {
    if (!target || !target.closest) return false;

    return !!target.closest(
      [
        "a",
        "button",
        "input",
        "select",
        "textarea",
        "summary",
        "details",
        "label",
        "form",
        "[role='button']",
        "[role='link']",
        "[onclick]",
        "[tabindex]"
      ].join(",")
    );
  }

  document.addEventListener("click", function (ev) {
    if (isBlockedTarget(ev.target)) {
      ev.preventDefault();
      ev.stopPropagation();
      return false;
    }
  }, true);

  document.addEventListener("submit", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    return false;
  }, true);

  document.addEventListener("keydown", function (ev) {
    var key = ev.key || "";
    if ((key === "Enter" || key === " ") && isBlockedTarget(ev.target)) {
      ev.preventDefault();
      ev.stopPropagation();
      return false;
    }
  }, true);
})();
</script>
""".strip()


_DISPLAY_ONLY_STYLE = r"""
<style>
  a,
  button,
  input,
  select,
  textarea,
  summary,
  details,
  label,
  [role="button"],
  [role="link"],
  [onclick],
  [tabindex] {
    cursor: default !important;
  }
</style>
""".strip()


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


def strip_style_and_script_blocks(html: str) -> str:
    return _STYLE_SCRIPT_RE.sub("", html)


def _inject_display_only_guards(raw_html: str) -> str:
    """
    Inject a tiny guard into iframe srcdoc so report HTML is displayed but not
    practically interactive.

    This deliberately runs inside the iframe, not in the parent plotsrv page.
    """
    guard = _DISPLAY_ONLY_STYLE + "\n" + _DISPLAY_ONLY_SCRIPT

    if _HEAD_CLOSE_RE.search(raw_html):
        return _HEAD_CLOSE_RE.sub(guard + "\n</head>", raw_html, count=1)

    if _BODY_OPEN_RE.search(raw_html):
        return _BODY_OPEN_RE.sub(lambda m: m.group(0) + "\n" + guard, raw_html, count=1)

    if _HTML_OPEN_RE.search(raw_html):
        return _HTML_OPEN_RE.sub(
            lambda m: m.group(0) + "\n<head>" + guard + "</head>", raw_html, count=1
        )

    return (
        "<!doctype html><html><head>"
        + guard
        + "</head><body>"
        + raw_html
        + "</body></html>"
    )


def _sanitize_html(html: str) -> tuple[str, bool]:
    """
    Best-effort sanitization.
    Returns (sanitized_html, used_bleach?).
    """
    try:
        import bleach  # type: ignore

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

        cleaned = bleach.linkify(cleaned, callbacks=[bleach.callbacks.nofollow])
        return cleaned, True
    except Exception:
        return _escape_html(html), False


def _iframe_html(
    raw_html: str,
    *,
    sandbox: str,
    display_only: bool,
) -> str:
    iframe_html = _inject_display_only_guards(raw_html) if display_only else raw_html
    srcdoc = _escape_srcdoc(iframe_html)

    mode_attr = "display-only" if display_only else "interactive"

    return f"""
    <div class="plotsrv-html-iframe-wrap" data-plotsrv-html-frame="{mode_attr}">
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
          - obj: {"html": "<...>", "unsafe": bool, "sandbox": "..."} optional
          - obj: {"html": "<...>", "interactive": true} optional escape hatch
        """
        sanitize = config.get_html_sanitize()
        unsafe = not sanitize

        # For HTML reports, default to a sandbox that allows our injected blocker
        # script to run, while still preventing parent-page access because we do
        # not set allow-same-origin.
        configured_sandbox = config.get_html_sandbox()
        sandbox = configured_sandbox if configured_sandbox else "allow-scripts"

        raw_html = ""
        interactive = False

        if isinstance(obj, dict):
            raw_html = str(obj.get("html") or "")

            if "unsafe" in obj:
                unsafe = bool(obj.get("unsafe"))
            elif "sanitize" in obj:
                unsafe = not bool(obj.get("sanitize"))

            if obj.get("sandbox"):
                sandbox = str(obj.get("sandbox") or sandbox)

            interactive = bool(obj.get("interactive") or False)
        else:
            raw_html = str(obj)

        max_chars = config.get_truncation_max_chars("html")
        if max_chars is None:
            raw_html2 = raw_html
            truncation = Truncation(truncated=False)
        else:
            from .limits import TextLimits

            raw_html2, truncation = truncate_text(
                raw_html,
                limits=TextLimits(max_chars=max_chars),
            )

        if unsafe:
            display_only = not interactive
            html = _iframe_html(
                raw_html2,
                sandbox=sandbox,
                display_only=display_only,
            )
            return RenderResult(
                kind="html",
                html=html,
                mime="text/html",
                truncation=truncation,
                meta={
                    "view_id": view_id,
                    "mode": "unsafe_iframe",
                    "sandbox": sandbox,
                    "display_only": display_only,
                },
            )

        sanitized, used_bleach = _sanitize_html(raw_html2)

        if used_bleach:
            html = (
                f"<div class='plotsrv-html plotsrv-html--sanitized'>{sanitized}</div>"
            )
            note = None
        else:
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
