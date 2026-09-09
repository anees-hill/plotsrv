"""Separate foreground capture, background notification admission and queue memory."""

import gc
import json
import threading
import time
import tracemalloc

import pytest

from plotsrv import checks
from plotsrv.checks import CheckEngine
from plotsrv.checks_config import parse_checks
from plotsrv.webhooks import Outcome, WebhookDispatcher, MAX_BYTES, MAX_ITEMS
from tests.test_checks import spec
from tests.test_webhooks import configuration, rule, event

pytestmark = pytest.mark.benchmark


@pytest.mark.parametrize(
    "case", ["without_notifications", "stalled_notifications", "notification_admission"]
)
def test_webhook_path_latency(benchmark, case):
    release, entered = threading.Event(), threading.Event()

    def sender(*args):
        entered.set()
        release.wait(10)
        return Outcome("delivered", 200)

    rules = (
        (rule(),)
        if case != "without_notifications"
        else parse_checks({"rules": [spec()]})
    )
    engine = CheckEngine(
        rules,
        start=False,
        webhooks=configuration() if case != "without_notifications" else None,
    )
    dispatcher = engine.notifications
    if dispatcher:
        dispatcher._sender = sender
        dispatcher.submit(rules[0], event())
        assert entered.wait(1)
    records = [({"duration": 20}, {"source_revision": 1})]
    item = event(2)

    def reset():
        engine._pending.clear()
        engine._pending_bytes = 0
        engine._cpu_credit = checks.CAPTURE_CPU_BURST
        engine._tokens = checks.BURST
        engine._refill = time.monotonic()
        if case == "notification_admission":
            with dispatcher._condition:
                dispatcher._queue[:] = [dispatcher._inflight]
                dispatcher._bytes = len(dispatcher._inflight.body)
                dispatcher._last_cursor[("latency", "ops")] = 1

    try:
        fn = dispatcher.submit if case == "notification_admission" else engine.submit
        args = (
            (rules[0], item)
            if case == "notification_admission"
            else ("metrics", "state", records)
        )
        benchmark.pedantic(
            fn, args=args, setup=reset, rounds=100, iterations=1, warmup_rounds=5
        )
    finally:
        engine.close(0)
        release.set()
        assert engine.close(1)


def test_webhook_queue_memory_and_idle_report():
    release, entered = threading.Event(), threading.Event()

    def sender(*args):
        entered.set()
        release.wait(10)
        return Outcome("delivered", 200)

    r = rule()
    d = WebhookDispatcher(configuration(), [r], sender=sender)
    d.submit(r, event())
    assert entered.wait(1)
    gc.collect()
    tracemalloc.start()
    try:
        for n in range(2, 1002):
            d.submit(r, event(n))
        retained, peak = tracemalloc.get_traced_memory()
        count, encoded = len(d._queue), d._bytes
        assert count <= MAX_ITEMS and encoded <= MAX_BYTES
        assert not d.close(0)
        release.set()
        assert d.close(1)
        gc.collect()
        drained, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        release.set()
        d.close(1)
    idle = WebhookDispatcher(configuration(), [r])
    cpu = time.process_time()
    time.sleep(0.1)
    idle_cpu = time.process_time() - cpu
    assert idle.close(1)
    print(
        "webhook_resource_report="
        + json.dumps(
            dict(
                items=count,
                encoded_bytes=encoded,
                traced_retained=retained,
                traced_peak=peak,
                after_close=drained,
                idle_100ms_cpu_ms=idle_cpu * 1000,
            )
        )
    )
