from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
import gc
import json
import threading
import time
import weakref

import pytest
from fastapi.testclient import TestClient

from plotsrv import checks, config, ingestion, settings, store
from plotsrv.checks import CheckEngine, evaluate
from plotsrv.checks_config import parse_checks
from plotsrv.checks_evidence import Budget, Evidence, select


def rule(**kwargs):
    return parse_checks(
        {
            "rules": [
                dict(
                    id="latency",
                    source="metrics",
                    kind="state",
                    path=["duration"],
                    op="gt",
                    value=10,
                    **kwargs,
                )
            ]
        }
    )[0]


def spec(**kwargs):
    return (
        dict(
            id="latency",
            source="metrics",
            kind="state",
            path=["duration"],
            op="gt",
            value=10,
        )
        | kwargs
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    store.reset()
    yield
    store.reset()


@pytest.fixture
def engine():
    value = CheckEngine(parse_checks({"rules": [spec()]}))
    yield value
    value.close()


def submit(engine, value, revision=1):
    engine.submit(
        "metrics",
        "state",
        [(value, dict(source_revision=revision, received_at="2026-09-09T00:00:00Z"))],
    )
    assert engine.flush(1)
    return engine.snapshot()


@pytest.mark.parametrize(
    "op,value,trigger",
    [
        ("eq", 10, True),
        ("ne", 11, True),
        ("lt", 9, True),
        ("le", 10, True),
        ("gt", 11, True),
        ("ge", 10, True),
        ("gt", 10, False),
    ],
)
def test_operators(op, value, trigger):
    r = parse_checks({"rules": [spec(op=op)]})[0]
    assert evaluate(r, Evidence(value))[0] == ("triggered" if trigger else "ok")


@pytest.mark.parametrize(
    "value", [None, True, "11", float("nan"), float("inf"), [11], {}, 10**400]
)
def test_invalid_values_never_pass(value):
    r = rule()
    result = select(r, {"duration": value}, Budget())
    assert evaluate(r, result)[0] == "unknown"


def test_exact_large_int_and_rational_comparison():
    r = parse_checks({"rules": [spec(value=2**100, op="gt")]})[0]
    assert evaluate(r, Evidence(2**100 + 1))[0] == "triggered"
    assert evaluate(r, Evidence(Fraction(2**101 + 1, 2)))[0] == "triggered"
    assert evaluate(r, Evidence(float(2**100)))[0] == "ok"


@pytest.mark.parametrize(
    "change",
    [
        dict(op="eval"),
        dict(value=None),
        dict(value=True, op="gt"),
        dict(path="a.b"),
        dict(path=[-1]),
        dict(path=[True]),
        dict(path=["x"] * 9),
        dict(severity="error"),
        dict(enabled="false"),
        dict(notify=["unknown"]),
        dict(input="table"),
        dict(input="observation"),
        dict(kind="state", metric="mean"),
    ],
)
def test_invalid_configuration(change):
    with pytest.raises(ValueError):
        parse_checks({"rules": [spec(**change)]})


def test_config_disabled_duplicate_and_bounds():
    assert not parse_checks({"enabled": False, "rules": [spec()]})[0].enabled
    for rules in ([spec(), spec()], [spec(id=str(i)) for i in range(9)]):
        with pytest.raises(ValueError):
            parse_checks({"rules": rules})
    with pytest.raises(ValueError):
        parse_checks({"extra": True})


def test_state_baseline_transitions_unknown_and_real_recovery(engine):
    assert engine.snapshot()["states"][0]["state"] == "unknown"
    data = submit(engine, {"duration": 11})
    assert data["states"][0]["state"] == "triggered" and not data["events"]
    assert not submit(engine, {"duration": 12}, 2)["events"]
    data = submit(engine, {"duration": 3}, 3)
    assert [e["event_type"] for e in data["events"]] == ["recovered"]
    submit(engine, {"duration": 20}, 4)
    submit(engine, {}, 5)
    data = submit(engine, {"duration": 0}, 6)
    assert [e["event_type"] for e in data["events"]] == [
        "recovered",
        "triggered",
        "unavailable",
        "available",
    ]
    assert data["states"][0]["severity"] == "warning"
    assert data["events"][1]["context"]["source_revision"] == 4
    assert data["events"][1]["event_id"].startswith(engine.generation)


def test_unusual_keys_and_no_callbacks_or_sparse_scans():
    r = parse_checks({"rules": [spec(path=["a.b", 0, "/value"])]})[0]
    assert select(r, {"a.b": [{"/value": 11}]}, Budget()).value == 11

    class Hostile:
        def __eq__(self, other):
            raise AssertionError("equality executed")

        def __hash__(self):
            return 1

        def __repr__(self):
            raise AssertionError("repr executed")

    assert select(rule(), {Hostile(): 0, "duration": 11}, Budget()).value == 11
    assert select(rule(), Hostile(), Budget()).reason
    huge = {i: i for i in range(100000)}
    huge.clear()  # construct sparse backing with deletes instead of clear below
    huge = dict.fromkeys(range(100000))
    for key in range(100000):
        del huge[key]
    huge["duration"] = 11
    assert select(rule(), huge, Budget()).reason


def test_coalescing_and_overload_invalidate_current_state_without_false_recovery():
    e = CheckEngine([rule()], start=False)
    try:
        e.submit("metrics", "state", [({"duration": 20}, {"source_revision": 1})])
        e.submit("metrics", "state", [({"duration": 0}, {"source_revision": 2})])
        assert e.snapshot()["coalesced"] == 1
        e.start()
        assert e.flush(1)
        assert e.snapshot()["states"][0]["state"] == "ok"
        e._tokens = 0
        e._refill = time.monotonic()
        e.submit("metrics", "state", [({"duration": 20}, {"source_revision": 3})])
        data = e.snapshot()
        assert data["states"][0]["state"] == "unknown"
        assert data["states"][0]["coverage_lost"] >= 2
        e._tokens = 10
        data = submit(e, {"duration": 0}, 4)
        assert not any(x["event_type"] == "recovered" for x in data["events"])
    finally:
        e.close()


def test_events_are_ordered_occurrences_and_survive_source_release():
    rules = parse_checks({"rules": [spec(kind="event")]})
    e = CheckEngine(rules, start=False)

    class Large:
        pass

    source = Large()
    source.data = bytearray(10_000_000)
    reference = weakref.ref(source)
    rows = [
        (
            {"duration": 12, "ignored": source, "timestamp": "2026-09-09T12:00:00Z"},
            {"batch_position": i, "source_revision": i},
        )
        for i in range(4)
    ]
    e.submit("metrics", "event", rows)
    del rows, source
    gc.collect()
    assert reference() is None
    e.start()
    assert e.flush(1)
    data = e.snapshot()
    assert data["states"][0]["state"] == "ok"
    assert [x["context"]["batch_position"] for x in data["events"]] == [0, 1, 2, 3]
    assert all(x["event_type"] == "match" for x in data["events"])
    assert data["events"][0]["context"]["source_time_origin"] == "publisher_supplied"
    e.close()


def test_queue_and_history_caps_and_cursor(monkeypatch):
    monkeypatch.setattr(checks, "MAX_JOBS", 3)
    monkeypatch.setattr(checks, "MAX_EVENTS", 2)
    e = CheckEngine(parse_checks({"rules": [spec(kind="event")]}), start=False)
    try:
        e.submit(
            "metrics",
            "event",
            [({"duration": 12}, {"source_revision": i}) for i in range(20)],
        )
        data = e.snapshot()
        assert data["queued"] == 3 and data["pending_bytes"] <= checks.MAX_PENDING_BYTES
        assert data["states"][0]["coverage_lost"] == 17
        e.start()
        assert e.flush(1)
        data = e.snapshot()
        assert len(data["events"]) == 2 and data["history_gap"]
        assert len(e.snapshot(after=data["cursor"] - 1)["events"]) == 1
        assert e.snapshot(after=data["cursor"], generation="old")["history_gap"]
    finally:
        e.close()


def test_shutdown_and_disabled_engine_create_no_idle_threads():
    before = {t.ident for t in threading.enumerate()}
    e = CheckEngine([])
    assert e._thread is None and e.close()
    assert {t.ident for t in threading.enumerate()} == before
    e = CheckEngine([rule()])
    assert e.close()
    assert not e._thread.is_alive()
    e.start()
    assert not e._thread.is_alive()


def test_busy_admission_is_nonblocking_and_marks_gap(engine):
    acquired = threading.Event()
    release = threading.Event()

    def hold():
        with engine._condition:
            acquired.set()
            release.wait(2)

    t = threading.Thread(target=hold)
    t.start()
    assert acquired.wait(1)
    try:
        engine.submit("metrics", "state", [({"duration": 20}, {"source_revision": 1})])
        assert engine._lost["latency"] == 1
    finally:
        release.set()
        t.join(1)
    assert engine.snapshot()["states"][0]["reason"] == "coverage_gap"


def test_worker_failure_is_nonfatal_and_restart_does_not_overlap(monkeypatch):
    e = CheckEngine([rule()])
    original = e._process

    def fail(job):
        raise RuntimeError("private-source-details")

    monkeypatch.setattr(e, "_process", fail)
    try:
        data = submit(e, {"duration": 20})
        assert data["failures"] == 1
        assert data["states"][0]["state"] == "unknown"
        assert "private-source-details" not in json.dumps(data)
        monkeypatch.setattr(e, "_process", original)
        data = submit(e, {"duration": 0}, 2)
        assert data["states"][0]["state"] == "ok"
        assert not any(x["event_type"] == "recovered" for x in data["events"])
    finally:
        e.close()


def test_hostile_observation_tags_cannot_execute_callbacks():
    class Hostile:
        def __eq__(self, other):
            raise AssertionError("callback executed")

    r = replace(rule(), input="observation", metric="value", scope="supplied_value")
    source = {"type": Hostile(), "observation_version": 1, "recipe_version": 1}
    assert select(r, source, Budget()).reason == "incompatible_observation"
    source = {
        "type": "plotsrv_observation",
        "observation_version": 1,
        "recipe_version": 1,
        "provenance": {"selection": {"path": [Hostile()]}},
    }
    assert select(r, source, Budget()).reason == "incompatible_source_scope"


def test_snapshot_is_detached_and_stale_inflight_state_cannot_recover(monkeypatch):
    e = CheckEngine([replace(rule(), value=2**100)])
    started = threading.Event()
    release = threading.Event()
    try:
        submit(e, {"duration": 2**100 + 1})
        original = e._process

        def block(job):
            started.set()
            release.wait(2)
            original(job)

        monkeypatch.setattr(e, "_process", block)
        e.submit("metrics", "state", [({"duration": 0}, {"source_revision": 2})])
        assert started.wait(1)
        e._tokens = 0
        e._refill = time.monotonic()
        e.submit(
            "metrics", "state", [({"duration": 2**100 + 2}, {"source_revision": 3})]
        )
        release.set()
        assert e.flush(1)
        data = e.snapshot()
        assert data["states"][0]["state"] == "unknown"
        assert not any(x["event_type"] == "recovered" for x in data["events"])
        data["states"][0]["observed_value"]["value"] = "changed"
        assert e.snapshot()["states"][0]["observed_value"]["value"] != "changed"
    finally:
        release.set()
        e.close()


def test_json_document_numeric_boolean_and_normalized_text_limits():
    from plotsrv.json_model import build_json_document

    document = build_json_document(
        {"duration": 20, "status": " ok\n"}, source_format="python_object"
    )
    assert select(rule(), document, Budget()).value == 20
    text_rule = replace(rule(), path=("status",), op="eq", value="ok")
    assert select(text_rule, document, Budget()).reason
    document["pretty_text"] = "x" * 10_000_000
    document["raw_text"] = "x" * 10_000_000
    assert select(rule(), document, Budget()).value == 20
    document["root"]["truncated"] = True
    assert select(rule(), document, Budget()).reason


def test_observation_units_and_inspection_are_required():
    from tests.test_observation_presentation import summary

    r = replace(
        rule(),
        input="observation",
        metric="value",
        scope="supplied_value",
        unit="seconds",
    )
    s = summary({"duration": 20})
    assert select(r, s, Budget()).reason == "unit_mismatch"
    r = replace(r, unit=None)
    s["fields"][0]["values_inspected"] = 0
    assert select(r, s, Budget()).reason == "no_inspected_values"
