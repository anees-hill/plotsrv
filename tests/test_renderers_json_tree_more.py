# tests/test_renderers_json_tree_more.py
from __future__ import annotations

from plotsrv.renderers.json_tree import JsonTreeRenderer
from plotsrv.renderers.limits import JsonLimits


def test_json_tree_truncates_by_list_items_and_renders_more_badge() -> None:
    r = JsonTreeRenderer(
        limits=JsonLimits(
            max_depth=10,
            max_nodes=5000,
            max_string_chars=1000,
            max_list_items=2,
            max_dict_items=200,
        )
    )
    out = r.render({"xs": [1, 2, 3, 4]}, view_id="v1")

    assert out.truncation is not None
    assert out.truncation.truncated is True
    assert out.truncation.details and out.truncation.details.get("hit") in (
        "max_list_items",
        "max_nodes",
        "max_depth",
        "max_string_chars",
    )
    assert "more items" in out.html


def test_json_tree_truncates_by_string_chars_and_marks_truncation() -> None:
    r = JsonTreeRenderer(
        limits=JsonLimits(
            max_depth=10,
            max_nodes=5000,
            max_string_chars=3,
            max_list_items=200,
            max_dict_items=200,
        )
    )
    out = r.render({"a": "abcdefgh"}, view_id="v1")
    assert out.truncation is not None
    assert out.truncation.truncated is True
    assert out.truncation.details and out.truncation.details.get("hit") in (
        "max_string_chars",
        "max_nodes",
        "max_depth",
    )
    assert "abc…" in out.html


def test_json_tree_truncates_by_max_nodes() -> None:
    # Force max_nodes extremely low so we trip the node cap quickly
    r = JsonTreeRenderer(
        limits=JsonLimits(
            max_depth=10,
            max_nodes=3,
            max_string_chars=1000,
            max_list_items=200,
            max_dict_items=200,
        )
    )
    big = {"a": {"b": {"c": {"d": 1}}}}
    out = r.render(big, view_id="v1")

    assert out.truncation is not None
    assert out.truncation.truncated is True
    assert out.truncation.details and out.truncation.details.get("hit") in (
        "max_nodes",
        "max_depth",
    )
    assert "node limit" in out.html or "…" in out.html
