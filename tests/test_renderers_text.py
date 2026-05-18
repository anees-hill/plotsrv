from __future__ import annotations

from plotsrv.renderers.text import (
    ANCHOR_PREFIX,
    TextPayload,
    TextRenderer,
    _strip_anchor_header,
    _to_text_and_anchor,
)


def test_strip_anchor_header_head_default() -> None:
    text, anchor = _strip_anchor_header("hello")
    assert text == "hello"
    assert anchor == "head"


def test_strip_anchor_header_tail() -> None:
    text, anchor = _strip_anchor_header(ANCHOR_PREFIX + "tail\nhello")
    assert text == "hello"
    assert anchor == "tail"


def test_strip_anchor_header_unknown_defaults_head() -> None:
    text, anchor = _strip_anchor_header(ANCHOR_PREFIX + "whatever\nhello")
    assert text == "hello"
    assert anchor == "head"


def test_strip_anchor_header_without_newline() -> None:
    text, anchor = _strip_anchor_header(ANCHOR_PREFIX + "tail")
    assert text == ""
    assert anchor == "tail"


def test_to_text_and_anchor_text_payload() -> None:
    text, anchor = _to_text_and_anchor(TextPayload("abc", anchor="tail"))
    assert text == "abc"
    assert anchor == "tail"


def test_to_text_and_anchor_bytes_valid_utf8() -> None:
    text, anchor = _to_text_and_anchor(b"hello")
    assert text == "hello"
    assert anchor == "head"


def test_to_text_and_anchor_repr_fallback() -> None:
    text, anchor = _to_text_and_anchor({"a": 1})
    assert text == "{'a': 1}"
    assert anchor == "head"


def test_text_renderer_includes_new_toolbar_controls(monkeypatch) -> None:
    monkeypatch.setattr(
        "plotsrv.config.get_truncation_max_chars", lambda kind, view_id=None: 100
    )

    out = TextRenderer().render("INFO hello", view_id="v1")

    assert 'data-plotsrv-action="copy"' in out.html
    assert 'data-plotsrv-action="wrap"' in out.html
    assert 'data-plotsrv-action="reverse"' in out.html
    assert 'data-plotsrv-action="colour"' in out.html
    assert 'data-plotsrv-text-reverse-indicator="1"' in out.html
    assert 'data-plotsrv-text-anchor="head"' in out.html


def test_text_renderer_tail_anchor_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "plotsrv.config.get_truncation_max_chars", lambda kind, view_id=None: 100
    )

    out = TextRenderer().render(TextPayload("hello", anchor="tail"), view_id="v1")

    assert out.meta["anchor"] == "tail"
    assert 'data-plotsrv-text-anchor="tail"' in out.html


def test_text_renderer_passes_view_id_to_truncation_config(monkeypatch) -> None:
    calls = []

    def fake_get_truncation_max_chars(kind, view_id=None):
        calls.append((kind, view_id))
        return 5

    monkeypatch.setattr(
        "plotsrv.config.get_truncation_max_chars",
        fake_get_truncation_max_chars,
    )

    out = TextRenderer().render("abcdefghijk", view_id="logs:api")

    assert calls == [("text", "logs:api")]
    assert out.truncation is not None
    assert out.truncation.truncated is True
