"""Common Python logs get useful views only when the shape is unambiguous."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from plotsrv.streams.http_adapter import adapt_frame
from plotsrv.streams.http_profile import HttpProfile, ProfileBudget
from plotsrv.streams.log_profile import LogProfile, PREFIX
from plotsrv.streams.text_framing import TextFrame
from tests.test_streams import client, reset_stream_state, _append, _register_stream

NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "python_logs"


def structured():
    return [
        json.loads(line)
        for line in (FIXTURES / "structured.jsonl").read_text().splitlines()
    ]


def text_records():
    return [
        adapt_frame(
            TextFrame(line.encode(), 0, len(line)), observed_at=NOW, adapter="text"
        )
        for line in (FIXTURES / "standard.log").read_text().splitlines()
    ]


@pytest.mark.parametrize(
    "records,kind",
    [
        (structured(), "python_json:timestamp,level,logger,message"),
        (text_records(), "python_text"),
    ],
)
def test_detection_projection_and_recipes(records, kind):
    budget = ProfileBudget()
    profile = LogProfile(budget=budget)
    for sequence, record in enumerate(records, 1):
        profile.add(sequence, record, NOW)
    descriptor = profile.describe("worker:log", list(records[0]))
    assert descriptor["kind"] == kind
    assert descriptor["event_count"] == 3
    assert [recipe["name"] for recipe in descriptor["recipes"]] == [
        "Recent log events",
        "Warnings and errors",
        "Events by level over time",
        "Busiest loggers",
    ]
    assert all(recipe["sourceId"] == "worker:log" for recipe in descriptor["recipes"])
    assert (
        descriptor["recipes"][1]["presentation"]["filters"][1]["value"]
        == "WARNING\nERROR\nCRITICAL"
    )
    assert descriptor["recipes"][2]["presentation"]["plot"]["type"] == "time-count"
    assert (
        descriptor["recipes"][3]["presentation"]["plot"]["seriesField"]
        == descriptor["fields"]["level"]
    )
    assert profile.projection(3)["logger"] == "worker.db"
    assert profile.projection(3)["message"] == "Connection failed"
    assert budget.used > 0
    profile.clear()
    assert budget.used == 0


@pytest.mark.parametrize(
    "record",
    [
        {"level": "INFO", "logger": "worker", "message": "missing time"},
        {
            "timestamp": "2026-09-99 12:00:00",
            "level": "INFO",
            "logger": "worker",
            "message": "invalid time",
        },
        {
            "timestamp": NOW.isoformat(),
            "level": ["INFO"],
            "logger": "worker",
            "message": "bad level",
        },
        {
            "timestamp": NOW.isoformat(),
            "level": "INFO",
            "logger": "bad logger!",
            "message": "bad logger",
        },
        {
            "timestamp": NOW.isoformat(),
            "level": "INFO",
            "logger": "worker",
            "message": "both",
            "http": {},
        },
        {
            "log_schema_version": 2,
            "timestamp": NOW.isoformat(),
            "level": "INFO",
            "logger": "worker",
            "message": "version",
        },
    ],
)
def test_ambiguous_and_incomplete_records_stay_generic(record):
    profile = LogProfile()
    profile.add(1, record, NOW)
    assert profile.describe("worker:log", list(record))["recipes"] == []


def test_partial_text_and_http_do_not_get_log_views():
    for record in text_records()[:1]:
        for flag in ("partial", "truncated", "ambiguous"):
            profile = LogProfile()
            profile.add(1, {**record, "raw": {**record["raw"], flag: True}}, NOW)
            assert not profile.describe("worker:log", list(record))["recipes"]
    http = {"method": "GET", "path": "/", "status": 200}
    profile = LogProfile()
    profile.add(1, http, NOW)
    assert profile.projection(1) is None
    existing = HttpProfile()
    existing.add(1, http, NOW)
    assert existing.describe("web:access", list(http))["recipes"]


def test_session_mapping_is_stable_and_collision_disables():
    profile = LogProfile()
    profile.add(1, structured()[0], NOW)
    identity = profile.identity
    profile.add(2, text_records()[0], NOW)
    assert profile.projection(2) is None
    assert profile.identity == identity
    profile.add(3, {**structured()[1], PREFIX + "spoof": 1}, NOW)
    assert profile.disabled
    assert not profile.describe("worker:log", ["message"])["recipes"]


def test_log_time_origin_is_fixed_by_first_recognised_event():
    first, second = structured()[:2]
    profile = LogProfile()
    profile.add(1, first, NOW)
    profile.add(2, {**second, "timestamp": "invalid"}, NOW)
    assert profile.time_origin == "event"
    assert profile.projection(2) is None
    text = text_records()
    profile = LogProfile()
    profile.add(1, text[0], NOW)
    profile.add(2, text[2], NOW)
    assert profile.time_origin == "received"
    assert profile.projection(2)["time"] == NOW.isoformat()

    naive = {**first, "timestamp": "2026-09-09 12:00:00"}
    profile = LogProfile()
    profile.add(1, naive, NOW)
    assert profile.time_origin == "received"
    assert profile.projection(1)["time"] == NOW.isoformat()


def test_stdlib_json_field_names_and_ambiguous_dual_shape():
    record = {
        "asctime": "2026-09-09 12:00:00,000",
        "levelname": "ERROR",
        "name": "worker.db",
        "message": "Connection failed",
    }
    profile = LogProfile()
    profile.add(1, record, NOW)
    assert profile.describe("worker:log", list(record))["kind"].startswith(
        "python_json:asctime"
    )
    assert profile.projection(1)["time"] == NOW.isoformat()
    ambiguous = {**record, **structured()[0]}
    profile = LogProfile()
    profile.add(1, ambiguous, NOW)
    assert not profile.describe("worker:log", list(ambiguous))["recipes"]


def test_stream_response_includes_log_profile_and_projection(client):
    _register_stream(client)
    records = structured()
    _append(client, batch_sequence=0, records=records)
    data = client.get("/stream/data", params={"view": "logs:worker stream"}).json()
    assert data["log_profile"]["event_count"] == 3
    assert data["http_profile"]["recipes"] == []
    assert [row["log_projection"]["level"] for row in data["records"]] == [
        "INFO",
        "WARNING",
        "ERROR",
    ]
    assert [row["data"] for row in data["records"]] == records
