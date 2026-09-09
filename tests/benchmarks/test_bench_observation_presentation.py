"""Server receipt/rendering costs; no source inspection in the timed operations."""

import gc
import json
import threading
import tracemalloc

import numpy as np
import pandas as pd
import pytest

from plotsrv import ingestion, settings, store
from plotsrv.app import get_artifact
from plotsrv.observations import history
from plotsrv.observations.capture import capture_detached
from plotsrv.observations.models import ObservationBudget
from plotsrv.observations.receiver import receive_observation
from plotsrv.observations.rendering import render_observation
from plotsrv.observations.summary import build_summary

pytestmark = pytest.mark.benchmark


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    ingestion.reset_ingestion()
    store.reset()
    source = pd.DataFrame(np.arange(800000).reshape(100000, 8))
    budget = ObservationBudget(capture_ms=50)
    value = build_summary(
        capture_detached(source, view_id="bench", budget=budget),
        budget=budget,
        publisher_session="bench",
    )
    for revision in range(1, 17):
        history.append(
            "bench",
            value,
            revision=revision,
            previous_revision=revision - 1,
            received_at=revision,
        )
    yield value
    store.reset()


@pytest.mark.parametrize(
    "mode", ["receipt_without_history", "receipt", "render", "cached_render"]
)
def test_observation_server_latency(benchmark, evidence, monkeypatch, mode):
    payload = dict(
        kind="artifact",
        artifact_kind="json",
        observation=evidence,
        view_id="bench",
        force=True,
    )
    if mode == "receipt_without_history":
        monkeypatch.setattr(history, "append", lambda *args, **kwargs: False)
    if mode.startswith("receipt"):
        function = lambda: receive_observation(payload)
    elif mode == "render":
        entries, _ = history.read("bench", revision=16)
        function = lambda: render_observation(
            evidence, view_id="bench", entries=entries
        )
    else:
        receive_observation(payload)
        get_artifact(view="bench")
        function = lambda: get_artifact(view="bench")
    benchmark.pedantic(function, rounds=100, iterations=1, warmup_rounds=5)


def test_observation_history_memory_plateau(evidence):
    history.clear()
    threads = {t.ident for t in threading.enumerate()}
    gc.collect()
    tracemalloc.start()
    for source in range(256):
        for revision in range(1, 33):
            history.append(
                str(source),
                evidence,
                revision=revision,
                previous_revision=revision - 1,
                received_at=revision,
            )
    gc.collect()
    retained, peak = tracemalloc.get_traced_memory()
    counts = history.stats()
    assert counts["bytes"] <= history.MAX_TOTAL_BYTES
    assert counts["sources"] <= history.MAX_SOURCES
    assert counts["entries"] <= history.MAX_SOURCES * history.MAX_ENTRIES
    history.clear()
    gc.collect()
    released, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert {t.ident for t in threading.enumerate()} == threads
    print(
        json.dumps(
            dict(
                case="bounded_history",
                **counts,
                python_retained=retained,
                python_peak=peak,
                after_clear=released,
            )
        )
    )


def test_observation_render_memory(evidence):
    entries, _ = history.read("bench", revision=16)
    gc.collect()
    tracemalloc.start()
    result = render_observation(evidence, view_id="bench", entries=entries)
    retained, peak = tracemalloc.get_traced_memory()
    html_bytes = len(result.html.encode())
    del result
    gc.collect()
    released, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            dict(
                case="render",
                html_bytes=html_bytes,
                python_retained=retained,
                python_peak=peak,
                after_release=released,
            )
        )
    )
