# tests/test_renderers_limits_text.py
from __future__ import annotations

from plotsrv.renderers.limits import TextLimits, truncate_text, safe_scalar_text
from plotsrv.renderers.text import TextRenderer


def test_truncate_text_no_truncation() -> None:
    s = "hello\nworld\n"
    out, trunc = truncate_text(s, limits=TextLimits(max_chars=100, max_lines=None))
    assert out == s
    assert trunc.truncated is False


def test_truncate_text_by_max_chars_appends_ellipsis() -> None:
    s = "x" * 10
    out, trunc = truncate_text(s, limits=TextLimits(max_chars=5, max_lines=None))
    assert out.startswith("x" * 5)
    assert out.endswith("…") or out.endswith("\n…")
    assert trunc.truncated is True
    assert trunc.reason == "text truncated by limits"
    assert trunc.details and trunc.details.get("truncated_by") == "max_chars"


def test_truncate_text_by_max_lines_then_chars() -> None:
    s = "a\nb\nc\nd\n"
    out, trunc = truncate_text(s, limits=TextLimits(max_chars=3, max_lines=2))
    # first trunc to 2 lines => "a\nb\n" then max_chars => "a\nb"
    assert "…" in out
    assert trunc.truncated is True
    assert trunc.details and trunc.details.get("truncated_by") in (
        "max_lines",
        "max_chars",
    )


def test_safe_scalar_text_truncates() -> None:
    s, was = safe_scalar_text("x" * 10, max_chars=4)
    assert s == "xxxx…"
    assert was is True


def test_text_renderer_renders_toolbar_and_pre() -> None:
    r = TextRenderer(limits=TextLimits(max_chars=100, max_lines=None))
    out = r.render("hello <b>world</b>", view_id="v1")
    assert out.kind == "text"
    assert "data-plotsrv-toolbar" in out.html
    assert "data-plotsrv-pre" in out.html
    # html should be escaped
    assert "&lt;b&gt;" in out.html
    assert out.meta and out.meta["view_id"] == "v1"


def test_text_renderer_bytes_decode() -> None:
    r = TextRenderer(limits=TextLimits(max_chars=100, max_lines=None))
    out = r.render(b"\xff", view_id="v1")
    assert out.kind == "text"
    assert "plotsrv-pre" in out.html
