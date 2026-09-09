"""Check admission cost and bounded memory, excluding source/config construction."""

import gc
import json
import threading
import time
import tracemalloc

import pytest

from plotsrv import checks
from plotsrv.checks import CheckEngine
from plotsrv.checks_config import parse_checks
from tests.test_checks import spec
from tests.test_observation_presentation import summary

pytestmark = pytest.mark.benchmark


@pytest.mark.parametrize(
    "case",
    [
        "disabled",
        "scalar",
        "huge_mapping",
        "observation",
        "sampled_frame",
        "overloaded_event_batch",
    ],
)
def test_checks_admission_latency(benchmark, case):
    rule = spec()
    source = {"duration": 20}
    if case == "huge_mapping":
        source = dict.fromkeys(range(1_000_000))
        source["duration"] = 20
    if case == "observation":
        source = summary({"duration": 20})
        rule.update(input="observation", metric="value", scope="supplied_value")
    if case == "sampled_frame":
        import numpy as np
        import pandas as pd

        source = summary(
            pd.DataFrame(
                {
                    name: np.arange(100000)
                    for name in ["duration"] + [str(i) for i in range(7)]
                }
            )
        )
        rule.update(input="observation", metric="mean", scope="base_sample")
    if case == "overloaded_event_batch":
        rule["kind"] = "event"
    rules = parse_checks({"rules": [rule]}) if case != "disabled" else ()
    engine = CheckEngine(rules, start=False)
    records = [
        (source, {"source_revision": i})
        for i in range(100 if case == "overloaded_event_batch" else 1)
    ]

    def reset():
        engine._pending.clear()
        engine._pending_bytes = 0
        engine._cpu_credit = checks.CAPTURE_CPU_BURST
        engine._tokens = 0 if case == "overloaded_event_batch" else checks.BURST
        engine._refill = time.monotonic()

    try:
        benchmark.pedantic(
            engine.submit,
            args=("metrics", rule["kind"], records),
            setup=reset,
            rounds=100,
            iterations=1,
            warmup_rounds=5,
        )
        if case in ("scalar", "observation", "sampled_frame"):
            assert next(iter(engine._pending.values())).evidence[0][1].reason is None
    finally:
        engine.close()


def test_check_memory_and_idle_report():
    rules = parse_checks({"rules": [spec(kind="event")]})
    engine = CheckEngine(rules, start=False)
    rows = [
        ({"duration": 20, "ignored": "x" * 1_000_000}, {"source_revision": i})
        for i in range(100)
    ]
    gc.collect()
    tracemalloc.start()
    for _ in range(100):
        engine._tokens = checks.BURST
        engine._cpu_credit = checks.CAPTURE_CPU_BURST
        engine.submit("metrics", "event", rows)
    retained, peak = tracemalloc.get_traced_memory()
    stats = engine.snapshot()
    assert stats["pending_bytes"] <= checks.MAX_PENDING_BYTES
    assert stats["queued"] <= checks.MAX_JOBS
    engine.start()
    assert engine.flush(2)
    gc.collect()
    drained, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    cpu = time.process_time()
    time.sleep(0.1)
    idle_cpu = time.process_time() - cpu
    assert engine._idle
    engine.close()
    assert not engine._thread.is_alive()
    print(
        json.dumps(
            dict(
                case="checks_queue",
                queued=stats["queued"],
                reserved=stats["pending_bytes"],
                traced_retained=retained,
                traced_peak=peak,
                after_drain=drained,
                idle_100ms_cpu_ms=idle_cpu * 1000,
            )
        )
    )
