from __future__ import annotations

import gc
import threading
import weakref
from dataclasses import replace

import pytest

from plotsrv.observations import admission, capture
from plotsrv.observations.admission import CaptureEngine
from plotsrv.observations.models import CaptureOptions, ObservationBudget


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(admission.time, "monotonic", lambda: now[0])
    return now


@pytest.mark.parametrize(
    "changes",
    [
        dict(max_rows=True),
        dict(max_fields=100000),
        dict(capture_ms=float("nan")),
        dict(process_interval_s=0),
        dict(max_output_bytes=65536, max_pending_bytes=4096),
        dict(max_depth=-1),
    ],
)
def test_reject_unsafe_budgets(changes):
    with pytest.raises(ValueError):
        ObservationBudget(**changes)


@pytest.mark.parametrize(
    "settings", [None, {"unknown": 1}, {"max_rows": "5"}, {"capture_ms": float("inf")}]
)
def test_reject_invalid_mapping(settings):
    with pytest.raises(ValueError):
        ObservationBudget.from_mapping(settings)


@pytest.mark.parametrize(
    "settings",
    [
        dict(include_examples=1),
        dict(fields=["x"]),
        dict(fields=("x" * 129,)),
        dict(path=(object(),)),
        dict(path=tuple(range(7))),
    ],
)
def test_reject_unsafe_options(settings):
    with pytest.raises(ValueError):
        CaptureOptions(**settings)


def test_config_validates_without_echoing_input(monkeypatch, caplog):
    from plotsrv import config

    monkeypatch.setattr(
        config, "_merged_section", lambda section: {"observe": {"max_rows": 8}}
    )
    assert config.get_observation_budget().max_rows == 8
    monkeypatch.setattr(
        config, "_merged_section", lambda section: {"observe": {"token": "SECRET"}}
    )
    assert config.get_observation_budget() == ObservationBudget()
    assert "SECRET" not in caplog.text


def test_queue_reserves_before_capture_and_keeps_inflight_charged(clock, monkeypatch):
    engine = CaptureEngine(replace(ObservationBudget(), max_pending=1))
    assert engine.submit("a", {"x": 1}) == "accepted"
    work = engine.take()
    assert work and engine.stats()["reserved_bytes"] == engine.budget.max_output_bytes
    clock[0] += 2

    class Source:
        pass

    source = Source()
    ref = weakref.ref(source)

    def forbidden(*args, **kwargs):
        raise AssertionError("capture performed after failed admission")

    monkeypatch.setattr(capture, "capture_detached", forbidden)
    assert engine.submit("b", source) == "overloaded"
    assert engine.submit("a", source) == "view_pending"
    del source
    gc.collect()
    assert ref() is None
    assert engine.finish(work.token)
    assert not engine.finish(work.token)
    assert engine.stats()["reserved"] == 0


def test_byte_reservation_caps_queue_independently(clock):
    budget = replace(ObservationBudget(), max_pending_bytes=65536)
    engine = CaptureEngine(budget)
    assert engine.submit("a", 1) == "accepted"
    clock[0] += 2
    assert engine.submit("b", 2) == "overloaded"


def test_process_view_cadence_and_bounded_identity_catalogue(clock):
    engine = CaptureEngine(
        replace(ObservationBudget(), max_view_ids=2, process_interval_s=0.05)
    )
    assert engine.submit("a", 1) == "accepted"
    work = engine.take()
    assert engine.finish(work.token)
    assert engine.submit("b", 1) == "process_cadence"
    clock[0] += 0.1
    assert engine.submit("a", 1) == "view_cadence"
    assert engine.submit("b", 1) == "accepted"
    work = engine.take()
    assert engine.finish(work.token)
    clock[0] += 0.1
    for i in range(10000):
        assert engine.submit(str(i), object()) == "identity_capacity"
    assert engine.stats()["view_ids"] == 2
    clock[0] += 2
    assert engine.submit("new", 2) == "accepted"
    assert engine.stats()["view_ids"] == 2


def test_hot_path_does_not_wait_on_lock_and_close_reaps_when_contended(clock):
    engine = CaptureEngine()
    assert engine.submit("a", 1) == "accepted"
    with engine._lock:
        assert engine.submit("b", object()) == "busy"
        assert engine.take() is None
        assert not engine.finish(1)
        engine.close()
        assert not engine.reopen()
    assert engine.take() is None
    assert engine.stats()["reserved"] == 0
    assert engine.reopen()
    clock[0] += 2
    assert engine.submit("b", 1) == "accepted"


def test_close_preserves_inflight_accounting_until_ack(clock):
    engine = CaptureEngine()
    assert engine.submit("a", 1) == "accepted"
    first = engine.take()
    clock[0] += 2
    assert engine.submit("b", 2) == "accepted"
    engine.close()
    assert engine.stats()["pending"] == 0
    assert engine.stats()["reserved"] == 1
    assert not engine.reopen()
    assert engine.submit("c", 3) == "closed"
    assert engine.finish(first.token)
    assert engine.reopen()


def test_close_during_capture_does_not_allow_restart_or_parallel_capture(
    clock, monkeypatch
):
    engine = CaptureEngine()
    entered, release = threading.Event(), threading.Event()
    real = capture.capture_detached

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return real(*args, **kwargs)

    monkeypatch.setattr(capture, "capture_detached", paused)
    result = []
    thread = threading.Thread(target=lambda: result.append(engine.submit("a", 1)))
    thread.start()
    try:
        assert entered.wait(2)
        clock[0] += 2
        assert engine.submit("b", 2) == "capture_busy"
        engine.close()
        assert not engine.reopen()
        assert engine.stats()["reserved"] == 1
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert result == ["closed"]
    assert engine.stats()["reserved"] == 0
    assert engine.reopen()


def test_failed_and_contended_capture_release_capacity(clock, monkeypatch, caplog):
    engine = CaptureEngine()

    def failed(*args, **kwargs):
        raise ValueError("SECRET credential")

    monkeypatch.setattr(capture, "capture_detached", failed)
    assert engine.submit("a", object()) == "capture_failed"
    assert engine.stats()["reserved"] == 0
    assert "SECRET" not in caplog.text
    clock[0] += 2

    def contended(*args, **kwargs):
        engine._lock.acquire()
        return object()

    monkeypatch.setattr(capture, "capture_detached", contended)
    try:
        assert engine.submit("b", object()) == "busy"
    finally:
        engine._lock.release()
    assert engine.stats()["reserved"] == 0


def test_process_control_exceptions_propagate_without_leaking_reservations(
    clock, monkeypatch
):
    engine = CaptureEngine()

    def cancelled(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(capture, "capture_detached", cancelled)
    with pytest.raises(KeyboardInterrupt):
        engine.submit("a", 1)
    assert engine.stats()["reserved"] == 0


def test_pending_queue_has_only_detached_bytes_and_no_idle_workers(clock):
    before = {t.ident for t in threading.enumerate()}
    engine = CaptureEngine()
    import numpy as np

    source = np.arange(1000000)
    ref = weakref.ref(source)
    assert engine.submit("a", source) == "accepted"
    del source
    gc.collect()
    assert ref() is None
    work = engine.take()
    assert type(work.envelope.payload) is bytes
    assert engine.finish(work.token)
    engine.close()
    assert {t.ident for t in threading.enumerate()} == before


def test_singleton_does_not_reparse_config_per_call(monkeypatch):
    from plotsrv import config

    monkeypatch.setattr(admission, "_ENGINE", None)
    calls = []

    def budget():
        calls.append(1)
        return ObservationBudget()

    monkeypatch.setattr(config, "get_observation_budget", budget)
    assert admission.get_capture_engine() is admission.get_capture_engine()
    assert calls == [1]
