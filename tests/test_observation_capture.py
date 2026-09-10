from __future__ import annotations

import gc
import json
import weakref
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from plotsrv.observations import adapters
from plotsrv.observations.capture import capture_detached, positions
from plotsrv.observations.models import CaptureOptions, ObservationBudget

BUDGET = ObservationBudget(capture_ms=50)


def capture(source, **kwargs):
    return capture_detached(
        source, budget=kwargs.pop("budget", BUDGET), **kwargs
    ).document()


class Trap:
    def __getattribute__(self, name):
        raise AssertionError("SECRET property evaluated")

    def __repr__(self):
        raise AssertionError("SECRET repr evaluated")

    def __iter__(self):
        raise AssertionError("SECRET iterator evaluated")

    def __array__(self, *args, **kwargs):
        raise AssertionError("SECRET array evaluated")

    def __eq__(self, other):
        raise AssertionError("SECRET comparison evaluated")

    def __hash__(self):
        return hash("x")


@pytest.mark.parametrize(
    "factory",
    [
        Trap,
        lambda: iter([1, 2]),
        lambda: (x for x in [1]),
        lambda: type("ListSubclass", (list,), {})([Trap()]),
    ],
)
def test_unknown_objects_never_evaluated(factory):
    result = capture(factory())
    assert result["source_type"] == "unsupported"
    assert result["reasons"] == ["unsupported_value"]
    assert "SECRET" not in json.dumps(result)


def test_custom_metaclass_not_compared_or_hashed():
    class Meta(type):
        def __hash__(self):
            raise AssertionError

        def __eq__(self, other):
            raise AssertionError

    assert capture(Meta("Thing", (), {})())["reasons"] == ["unsupported_value"]


def test_builtin_types_detachment_cycles_and_selection():
    nested = [1, {"n": 2}]
    source = {"wanted": nested, "secret": Trap()}
    result = capture_detached(
        source, budget=BUDGET, options=CaptureOptions(fields=("wanted",))
    )
    before = result.payload
    nested[1]["n"] = 999
    assert result.payload == before
    # Check the detached value, not unrelated metadata such as the timestamp.
    captured_nested = json.loads(before)["base_sample"][0]["items"][0]["value"]
    assert captured_nested["items"][1]["value"]["items"][0]["value"]["value"] == 2
    assert "secret" not in before.decode()
    nested.append(nested)
    assert "cycle" in capture(nested)["reasons"]
    assert (
        capture(source, options=CaptureOptions(path=("wanted", 0)))["base_sample"][0][
            "value"
        ]
        == 1
    )
    assert (
        "path_not_inspected_or_absent"
        in capture({"x": 1}, options=CaptureOptions(path=("missing",)))["reasons"]
    )
    # Lookup must not invoke custom key equality, even with a colliding hash.
    assert capture({Trap(): Trap()}, options=CaptureOptions(path=("x",)))[
        "reasons"
    ] == ["path_not_inspected_or_absent"]


def test_scalar_tags_and_large_variable_values():
    result = capture([None, float("nan"), float("inf"), 2**100, 2**10000, True])
    values = [x["value"] for x in result["base_sample"][0]["items"]]
    assert [x["type"] for x in values] == [
        "null",
        "nonfinite",
        "nonfinite",
        "integer",
        "omitted",
        "bool",
    ]
    assert values[3]["value"] == str(2**100)
    huge = "\U0001f600" * 1_000_000
    result = capture(huge)
    assert result["coverage"]["value_bytes"] <= BUDGET.max_value_bytes
    assert result["base_sample"][0]["truncated"]
    assert len(json.dumps(result)) < 4096
    assert "hex" not in capture(b"secret")["base_sample"][0]
    assert (
        capture(b"ab", options=CaptureOptions(include_examples=True))["base_sample"][0][
            "hex"
        ]
        == "6162"
    )


def test_category_and_depth_budgets():
    result = capture(["a", "b", "c"], budget=replace(BUDGET, max_categories=2))
    assert "category_budget" in result["reasons"]
    nested = 1
    for _ in range(100):
        nested = {"next": nested}
    result = capture(nested)
    assert "depth_budget" in result["reasons"]
    assert result["coverage"]["nodes"] < 30


@pytest.mark.parametrize("shape", [(10**10,), (10**5, 10**5)])
def test_huge_logical_strided_array_reads_only_sample(shape):
    source = np.broadcast_to(np.array([7]), shape)
    result = capture(source)
    assert result["metadata"]["shape"] == list(shape)
    assert result["coverage"]["elements_read"] == 32
    assert result["base_sample"][0]["position"] == 0
    assert result["base_sample"][-1]["position"] == source.size - 1
    assert all(x["value"]["value"] == 7 for x in result["base_sample"])


def test_negative_noncontiguous_array_and_no_parent_retention():
    parent = np.arange(1_000_000).reshape(1000, 1000)
    source = parent[::-3, ::7]
    root_ref, view_ref = weakref.ref(parent), weakref.ref(source)
    envelope = capture_detached(source, budget=BUDGET)
    expected = int(source[-1, -1])
    parent[:] = -1
    assert envelope.document()["base_sample"][-1]["value"]["value"] == expected
    del source, parent
    gc.collect()
    assert root_ref() is None and view_ref() is None


def test_reject_foreign_array_owner_and_subclasses():
    source = np.lib.stride_tricks.as_strided(
        np.array([1]), shape=(10**9,), strides=(8,)
    )
    assert capture(source)["reasons"] == ["unsafe_array_owner"]
    assert (
        capture(np.array([1]).view(type("Subclass", (np.ndarray,), {})))["source_type"]
        == "unsupported"
    )


def test_few_rows_with_enormous_fixed_or_object_cells(monkeypatch):
    fixed = np.zeros(2, dtype="U1000000")
    result = capture(fixed)
    assert result["coverage"]["elements_read"] == 0
    assert "oversized_fixed_cell" in result["reasons"]
    source = pd.DataFrame({"nested": [["x" * 2_000_000] * 100000], "unknown": [None]})
    source._mgr.blocks[0].values[1, 0] = Trap()
    ref = weakref.ref(source)
    envelope = capture_detached(source, budget=BUDGET)
    del source
    gc.collect()
    assert ref() is None
    result = envelope.document()
    assert result["coverage"]["value_bytes"] <= 32 * BUDGET.max_value_bytes + 64
    assert len(envelope.payload) <= BUDGET.max_output_bytes
    assert "value_truncated" in result["reasons"]


def test_wide_pandas_never_builds_column_index_or_full_conversions(monkeypatch):
    source = pd.DataFrame(np.zeros((2, 100_000)))
    assert source._mgr._blknos is None

    def forbidden(*args, **kwargs):
        raise AssertionError("whole conversion")

    for name in ("to_numpy", "memory_usage", "copy"):
        monkeypatch.setattr(pd.DataFrame, name, forbidden)
    monkeypatch.setattr(type(source._mgr), "_rebuild_blknos_and_blklocs", forbidden)
    result = capture(source, options=CaptureOptions(fields=(99999,)))
    assert result["metadata"]["shape"] == [2, 100_000]
    assert result["base_sample"] == []
    assert "placement_budget" in result["reasons"]
    assert result["coverage"]["elements_read"] == 0
    assert source._mgr._blknos is None


def test_pandas_nullable_object_and_unsafe_extension():
    source = pd.DataFrame(
        {
            "i": pd.array([1, None], dtype="Int64"),
            "f": pd.array([None, 1.5], dtype="Float64"),
            "c": pd.Categorical(["a", "b"]),
            "o": [None, {"x": 1}],
        }
    )
    source._mgr.blocks[-1].values[0, 0] = Trap()
    result = capture(source)
    assert result["base_sample"][0]["samples"][1]["value"]["type"] == "null"
    assert result["base_sample"][1]["samples"][1]["value"]["value"] == 1.5
    assert "unsupported_column_storage" in result["reasons"]
    assert "unsupported_value" in result["reasons"]


def test_base_distributed_and_targeted_probes_stay_separate():
    source = np.full(100, None, dtype=object)
    source[24] = 5
    result = capture(source, budget=replace(BUDGET, max_rows=2, exploratory_rows=2))
    assert [x["position"] for x in result["base_sample"]] == [0, 99]
    assert all(x["value"]["type"] == "null" for x in result["base_sample"])
    assert any(x["value"].get("value") == 5 for x in result["exploratory"])
    source[99] = 9
    result = capture(source)
    assert result["base_sample"][-1]["value"]["value"] == 9
    assert result["exploratory"] == []


def test_detect_obvious_mutation_even_on_budget_exit(monkeypatch):
    source = pd.DataFrame({"x": [1, 2]})
    real = adapters._array_value

    def read(c, array, index, np, **kwargs):
        value = real(c, array, index, np, **kwargs)
        source["new"] = [3, 4]
        return value

    monkeypatch.setattr(adapters, "_array_value", read)
    result = capture(source, budget=replace(BUDGET, max_elements=2))
    assert "concurrent_mutation" in result["reasons"]
    assert result["base_sample"] == []


@pytest.mark.parametrize(
    "limit,value", [("max_elements", 3), ("max_nodes", 3), ("max_capture_bytes", 4096)]
)
def test_structural_limits_stop_actual_reads(limit, value):
    budget = replace(BUDGET, **{limit: value})
    result = capture(np.arange(1000), budget=budget)
    assert result["coverage"]["elements_read"] <= budget.max_elements
    assert result["coverage"]["nodes"] <= budget.max_nodes
    assert result["coverage"]["charged_capture_bytes"] <= budget.max_capture_bytes
    assert result["reasons"]


def test_output_byte_limit_and_no_source_in_errors(monkeypatch, caplog):
    budget = replace(
        BUDGET,
        max_output_bytes=4096,
        max_capture_bytes=1024 * 1024,
        max_value_bytes=1024,
    )
    result = capture_detached(["x" * 1024] * 32, view_id="😀" * 512, budget=budget)
    assert len(result.payload) <= 4096
    assert "output_byte_budget" in result.document()["reasons"]

    def fail(*args):
        raise ValueError("SECRET credential")

    monkeypatch.setattr(adapters, "capture_array", fail)
    result = capture(np.array([1]))
    assert result["reasons"] == ["unsafe_or_changed_source"]
    assert "SECRET" not in json.dumps(result) + caplog.text


def test_polars_capture_is_disabled_without_native_access(monkeypatch):
    pl = pytest.importorskip("polars")
    source = pl.DataFrame({"x": [1, 2]})
    ref = weakref.ref(source)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("native access")

    monkeypatch.setattr(pl.DataFrame, "height", property(forbidden))
    monkeypatch.setattr(pl.DataFrame, "width", property(forbidden))
    monkeypatch.setattr(pl.DataFrame, "to_series", forbidden)
    envelope = capture_detached(source, budget=BUDGET)
    assert envelope.document()["reasons"] == ["polars_capture_unavailable"]
    assert calls == []
    del source
    gc.collect()
    assert ref() is None


def test_elapsed_deadline_is_additional_to_structural_limits(monkeypatch):
    from plotsrv.observations import capture as module

    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    result = capture(np.arange(10))
    assert result["coverage"]["elements_read"] == 0
    assert result["reasons"] == ["soft_deadline"]


def test_numpy_temporal_nonfinite_and_tiny_integer_byte_budget():
    result = capture(np.array(["2020-01-01", "NaT"], dtype="datetime64[D]"))
    assert result["base_sample"][0]["value"]["unit"] == "D"
    assert result["base_sample"][1]["value"]["null"] is True
    result = capture(np.array([float("nan"), float("-inf")]))
    assert [x["value"]["type"] for x in result["base_sample"]] == [
        "nonfinite",
        "nonfinite",
    ]
    result = capture(2**100, budget=replace(BUDGET, max_value_bytes=16))
    assert "integer_too_large" in result["reasons"]


def test_fixed_strings_and_structured_dtype_do_not_expand_schema():
    result = capture(np.array(["hello", "é"]))
    assert result["base_sample"][1]["value"]["value"] == "é"
    source = np.zeros(1, dtype=[("x" + str(i), "i1") for i in range(10000)])
    result = capture(source)
    assert result["coverage"]["elements_read"] == 0
    assert "unsupported_dtype" in result["reasons"]
    assert len(json.dumps(result)) < 1024


def test_selected_fields_avoid_nested_cell_copy_and_name_matching_is_exact():
    source = pd.DataFrame({"safe": [1], "secret": [None]})
    nested = Trap()
    ref = weakref.ref(nested)
    source._mgr.blocks[-1].values[0, 0] = nested
    envelope = capture_detached(
        source, budget=BUDGET, options=CaptureOptions(fields=("safe",))
    )
    assert "secret" not in envelope.payload.decode()
    assert envelope.document()["base_sample"][0]["samples"][0]["value"]["value"] == 1
    del nested, source
    gc.collect()
    assert ref() is None


def test_array_shape_change_is_reported(monkeypatch):
    source = np.arange(4)
    real = adapters._array_value

    def read(c, array, index, np, **kwargs):
        result = real(c, array, index, np, **kwargs)
        source.shape = (2, 2)
        return result

    monkeypatch.setattr(adapters, "_array_value", read)
    result = capture(source, budget=replace(BUDGET, max_elements=1))
    assert "concurrent_mutation" in result["reasons"]
    assert result["base_sample"] == []


def test_dict_size_change_is_reported(monkeypatch):
    from plotsrv.observations.capture import Capture

    source = {"x": 1}
    real = Capture.value

    def read(self, value, *args, **kwargs):
        result = real(self, value, *args, **kwargs)
        if type(value) is int:
            source["y"] = 2
        return result

    monkeypatch.setattr(Capture, "value", read)
    result = capture(source)
    assert result["reasons"] == ["concurrent_mutation"]
    assert result["base_sample"][0]["items"] == []


def test_polars_lazy_and_missing_native_getter_fail_closed(monkeypatch):
    pl = pytest.importorskip("polars")
    source = pl.DataFrame({"x": [1]})
    lazy = source.lazy()

    def forbidden(*args, **kwargs):
        raise AssertionError("lazy computation")

    monkeypatch.setattr(pl.LazyFrame, "collect", forbidden)
    assert capture(lazy)["reasons"] == ["unsupported_value"]
    monkeypatch.delattr(type(source.to_series()._s), "get_i64")
    result = capture(source)
    assert result["reasons"] == ["polars_capture_unavailable"]
    assert result["base_sample"] == []


def test_sampling_labels_and_unicode_replacement_are_truthful():
    result = capture({"x": [1, 2]})
    assert result["sampling"] == "bounded_insertion_order_fields"
    assert (
        result["base_sample"][0]["items"][0]["value"]["sampling"]
        == "deterministic_distributed_positions"
    )
    result = capture("\ud800")
    assert result["base_sample"][0]["encoding_replaced"]
    assert "invalid_unicode_replaced" in result["reasons"]
    with pytest.raises(ValueError):
        CaptureOptions(fields=("x", 0))


def test_dtype_or_block_storage_replacement_is_detected(monkeypatch):
    array = np.arange(4, dtype=np.int64)
    frame = pd.DataFrame({"x": [1, 2]})
    real = adapters._array_value

    def read(c, source, index, np, **kwargs):
        result = real(c, source, index, np, **kwargs)
        array.dtype = np.float64
        frame._mgr.blocks[0].values = frame._mgr.blocks[0].values.copy()
        return result

    monkeypatch.setattr(adapters, "_array_value", read)
    assert "concurrent_mutation" in capture(array)["reasons"]
    assert "concurrent_mutation" in capture(frame)["reasons"]


@pytest.mark.parametrize(
    "factory", [lambda: np.array([1, 2]), lambda: [{"secret": 1}], lambda: 1]
)
def test_unsupported_field_selection_never_captures_unselected_values(factory):
    result = capture(factory(), options=CaptureOptions(fields=("safe",)))
    assert result["reasons"] == ["unsupported_field_selection"]
    assert result["base_sample"] == []
    assert result["coverage"]["elements_read"] == 0
