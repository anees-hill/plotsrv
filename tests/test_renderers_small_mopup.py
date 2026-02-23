# tests/test_renderers_small_mopup.py
from __future__ import annotations

from plotsrv.renderers.image import ImageRenderer
from plotsrv.renderers.python import PythonRenderer
from plotsrv.renderers.traceback import TracebackRenderer


def test_python_renderer_escapes_html() -> None:
    r = PythonRenderer()
    out = r.render("x = '<tag>'", view_id="v1")
    assert out.kind == "python"
    assert "&lt;tag&gt;" in out.html
    assert out.meta and out.meta["view_id"] == "v1"


def test_traceback_renderer_can_render_false_on_bad_payloads() -> None:
    r = TracebackRenderer()
    assert r.can_render("nope") is False
    assert r.can_render({"type": "traceback", "frames": "nope"}) is False
    assert r.can_render({"type": "nope", "frames": []}) is False


def test_traceback_renderer_escapes_fields() -> None:
    r = TracebackRenderer()
    payload = {
        "type": "traceback",
        "exc_type": "<Bad>",
        "exc_msg": "x & y",
        "frames": [
            {
                "filename": "<f.py>",
                "lineno": 1,
                "function": "fn<script>",
                "line": "raise <bad>",
                "context_before": ["a & b"],
                "context_after": ["</tag>"],
            }
        ],
    }
    out = r.render(payload, view_id="v1")
    assert "&lt;Bad&gt;" in out.html
    assert "x &amp; y" in out.html
    assert "fn&lt;script&gt;" in out.html
    assert "&lt;f.py&gt;:1" in out.html
    assert "&lt;bad&gt;" in out.html


def test_image_renderer_can_render_false_without_required_keys() -> None:
    r = ImageRenderer()
    assert r.can_render({"mime": "image/png"}) is False
    assert r.can_render({"data_b64": "abc"}) is False
    assert r.can_render("nope") is False
