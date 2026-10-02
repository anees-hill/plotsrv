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
        # Warm this path too: coverage's first-call setup is not capture memory.
        assert engine.submit("warmup", source) == "closed"
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


@pytest.mark.parametrize("case", ["sparse_dict", "cold_wide_frame"])
@pytest.mark.parametrize("size", [100_000, 1_000_000])
def test_cold_backing_storage_latency(benchmark, case, size):
    from plotsrv.observations.capture import capture_detached
    from plotsrv.observations.models import CaptureOptions

    engine = CaptureEngine()  # Initialize adapters before timing.

    def setup():
        if case == "sparse_dict":
            source = dict.fromkeys(range(size), 1)
            for i in range(size - 1):
                del source[i]
        else:
            source = pd.DataFrame(np.zeros((1, size)))
            source["text"] = "x"
            source = source.select_dtypes(include="number")
            assert source._mgr._blknos is None
        return (source,), {
            "budget": engine.budget,
            "options": CaptureOptions(fields=(size - 1,)),
        }

    envelope = benchmark.pedantic(
        capture_detached, setup=setup, rounds=10, iterations=1
    )
    document = envelope.document()
    # Adding then selecting columns gives pandas a plain integer Index: one
    # label read is expected; no source value or placement scan is permitted.
    assert document["coverage"]["elements_read"] == (0 if case == "sparse_dict" else 1)
    if case == "cold_wide_frame":
        assert document["base_sample"] == []
    assert (
        "mapping_storage_budget" if case == "sparse_dict" else "placement_budget"
    ) in document["reasons"]


@pytest.mark.parametrize("case", ["view_cadence", "process_cadence", "full", "busy"])
@pytest.mark.parametrize("id_length", [8, 512])
def test_rejected_admission_latency(benchmark, case, id_length, monkeypatch):
    from plotsrv.observations import admission

    monkeypatch.setattr(admission.time, "monotonic", lambda: 100.0)
    engine = CaptureEngine()
    identity = "a" * id_length
    if case == "view_cadence":
        assert engine.submit(identity, 1) == "accepted"
        work = engine.take()
        assert engine.finish(work.token)
    elif case == "process_cadence":
        engine._tokens = 0
    elif case == "full":
        for i in range(engine.budget.max_pending):
            engine._tokens = float(engine._burst)
            assert engine.submit(str(i), 1) == "accepted"
    else:
        engine._lock.acquire()
    try:
        result = benchmark.pedantic(
            engine.submit, args=(identity, object()), rounds=100, iterations=100
        )
        assert result == {"full": "overloaded", "busy": "busy"}.get(case, case)
    finally:
        if case == "busy":
            engine._lock.release()
        engine.close()


@pytest.mark.parametrize("case", ["nested", "unicode", "escaped_output", "binary"])
def test_maximum_budget_memory_report(case, monkeypatch):
    from plotsrv.observations.capture import Capture, capture_detached
    from plotsrv.observations.models import CaptureOptions, ObservationBudget

    budget = ObservationBudget(
        max_rows=128,
        max_fields=32,
        max_elements=4096,
        max_nodes=4096,
        max_depth=8,
        max_value_bytes=1024,
        max_categories=64,
        max_capture_bytes=1024 * 1024,
        max_output_bytes=4096 if case == "escaped_output" else 256 * 1024,
        exploratory_rows=16,
        capture_ms=50,
    )
    if case == "nested":
        source = 1
        for _ in range(8):
            source = [source] * 128
    else:
        source = [
            {
                "unicode": "😀" * 100_000,
                "escaped_output": "\x00" * 100_000,
                "binary": b"x" * 100_000,
            }[case]
        ] * 128
    # Structural-limit stress, explicitly without the supplementary deadline.
    # Tracing would otherwise stop early and under-measure worst-case allocation.
    real = Capture.__init__

    def initialize(self, *args):
        real(self, *args)
        self.deadline = float("inf")

    monkeypatch.setattr(Capture, "__init__", initialize)
    gc.collect()
    tracemalloc.start()
    envelope = capture_detached(
        source, budget=budget, options=CaptureOptions(include_examples=True)
    )
    retained, peak = tracemalloc.get_traced_memory()
    payload_bytes = len(envelope.payload)
    document = envelope.document()
    assert document["coverage"]["charged_capture_bytes"] <= budget.max_capture_bytes
    assert document["coverage"]["nodes"] <= budget.max_nodes
    del envelope, document
    gc.collect()
    post_release, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "case": "maximum_" + case,
                "retained_bytes": retained,
                "peak_bytes": peak,
                "post_release_bytes": post_release,
                "payload_bytes": payload_bytes,
            }
        )
    )
    assert payload_bytes <= budget.max_output_bytes
    assert peak < budget.max_capture_bytes * 4


def test_polars_literal_native_rss_report():
    import os
    import subprocess
    import sys
    import textwrap

    pytest.importorskip("polars")
    if not os.path.exists("/proc/self/statm"):
        pytest.skip("Linux RSS measurement")
    script = textwrap.dedent("""
        import gc, json, os, resource, time
        import polars as pl
        from plotsrv.observations.admission import CaptureEngine
        from plotsrv.observations.models import CaptureOptions
        engine = CaptureEngine()
        # Source allocation is outside the measured boundary. Polars retains a
        # scalar column lazily; a series lookup used to materialize 16MB here.
        frame = pl.DataFrame({"row": pl.arange(0, 4_000_000, eager=True)}).with_columns(pl.lit(7).alias("value"))
        def rss():
            with open("/proc/self/statm") as f:
                return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        gc.collect()
        before, peak_before = rss(), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        start = time.perf_counter()
        assert engine.submit("literal", frame, CaptureOptions(fields=(1,))) == "accepted"
        elapsed_ms = (time.perf_counter() - start) * 1000
        retained, peak = rss(), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        work = engine.take()
        assert work.envelope.document()["reasons"] == ["polars_capture_unavailable"]
        assert engine.finish(work.token)
        del work
        gc.collect()
        print(json.dumps({"case": "polars_literal", "elapsed_ms": elapsed_ms,
            "rss_delta_bytes": retained-before, "peak_rss_delta_bytes": peak-peak_before,
            "post_drain_rss_delta_bytes": rss()-before}))
        assert retained - before < 8 * 1024 * 1024
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    print(result.stdout.strip())
