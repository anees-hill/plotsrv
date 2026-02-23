# src/plotsrv/renderers/registry.py
from __future__ import annotations

from typing import Any

from .base import Renderer, RenderResult


_RENDERERS: list[Renderer] = []


def register_renderer(r: Renderer) -> None:
    _RENDERERS.append(r)


def choose_renderer(obj: Any, *, kind_hint: str | None = None) -> Renderer | None:
    """
    Choose a renderer with safety-oriented ordering.

    Key behaviour:
    - If kind_hint provided: try exact kind match first.
    - For strings with no hint: prefer "python"/"text" renderers over "html",
      and only allow HTML renderers to win if the string looks like HTML.
    - Otherwise: first can_render wins.
    """
    # 1) Honour explicit hint first
    if kind_hint:
        for r in _RENDERERS:
            if getattr(r, "kind", None) == kind_hint and r.can_render(obj):
                return r

    # 2) Safety ordering for strings when no hint:
    #    avoid "any str => HTML" behaviour.
    if isinstance(obj, str):
        htmlish = _looks_like_html(obj)

        # Prefer code/text-ish renderers first
        preferred_kinds = ("python", "traceback", "text", "json")
        for k in preferred_kinds:
            for r in _RENDERERS:
                if getattr(r, "kind", None) == k and r.can_render(obj):
                    return r

        # Only let HTML renderers win if it actually looks like HTML
        if htmlish:
            for r in _RENDERERS:
                if getattr(r, "kind", None) == "html" and r.can_render(obj):
                    return r

        # Fall back to first match (but still avoid html if not htmlish)
        for r in _RENDERERS:
            if getattr(r, "kind", None) == "html":
                continue
            if r.can_render(obj):
                return r

        # As a last resort, allow html if it can render (should be rare)
        for r in _RENDERERS:
            if r.can_render(obj):
                return r
        return None

    # 3) Default: first match wins
    for r in _RENDERERS:
        if r.can_render(obj):
            return r
    return None


def render_any(obj: Any, *, view_id: str, kind_hint: str | None = None) -> RenderResult:
    r = choose_renderer(obj, kind_hint=kind_hint)
    if r is None:
        # fallback: repr
        from ..artifacts import Truncation

        return RenderResult(
            kind="text",
            html=f"<pre>{_escape_html(repr(obj))}</pre>",
            truncation=Truncation(truncated=False),
            meta={"fallback": True},
        )
    return r.render(obj, view_id=view_id)


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _looks_like_html(s: str) -> bool:
    """
    Conservative heuristic: only treat as HTML if it starts with a tag-ish token.
    """
    t = s.lstrip()
    if not t.startswith("<"):
        return False
    head = t[:2000]
    # must contain a close angle bracket early-ish
    if ">" not in head:
        return False
    # common tag-ish starters
    starters = (
        "<!doctype",
        "<html",
        "<div",
        "<span",
        "<p",
        "<pre",
        "<code",
        "<table",
        "<details",
        "<summary",
    )
    return head.lower().startswith(starters) or head[1:2].isalpha()
