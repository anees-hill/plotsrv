# src/plotsrv/renderers/registry.py
from __future__ import annotations

from typing import Any

from .base import Renderer, RenderResult


_RENDERERS: list[Renderer] = []


def register_renderer(r: Renderer) -> None:
    _RENDERERS.append(r)


def choose_renderer(obj: Any, *, kind_hint: str | None = None) -> Renderer | None:
    # If a hint is provided, try those first
    if kind_hint:
        for r in _RENDERERS:
            if getattr(r, "kind", None) == kind_hint and r.can_render(obj):
                return r

    # Otherwise first match wins
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
            kind="text",  # best-effort
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
