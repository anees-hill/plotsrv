# tests/test_renderers_json_tree.py
from __future__ import annotations

from plotsrv.renderers.json_tree import JsonTreeRenderer
from plotsrv.renderers.limits import JsonLimits


def test_json_tree_renders_toolbar_and_tree() -> None:
    r = JsonTreeRenderer()
    out = r.render({"a": 1, "b": {"c": 2}}, view_id="v1")
    assert out.kind == "json"
    assert 'data-plotsrv-toolbar="json"' in out.html
    assert 'data-plotsrv-json="1"' in out.html
    assert out.meta and out.meta["view_id"] == "v1"
    assert out.truncation is not None
    assert out.truncation.truncated is False


def test_json_tree_truncates_by_depth() -> None:
    r = JsonTreeRenderer(
        limits=JsonLimits(
            max_depth=0,
            max_nodes=5000,
            max_string_chars=1000,
            max_list_items=200,
            max_dict_items=200,
        )
    )
    out = r.render({"a": {"b": {"c": 1}}}, view_id="v1")
    assert out.truncation is not None
    assert out.truncation.truncated is True
    assert out.truncation.details and out.truncation.details.get("hit") in (
        "max_depth",
        "max_nodes",
    )


def test_json_tree_truncates_by_dict_items() -> None:
    r = JsonTreeRenderer(
        limits=JsonLimits(
            max_depth=10,
            max_nodes=5000,
            max_string_chars=1000,
            max_list_items=200,
            max_dict_items=2,
        )
    )
    out = r.render({"a": 1, "b": 2, "c": 3}, view_id="v1")
    assert out.truncation is not None
    assert out.truncation.truncated is True
    assert out.truncation.details and out.truncation.details.get("hit") in (
        "max_dict_items",
        "max_nodes",
        "max_depth",
    )
    assert "more keys" in out.html
