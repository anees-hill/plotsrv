from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from plotsrv import app as app_module
from plotsrv import config, http_streams, store
from plotsrv.app import app
from plotsrv.streams.models import STREAM_PROTOCOL_VERSION
from plotsrv.streams.server_state import StreamRegistry


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = StreamRegistry()
    store.reset()
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    monkeypatch.setattr(config, "get_status_local_only", lambda: False)
    monkeypatch.setattr(app_module, "stream_registry", registry)
    monkeypatch.setattr(http_streams, "stream_registry", registry)
    yield
    store.reset()


def test_ordinary_arrival_activity_is_process_local_and_bounded() -> None:
    view_id = "demo:bounded"
    start = datetime(2026, 1, 1, tzinfo=UTC)

    for index in range(store.MAX_DATA_ACTIVITY_EVENTS + 20):
        store.record_data_arrival(
            view_id=view_id,
            received_at=(start + timedelta(seconds=index)).isoformat(),
        )

    activity = store.get_data_activity(view_id=view_id)

    assert activity["scope"] == "process_lifetime"
    assert activity["bounded"] is True
    assert activity["limit"] == 256
    assert activity["event_count"] == 256
    assert activity["represented_item_count"] == 256
    assert activity["events"][0]["received_at"] == (
        start + timedelta(seconds=20)
    ).isoformat()


def test_published_content_records_arrival_but_errors_and_restore_do_not() -> None:
    view_id = "demo:message"
    store.set_artifact(obj="one", kind="text", view_id=view_id)
    first = store.get_data_activity(view_id=view_id)
    assert first["event_count"] == 1

    store.mark_error("render failed", view_id=view_id)
    assert store.get_data_activity(view_id=view_id)["event_count"] == 1

    store.set_artifact(
        obj="restored",
        kind="text",
        view_id="demo:restored",
        record_arrival=False,
    )
    assert store.get_data_activity(view_id="demo:restored")["events"] == []


def test_status_exposes_activity_scope_source_and_last_arrival() -> None:
    view_id = "demo:status"
    store.set_table(
        pd.DataFrame({"value": [1]}),
        html_simple=None,
        view_id=view_id,
    )

    response = TestClient(app).get("/status", params={"view": view_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_activity"]["represents"] == "published_updates"
    assert payload["data_activity"]["retention_note"].startswith(
        "Bounded activity observed"
    )
    assert payload["last_data_arrival_at"] == payload["data_activity"]["events"][-1][
        "received_at"
    ]
    assert payload["data_source"] == {
        "type": "publish",
        "label": "Python/API publish",
    }
    assert payload["stream_status"] is None


def test_stream_activity_counts_records_but_excludes_heartbeats_and_retries() -> None:
    client = TestClient(app)
    view_id = "logs:activity"
    identity = {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": view_id,
        "client_id": "client",
        "session_id": "session",
    }
    registered = client.post(
        "/stream/register",
        json={**identity, "label": "activity", "section": "logs"},
    )
    assert registered.status_code == 200
    assert store.get_data_activity(view_id=view_id)["event_count"] == 0

    append_payload = {
        **identity,
        "batch_id": "batch-0",
        "batch_sequence": 0,
        "records": [{"value": 1}, {"value": 2}, {"value": 3}],
    }
    appended = client.post("/stream/append", json=append_payload)
    assert appended.status_code == 200

    heartbeat = client.post(
        "/stream/heartbeat",
        json={**identity, "delivery_state": "retrying", "pending_delivery": True},
    )
    assert heartbeat.status_code == 200

    heartbeat_payload = client.get("/status", params={"view": view_id}).json()
    assert heartbeat_payload["stream_status"]["lifecycle"] == "retrying"
    assert heartbeat_payload["data_activity"]["event_count"] == 1

    duplicate = client.post("/stream/append", json=append_payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    payload = client.get("/status", params={"view": view_id}).json()
    activity = payload["data_activity"]
    assert activity["represents"] == "accepted_stream_records"
    assert activity["event_count"] == 1
    assert activity["represented_item_count"] == 3
    assert activity["events"][0]["count"] == 3
    assert activity["events"][0]["source"] == "stream"
    assert payload["stream_status"]["lifecycle"] == "live"
    assert payload["data_source"] == {"type": "stream", "label": "Stream producer"}
