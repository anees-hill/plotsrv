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
