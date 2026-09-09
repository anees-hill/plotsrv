"""HTTP interpretation is optional, bounded and never modifies raw evidence."""

from datetime import datetime, timezone, timedelta
import json

import pytest
from plotsrv.streams.http_profile import (
    HttpProfile,
    MAX_RECORDS,
    PREFIX,
    validate_override,
)
from plotsrv.streams.http_adapter import adapt_frame
from plotsrv.streams.text_framing import TextFrame
from tests.test_streams import client, reset_stream_state, _register_stream, _append

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def event(**values):
    return {"method": "GET", "path": "/item/123?token=secret", "status": 200, **values}


def describe(records, override=None):
    profile = HttpProfile(override)
    for i, record in enumerate(records, 1):
        profile.add(i, record, NOW + timedelta(seconds=i))
    return profile, profile.describe("test:layout", list(records[0]) if records else [])


def test_flat_structured_and_adapter_have_valid_units_separate_times_and_raw():
    source = event(
        duration_ms=12.5, timestamp=NOW.isoformat(), route="/item/{id}?secret=yes"
    )
    original = json.dumps(source)
    profile, data = describe([source])
    assert data["time_origin"] == "event"
    assert len(data["recipes"]) == 8
    assert profile.rows[1]["endpoint"] == "/item/{id}"
    assert "secret" not in json.dumps(profile.projection(1))
    assert json.dumps(source) == original
    assert data["recipes"][0]["sourceId"] == "test:layout"
    adapted = adapt_frame(
        TextFrame(b'INFO: 127.0.0.1:99 - "GET /ok HTTP/1.1" 200', 0, 64),
        observed_at=NOW,
        adapter="uvicorn",
    )
    profile, data = describe([adapted, {"event": {"kind": "traceback"}}])
    assert data["request_count"] == 1
    assert data["time_origin"] == "observed"
    assert len(data["recipes"]) == 5
    assert profile.rows[2] is None


@pytest.mark.parametrize(
    "record",
    [
        event(status="200"),
        event(status=True),
        event(status=600),
        event(method="maybe"),
        event(path="https://example.test/a"),
        event(path="/a\x00"),
        event(path="/" + "a" * 2000),
        {"time": 10, "path": "/"},
        {**event(), "http": event()},
        {"log_schema_version": 2, **event()},
        {**event(), **{str(i): i for i in range(33)}},
    ],
)
def test_unknown_invalid_and_ambiguous_are_raw_only(record):
    _, data = describe([record])
    assert data["recipes"] == []


@pytest.mark.parametrize(
    "duration", [None, "12", -1, True, float("inf"), float("nan"), 10**100]
)
def test_invalid_duration_never_enables_latency(duration):
    _, data = describe([event(duration_ms=duration, time=100)])
    assert len(data["recipes"]) == 5
    assert data["time_origin"] == "received"


def test_explicit_mapping_disable_and_validation():
    mapping = {
        "method": ["verb"],
        "path": ["url"],
        "status": ["code"],
        "duration": ["time"],
        "duration_unit": "s",
    }
    profile, data = describe(
        [{"verb": "GET", "url": "/", "code": 503, "time": 0.5}], mapping
    )
    assert profile.rows[1]["duration"] == 500
    assert len(data["recipes"]) == 8
    assert describe([event()], False)[1]["recipes"] == []
    for override in (
        True,
        {**mapping, "duration_unit": "minutes"},
        {**mapping, "path": "/some/file"},
        {"method": ["x"]},
    ):
        with pytest.raises(ValueError):
            validate_override(override)
        assert describe([event()], override)[1]["recipes"] == []


def test_bounded_window_cardinality_eviction_and_identity_no_remapping():
    profile = HttpProfile()
    for i in range(MAX_RECORDS * 3):
        profile.add(i, event(path=f"/user/{i}"), NOW)
    assert len(profile.rows) == MAX_RECORDS
    assert profile.describe("a", ["path"])["first_sequence"] == MAX_RECORDS * 2
    first = profile.identity
    profile.add(2000, {"http": event()}, NOW)
    assert profile.rows[2000] is None
    profile.add(2001, event(route="/user/{id}", timestamp=NOW.isoformat()), NOW)
    assert profile.identity == first
    assert profile.time_origin == "received"
    assert profile.endpoint_origin == "path"
    profile.evict(2001)
    assert profile.projection(2001) is None
    assert describe([event()])[0].identity == first
    assert describe([event(timestamp=NOW.isoformat())])[0].identity != first


def test_collision_and_compact_history_are_unavailable():
    profile, _ = describe([event()])
    assert profile.describe("x", [], historical=True)["recipes"] == []
    profile.add(2, {**event(), PREFIX + "collision": "raw"}, NOW)
    assert profile.disabled and not profile.rows
    assert profile.describe("x", [])["recipes"] == []


def test_http_response_incremental_retry_raw_and_catalogue(client, monkeypatch):
    from plotsrv import config, store
    from plotsrv.streams.server_state import stream_registry

    monkeypatch.setattr(config, "get_stream_raw_max_records", lambda: 2)
    _register_stream(client)
    records = [event(), {"message": "Traceback (most recent call last):"}]
    _append(client, batch_sequence=0, records=records)
    _append(client, batch_sequence=0, records=records)
    data = client.get("/stream/data", params={"view": "logs:worker stream"}).json()
    assert [row["data"] for row in data["records"]] == records
    assert data["http_profile"]["request_count"] == 1
    assert data["http_profile"]["inspected_count"] == 2
    assert all(
        spec["sourceId"] == "logs:worker stream"
        for spec in data["http_profile"]["recipes"]
    )
    _append(client, batch_sequence=1, records=[event(status=500)])
    data = client.get(
        "/stream/data", params={"view": "logs:worker stream", "after": 2}
    ).json()
    assert len(data["records"]) == 1
    assert data["http_profile"]["request_count"] == 1
    assert data["http_profile"]["first_sequence"] == 2
    assert len(stream_registry._streams["logs:worker stream"].http_profile.rows) == 2


def test_mapping_is_detached_and_partial_adapter_events_are_not_requests():
    mapping = {"method": ["method"], "path": ["path"], "status": ["status"]}
    profile = HttpProfile(mapping)
    mapping["status"][0] = "different"
    profile.add(1, event(), NOW)
    assert profile.rows[1]["status"] == 200
    adapted = adapt_frame(
        TextFrame(b'INFO: 127.0.0.1:99 - "GET / HTTP/1.1" 200', 0, 55),
        observed_at=NOW,
        adapter="uvicorn",
    )
    for key in ("partial", "truncated", "ambiguous"):
        source = {**adapted, "raw": {**adapted["raw"], key: True}}
        assert describe([source])[1]["recipes"] == []


@pytest.mark.parametrize(
    "unit,expected", [("ns", 0.000002), ("us", 0.002), ("ms", 2), ("s", 2000)]
)
def test_explicit_duration_units(unit, expected):
    mapping = {
        "method": ["method"],
        "path": ["path"],
        "status": ["status"],
        "duration": ["elapsed"],
        "duration_unit": unit,
    }
    profile, _ = describe([event(elapsed=2)], mapping)
    assert profile.rows[1]["duration"] == pytest.approx(expected)


def test_naive_time_and_later_clock_loss_do_not_change_mapping():
    profile, data = describe([event(timestamp="2026-09-09T01:02:03")])
    assert data["time_origin"] == "received"
    profile, _ = describe(
        [event(timestamp=NOW.isoformat()), event(timestamp="invalid")]
    )
    assert profile.time_origin == "event"
    assert profile.rows[2]["time"] is None


def test_wide_and_long_column_names_cannot_produce_unstorable_recipes():
    profile, _ = describe([event()])
    for columns in (
        [str(i) for i in range(101)],
        ["x" * 257],
        ["x" * 100 + str(i) for i in range(32)],
    ):
        assert not profile.describe("x", columns)["recipes"]
    data = profile.describe("x", ["x" * 100 + str(i) for i in range(20)])
    assert all(
        len(json.dumps(spec, ensure_ascii=False)) < 16384 for spec in data["recipes"]
    )


def test_catalogue_locked_recipes_keep_only_admitted_source(
    tmp_path, monkeypatch, client
):
    from plotsrv import settings, ingestion, store
    from tests.test_ingestion import configure

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    configure(
        tmp_path, monkeypatch, key=False, mode="catalogue-locked", ids=["web:access"]
    )
    try:
        _register_stream(client, view_id="web:access")
        _append(client, view_id="web:access", batch_sequence=0, records=[event()])
        data = client.get("/stream/data", params={"view": "web:access"}).json()
        assert len(data["http_profile"]["recipes"]) == 5
        assert set(store._VIEWS) == {"web:access"}
        assert all(
            spec["sourceId"] == "web:access" for spec in data["http_profile"]["recipes"]
        )
    finally:
        ingestion.reset_ingestion()
