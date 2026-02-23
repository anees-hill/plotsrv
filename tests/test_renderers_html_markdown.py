# tests/test_renderers_html_markdown.py
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

import plotsrv.renderers.html as html_mod
import plotsrv.renderers.markdown as md_mod


# ----------------------------
# HTML renderer tests
# ----------------------------


def test_strip_style_and_script_blocks() -> None:
    raw = "<div>ok</div><script>alert(1)</script><style>body{}</style><p>x</p>"
    out = html_mod.strip_style_and_script_blocks(raw)
    assert "<script" not in out.lower()
    assert "<style" not in out.lower()
    assert "<div>ok</div>" in out
    assert "<p>x</p>" in out


def test_html_renderer_unsafe_iframe_mode() -> None:
    r = html_mod.HtmlRenderer()
    obj = {
        "html": "<h1>Hi</h1><script>alert(1)</script>",
        "unsafe": True,
        "sandbox": "allow-forms",
    }
    rr = r.render(obj, view_id="v1")

    assert rr.kind == "html"
    assert rr.meta and rr.meta["mode"] == "unsafe_iframe"
    assert "sandbox=" in rr.html
    assert "allow-forms" in rr.html
    assert "srcdoc=" in rr.html
    # Unsafe mode must NOT sanitize; HTML appears inside srcdoc
    assert (
        "&lt;h1&gt;" not in rr.html
    )  # iframe srcdoc is raw-html escaped only for attribute quoting
    assert "<h1>Hi</h1>" in rr.html


def test_html_renderer_safe_mode_without_bleach_escapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force bleach import to fail even if installed
    monkeypatch.delitem(sys.modules, "bleach", raising=False)

    import builtins

    real_import = builtins.__import__

    def deny_bleach(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "bleach" or name.startswith("bleach."):
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", deny_bleach)

    r = html_mod.HtmlRenderer()
    rr = r.render("<div>Hi</div><script>alert(1)</script>", view_id="v1")

    assert rr.kind == "html"
    assert rr.meta and rr.meta["mode"] == "escaped_preview"
    assert "Install <code>bleach</code>" in rr.html
    # Must be escaped (safe preview)
    assert "&lt;div&gt;Hi&lt;/div&gt;" in rr.html
    # Don't assert script presence; implementation may strip it before preview.
    assert "<script" not in rr.html.lower()


def test_html_renderer_safe_mode_with_bleach_sanitizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fake bleach module
    def fake_clean(s: str, **kwargs: Any) -> str:
        # crude "sanitize": strip script/style blocks (like real flow) and remove any remaining "<script"
        s2 = html_mod.strip_style_and_script_blocks(s)
        return s2.replace("<script", "&lt;script").replace(
            "</script>", "&lt;/script&gt;"
        )

    def fake_linkify(s: str, callbacks: Any = None) -> str:
        return s  # no-op

    fake_bleach = SimpleNamespace(
        clean=fake_clean,
        linkify=fake_linkify,
        callbacks=SimpleNamespace(nofollow=lambda attrs, new=False: attrs),
    )
    monkeypatch.setitem(sys.modules, "bleach", fake_bleach)

    r = html_mod.HtmlRenderer()
    rr = r.render("<div>Hi</div><script>alert(1)</script>", view_id="v1")

    assert rr.kind == "html"
    assert rr.meta and rr.meta["mode"] == "sanitized"
    assert "plotsrv-html--sanitized" in rr.html
    assert "<div>Hi</div>" in rr.html
    assert "<script" not in rr.html.lower()


# ----------------------------
# Markdown renderer tests
# ----------------------------


def test_markdown_renderer_can_render() -> None:
    r = md_mod.MarkdownRenderer()
    assert r.can_render("x") is True
    assert r.can_render({"text": "x"}) is True
    assert r.can_render({"nope": "x"}) is False


def test_markdown_render_missing_markdown_package_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force markdown import to fail even if installed
    monkeypatch.delitem(sys.modules, "markdown", raising=False)

    import builtins

    real_import = builtins.__import__

    def deny_markdown(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "markdown" or name.startswith("markdown."):
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", deny_markdown)

    r = md_mod.MarkdownRenderer()
    rr = r.render("# Hi <b>x</b>", view_id="v1")

    assert rr.kind == "markdown"
    assert rr.meta and rr.meta["rendered"] is False
    assert "markdown render failed" in (rr.meta.get("note") or "")
    # Escaped fallback
    assert "&lt;b&gt;" in rr.html


def test_markdown_bleach_missing_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Provide fake markdown module (so markdown step succeeds)
    fake_markdown = SimpleNamespace(
        markdown=lambda text, extensions=None: "<h1>Hi</h1><script>alert(1)</script>"
    )
    monkeypatch.setitem(sys.modules, "markdown", fake_markdown)

    # Force bleach import to fail even if installed
    monkeypatch.delitem(sys.modules, "bleach", raising=False)

    import builtins

    real_import = builtins.__import__

    def deny_bleach(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "bleach" or name.startswith("bleach."):
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", deny_bleach)

    r = md_mod.MarkdownRenderer()
    rr = r.render("# Hi", view_id="v1")  # unsafe_html False by default

    assert rr.kind == "markdown"
    # Must fail closed (do NOT show unsanitized html_body)
    assert rr.meta and rr.meta["rendered"] is False
    assert "sanitization is not available" in rr.html.lower()
    assert "<script" not in rr.html.lower()


def test_markdown_unsafe_html_true_allows_raw_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_markdown = SimpleNamespace(
        markdown=lambda text, extensions=None: "<p>Hi</p><script>alert(1)</script>"
    )
    monkeypatch.setitem(sys.modules, "markdown", fake_markdown)

    # bleach irrelevant here; unsafe_html bypasses sanitization
    monkeypatch.delitem(sys.modules, "bleach", raising=False)

    r = md_mod.MarkdownRenderer()
    rr = r.render({"text": "hi", "unsafe_html": True}, view_id="v1")

    assert rr.kind == "markdown"
    assert rr.meta and rr.meta["rendered"] is True
    assert rr.meta["unsafe_html"] is True
    assert rr.meta["sanitized"] is False
    assert "<script" in rr.html.lower()


def test_markdown_bleach_present_sanitizes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_markdown = SimpleNamespace(
        markdown=lambda text, extensions=None: "<p>Hi</p><script>alert(1)</script>"
    )
    monkeypatch.setitem(sys.modules, "markdown", fake_markdown)

    def fake_clean(html: str, **kwargs: Any) -> str:
        # remove script blocks
        return html.replace("<script>alert(1)</script>", "")

    def fake_linkify(html: str) -> str:
        return html

    fake_bleach = SimpleNamespace(clean=fake_clean, linkify=fake_linkify)
    monkeypatch.setitem(sys.modules, "bleach", fake_bleach)

    r = md_mod.MarkdownRenderer()
    rr = r.render("hi", view_id="v1")  # unsafe_html False => sanitize

    assert rr.kind == "markdown"
    assert rr.meta and rr.meta["rendered"] is True
    assert rr.meta["unsafe_html"] is False
    assert rr.meta["sanitized"] is True
    assert "<script" not in rr.html.lower()
    assert "<p>Hi</p>" in rr.html
