"""Run with pytest -s --benchmark-only; inputs/imports are outside measurements."""

from __future__ import annotations

import gc
import json
import tracemalloc

import numpy as np
import pandas as pd
import pytest

from plotsrv.observations.admission import CaptureEngine

pytestmark = pytest.mark.benchmark


def _source(case):
    if case == "small":
        return {"rows": 123, "seconds": 0.125, "ok": True}
    if case == "large_array":
        return np.broadcast_to(np.array([7.0]), (10**10,))
    if case == "large_frame":
        return pd.DataFrame(np.zeros((100_000, 8)))
    if case == "huge_cell":
        return {"text": "x" * 16_000_000}
    return None


def _drain(engine):
    while (work := engine.take()) is not None:
        assert engine.finish(work.token)
    # Isolate admitted-call cost without sleeping or including cadence in timing.
    engine._views.clear()
    engine._waiting.clear()
    engine._yielded.clear()
    engine._tokens = float(engine._burst)


@pytest.mark.parametrize(
    "case", ["skipped", "small", "large_array", "large_frame", "huge_cell"]
)
def test_capture_boundary_latency(benchmark, case):
    source = _source(case)
    engine = CaptureEngine()
    if case == "skipped":
        engine.close()

    def setup():
        _drain(engine)

    result = benchmark.pedantic(
        engine.submit,
        args=("measurement", source),
        setup=setup,
        rounds=100,
        iterations=1,
        warmup_rounds=5,
    )
    assert result == ("closed" if case == "skipped" else "accepted")
    _drain(engine)


@pytest.mark.parametrize(
    "case", ["skipped", "small", "large_array", "large_frame", "huge_cell"]
)
def test_capture_memory_report(case):
    source = _source(case)
    engine = CaptureEngine()
    if case == "skipped":
        engine.close()
    else:
        assert engine.submit("warmup", source) == "accepted"
        _drain(engine)
    gc.collect()
    tracemalloc.start()
    engine.submit("measurement", source)
    retained, peak = tracemalloc.get_traced_memory()
    work = engine.take()
    payload_bytes = len(work.envelope.payload) if work else 0
    if work:
        assert engine.finish(work.token)
    del work
    gc.collect()
    post_drain, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "case": case,
                "retained_bytes": retained,
                "peak_bytes": peak,
                "post_drain_bytes": post_drain,
                "payload_bytes": payload_bytes,
            }
        )
    )
    assert engine.stats()["reserved"] == 0
    assert payload_bytes <= engine.budget.max_output_bytes
    assert peak < engine.budget.max_capture_bytes * 4


def test_full_mailbox_memory_report():
    source = ["é" * 1000] * 32
    engine = CaptureEngine()
    engine.submit("warmup", source)
    _drain(engine)
    gc.collect()
    tracemalloc.start()
    for index in range(engine.budget.max_pending):
        engine._tokens = float(engine._burst)
        assert engine.submit(str(index), source) == "accepted"
    retained, peak = tracemalloc.get_traced_memory()
    engine._tokens = float(engine._burst)
    assert engine.submit("overflow", source) == "overloaded"
    assert engine.stats()["reserved"] == engine.budget.max_pending
    while (work := engine.take()) is not None:
        assert engine.finish(work.token)
    del work
    gc.collect()
    post_drain, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "case": "full_mailbox",
                "retained_bytes": retained,
                "peak_bytes": peak,
                "post_drain_bytes": post_drain,
            }
        )
    )
    assert engine.stats()["reserved"] == 0
    assert peak < engine.budget.max_pending_bytes + engine.budget.max_capture_bytes * 4
