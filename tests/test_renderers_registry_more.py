from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import plotsrv.renderers.registry as reg
from plotsrv.artifacts import Truncation
from plotsrv.renderers.base import RenderResult


def _reset_registry() -> None:
    reg._RENDERERS.clear()


@dataclass
class DummyRenderer:
    kind: str
    can: bool = True

    def can_render(self, obj: Any) -> bool:
        return self.can

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        return RenderResult(
            kind=self.kind,  # type: ignore[arg-type]
            html=f"<div>{self.kind}:{view_id}</div>",
            truncation=Truncation(truncated=False),
            meta={"kind": self.kind},
        )


def test_register_renderer_appends() -> None:
    _reset_registry()
    r = DummyRenderer(kind="text")
    reg.register_renderer(r)
    assert reg._RENDERERS[-1] is r


def test_choose_renderer_kind_hint_falls_back_when_hint_cannot_render() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="html", can=False))
    reg.register_renderer(DummyRenderer(kind="text", can=True))

    r = reg.choose_renderer("hello", kind_hint="html")
    assert r is not None
    assert r.kind == "text"


def test_choose_renderer_string_prefers_python_then_traceback_then_text_then_json() -> (
    None
):
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="html", can=True))
    reg.register_renderer(DummyRenderer(kind="json", can=True))
    reg.register_renderer(DummyRenderer(kind="text", can=True))
    reg.register_renderer(DummyRenderer(kind="python", can=True))

    r = reg.choose_renderer("print('x')")
    assert r is not None
    assert r.kind == "python"


def test_choose_renderer_string_can_choose_traceback_when_python_declines() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="python", can=False))
    reg.register_renderer(DummyRenderer(kind="traceback", can=True))
    reg.register_renderer(DummyRenderer(kind="text", can=True))

    r = reg.choose_renderer("Traceback...")
    assert r is not None
    assert r.kind == "traceback"


def test_choose_renderer_non_html_string_skips_html_in_fallback_branch() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="html", can=True))
    reg.register_renderer(DummyRenderer(kind="custom", can=True))

    r = reg.choose_renderer("plain text")
    assert r is not None
    assert r.kind == "custom"


def test_choose_renderer_last_resort_allows_html_when_only_html_matches() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="html", can=True))

    r = reg.choose_renderer("plain text")
    assert r is not None
    assert r.kind == "html"


def test_choose_renderer_non_string_default_first_match() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="json", can=True))
    reg.register_renderer(DummyRenderer(kind="text", can=True))

    r = reg.choose_renderer({"a": 1})
    assert r is not None
    assert r.kind == "json"


def test_choose_renderer_returns_none_when_nothing_matches() -> None:
    _reset_registry()
    reg.register_renderer(DummyRenderer(kind="text", can=False))
    assert reg.choose_renderer("hello") is None


def test_escape_html_escapes_all_special_chars() -> None:
    s = reg._escape_html("""<&>"'""")
    assert s == "&lt;&amp;&gt;&quot;&#39;"


def test_looks_like_html_more_cases() -> None:
    assert reg._looks_like_html("<!DOCTYPE html><html></html>") is True
    assert reg._looks_like_html("<table><tr></tr></table>") is True
    assert reg._looks_like_html("<custom-tag>hi</custom-tag>") is True
    assert reg._looks_like_html("   <x>hi</x>") is True
    assert reg._looks_like_html("   no <div>x</div>") is False
    assert reg._looks_like_html("<") is False
    assert reg._looks_like_html("<notclosed") is False
