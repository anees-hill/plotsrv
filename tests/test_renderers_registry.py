# tests/test_renderers_registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import plotsrv.renderers.registry as reg
from plotsrv.renderers.base import RenderResult
from plotsrv.artifacts import Truncation


def _reset_registry() -> None:
    # registry is module-global; clear it between tests
    reg._RENDERERS.clear()


@dataclass
class DummyRenderer:
    kind: str
    _can: bool = True

    def can_render(self, obj: Any) -> bool:
        return self._can

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        return RenderResult(
            kind=self.kind,  # type: ignore[arg-type]
            html=f"<div>{self.kind}:{view_id}</div>",
            truncation=Truncation(truncated=False),
            meta={"obj": obj},
        )


def test_choose_renderer_honours_kind_hint_first() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="text", _can=True))
    reg.register_renderer(DummyRenderer(kind="html", _can=True))

    r = reg.choose_renderer("<div>hi</div>", kind_hint="html")
    assert r is not None
    assert r.kind == "html"


def test_choose_renderer_string_prefers_text_over_html_when_not_htmlish() -> None:
    _reset_registry()
    # html renderer can render any str, but should not win for plain text
    reg.register_renderer(DummyRenderer(kind="html", _can=True))
    reg.register_renderer(DummyRenderer(kind="text", _can=True))

    r = reg.choose_renderer("just some text")
    assert r is not None
    assert r.kind == "text"


def test_choose_renderer_string_allows_html_when_htmlish() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="text", _can=True))
    reg.register_renderer(DummyRenderer(kind="html", _can=True))

    r = reg.choose_renderer("<div>hello</div>")
    assert r is not None
    assert r.kind == "text" or r.kind == "html"
    # BUT due to special htmlish branch, html should be chosen only if preferred kinds don't match.
    # Our dummy "text" always matches, so to test html selection we need text to decline:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="text", _can=False))
    reg.register_renderer(DummyRenderer(kind="html", _can=True))

    r2 = reg.choose_renderer("<div>hello</div>")
    assert r2 is not None
    assert r2.kind == "html"


def test_looks_like_html_heuristic() -> None:
    assert reg._looks_like_html("<div>x</div>") is True
    assert reg._looks_like_html(" <span>x</span>") is True
    assert reg._looks_like_html("nope <div>") is False
    assert reg._looks_like_html("<notclosed") is False


def test_render_any_falls_back_to_repr_when_no_renderer() -> None:
    _reset_registry()

    class X:
        def __repr__(self) -> str:
            return "<X&>"

    rr = reg.render_any(X(), view_id="v1")
    assert rr.kind == "text"
    assert "&lt;X&amp;&gt;" in rr.html
    assert rr.meta and rr.meta.get("fallback") is True


def test_render_any_uses_renderer_when_available() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="text", _can=True))

    rr = reg.render_any("hi", view_id="v1")
    assert rr.html == "<div>text:v1</div>"
