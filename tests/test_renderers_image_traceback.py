# tests/test_renderers_image_traceback.py
from __future__ import annotations

from plotsrv.renderers.image import ImageRenderer
from plotsrv.renderers.traceback import TracebackRenderer


def test_image_renderer_can_render_and_embeds_data_uri() -> None:
    r = ImageRenderer()
    obj = {"mime": "image/png", "data_b64": "abcd", "filename": "x.png"}
    assert r.can_render(obj) is True
    out = r.render(obj, view_id="v1")
    assert out.kind == "image"
    assert "data:image/png;base64,abcd" in out.html
    assert "x.png" in out.html
    assert out.meta and out.meta["mime"] == "image/png"


def test_traceback_renderer_renders_frames() -> None:
    r = TracebackRenderer()
    payload = {
        "type": "traceback",
        "exc_type": "ValueError",
        "exc_msg": "bad",
        "frames": [
            {
                "filename": "a.py",
                "lineno": 10,
                "function": "fn",
                "line": "raise ValueError()",
                "context_before": ["x=1"],
                "context_after": ["y=2"],
            }
        ],
    }
    assert r.can_render(payload) is True
    out = r.render(payload, view_id="v1")
    assert out.kind == "traceback"
    assert "ValueError" in out.html
    assert "a.py:10" in out.html
    assert "<details" in out.html
    assert "<mark>" in out.html
    assert out.meta and out.meta["frames"] == 1
