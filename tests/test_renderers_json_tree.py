# tests/test_renderers_json_tree.py
from __future__ import annotations

from plotsrv.json_model import build_json_document
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


def test_json_tree_renders_bounded_table_and_plot_modes_for_rectangular_json() -> None:
    doc = build_json_document(
        [{"time": 1, "status": "ok"}, {"time": 2, "status": "warn"}],
        source_format="json_file",
    )

    out = JsonTreeRenderer().render(doc, view_id="v1")

    assert 'data-json-mode="json">JSON</button>' in out.html
    assert 'data-json-mode="table">Table</button>' in out.html
    assert 'data-json-mode="plot">Plot</button>' in out.html
    assert 'data-json-panel="table"' in out.html
    assert 'data-json-table-grid="1"' in out.html
    assert 'data-json-table-data="1"' in out.html
    assert 'id="table-search-input"' in out.html
    assert 'id="table-plot-controls"' in out.html


def test_json_tree_keeps_non_rectangular_json_out_of_the_table_explorer() -> None:
    doc = build_json_document(
        [{"time": 1, "detail": {"nested": True}}],
        source_format="json_file",
    )

    out = JsonTreeRenderer().render(doc, view_id="v1")

    assert 'data-json-mode="table"' not in out.html
    assert 'data-json-mode="plot"' not in out.html
    assert 'data-json-table-grid="1"' not in out.html


def test_json_tree_refuses_unsafe_integer_table_data_from_document_payload() -> None:
    doc = build_json_document([{"identifier": 1}], source_format="json_file")
    doc["table_data"] = {
        "columns": ["identifier"],
        "rows": [{"identifier": 2**53}],
    }

    out = JsonTreeRenderer().render(doc, view_id="v1")

    assert 'data-json-mode="table"' not in out.html
    assert 'data-json-mode="plot"' not in out.html
    assert 'data-json-table-grid="1"' not in out.html
