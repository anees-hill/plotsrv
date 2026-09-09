from __future__ import annotations

from dataclasses import replace
import json
import math

import numpy as np
import pandas as pd
import pytest

from plotsrv.observations.capture import capture_detached
from plotsrv.observations.models import ObservationBudget, ObservationOptions
from plotsrv.observations.summary import build_summary, encode_summary, validate_summary

BUDGET = ObservationBudget(capture_ms=50)


def summary(source, *, budget=BUDGET, options=ObservationOptions()):
    result = build_summary(
        capture_detached(source, budget=budget, options=options, view_id="observed"),
        budget=budget,
        publisher_session="test-session",
    )
    assert validate_summary(result, view_id="observed") is result
    assert len(encode_summary(result)) <= min(budget.max_output_bytes, 65536)
    return result


def test_frame_useful_statistics_are_scoped_to_distributed_evidence():
    result = summary(pd.DataFrame({"x": np.arange(10000), "y": [None] * 10000}))
    assert result["metadata"]["shape"] == [10000, 2]
    x, y = result["fields"]
    assert x["scope"] == "base_sample"
    assert x["numeric"]["min"]["value"] == 0
    assert x["numeric"]["max"]["value"] == 9999
    assert sum(b["count"] for b in x["numeric"]["histogram"]) == x["numeric"]["count"]
    assert y["missingness"]["fraction"] == 1
    assert y["missingness"]["denominator"] <= 32
    assert "numeric" not in y
    assert result["exploration"]["included_in_base_statistics"] is False
    assert "base_sample" not in result and "exploratory_examples" not in result
    assert all("examples" not in field for field in result["fields"])


def test_small_noncontiguous_array_and_exact_integer_arithmetic():
    source = np.arange(20).reshape(4, 5).T
    field = summary(source)["fields"][0]
    assert field["scope"] == "complete_small_inspection"
    assert field["numeric"]["mean"] == {
        "type": "rational",
        "numerator": "19",
        "denominator": 2,
    }
    assert field["numeric"]["distinct_values_observed"] == 20
    assert field["numeric"]["quantiles"]["p50"]["value"] == 9
    big = summary([2**63, 2**63 + 1])["fields"][0]["numeric"]
    assert big["max"]["value"] == str(2**63 + 1)
    assert big["mean"] == {
        "type": "rational",
        "numerator": str(2**64 + 1),
        "denominator": 2,
    }


def test_nested_supplied_metrics_selection_and_precision():
    result = summary(
        {"metrics": {"count": 2**63, "ok": True}, "secret": "hidden"},
        options=ObservationOptions(path=("metrics",), fields=("count",)),
    )
    assert "hidden" not in encode_summary(result).decode()
    field = result["fields"][0]
    assert field["scope"] == "supplied_value"
    assert field["value"] == {"type": "integer", "value": str(2**63)}


@pytest.mark.parametrize(
    "values",
    [
        [-1e308, 1e308],
        [1e308, 1e308],
        [1.0, float("nan"), float("inf"), None],
        [2**63, 1.5],
    ],
)
def test_finite_json_extreme_values(values):
    result = summary(values)
    json.loads(encode_summary(result), parse_constant=lambda value: pytest.fail(value))
    field = result["fields"][0]
    if values[-1] is None:
        assert field["missingness"]["missing"] == 2
        assert field["nonfinite"] == 2
    if type(values[0]) is int:
        assert field["numeric"]["mean_unavailable"] == "numeric_precision_or_range"


def test_unknown_is_not_missing_or_all_clear():
    class Trap:
        def __repr__(self):
            pytest.fail("repr called")

    field = summary([None, Trap()])["fields"][0]
    assert field["not_inspected"] == 1
    assert field["values_inspected"] == 1
    assert field["missingness"] == {"missing": 1, "denominator": 1, "fraction": 1.0}


def test_categories_prefixes_and_explicit_examples():
    result = summary(["a" * 1000, "b", "b"])
    category = result["fields"][0]["categories"]
    assert category["prefixes_or_capped"] is True
    assert category["complete_for_captured_values"] is False
    assert len(category["top"]) <= 16
    assert category["top"][0]["count"] == 2
    result = summary([1, 2], options=ObservationOptions(include_examples=True))
    assert result["fields"][0]["examples"]


def test_output_budget_includes_provenance_and_drops_examples_first():
    source = pd.DataFrame(
        {str(i): ["x" * 1000 + str(j) for j in range(128)] for i in range(32)}
    )
    budget = replace(BUDGET, max_rows=128, max_fields=32, max_output_bytes=4096)
    result = summary(
        source, budget=budget, options=ObservationOptions(include_examples=True)
    )
    assert result["provenance"]["publisher_session"] == "test-session"
    assert result["reasons"]


@pytest.mark.parametrize(
    "change",
    [
        {"observation_version": 2},
        {"recipe_version": True},
        {"fields": [1]},
        {"source_type": {}},
        {"metadata": []},
        {"base_sample": []},
        {"captured_at_unix_s": float("inf")},
        {"examples_enabled": False, "exploratory_examples": []},
    ],
)
def test_receiver_rejects_wrong_version_shape_and_private_evidence(change):
    result = summary(1)
    result.update(change)
    with pytest.raises(ValueError):
        validate_summary(result, view_id="observed")


def test_deep_explicit_examples_fit_the_wire_structure_budget():
    source = 1
    for _ in range(8):
        source = [source] * 2
    result = summary(
        source,
        budget=replace(BUDGET, max_depth=8),
        options=ObservationOptions(include_examples=True),
    )
    assert result["fields"][0]["examples"]


def test_summary_releases_decoded_evidence_without_cyclic_gc(monkeypatch):
    import gc
    import weakref
    from plotsrv.observations.models import CaptureEnvelope

    class WorkingDocument(dict):
        pass

    envelope = capture_detached({"metrics": {"x": [1, 2, 3]}}, budget=BUDGET)
    original = CaptureEnvelope.document
    references = []

    def document(self):
        value = WorkingDocument(original(self))
        references.append(weakref.ref(value))
        return value

    monkeypatch.setattr(CaptureEnvelope, "document", document)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(100):
            result = build_summary(envelope, budget=BUDGET)
            del result
        assert all(ref() is None for ref in references)
    finally:
        if was_enabled:
            gc.enable()
