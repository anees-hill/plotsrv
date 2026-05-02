# tests/test_json_model.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from plotsrv.json_model import (
    JsonModelLimits,
    _coerce_limits,
    build_json_document,
    build_pretty_text,
    classify_json_value,
    looks_like_image_payload,
)


def _child(root: dict[str, Any], key: str) -> dict[str, Any]:
    for ch in root["children"]:
        if ch["display_key"] == key:
            return ch
    raise AssertionError(f"Missing child {key!r}")


def test_build_json_document_basic_dict() -> None:
    doc = build_json_document(
        {"a": 1, "b": [2, 3]},
        source_format="python_object",
        raw_text=None,
        source_filename=None,
    )

    assert doc["type"] == "plotsrv_json_document"
    assert doc["version"] == 1
    assert doc["source_format"] == "python_object"
    assert doc["raw_text"] is None
    assert doc["meta"]["truncated"] is False
    assert doc["root"]["display_key"] == "root"

    a = _child(doc["root"], "a")
    assert a["preview"] == "1"
    assert a["full_value"] == "1"
    assert a["preview_truncated"] is False

    b = _child(doc["root"], "b")
    assert b["value_kind"] == "list"
    assert b["child_count"] == 2


def test_build_json_document_preserves_raw_text_and_filename() -> None:
    doc = build_json_document(
        {"a": 1},
        source_format="json_file",
        raw_text='{"a": 1}',
        source_filename="x.json",
    )

    assert doc["raw_text"] == '{"a": 1}'
    assert doc["meta"]["source_filename"] == "x.json"


def test_build_json_document_truncates_by_depth() -> None:
    doc = build_json_document(
        {"a": {"b": 1}},
        source_format="python_object",
        limits=JsonModelLimits(max_depth=0),
    )

    assert doc["meta"]["truncated"] is True
    assert doc["meta"]["hit"] == "max_depth"
    assert doc["root"]["truncated"] is True
    assert doc["root"]["truncation_reason"] == "depth limit"


def test_build_json_document_truncates_dict_items() -> None:
    doc = build_json_document(
        {"a": 1, "b": 2, "c": 3},
        source_format="python_object",
        limits=JsonModelLimits(max_dict_items=2),
    )

    assert doc["meta"]["truncated"] is True
    assert doc["meta"]["hit"] == "max_dict_items"
    assert doc["root"]["truncated"] is True
    assert doc["root"]["truncation_reason"] == "dict item limit"
    assert len(doc["root"]["children"]) == 2


def test_build_json_document_truncates_list_items() -> None:
    doc = build_json_document(
        {"xs": [1, 2, 3]},
        source_format="python_object",
        limits=JsonModelLimits(max_list_items=2),
    )

    xs = _child(doc["root"], "xs")
    assert doc["meta"]["truncated"] is True
    assert doc["meta"]["hit"] == "max_list_items"
    assert xs["truncated"] is True
    assert xs["truncation_reason"] == "list item limit"
    assert len(xs["children"]) == 2


def test_build_json_document_truncates_string_preview() -> None:
    doc = build_json_document(
        {"a": "abcdef"},
        source_format="python_object",
        limits=JsonModelLimits(max_preview_chars=3, max_string_chars=3),
    )

    a = _child(doc["root"], "a")
    assert doc["meta"]["truncated"] is True
    assert doc["meta"]["hit"] == "max_string_chars"
    assert a["preview"] == "abc…"
    assert a["full_value"] == "abcdef"
    assert a["preview_truncated"] is True
    assert a["truncation_reason"] == "string preview limit"


def test_build_json_document_truncates_by_max_nodes() -> None:
    doc = build_json_document(
        {"a": {"b": {"c": 1}}},
        source_format="python_object",
        limits=JsonModelLimits(max_nodes=2),
    )

    assert doc["meta"]["truncated"] is True
    assert doc["meta"]["hit"] == "max_nodes"


def test_build_json_document_handles_tuples_and_sets() -> None:
    doc = build_json_document(
        {"t": (1, 2), "s": {"x", "y"}},
        source_format="python_object",
    )

    t = _child(doc["root"], "t")
    s = _child(doc["root"], "s")
    assert t["value_kind"] == "list"
    assert t["type_label"] == "tuple"
    assert s["value_kind"] == "list"
    assert s["type_label"] == "set"


def test_classify_json_value_scalars() -> None:
    assert classify_json_value("x")["node_kind"] == "scalar"
    assert classify_json_value(1)["value_kind"] == "int"
    assert classify_json_value(1.2)["value_kind"] == "float"
    assert classify_json_value(True)["value_kind"] == "bool"
    assert classify_json_value(None)["type_label"] == "NoneType"


def test_image_payload_detection_and_classification() -> None:
    payload = {"mime": "image/png", "data_b64": "abc", "filename": "x.png"}
    assert looks_like_image_payload(payload) is True
    cls = classify_json_value(payload)
    assert cls["value_kind"] == "dict"  # image payload is still a dict first


def test_build_pretty_text_with_unserializable_object() -> None:
    class X:
        def __repr__(self) -> str:
            return "<X>"

    text = build_pretty_text({"x": X()})
    assert "<X>" in text


@dataclass
class DuckLimits:
    max_depth: int = 1
    max_nodes: int = 2
    max_dict_items: int = 3
    max_list_items: int = 4
    max_string_chars: int = 5


def test_coerce_limits_accepts_duck_typed_limits() -> None:
    out = _coerce_limits(DuckLimits())
    assert out.max_depth == 1
    assert out.max_nodes == 2
    assert out.max_dict_items == 3
    assert out.max_list_items == 4
    assert out.max_string_chars == 5
    assert out.max_preview_chars == 5


def test_build_json_document_dataframe_if_pandas_available() -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"a": [1, 2]})

    doc = build_json_document({"df": df}, source_format="python_object")
    df_node = _child(doc["root"], "df")

    assert df_node["node_kind"] == "leaf_artifact"
    assert df_node["value_kind"] == "table"
    assert "DataFrame" in df_node["preview"]
