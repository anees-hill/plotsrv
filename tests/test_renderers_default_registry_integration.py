# tests/test_renderers_default_registry_integration.py
from __future__ import annotations

import plotsrv.renderers.registry as reg
from plotsrv.renderers import register_default_renderers


def _reset_registry() -> None:
    reg._RENDERERS.clear()


def test_register_default_renderers_registers_expected_kinds_in_order() -> None:
    _reset_registry()
    register_default_renderers()

    kinds = [getattr(r, "kind", None) for r in reg._RENDERERS]
    # This order is important for safety: Text should come before Html.
    assert kinds == [
        "plot",
        "table",
        "image",
        "markdown",
        "json",
        "python",
        "traceback",
        "text",
        "html",
    ]


def test_choose_renderer_string_prefers_python_over_html_and_text() -> None:
    _reset_registry()
    register_default_renderers()

    # "python" renderer can_render(str) => registry should choose python first
    r = reg.choose_renderer("x = 1\nprint(x)")
    assert r is not None
    assert r.kind == "python"


def test_choose_renderer_string_htmlish_still_prefers_python_if_present() -> None:
    _reset_registry()
    register_default_renderers()

    # Even if it looks like HTML, python renderer wins (by design of current policy)
    # (If later you decide htmlish should override python, this test should be adjusted.)
    r = reg.choose_renderer("<div>hello</div>")
    assert r is not None
    assert r.kind == "python"


def test_render_any_with_kind_hint_can_force_html() -> None:
    _reset_registry()
    register_default_renderers()

    rr = reg.render_any("<div>hello</div>", view_id="v1", kind_hint="html")
    assert rr.kind == "html"
    assert "plotsrv-html" in rr.html or "iframe" in rr.html
