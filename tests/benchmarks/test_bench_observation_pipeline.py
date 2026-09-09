"""Paired public foreground/capture baseline; bounded background work separately."""

from __future__ import annotations

import gc
import json
import threading
import time
import tracemalloc

import numpy as np
import pandas as pd
import pytest

from plotsrv import publisher
from plotsrv.observations import runtime
from plotsrv.observations.admission import CaptureEngine
from plotsrv.observations.capture import capture_detached
from plotsrv.observations.models import ObservationBudget, ObservationOptions
from plotsrv.observations.runtime import ObservationWorker
from plotsrv.observations.summary import build_summary, encode_summary

pytestmark = pytest.mark.benchmark


def source(case):
    if case == "metrics":
        return {"rows": 123, "seconds": 0.125, "ok": True}
    if case == "frame":
        return pd.DataFrame(np.zeros((100000, 8)))
    if case == "broadcast":
        return np.broadcast_to(np.array([7.0]), (10**10,))
    return {"text": "x" * 16000000}


def drain(engine):
    while (work := engine.take()) is not None:
        engine.finish(work.token)
    engine._views.clear()
    engine._waiting.clear()
    engine._yielded.clear()
    engine._tokens = float(engine._burst)


@pytest.mark.parametrize("case", ["metrics", "frame", "broadcast", "huge_string"])
@pytest.mark.parametrize("entry", ["capture", "public"])
def test_foreground(benchmark, monkeypatch, case, entry):
    obj = source(case)
    engine = CaptureEngine()
    worker = ObservationWorker(engine)
    # Keep the consumer from racing foreground timing. Drain outside each trial.
    monkeypatch.setattr(worker, "start", lambda: True)
    monkeypatch.setattr(runtime, "_WORKER", worker)
    worker.route(view_id="bench", label=None, force=False)
    function = (
        (lambda: engine.submit("bench", obj))
        if entry == "capture"
        else (lambda: publisher.publish_view(obj, observe=True, view_id="bench"))
    )
    benchmark.pedantic(
        function, setup=lambda: drain(engine), rounds=100, iterations=1, warmup_rounds=5
    )
    assert engine.stats()["counters"]["accepted"] >= 100
    drain(engine)


def test_hot_skipped_public_call(benchmark, monkeypatch):
    engine = CaptureEngine()
    worker = ObservationWorker(engine)
    monkeypatch.setattr(runtime, "_WORKER", worker)
    monkeypatch.setattr(worker, "start", lambda: True)
    engine.close()
    obj = source("frame")
    publisher.publish_view(obj, observe=True, view_id="bench")
    benchmark.pedantic(
        publisher.publish_view,
        args=(obj,),
        kwargs={"observe": True, "view_id": "bench"},
        rounds=100,
        iterations=100,
    )
    assert engine.stats()["reserved"] == 0


@pytest.mark.parametrize("case", ["metrics", "frame", "broadcast", "huge_string"])
def test_summary_cost(benchmark, case):
    budget = ObservationBudget()
    envelope = capture_detached(source(case), budget=budget)
    result = benchmark.pedantic(
        build_summary,
        args=(envelope,),
        kwargs={"budget": budget},
        rounds=100,
        iterations=1,
        warmup_rounds=5,
    )
    assert len(encode_summary(result)) <= 65536


def test_worker_memory_and_idle_report(monkeypatch):
    obj = source("frame")
    engine = CaptureEngine()
    worker = ObservationWorker(engine)
    entered, release = threading.Event(), threading.Event()
    payload_sizes = []

    def blocked(summary, view_id, route):
        entered.set()
        release.wait(5)
        payload_sizes.append(len(encode_summary(summary)))
        return True

    monkeypatch.setattr(worker, "_deliver", blocked)
    worker.route(view_id="warmup", label=None, force=False)
    worker.start()
    gc.collect()
    tracemalloc.start()
    for i in range(1000):
        worker.submit(obj, ObservationOptions(), view_id=str(i), force=False)
    assert entered.wait(1)
    retained, peak = tracemalloc.get_traced_memory()
    stats = engine.stats()
    release.set()
    assert engine.flush(5)
    gc.collect()
    after, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # Short isolated idle observation, not a correctness assertion on scheduling.
    cpu = time.process_time()
    time.sleep(0.1)
    idle_cpu = time.process_time() - cpu
    worker.stop(timeout=1)
    print(
        json.dumps(
            {
                "retained_bytes": retained,
                "peak_bytes": peak,
                "after_drain_bytes": after,
                "reserved": stats["reserved"],
                "reserved_capture_bytes": stats["reserved_bytes"],
                "max_summary_bytes": max(payload_sizes),
                "idle_process_cpu_over_100ms": idle_cpu,
            }
        )
    )
    assert stats["reserved"] <= 8
    assert len(worker._routes) <= 128


@pytest.mark.parametrize("case", ["wide_numeric", "unicode_examples", "deep_examples"])
def test_maximum_summary_allocation_report(case, monkeypatch):
    from plotsrv.observations.capture import Capture
    from plotsrv.observations.summary import validate_summary

    budget = ObservationBudget(
        max_rows=128,
        max_fields=32,
        max_elements=4096,
        max_nodes=4096,
        max_depth=8,
        max_value_bytes=1024,
        max_categories=64,
        max_capture_bytes=1024 * 1024,
        max_output_bytes=256 * 1024,
        exploratory_rows=16,
        capture_ms=50,
    )
    if case == "wide_numeric":
        obj = pd.DataFrame({str(i): [2**127 + j for j in range(64)] for i in range(16)})
    elif case == "unicode_examples":
        obj = ["😀" * 1000 + str(i) for i in range(128)]
    else:
        obj = 1
        for _ in range(8):
            obj = [obj] * 128
    original = Capture.__init__

    def initialize(self, *args):
        original(self, *args)
        self.deadline = float("inf")

    monkeypatch.setattr(Capture, "__init__", initialize)
    envelope = capture_detached(
        obj,
        budget=budget,
        options=ObservationOptions(include_examples=True),
        view_id="max",
    )
    gc.collect()
    tracemalloc.start()
    start = time.perf_counter()
    result = build_summary(envelope, budget=budget, publisher_session="test")
    elapsed = time.perf_counter() - start
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    validate_summary(result, view_id="max")
    assert len(encode_summary(result)) <= 65536
    print(
        json.dumps(
            {
                "case": case,
                "capture_bytes": len(envelope.payload),
                "summary_bytes": len(encode_summary(result)),
                "summary_traced_peak_bytes": peak,
                "summary_traced_retained_bytes": retained,
                "summary_seconds_with_tracing": elapsed,
                "reasons": result["reasons"],
            }
        )
    )


def test_first_inline_setup_after_imports(benchmark, monkeypatch, tmp_path):
    from plotsrv import settings
    from plotsrv.observations import admission

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.setattr(runtime, "_WORKER", None)
    monkeypatch.setattr(admission, "_ENGINE", None)
    monkeypatch.setattr(ObservationWorker, "_deliver", lambda *args: True)
    obj = {"rows": 123}

    def setup():
        runtime._WORKER = None
        admission._ENGINE = None

    def teardown(*args, **kwargs):
        worker = runtime._WORKER
        assert worker.engine.flush(1)
        worker.stop(timeout=1)

    benchmark.pedantic(
        publisher.publish_view,
        args=(obj,),
        kwargs={"observe": True, "view_id": "first"},
        setup=setup,
        teardown=teardown,
        rounds=30,
        iterations=1,
    )


@pytest.mark.parametrize("case", ["metrics", "frame", "broadcast", "huge_string"])
def test_interleaved_foreground_report(case, monkeypatch):
    from statistics import median

    obj = source(case)
    engine = CaptureEngine()
    worker = ObservationWorker(engine)
    monkeypatch.setattr(worker, "start", lambda: True)
    monkeypatch.setattr(runtime, "_WORKER", worker)
    worker.route(view_id="bench", label=None, force=False)
    functions = {
        "capture": lambda: engine.submit("bench", obj),
        "public": lambda: publisher.publish_view(obj, observe=True, view_id="bench"),
    }
    times = {"capture": [], "public": []}
    for trial in range(110):
        for name in (("capture", "public") if trial % 2 else ("public", "capture")):
            drain(engine)
            start = time.perf_counter_ns()
            functions[name]()
            duration = time.perf_counter_ns() - start
            if trial >= 10:
                times[name].append(duration / 1000)
    drain(engine)
    print(
        json.dumps(
            {
                "paired_case": case,
                "capture_median_us": median(times["capture"]),
                "public_median_us": median(times["public"]),
                "paired_delta_median_us": median(
                    [p - c for p, c in zip(times["public"], times["capture"])]
                ),
                "public_max_us": max(times["public"]),
            }
        )
    )
