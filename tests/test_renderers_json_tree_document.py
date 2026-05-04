# tests/test_renderers_json_tree_document.py
from __future__ import annotations

from typing import Any

from plotsrv.renderers.json_tree import JsonTreeRenderer


def _child(root: dict[str, Any], key: str) -> dict[str, Any]:
    for ch in root["children"]:
        if ch["display_key"] == key:
            return ch
    raise AssertionError(f"Missing child {key!r}")


def _doc() -> dict[str, Any]:
    return {
        "type": "plotsrv_json_document",
        "version": 1,
        "source_format": "json_file",
        "raw_text": '{"a": 1, "long": "abcdef"}',
        "pretty_text": '{\n  "a": 1,\n  "long": "abcdef"\n}',
        "root": {
            "id": "root",
            "path": [],
            "depth": 0,
            "label": "root",
            "display_key": "root",
            "node_kind": "container",
            "value_kind": "dict",
            "type_label": "object",
            "icon_key": "json",
            "summary": "2 keys",
            "preview": None,
            "full_value": None,
            "preview_truncated": False,
            "child_count": 2,
            "descendant_count": 2,
            "descendant_layer_count": 1,
            "expandable": True,
            "children": [
                {
                    "id": "root/a",
                    "path": ["a"],
                    "depth": 1,
                    "label": "a",
                    "display_key": "a",
                    "node_kind": "scalar",
                    "value_kind": "int",
                    "type_label": "int",
                    "icon_key": None,
                    "summary": None,
                    "preview": "1",
                    "full_value": "1",
                    "preview_truncated": False,
                    "child_count": 0,
                    "descendant_count": 0,
                    "descendant_layer_count": 0,
                    "expandable": False,
                    "children": [],
                    "truncated": False,
                    "truncation_reason": None,
                },
                {
                    "id": "root/long",
                    "path": ["long"],
                    "depth": 1,
                    "label": "long",
                    "display_key": "long",
                    "node_kind": "scalar",
                    "value_kind": "str",
                    "type_label": "str",
                    "icon_key": None,
                    "summary": None,
                    "preview": "abc…",
                    "full_value": "abcdef",
                    "preview_truncated": True,
                    "child_count": 0,
                    "descendant_count": 0,
                    "descendant_layer_count": 0,
                    "expandable": False,
                    "children": [],
                    "truncated": False,
                    "truncation_reason": None,
                },
            ],
            "truncated": False,
            "truncation_reason": None,
        },
        "meta": {
            "node_count": 3,
            "max_depth_seen": 1,
            "truncated": False,
            "hit": None,
            "source_filename": "x.json",
        },
    }


def test_json_tree_renders_document_payload() -> None:
    r = JsonTreeRenderer()
    out = r.render(_doc(), view_id="v1")

    assert out.kind == "json"
    assert 'data-plotsrv-json-source-format="json_file"' in out.html
    assert 'data-json-panel="json"' in out.html
    assert 'data-json-panel="simple"' in out.html
    assert 'data-json-panel="text"' in out.html
    assert "Pinned values" in out.html
    assert out.meta and out.meta["source_format"] == "json_file"
    assert out.meta["has_raw_text"] is True


def test_json_tree_scalar_rows_include_pin_metadata_and_hidden_value() -> None:
    r = JsonTreeRenderer()
    out = r.render(_doc(), view_id="v1")

    assert 'data-json-pin-toggle="root/a"' in out.html
    assert 'data-json-key="a"' in out.html
    assert 'data-json-full-value="1"' in out.html
    assert 'data-json-full-value-text="1"' in out.html
    assert ">1</pre>" in out.html


def test_json_tree_uses_pretty_text_when_raw_text_missing() -> None:
    doc = _doc()
    doc["raw_text"] = None
    doc["pretty_text"] = "PRETTY TEXT"

    r = JsonTreeRenderer()
    out = r.render(doc, view_id="v1")

    assert 'data-plotsrv-json-raw-text="null"' in out.html
    assert "PRETTY TEXT" in out.html


def test_json_tree_invalid_document_payload_falls_back_safely() -> None:
    r = JsonTreeRenderer()
    out = r.render(
        {
            "type": "plotsrv_json_document",
            "root": "not-a-dict",
            "meta": {},
        },
        view_id="v1",
    )

    assert out.kind == "json"
    assert "Invalid JSON document payload" in out.html
    assert out.meta and out.meta["invalid_document"] is True
    assert out.truncation is not None
    assert out.truncation.truncated is False


def test_json_tree_truncation_metadata_in_document_payload() -> None:
    doc = _doc()
    doc["meta"]["truncated"] = True
    doc["meta"]["hit"] = "max_nodes"

    r = JsonTreeRenderer()
    out = r.render(doc, view_id="v1")

    assert out.truncation is not None
    assert out.truncation.truncated is True
    assert out.truncation.reason == "json tree truncated by limits"
    assert out.truncation.details
    assert out.truncation.details["hit"] == "max_nodes"


def test_json_tree_truncated_node_badge_texts() -> None:
    doc = _doc()
    first = doc["root"]["children"][0]
    first["truncated"] = True
    first["truncation_reason"] = "dict item limit"

    r = JsonTreeRenderer()
    out = r.render(doc, view_id="v1")

    assert "more keys" in out.html
