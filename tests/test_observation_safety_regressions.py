from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from plotsrv.observations.capture import Capture, capture_detached
from plotsrv.observations.models import CaptureOptions, ObservationBudget

BUDGET = replace(ObservationBudget(), capture_ms=50)


def test_sparse_dictionary_storage_is_bounded_before_iteration(monkeypatch):
    source = dict.fromkeys(range(100_000), 1)
    for index in range(99_999):
        del source[index]
    assert len(source) == 1
    assert dict.__sizeof__(source) > BUDGET.max_capture_bytes
    real = Capture.value
    visited = []

    def checked(self, value, *args, **kwargs):
        if type(value) is int:
            visited.append(value)
        return real(self, value, *args, **kwargs)

    monkeypatch.setattr(Capture, "value", checked)
    for obj, options in (
        (source, CaptureOptions()),
        ({"nested": source}, CaptureOptions()),
        (source, CaptureOptions(path=(99999,))),
    ):
        result = capture_detached(obj, budget=BUDGET, options=options).document()
        assert "mapping_storage_budget" in result["reasons"]
    assert visited == []


def test_dictionary_backing_scans_share_aggregate_byte_budget():
    # Each dictionary fits alone, but scanning many sparse backing tables must
    # not multiply that work beyond the one capture allowance.
    children = []
    for i in range(16):
        child = dict.fromkeys(range(2000), i)
        for index in range(1999):
            del child[index]
        children.append(child)
    result = capture_detached(children, budget=BUDGET).document()
    assert "mapping_storage_budget" in result["reasons"]
    assert result["coverage"]["charged_capture_bytes"] <= BUDGET.max_capture_bytes


def test_wide_uncached_pandas_placement_is_never_requested():
    frame = pd.DataFrame(np.zeros((1, 100_000)))
    frame["text"] = "x"
    frame = frame.select_dtypes(include="number")
    assert frame._mgr._blknos is None
    result = capture_detached(
        frame, budget=BUDGET, options=CaptureOptions(fields=(99999,))
    ).document()
    assert result["metadata"]["shape"] == [1, 100_000]
    assert "placement_budget" in result["reasons"]
    assert result["base_sample"] == []
    assert frame._mgr._blknos is None


def test_wide_existing_column_maps_can_be_read_without_building_them(monkeypatch):
    frame = pd.DataFrame(np.arange(200000).reshape(2, 100000))
    frame._mgr.blknos  # Source already has maps; capture must not create any.

    def forbidden(*args, **kwargs):
        raise AssertionError("full column map rebuild")

    monkeypatch.setattr(type(frame._mgr), "_rebuild_blknos_and_blklocs", forbidden)
    result = capture_detached(
        frame, budget=BUDGET, options=CaptureOptions(fields=(99999,))
    ).document()
    assert [v["value"]["value"] for v in result["base_sample"][0]["samples"]] == [
        99999,
        199999,
    ]


def test_polars_literals_are_not_materialized_or_sampled(monkeypatch):
    pl = pytest.importorskip("polars")
    frame = pl.DataFrame({"row": pl.arange(0, 1_000_000, eager=True)}).with_columns(
        pl.lit(7).alias("value")
    )
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("materialization or native lock")

    monkeypatch.setattr(pl.DataFrame, "to_series", forbidden)
    monkeypatch.setattr(pl.DataFrame, "height", property(forbidden))
    result = capture_detached(
        frame, budget=BUDGET, options=CaptureOptions(fields=(1,))
    ).document()
    assert result["reasons"] == ["polars_capture_unavailable"]
    assert result["coverage"]["elements_read"] == 0
    assert calls == []


@pytest.mark.parametrize("dtype", ["Int64", "Float64", "boolean"])
@pytest.mark.parametrize("node_limit", [1, 2, 8])
def test_nullable_masks_cannot_bypass_node_limits(dtype, node_limit):
    frame = pd.DataFrame({0: pd.array([None] * 1000, dtype=dtype)})
    result = capture_detached(
        frame, budget=replace(BUDGET, max_nodes=node_limit)
    ).document()

    def typed_nodes(value):
        if type(value) is dict:
            return int("type" in value) + sum(typed_nodes(v) for v in value.values())
        if type(value) is list:
            return sum(typed_nodes(v) for v in value)
        return 0

    assert typed_nodes(result) <= result["coverage"]["nodes"] <= node_limit


@pytest.mark.parametrize("index_kind", ["datetime", "timedelta", "multi"])
def test_common_temporal_columns_and_indexes_preserve_other_fields(
    index_kind, monkeypatch
):
    frame = pd.DataFrame(
        {
            "number": [1, 2, 3],
            "date": pd.date_range("2020-01-01", periods=3),
            "tz": pd.date_range("2020-01-01", periods=3, tz="Europe/London"),
            "duration": pd.timedelta_range(0, periods=3),
            "unsupported": pd.Categorical(["a", "b", "c"]),
        }
    )
    frame.index = {
        "datetime": pd.date_range("2000", periods=3),
        "timedelta": pd.timedelta_range(0, periods=3),
        "multi": pd.MultiIndex.from_tuples([("a", 1), ("b", 2), ("c", 3)]),
    }[index_kind]
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("index materialization")

    monkeypatch.setattr(pd.MultiIndex, "_values", property(forbidden))
    monkeypatch.setattr(pd.DataFrame, "dtypes", property(forbidden))
    result = capture_detached(frame, budget=BUDGET).document()
    assert result["metadata"]["shape"] == [3, 5]
    assert len(result["base_sample"]) == 4
    assert result["base_sample"][0]["samples"][0]["value"]["value"] == 1
    fields = result["metadata"]["fields"]
    assert fields[0]["dtype"] == {"kind": "i", "itemsize": 8}
    assert fields[1]["dtype"]["temporal_kind"] == "datetime"
    assert fields[2]["dtype"]["timezone"] == "UTC"
    assert fields[3]["dtype"]["temporal_kind"] == "duration"
    assert fields[4]["reason"] == "unsupported_column_storage"
    assert calls == []


def test_multiindex_columns_use_positions_without_expanding_labels(monkeypatch):
    frame = pd.DataFrame(np.arange(8).reshape(2, 4))
    frame.columns = pd.MultiIndex.from_product([["a", "b"], ["x", "y"]])
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("column materialization")

    monkeypatch.setattr(pd.MultiIndex, "_values", property(forbidden))
    result = capture_detached(frame, budget=BUDGET).document()
    assert result["metadata"]["shape"] == [2, 4]
    assert len(result["base_sample"]) == 4
    assert "unsupported_column_label" in result["reasons"]
    assert calls == []


def test_budget_is_shared_across_fields_and_partial_samples_remain_distributed():
    frame = pd.DataFrame(np.arange(16000).reshape(1000, 16))
    result = capture_detached(frame, budget=BUDGET).document()
    assert len(result["metadata"]["fields"]) == len(result["base_sample"]) == 16
    for field in result["base_sample"]:
        assert len(field["samples"]) >= 3
        sampled = [s["position"] for s in field["samples"]]
        assert sampled[0] == 0 and sampled[-1] == 999
        assert any(300 <= p <= 700 for p in sampled)
    assert result["coverage"]["charged_capture_bytes"] <= BUDGET.max_capture_bytes


def test_expensive_first_object_field_leaves_capacity_for_numeric_fields():
    frame = pd.DataFrame(
        {"nested": [None] * 1000, **{f"x{i}": np.arange(1000) for i in range(15)}}
    )
    # Assign directly so fixture creation doesn't itself copy the huge cell.
    frame._mgr.blocks[0].values[0, 0] = ["x" * 1_000_000] * 100_000
    result = capture_detached(frame, budget=BUDGET).document()
    assert len(result["base_sample"]) == 16
    assert all(len(f["samples"]) >= 3 for f in result["base_sample"][1:])
    assert "field_byte_budget" in result["reasons"]


@pytest.mark.parametrize("kind", ["object", "float", "datetime", "timedelta"])
def test_uninformative_base_probes_across_the_whole_source(kind):
    if kind == "object":
        source = np.full(1000, None, dtype=object)
        useful = 42
    elif kind == "float":
        source = np.full(1000, np.nan)
        useful = 42.0
    else:
        dtype = "datetime64[D]" if kind == "datetime" else "timedelta64[D]"
        source = np.full(1000, "NaT", dtype=dtype)
        useful = np.array(42, dtype=dtype)[()]
    # Probe's last disjoint interior position, far beyond the old head-only probes.
    source[971] = useful
    result = capture_detached(source, budget=BUDGET).document()
    base_positions = {s["position"] for s in result["base_sample"]}
    probes = result["exploratory"]
    assert len(probes) == BUDGET.exploratory_rows
    assert base_positions.isdisjoint(s["position"] for s in probes)
    assert probes[0]["position"] < 100 and probes[-1]["position"] > 900
    value = probes[-1]["value"]
    assert value.get("value") == 42 or (
        value.get("ticks") == "42" and not value["null"]
    )
    assert (
        result["coverage"]["elements_read"] == BUDGET.max_rows + BUDGET.exploratory_rows
    )
    assert result["coverage"]["exact"] is False


@pytest.mark.parametrize("fields", [("missing",), ("outside",), (100,)])
def test_unmatched_fields_explain_absent_or_uninspected(fields):
    frame = pd.DataFrame({**{f"x{i}": [1] for i in range(16)}, "outside": [2]})
    result = capture_detached(
        frame, budget=BUDGET, options=CaptureOptions(fields=fields)
    ).document()
    assert result["base_sample"] == []
    assert "field_not_inspected_or_absent" in result["reasons"]


@pytest.mark.parametrize("source", [None, b"x", np.int64(1), np.float64(2), pd.NA])
def test_supported_scalar_source_labels_are_truthful(source):
    result = capture_detached(source, budget=BUDGET).document()
    assert result["source_type"] == "scalar"
    assert "unsupported_value" not in result["reasons"]
