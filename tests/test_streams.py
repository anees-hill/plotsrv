from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from fractions import Fraction
import json
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import threading
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
from fastapi.testclient import TestClient

from plotsrv import config, start_server, stop_server, store, stream_view
from plotsrv.app import app
from plotsrv.streams import api as stream_api
from plotsrv.streams import client as stream_client
from plotsrv.streams import file_source
from plotsrv.streams.client import StreamClient
from plotsrv.streams.file_source import JsonlBatch, JsonlFollower, JsonlRecord
from plotsrv.streams.models import (
    MAX_STREAM_BATCH_RECORDS,
    MAX_STREAM_ID_CHARS,
    MAX_STREAM_RECORD_BYTES,
    MAX_STREAM_REQUEST_BYTES,
    STREAM_PROTOCOL_VERSION,
    StreamAppend,
    StreamBatchValidationError,
    StreamClose,
    StreamHeartbeat,
    StreamRegistration,
    StreamRecord,
    StreamRecordValidationError,
    SourceHealth,
    SourceStatus,
    stream_record_size,
    recognize_structured_severity,
)
from plotsrv.streams.server_state import StreamRegistry, StreamStateError, stream_registry
from plotsrv.streams.summaries import SummaryLimits, SummaryWindow
from plotsrv.ui_assets import get_ui_assets


TEST_CLIENT_ID = "test-client"
TEST_SESSION_ID = "test-session"


@pytest.fixture(autouse=True)
def reset_stream_state(monkeypatch: pytest.MonkeyPatch) -> None:
    store.reset()
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    yield
    store.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _register_stream(
    client: TestClient,
    *,
    view_id: str = "logs:worker stream",
    label: str = "worker stream",
    section: str = "logs",
    client_id: str = TEST_CLIENT_ID,
    session_id: str = TEST_SESSION_ID,
) -> None:
    response = client.post(
        "/stream/register",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": view_id,
            "label": label,
            "section": section,
            "client_id": client_id,
            "session_id": session_id,
        },
    )
    assert response.status_code == 200, response.text


def _append(
    client: TestClient,
    *,
    batch_sequence: int,
    records: list[dict[str, object]],
    view_id: str = "logs:worker stream",
    client_id: str = TEST_CLIENT_ID,
    session_id: str = TEST_SESSION_ID,
) -> None:
    response = client.post(
        "/stream/append",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": view_id,
            "client_id": client_id,
            "session_id": session_id,
            "batch_id": f"batch-{batch_sequence}",
            "batch_sequence": batch_sequence,
            "records": records,
        },
    )
    assert response.status_code == 200, response.text


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 1.0) -> None:
    """Wait briefly for the deliberately asynchronous source worker."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _read_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=0.2) as response:  # noqa: S310 - local test server
        data = json.loads(response.read().decode("utf-8"))
    assert isinstance(data, dict)
    return data


def test_stream_page_uses_bundled_live_grid_and_exposes_ordered_records(
    client: TestClient,
) -> None:
    _register_stream(client)
    _append(
        client,
        batch_sequence=0,
        records=[{"sequence": 1, "nested": {"z": 2, "a": 1}}],
    )
    _append(
        client,
        batch_sequence=1,
        records=[{"sequence": 2, "new_field": None}],
    )

    page = client.get("/?view=logs:worker%20stream")
    assert page.status_code == 200
    assert 'data-kind="stream"' in page.text
    assert 'id="stream-grid"' in page.text
    assert 'id="stream-lifecycle-badge"' in page.text
    assert 'id="stream-health-inline"' in page.text
    assert 'id="stream-history-picker"' in page.text
    assert 'id="stream-history-session-select"' in page.text
    assert "Stored sessions" in page.text
    assert 'data-returning-kind="since-last-visit"' in page.text
    assert 'id="stream-since-visit-status"' in page.text
    assert "Since last visit" in page.text
    assert 'data-noteworthy-kind="stream-noteworthy"' in page.text
    assert 'id="stream-noteworthy-items"' in page.text
    assert "Noteworthy observations" in page.text
    assert 'data-summary-kind="derived-stream-history"' in page.text
    assert 'id="stream-summary-windows"' in page.text
    assert "Derived compact history" in page.text
    assert 'id="table-search-input"' in page.text
    assert 'id="table-group-by-select"' in page.text
    assert "No grouping" in page.text
    assert 'id="table-mode-table-btn"' in page.text
    assert 'id="table-mode-plot-btn"' in page.text
    assert 'id="table-plot-controls"' in page.text
    assert 'id="table-plot-output"' in page.text
    assert 'id="table-filters-toggle-btn"' in page.text
    assert 'id="table-columns-toggle-btn"' in page.text
    assert "refreshStream()" in page.text
    assert "/static/vendor/tabulator/5.5.0/tabulator.min.js" in page.text

    data = client.get("/stream/data", params={"view": "logs:worker stream"})
    assert data.status_code == 200
    payload = data.json()
    assert payload["client_id"] == TEST_CLIENT_ID
    assert payload["session_id"] == TEST_SESSION_ID
    assert payload["lifecycle"] == "live"
    assert payload["pending_delivery"] is False
    assert isinstance(payload["last_heartbeat_at"], str)
    assert payload["columns"] == ["sequence", "nested", "new_field"]
    assert [row["data"]["sequence"] for row in payload["records"]] == [1, 2]
    assert [row["browser_sequence"] for row in payload["records"]] == [1, 2]
    assert payload["first_available_browser_sequence"] == 1
    assert payload["next_browser_sequence"] == 3
    assert payload["records"][1]["data"]["new_field"] is None


def test_stream_data_after_cursor_returns_only_new_rows_and_schema_state(
    client: TestClient,
) -> None:
    _register_stream(client)
    _append(client, batch_sequence=0, records=[{"sequence": 1}])

    initial = client.get("/stream/data", params={"view": "logs:worker stream"})
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert [row["browser_sequence"] for row in initial_payload["records"]] == [1]
    assert initial_payload["schema_revision"] == 1
    assert initial_payload["reset_required"] is False
    assert initial_payload["reset_reason"] is None
    assert initial_payload["raw_window"] == {
        "first_browser_sequence": 1,
        "last_browser_sequence": 1,
        "record_count": 1,
        "max_record_count": stream_registry.max_recent_records,
    }

    _append(
        client,
        batch_sequence=1,
        records=[{"sequence": 2, "new_field": "added later"}],
    )
    incremental = client.get(
        "/stream/data",
        params={
            "view": "logs:worker stream",
            "after": 1,
            "session_id": initial_payload["session_id"],
        },
    )
    assert incremental.status_code == 200
    payload = incremental.json()
    assert [row["data"] for row in payload["records"]] == [
        {"sequence": 2, "new_field": "added later"}
    ]
    assert payload["returned_records"] == 1
    assert payload["returned_record_bytes"] > 0
    assert payload["max_returned_records"] == stream_registry.max_recent_records
    assert payload["max_returned_record_bytes"] > payload["returned_record_bytes"]
    assert payload["columns"] == ["sequence", "new_field"]
    assert payload["schema_revision"] == 2
    assert payload["first_available_browser_sequence"] == 1
    assert payload["last_available_browser_sequence"] == 2
    assert payload["next_browser_sequence"] == 3
    assert payload["requested_after_browser_sequence"] == 1
    assert payload["reset_required"] is False


def test_stream_data_requires_an_explicit_reset_for_an_aged_out_cursor() -> None:
    registry = StreamRegistry(max_recent_records=2)
    registration = StreamRegistration(
        view_id="logs:cursor-reset",
        label="cursor reset",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)
    registry.append(
        StreamAppend(
            view_id=registration.view_id,
            client_id=registration.client_id,
            session_id=registration.session_id,
            batch_id="first",
            batch_sequence=0,
            records=({"sequence": 1}, {"sequence": 2}, {"sequence": 3}),
        )
    )

    payload = registry.data(view_id=registration.view_id, after=0)

    assert [row["browser_sequence"] for row in payload["records"]] == [2, 3]
    assert payload["reset_required"] is True
    assert payload["reset_reason"] == "cursor_aged_out"
    assert payload["first_available_browser_sequence"] == 2
    assert payload["last_available_browser_sequence"] == 3
    assert payload["raw_window"] == {
        "first_browser_sequence": 2,
        "last_browser_sequence": 3,
        "record_count": 2,
        "max_record_count": 2,
    }

    # The predecessor is allowed: it proves the client received every row
    # that has since been evicted, so no reset is required.
    predecessor = registry.data(view_id=registration.view_id, after=1)
    assert [row["browser_sequence"] for row in predecessor["records"]] == [2, 3]
    assert predecessor["reset_required"] is False

    session_reset = registry.data(
        view_id=registration.view_id,
        after=3,
        session_id="replaced-session",
    )
    assert [row["browser_sequence"] for row in session_reset["records"]] == [2, 3]
    assert session_reset["reset_required"] is True
    assert session_reset["reset_reason"] == "session_changed"


def test_same_session_registration_is_idempotent_without_metadata_mutation(
    client: TestClient,
) -> None:
    payload = {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": "logs:identity",
        "label": "identity stream",
        "section": "logs",
        "client_id": "producer-a",
        "session_id": "session-a",
    }

    first = client.post("/stream/register", json=payload)
    repeated = client.post("/stream/register", json=payload)

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert repeated.json()["client_id"] == "producer-a"
    assert repeated.json()["session_id"] == "session-a"
    assert len(store.list_views()) == 1

    altered = client.post("/stream/register", json={**payload, "label": "renamed"})
    assert altered.status_code == 409
    data = client.get("/stream/data", params={"view": "logs:identity"})
    assert data.json()["label"] == "identity stream"


@pytest.mark.parametrize(
    ("client_id", "session_id"),
    (("producer-b", "session-b"), ("producer-a", "session-b"), ("producer-b", "session-a")),
)
def test_competing_active_producer_sessions_are_rejected(
    client: TestClient, client_id: str, session_id: str
) -> None:
    _register_stream(client, view_id="logs:ownership", client_id="producer-a", session_id="session-a")

    competing = client.post(
        "/stream/register",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": "logs:ownership",
            "label": "worker stream",
            "section": "logs",
            "client_id": client_id,
            "session_id": session_id,
        },
    )

    assert competing.status_code == 409
    assert "active producer session" in competing.json()["detail"]
    assert len(store.list_views()) == 1


def test_append_must_name_the_client_and_session_that_own_the_stream(
    client: TestClient,
) -> None:
    _register_stream(client, view_id="logs:ownership", client_id="producer-a", session_id="session-a")

    response = client.post(
        "/stream/append",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": "logs:ownership",
            "client_id": "producer-b",
            "session_id": "session-a",
            "batch_id": "forged-batch",
            "batch_sequence": 0,
            "records": [{"sequence": 1}],
        },
    )

    assert response.status_code == 409
    assert "append client does not own" in response.json()["detail"]


def test_heartbeat_and_expiry_report_transport_observation_not_clean_end() -> None:
    now = 100.0

    def clock() -> float:
        return now

    registration = StreamRegistration(
        view_id="logs:lifecycle",
        label="lifecycle",
        section="logs",
        client_id="producer-a",
        session_id="session-a",
    )
    registry = StreamRegistry(heartbeat_timeout_s=2.0, monotonic_clock=clock)
    state = registry.register(registration)
    assert state.lifecycle == "live"

    assert registry.heartbeat(
        StreamHeartbeat(
            view_id=registration.view_id,
            client_id=registration.client_id,
            session_id=registration.session_id,
            delivery_state="retrying",
            pending_delivery=True,
        )
    ).lifecycle == "retrying"
    now += 2.1
    registry.expire_stale_sessions()
    assert state.lifecycle == "incomplete"
    assert state.explicitly_closed is False

    # A later heartbeat proves this observer is again reachable; it does not
    # retroactively claim that the prior gap was a clean application exit.
    assert registry.heartbeat(
        StreamHeartbeat(
            view_id=registration.view_id,
            client_id=registration.client_id,
            session_id=registration.session_id,
            delivery_state="live",
            pending_delivery=False,
        )
    ).lifecycle == "live"
    now += 2.1
    registry.expire_stale_sessions()
    assert state.lifecycle == "disconnected"
    assert state.lifecycle != "ended"


def test_explicit_close_ends_only_after_a_completed_final_drain() -> None:
    registration = StreamRegistration(
        view_id="logs:close",
        label="close",
        section="logs",
        client_id="producer-a",
        session_id="session-a",
    )
    registry = StreamRegistry()
    state = registry.register(registration)

    assert registry.close(
        StreamClose(
            view_id=registration.view_id,
            client_id=registration.client_id,
            session_id=registration.session_id,
            drain_completed=True,
        )
    ).lifecycle == "ended"
    assert state.lifecycle == "ended"
    assert state.explicitly_closed is True

    with pytest.raises(StreamStateError, match="already closed as ended"):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id="after-close",
                batch_sequence=0,
                records=({"sequence": 1},),
            )
        )


def test_stream_close_route_reports_ended_or_incomplete_only_from_drain_outcome(
    client: TestClient,
) -> None:
    _register_stream(client, view_id="logs:close-route")
    base = {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": "logs:close-route",
        "client_id": TEST_CLIENT_ID,
        "session_id": TEST_SESSION_ID,
    }
    heartbeat = client.post(
        "/stream/heartbeat",
        json={**base, "delivery_state": "retrying", "pending_delivery": True},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["lifecycle"] == "retrying"

    incomplete = client.post(
        "/stream/close",
        json={**base, "drain_completed": False},
    )
    assert incomplete.status_code == 200
    assert incomplete.json()["lifecycle"] == "incomplete"


def test_stream_status_endpoint_exposes_transport_lifecycle_without_exit_claims(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register_stream(client, view_id="logs:status")
    live = client.get("/stream/status", params={"view": "logs:status"})
    assert live.status_code == 200
    assert live.json() == {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": "logs:status",
        "client_id": TEST_CLIENT_ID,
        "session_id": TEST_SESSION_ID,
        "lifecycle": "live",
        "last_heartbeat_at": live.json()["last_heartbeat_at"],
        "pending_delivery": False,
        "source_available": None,
        "source_transition": "unknown",
        "continuity_warning": None,
            "source_health": {
                "unread_source_bytes": None,
                "unacknowledged_source_bytes": None,
                "in_flight_records": None,
                "records_seen": None,
                "records_rejected": None,
            },
            "durable_history": {
                "state": "disabled",
                "persistence_enabled": False,
                "pending_writes": 0,
                "completed_writes": 0,
                "rejected_writes": 0,
                "failed_writes": 0,
                "last_error": None,
                "last_persisted_at": None,
            },
        }

    state = stream_registry._streams["logs:status"]
    state.last_heartbeat_monotonic = time.monotonic() - 1.0
    monkeypatch.setattr(config, "get_stream_heartbeat_timeout_s", lambda: 0.001)
    disconnected = client.get("/stream/status", params={"view": "logs:status"})
    assert disconnected.status_code == 200
    assert disconnected.json()["lifecycle"] == "disconnected"
    assert disconnected.json()["lifecycle"] != "ended"


def test_stream_endpoints_expose_sanitized_source_continuity_state(
    client: TestClient,
) -> None:
    view_id = "logs:source-continuity"
    _register_stream(client, view_id=view_id)
    heartbeat = client.post(
        "/stream/heartbeat",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": view_id,
            "client_id": TEST_CLIENT_ID,
            "session_id": TEST_SESSION_ID,
            "delivery_state": "live",
            "pending_delivery": False,
            "source_available": False,
            "source_transition": "missing",
            "continuity_warning": "The JSONL source was truncated; record continuity is uncertain.",
            "source_health": {
                "unread_source_bytes": 256,
                "unacknowledged_source_bytes": 320,
                "in_flight_records": 2,
                "records_seen": 14,
                "records_rejected": 3,
            },
        },
    )
    assert heartbeat.status_code == 200

    for route in ("/stream/status", "/stream/data"):
        response = client.get(route, params={"view": view_id})
        assert response.status_code == 200
        payload = response.json()
        assert payload["source_available"] is False
        assert payload["source_transition"] == "missing"
        assert payload["continuity_warning"] == (
            "The JSONL source was truncated; record continuity is uncertain."
        )
        assert payload["source_health"] == {
            "unread_source_bytes": 256,
            "unacknowledged_source_bytes": 320,
            "in_flight_records": 2,
            "records_seen": 14,
            "records_rejected": 3,
        }
        assert "/tmp/" not in str(payload)

    unsafe = client.post(
        "/stream/heartbeat",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": view_id,
            "client_id": TEST_CLIENT_ID,
            "session_id": TEST_SESSION_ID,
            "delivery_state": "live",
            "pending_delivery": False,
            "source_available": True,
            "source_transition": "continuing",
            "continuity_warning": "Permission denied: /tmp/private-source.jsonl",
        },
    )
    assert unsafe.status_code == 422

    invalid_health = client.post(
        "/stream/heartbeat",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": view_id,
            "client_id": TEST_CLIENT_ID,
            "session_id": TEST_SESSION_ID,
            "delivery_state": "live",
            "pending_delivery": False,
            "source_health": {"records_rejected": -1},
        },
    )
    assert invalid_health.status_code == 422


@pytest.mark.parametrize("field", ("view_id", "client_id", "session_id"))
def test_stream_identity_limits_match_browser_checkpoint_storage(
    client: TestClient, field: str
) -> None:
    """Producer ingress must not create an uncheckpointable session."""
    at_limit = "x" * MAX_STREAM_ID_CHARS
    assert stream_api._require_checkpoint_identifier(at_limit, field) == at_limit
    with pytest.raises(ValueError, match="at most 512 characters"):
        stream_api._require_checkpoint_identifier(
            "x" * (MAX_STREAM_ID_CHARS + 1), field
        )

    payload = {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": f"logs:checkpoint-identity-{field}",
        "label": "checkpoint identity",
        "section": "logs",
        "client_id": "client-at-limit",
        "session_id": "session-at-limit",
    }
    payload[field] = "x" * (MAX_STREAM_ID_CHARS + 1)
    response = client.post("/stream/register", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == f"stream {field} must be at most 512 characters"


@pytest.mark.parametrize("field", ("view_id", "client_id", "session_id"))
def test_stream_identity_unicode_contract_matches_browser_checkpoint_storage(
    client: TestClient, field: str
) -> None:
    """Checkpoint identities use code points and reject malformed Unicode."""
    emoji_identity = "\U0001f642" * 300
    assert stream_api._require_checkpoint_identifier(emoji_identity, field) == emoji_identity
    with pytest.raises(ValueError, match="well-formed Unicode"):
        stream_api._require_checkpoint_identifier("\ud800", field)

    payload = {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": "logs:unicode-checkpoint-identity",
        "label": "unicode checkpoint identity",
        "section": "logs",
        "client_id": "client",
        "session_id": "session",
    }
    payload[field] = emoji_identity
    accepted = client.post("/stream/register", json=payload)
    assert accepted.status_code == 200

    malformed_payload = {**payload, "view_id": "logs:malformed-checkpoint-identity"}
    malformed_payload[field] = "\ud800"
    # httpx correctly refuses to UTF-8 encode a Python surrogate itself.  Send
    # the wire form an external producer could submit instead.
    rejected = client.post(
        "/stream/register",
        content=json.dumps(malformed_payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == f"stream {field} must be well-formed Unicode"


def test_stream_identity_at_checkpoint_limit_is_accepted(client: TestClient) -> None:
    client_id = "c" * MAX_STREAM_ID_CHARS
    session_id = "s" * MAX_STREAM_ID_CHARS
    view_id = "v" * MAX_STREAM_ID_CHARS
    _register_stream(
        client,
        view_id=view_id,
        client_id=client_id,
        session_id=session_id,
    )

    data = client.get("/stream/data", params={"view": view_id})
    assert data.status_code == 200
    assert data.json()["client_id"] == client_id
    assert data.json()["session_id"] == session_id


def test_public_stream_view_rejects_an_uncheckpointable_view_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="view_id must be at most 512 characters"):
        stream_api.stream_view(
            source=tmp_path / "checkpoint-identity.jsonl",
            view_id="v" * (MAX_STREAM_ID_CHARS + 1),
        )


def test_stream_client_transmits_source_state_on_every_active_protocol_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = StreamRegistration(
        view_id="logs:source-state-wire",
        label="source state wire",
        section="logs",
        client_id="source-state-client",
        session_id="source-state-session",
    )
    client = StreamClient(
        host="127.0.0.1",
        port=1,
        registration=registration,
        source_status_provider=lambda: SourceStatus(
            source_available=False,
            source_transition="missing",
            continuity_warning="The JSONL source was truncated; record continuity is uncertain.",
        ),
        source_health_provider=lambda: {
            "unread_source_bytes": 256,
            "unacknowledged_source_bytes": 320,
            "in_flight_records": 2,
            "records_seen": 14,
            "records_rejected": 3,
        },
    )
    messages: list[tuple[str, dict[str, object]]] = []

    def request(path: str, payload: dict[str, object]) -> dict[str, object]:
        messages.append((path, payload))
        if path == "/stream/register":
            return {"ok": True, "next_batch_sequence": 0}
        if path == "/stream/append":
            return {"ok": True, "next_batch_sequence": 1}
        assert path == "/stream/heartbeat"
        return {"ok": True, "lifecycle": "live"}

    monkeypatch.setattr(client, "_request", request)
    assert client._ensure_registered(force=True) is True
    assert client.append_batch(
        JsonlBatch(
            batch_id="source-state-batch",
            records=(
                JsonlRecord(
                    data={"sequence": 1},
                    source_offset=0,
                    source_end_offset=15,
                    observed_at=datetime.now(UTC),
                ),
            ),
            source_offset=0,
            source_end_offset=15,
        )
    ) is True
    assert client.heartbeat_once() is True

    assert [path for path, _ in messages] == [
        "/stream/register",
        "/stream/append",
        "/stream/heartbeat",
    ]
    for _, payload in messages:
        assert payload["source_available"] is False
        assert payload["source_transition"] == "missing"
        assert payload["continuity_warning"] == (
            "The JSONL source was truncated; record continuity is uncertain."
        )
        assert payload["source_health"] == {
            "unread_source_bytes": 256,
            "unacknowledged_source_bytes": 320,
            "in_flight_records": 2,
            "records_seen": 14,
            "records_rejected": 3,
        }


def test_stream_client_serializes_source_health_capture_and_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed heartbeat cannot overtake a newer append health snapshot."""
    registry = StreamRegistry(max_noteworthy_items=16)
    registration = StreamRegistration(
        view_id="logs:ordered-source-health",
        label="ordered source health",
        section="logs",
        client_id="ordered-source-health-client",
        session_id="ordered-source-health-session",
    )
    registry.register(registration)
    client = StreamClient(
        host="127.0.0.1",
        port=1,
        registration=registration,
        source_health_provider=lambda: {
            "records_rejected": (
                1 if threading.current_thread().name == "delayed-heartbeat" else 2
            )
        },
    )
    # The registry was set up directly to isolate concurrent official-client
    # delivery from registration retry behaviour.
    client._registered.set()
    heartbeat_request_started = threading.Event()
    append_request_started = threading.Event()
    allow_heartbeat_response = threading.Event()
    delivered_rejections: list[int] = []

    def source_health(payload: dict[str, object]) -> SourceHealth:
        raw_health = payload["source_health"]
        assert isinstance(raw_health, dict)
        rejected = raw_health["records_rejected"]
        assert isinstance(rejected, int)
        return SourceHealth(records_rejected=rejected)

    def request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if path == "/stream/heartbeat":
            heartbeat_request_started.set()
            assert allow_heartbeat_response.wait(timeout=1.0)
            health = source_health(payload)
            registry.heartbeat(
                StreamHeartbeat(
                    view_id=registration.view_id,
                    client_id=registration.client_id,
                    session_id=registration.session_id,
                    delivery_state="live",
                    pending_delivery=False,
                    source_health=health,
                )
            )
            delivered_rejections.append(health.records_rejected or 0)
            return {"ok": True, "lifecycle": "live"}

        assert path == "/stream/append"
        append_request_started.set()
        health = source_health(payload)
        raw_records = payload["records"]
        assert isinstance(raw_records, list)
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id="ordered-source-health-batch",
                batch_sequence=0,
                records=tuple(raw_records),
                source_health=health,
            )
        )
        delivered_rejections.append(health.records_rejected or 0)
        return {"ok": True, "next_batch_sequence": 1}

    monkeypatch.setattr(client, "_request", request)
    heartbeat_result: list[bool] = []
    append_result: list[bool] = []
    heartbeat = threading.Thread(
        target=lambda: heartbeat_result.append(client.heartbeat_once()),
        name="delayed-heartbeat",
    )
    append = threading.Thread(
        target=lambda: append_result.append(
            client.append_batch(
                JsonlBatch(
                    batch_id="ordered-source-health-batch",
                    records=(
                        JsonlRecord(
                            data={"sequence": 1},
                            source_offset=0,
                            source_end_offset=15,
                            observed_at=datetime.now(UTC),
                        ),
                    ),
                    source_offset=0,
                    source_end_offset=15,
                )
            )
        ),
        name="newer-append",
    )
    heartbeat.start()
    assert heartbeat_request_started.wait(timeout=1.0)
    append.start()
    try:
        overtook_before_heartbeat_finished = append_request_started.wait(timeout=0.1)
    finally:
        allow_heartbeat_response.set()
        heartbeat.join(timeout=1.0)
        append.join(timeout=1.0)

    assert not heartbeat.is_alive()
    assert not append.is_alive()
    assert overtook_before_heartbeat_finished is False
    assert heartbeat_result == [True]
    assert append_result == [True]
    assert delivered_rejections == [1, 2]
    assert registry.data(view_id=registration.view_id)["cumulative"][
        "rejected_source_records"
    ] == "2"


def test_lifecycle_status_walkthrough_reports_clean_and_abrupt_observations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirror the clean, disconnected, and incomplete walkthrough states."""
    monkeypatch.setattr(config, "get_stream_heartbeat_timeout_s", lambda: 0.001)

    clean_view = "logs:walkthrough-clean"
    _register_stream(client, view_id=clean_view)
    clean = client.post(
        "/stream/close",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": clean_view,
            "client_id": TEST_CLIENT_ID,
            "session_id": TEST_SESSION_ID,
            "drain_completed": True,
        },
    )
    assert clean.status_code == 200
    assert client.get("/stream/status", params={"view": clean_view}).json()[
        "lifecycle"
    ] == "ended"

    disconnected_view = "logs:walkthrough-disconnected"
    _register_stream(client, view_id=disconnected_view)
    stream_registry._streams[disconnected_view].last_heartbeat_monotonic = (
        time.monotonic() - 1.0
    )
    disconnected = client.get("/stream/status", params={"view": disconnected_view})
    assert disconnected.status_code == 200
    assert disconnected.json()["lifecycle"] == "disconnected"
    assert disconnected.json()["lifecycle"] != "ended"

    incomplete_view = "logs:walkthrough-incomplete"
    _register_stream(client, view_id=incomplete_view)
    pending = client.post(
        "/stream/heartbeat",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": incomplete_view,
            "client_id": TEST_CLIENT_ID,
            "session_id": TEST_SESSION_ID,
            "delivery_state": "retrying",
            "pending_delivery": True,
        },
    )
    assert pending.status_code == 200
    stream_registry._streams[incomplete_view].last_heartbeat_monotonic = (
        time.monotonic() - 1.0
    )
    incomplete = client.get("/stream/status", params={"view": incomplete_view})
    assert incomplete.status_code == 200
    assert incomplete.json()["lifecycle"] == "incomplete"
    assert incomplete.json()["lifecycle"] != "ended"


def test_stream_handle_stop_performs_one_bounded_drain_then_close(tmp_path: Path) -> None:
    calls: list[object] = []

    class Follower:
        def stop(self, *, timeout: float | None = None) -> bool:
            calls.append(("stop", timeout))
            return True

        def drain(self, *, timeout_s: float, on_batch: Callable[[JsonlBatch], bool]) -> bool:
            calls.append(("drain", timeout_s))
            return True

        def health(self) -> dict[str, object]:
            return {}

    class Client:
        def begin_shutdown(self) -> None:
            calls.append("begin")

        def stop_heartbeats(self, *, timeout_s: float) -> bool:
            calls.append(("heartbeats", timeout_s))
            return True

        def append_batch(self, _batch: JsonlBatch, **_: object) -> bool:
            return True

        def close(self, *, drain_completed: bool, timeout_s: float) -> bool:
            calls.append(("close", drain_completed, timeout_s))
            return True

        def health(self) -> dict[str, object]:
            return {}

    handle = stream_api.StreamHandle(
        source=tmp_path / "source.jsonl",
        label="lifecycle",
        section="logs",
        host="127.0.0.1",
        port=8000,
        view_id="logs:lifecycle",
        client_id="producer-a",
        session_id="session-a",
        observation_started_at=datetime.now(UTC),
        source_existed_at_start=False,
        initial_offset=0,
        _follower=Follower(),  # type: ignore[arg-type]
        _client=Client(),  # type: ignore[arg-type]
    )

    handle.stop(timeout=0.05)
    handle.stop(timeout=0.05)

    assert [call[0] if isinstance(call, tuple) else call for call in calls] == [
        "begin",
        "heartbeats",
        "stop",
        "drain",
        "close",
    ]
    assert calls[-1][1] is True  # type: ignore[index]


def test_stream_creation_does_not_replace_application_signal_handlers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = signal.getsignal(signal.SIGTERM)

    class Client:
        def __init__(self, **_: object) -> None:
            pass

        def start(self) -> None:
            pass

        def append_batch(self, _batch: JsonlBatch, **_: object) -> bool:
            return True

        def begin_shutdown(self) -> None:
            pass

        def stop_heartbeats(self, *, timeout_s: float) -> bool:
            return True

        def close(self, *, drain_completed: bool, timeout_s: float) -> bool:
            return True

        def health(self) -> dict[str, object]:
            return {}

    monkeypatch.setattr(stream_api, "StreamClient", Client)
    monkeypatch.setattr(
        signal,
        "signal",
        lambda *_args, **_kwargs: pytest.fail("stream setup must not install a signal handler"),
    )
    handle = stream_api.stream_view(source=tmp_path / "signals.jsonl")
    try:
        assert signal.getsignal(signal.SIGTERM) is before
    finally:
        handle.stop()


def test_single_exit_cleanup_manager_uses_one_finite_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []

    class Handle:
        def stop(self, *, timeout: float | None = None) -> None:
            assert timeout is not None
            calls.append(timeout)

    manager = stream_api._stream_exit_cleanup_manager
    handle = Handle()
    manager.register(handle)  # type: ignore[arg-type]
    monkeypatch.setattr(config, "get_stream_process_exit_cleanup_timeout_s", lambda: 0.05)

    manager.cleanup()

    assert len(calls) == 1
    assert 0 < calls[0] <= 0.05


def test_ordinary_publish_cannot_replace_a_registered_stream_view(
    client: TestClient,
) -> None:
    _register_stream(client)
    _append(client, batch_sequence=0, records=[{"sequence": 1}])

    response = client.post(
        "/publish",
        json={
            "view_id": "logs:worker stream",
            "kind": "table",
            "table": {"columns": ["replacement"], "rows": [{"replacement": 1}]},
        },
    )
    assert response.status_code == 409
    assert store.get_kind("logs:worker stream") == "stream"

    page = client.get("/?view=logs:worker%20stream")
    assert 'data-kind="stream"' in page.text
    data = client.get("/stream/data", params={"view": "logs:worker stream"})
    assert [row["data"] for row in data.json()["records"]] == [{"sequence": 1}]


def test_stream_renderer_is_bundled() -> None:
    static_dir = (
        Path(__file__).parents[1]
        / "src"
        / "plotsrv"
        / "static"
    )
    bundle = (static_dir / get_ui_assets().js.removeprefix("/static/")).read_text("utf-8")

    assert "plotsrv source: js/renderers/stream.js" in bundle
    assert "core.loadStream = loadStream" in bundle
    assert "core.startStreamRefresh = startStreamRefresh" in bundle
    assert "state.streamRefreshTimer = window.setInterval" in bundle
    assert "visibilitychange" in bundle
    assert '"/stream/data?view="' in bundle
    assert '"/stream/history?view="' in bundle
    assert "STORED SESSION" in bundle
    assert "renderVisitComparison" in bundle
    assert "renderNoteworthy" in bundle
    assert "No zero-change conclusion is shown." in bundle
    assert "plotsrv system notice" in bundle


def test_stream_renderer_keeps_valid_cursor_updates_incremental() -> None:
    stream_source = (
        Path(__file__).parents[1]
        / "src"
        / "plotsrv"
        / "static"
        / "js"
        / "renderers"
        / "stream.js"
    ).read_text("utf-8")

    assert "&after=" in stream_source
    assert "&session_id=" in stream_source
    assert "await appendTableData(table, merged.additions)" in stream_source
    assert "await replaceTableData(table, rows)" in stream_source
    assert "core.configureTableExplorer" in stream_source
    assert "movableColumns: true" in stream_source
    assert "bounded recent raw observation window" in stream_source
    assert "Cursor reset:" in stream_source
    assert "Parser:" in stream_source
    assert "Continuity:" in stream_source
    assert "Durable history incomplete: live observation continues" in stream_source
    assert "Durable history incomplete: this stored session has a persistence gap" in stream_source
    assert '"/stream/history?view="' in stream_source
    assert "state.streamForceTableReplace = true" in stream_source
    assert 'current.textContent = "Current observation"' in stream_source
    assert "Stored sessions are fixed historical observations" in stream_source
    assert "visibilitychange" in stream_source
    assert "refreshVisibleStream" in stream_source
    assert "core.updateStreamVisitComparison(data)" in stream_source
    assert "renderVisitComparison(visitComparison)" in stream_source
    assert "renderNoteworthy(data.noteworthy)" in stream_source
    assert "core.setTablePlotSummaryRows(payload)" in stream_source
    assert "No zero-change conclusion is shown." in stream_source
    assert "plotsrv may not have observed every source event while you were away." in stream_source
    assert "This does not establish that plotsrv observed every source event." in stream_source
    assert 'article.dataset.noteworthyKind = "source_record"' in stream_source
    assert 'article.dataset.noteworthyKind = "system_notice"' in stream_source
    assert ".setColumns(" not in stream_source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_stream_checkpoint_comparison_is_exact_and_never_falls_back_to_zero() -> None:
    state_source = (
        Path(__file__).parents[1]
        / "src"
        / "plotsrv"
        / "static"
        / "js"
        / "core"
        / "state.js"
    )
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");

function payload({viewId = "logs:checkpoint", session = "session-a", instance = "instance-a", total, severity, counts, resetReason, warning, sourceAvailable = true, sourceTransition, rejected = "0", continuity = "0", noteworthy, noteworthySource, systemNotices = "0"}) {
  const normalizedCounts = Object.assign({warning: "0"}, counts);
  return {
    view_id: viewId,
    client_id: "client-a",
    session_id: session,
    stream_instance_id: instance,
    reset_required: !!resetReason,
    reset_reason: resetReason || null,
    continuity_warning: warning || null,
    source_transition: sourceTransition || (warning ? "truncated" : "continuing"),
    source_available: sourceAvailable,
    cumulative: {
      object_type: "stream_session_counters",
      counter_schema_version: 2,
      total_records: total,
      recognized_severity_records: severity,
      recognized_severity_counts: normalizedCounts,
      rejected_source_records: rejected,
      continuity_events: continuity,
      noteworthy_items: noteworthy || severity,
      noteworthy_source_records: noteworthySource || noteworthy || severity,
      system_notices: systemNotices,
      first_observed_at: "2026-01-01T00:00:00+00:00",
      last_observed_at: "2026-01-01T00:00:01+00:00",
      latest_server_sequence: total,
    },
  };
}

function browser(storage, activeViewId = "logs:checkpoint") {
  const localStorage = {
    getItem: (key) => storage.has(key) ? storage.get(key) : null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  };
  const context = {
    BigInt,
    JSON,
    Object,
    Array,
    String,
    RegExp,
    URLSearchParams,
    encodeURIComponent,
    localStorage,
    window: {
      PLOTSRV_CONFIG: {active_view_id: activeViewId},
      PLOTSRV: {core: {}, renderers: {}, state: {}, config: {}},
    },
  };
  vm.runInNewContext(source, context, {filename: "state.js"});
  return context.window.PLOTSRV.core;
}

const initialCounts = {
  emergency: "0", alert: "0", critical: "1", fatal: "0", error: "1",
};
const returnedCounts = {
  emergency: "0", alert: "0", critical: "2", fatal: "1", error: "2",
};
const firstStorage = new Map();
const firstBrowser = browser(firstStorage);
const first = firstBrowser.updateStreamVisitComparison(payload({
  total: "9007199254740993", severity: "2", counts: initialCounts,
}));
if (first.status !== "unavailable" || first.unavailable_reason !== "checkpoint_missing" || first.deltas !== null) {
  throw new Error("a first visit did not explicitly report its unavailable comparison");
}
const baselineStorage = new Map(firstStorage);

const malformedCheckpointStorage = new Map(baselineStorage);
const checkpointKey = firstBrowser.getStreamCheckpointKey("logs:checkpoint");
const malformedCheckpoint = JSON.parse(malformedCheckpointStorage.get(checkpointKey));
delete malformedCheckpoint.counters.recognized_severity_counts.error;
malformedCheckpointStorage.set(checkpointKey, JSON.stringify(malformedCheckpoint));
const malformedCheckpointBrowser = browser(malformedCheckpointStorage);
const malformedStoredCheckpoint = malformedCheckpointBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
}));
if (malformedStoredCheckpoint.status !== "unavailable" ||
    malformedStoredCheckpoint.unavailable_reason !== "counter_state_invalid" ||
    malformedStoredCheckpoint.deltas !== null) {
  throw new Error("a malformed saved checkpoint exposed a zero or exact comparison");
}

const leftOpen = firstBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  resetReason: "cursor_aged_out",
}));
if (leftOpen.status !== "available" || leftOpen.deltas.total_records !== "7") {
  throw new Error("an open browser did not compare against its fixed visit baseline");
}

const returnedBrowser = browser(new Map(baselineStorage));
const returned = returnedBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  resetReason: "cursor_aged_out",
}));
if (returned.status !== "available" || returned.exact_deltas !== true) {
  throw new Error("a compatible same-session checkpoint did not become available");
}
if (returned.deltas.total_records !== "7" ||
    returned.deltas.recognized_severity_records !== "3" ||
    returned.deltas.recognized_severity_counts.critical !== "1" ||
    returned.deltas.recognized_severity_counts.fatal !== "1" ||
    returned.deltas.recognized_severity_counts.error !== "1") {
  throw new Error("exact counters were narrowed or incorrectly compared");
}
if (returned.continuity.status !== "no_known_gap") {
  throw new Error("raw cursor compaction incorrectly made the cumulative comparison unavailable");
}

const continuityBrowser = browser(new Map(baselineStorage));
const continuity = continuityBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  warning: "The JSONL source was truncated; record continuity is uncertain.", continuity: "1",
}));
if (continuity.status !== "incomplete" || continuity.exact_deltas !== false ||
    continuity.unavailable_reason !== "continuity_uncertain" ||
    continuity.continuity.status !== "continuity_uncertain" ||
    !continuity.continuity.warning || continuity.deltas !== null) {
  throw new Error("a continuity gap exposed an exact or zero-delta comparison");
}

const clearedGapStorage = new Map(baselineStorage);
const clearedGapBrowser = browser(clearedGapStorage);
const clearedGap = clearedGapBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  rejected: "2", continuity: "1", noteworthy: "7", noteworthySource: "5", systemNotices: "2",
}));
if (clearedGap.status !== "incomplete" || clearedGap.exact_deltas !== false ||
    clearedGap.unavailable_reason !== "continuity_uncertain" ||
    clearedGap.continuity.status !== "continuity_uncertain" ||
    clearedGap.continuity.warning !== null || clearedGap.deltas !== null) {
  throw new Error("a past continuity event exposed an exact or zero-delta comparison");
}
const clearedGapCheckpoint = JSON.parse(
  clearedGapStorage.get(clearedGapBrowser.getStreamCheckpointKey("logs:checkpoint"))
);
if (clearedGapCheckpoint.continuity_status !== "continuity_uncertain") {
  throw new Error("a continuity-event delta was saved as a compatible checkpoint");
}
const reloadedClearedGapBrowser = browser(new Map(clearedGapStorage));
const reloadedClearedGap = reloadedClearedGapBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  rejected: "2", continuity: "1", noteworthy: "7", noteworthySource: "5", systemNotices: "2",
}));
if (reloadedClearedGap.status !== "incomplete" ||
    reloadedClearedGap.unavailable_reason !== "checkpoint_continuity_insufficient" ||
    reloadedClearedGap.deltas !== null) {
  throw new Error("a reload converted a continuity-event gap into an exact zero comparison");
}

const unavailableSourceBrowser = browser(new Map(baselineStorage));
const unavailableSource = unavailableSourceBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  sourceAvailable: false,
}));
if (unavailableSource.status !== "incomplete" || unavailableSource.exact_deltas !== false ||
    unavailableSource.unavailable_reason !== "source_unavailable" ||
    unavailableSource.continuity.status !== "source_unavailable" ||
    unavailableSource.deltas !== null) {
  throw new Error("a currently unavailable source exposed an exact or zero-delta comparison");
}

const unavailableVisitStorage = new Map(baselineStorage);
const unavailableVisitBrowser = browser(unavailableVisitStorage);
const unavailableVisit = unavailableVisitBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  sourceAvailable: false,
}));
if (unavailableVisit.status !== "incomplete" ||
    unavailableVisit.unavailable_reason !== "source_unavailable") {
  throw new Error("an unavailable visit did not remain incomplete");
}
const unavailableVisitCheckpoint = JSON.parse(
  unavailableVisitStorage.get(unavailableVisitBrowser.getStreamCheckpointKey("logs:checkpoint"))
);
if (unavailableVisitCheckpoint.checkpoint_schema_version !== 3 ||
    unavailableVisitCheckpoint.continuity_status !== "source_unavailable") {
  throw new Error("an unavailable visit was stored as a compatible checkpoint");
}
const returnedAfterUnavailableBrowser = browser(new Map(unavailableVisitStorage));
const returnedAfterUnavailable = returnedAfterUnavailableBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  sourceAvailable: true, sourceTransition: "continuing",
}));
if (returnedAfterUnavailable.status !== "incomplete" ||
    returnedAfterUnavailable.exact_deltas !== false ||
    returnedAfterUnavailable.unavailable_reason !== "checkpoint_continuity_insufficient" ||
    returnedAfterUnavailable.continuity.status !== "continuity_uncertain" ||
    returnedAfterUnavailable.deltas !== null) {
  throw new Error("a reload converted an unavailable source visit into an exact zero comparison");
}

const unknownContinuityBrowser = browser(new Map(baselineStorage));
const unknownContinuity = unknownContinuityBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  sourceAvailable: null, sourceTransition: "unknown",
}));
if (unknownContinuity.status !== "incomplete" || unknownContinuity.exact_deltas !== false ||
    unknownContinuity.unavailable_reason !== "continuity_uncertain" ||
    unknownContinuity.deltas !== null) {
  throw new Error("missing source-continuity evidence exposed exact deltas");
}

const recoveredSourceBrowser = browser(new Map(baselineStorage));
const sourceUnavailableDuringVisit = recoveredSourceBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  sourceAvailable: false,
}));
if (sourceUnavailableDuringVisit.status !== "incomplete" ||
    sourceUnavailableDuringVisit.unavailable_reason !== "source_unavailable") {
  throw new Error("a currently unavailable source did not block comparison");
}
const recoveredSource = recoveredSourceBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  sourceAvailable: true, sourceTransition: "continuing",
}));
if (recoveredSource.status !== "incomplete" || recoveredSource.exact_deltas !== false ||
    recoveredSource.unavailable_reason !== "continuity_uncertain" ||
    recoveredSource.deltas !== null) {
  throw new Error("a recovered source turned an unavailable interval into exact deltas");
}

const appearedSourceBrowser = browser(new Map(baselineStorage));
const appearedSource = appearedSourceBrowser.updateStreamVisitComparison(payload({
  total: "9007199254741000", severity: "5", counts: returnedCounts,
  sourceAvailable: true, sourceTransition: "appeared",
}));
if (appearedSource.status !== "incomplete" || appearedSource.exact_deltas !== false ||
    appearedSource.unavailable_reason !== "continuity_uncertain" ||
    appearedSource.deltas !== null) {
  throw new Error("a recovered source transition exposed exact deltas");
}

const changedSessionBrowser = browser(new Map(baselineStorage));
const changedSession = changedSessionBrowser.updateStreamVisitComparison(payload({
  session: "session-b", total: "1", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
  resetReason: "session_changed",
}));
if (changedSession.status !== "unavailable" || changedSession.unavailable_reason !== "session_changed" ||
    changedSession.deltas !== null) {
  throw new Error("a changed producer session fell back to a zero comparison");
}

const stateResetBrowser = browser(new Map(baselineStorage));
const stateReset = stateResetBrowser.updateStreamVisitComparison(payload({
  instance: "instance-b", total: "1", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
}));
if (stateReset.status !== "unavailable" || stateReset.unavailable_reason !== "stream_state_changed" ||
    stateReset.deltas !== null) {
  throw new Error("recreated server state fell back to a zero comparison");
}

const regressedBrowser = browser(new Map(baselineStorage));
const regressed = regressedBrowser.updateStreamVisitComparison(payload({
  total: "1", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
}));
if (regressed.status !== "unavailable" || regressed.unavailable_reason !== "counter_regressed" ||
    regressed.deltas !== null) {
  throw new Error("regressed state fell back to a zero comparison");
}

const nonRecordCounterStorage = new Map();
const nonRecordCounterFirstBrowser = browser(nonRecordCounterStorage);
nonRecordCounterFirstBrowser.updateStreamVisitComparison(payload({
  total: "5", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
  rejected: "3", noteworthy: "3", noteworthySource: "0", systemNotices: "3",
}));
const nonRecordCounterRegressionBrowser = browser(new Map(nonRecordCounterStorage));
const nonRecordCounterRegression = nonRecordCounterRegressionBrowser.updateStreamVisitComparison(payload({
  total: "6", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
  rejected: "2", noteworthy: "3", noteworthySource: "0", systemNotices: "3",
}));
if (nonRecordCounterRegression.status !== "unavailable" ||
    nonRecordCounterRegression.unavailable_reason !== "counter_regressed" ||
    nonRecordCounterRegression.deltas !== null) {
  throw new Error("a regressed cumulative rejection count exposed exact deltas");
}

const lostStateBrowser = browser(new Map());
const lostState = lostStateBrowser.updateStreamVisitComparison(payload({
  total: "9", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
}));
if (lostState.status !== "unavailable" || lostState.unavailable_reason !== "checkpoint_missing" ||
    lostState.deltas !== null) {
  throw new Error("lost browser state fell back to a zero comparison");
}

const emojiViewId = "\ud83d\ude42".repeat(300);
const emojiInitialStorage = new Map();
const emojiFirstBrowser = browser(emojiInitialStorage, emojiViewId);
const emojiFirst = emojiFirstBrowser.updateStreamVisitComparison(payload({
  viewId: emojiViewId, total: "2", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
}));
if (emojiFirst.status !== "unavailable" || emojiFirst.unavailable_reason !== "checkpoint_missing") {
  throw new Error("a valid non-BMP identity did not establish its checkpoint");
}
const emojiReturnedBrowser = browser(new Map(emojiInitialStorage), emojiViewId);
const emojiReturned = emojiReturnedBrowser.updateStreamVisitComparison(payload({
  viewId: emojiViewId, total: "3", severity: "0",
  counts: {emergency: "0", alert: "0", critical: "0", fatal: "0", error: "0"},
}));
if (emojiReturned.status !== "available" || emojiReturned.deltas.total_records !== "1") {
  throw new Error("a valid non-BMP identity did not produce exact deltas");
}
'''
    subprocess.run(
        ["node", "-e", script, str(state_source)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_stream_renderer_safely_executes_logfile_controlled_headers_and_values() -> None:
    """Run the browser module with DOM stubs to guard stream display behavior."""
    stream_source = (
        Path(__file__).parents[1]
        / "src"
        / "plotsrv"
        / "static"
        / "js"
        / "renderers"
        / "stream.js"
    )
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const unsafeName = '<img src=x onerror="throw new Error(1)">';
let options;
let appendedRows;
let updatedRows;
let replacementCount = 0;
let fetchCount = 0;
const requestUrls = [];
function element() {
  return {
    textContent: "",
    className: "",
    dataset: {},
    children: [],
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
  };
}
const status = element();
const healthStatus = element();
const lifecycleBadge = element();
const sinceVisitStatus = element();
const sinceVisitDetails = element();
const noteworthyStatus = element();
const noteworthyItems = element();
const eventListeners = {};
let intervalCallback;
const context = {
  Promise,
  fetch: async (url) => {
    fetchCount += 1;
    requestUrls.push(url);
    const firstResponse = fetchCount === 1;
    const resetResponse = fetchCount === 3;
    const resumedResponse = fetchCount === 4;
    const start = firstResponse ? 1 : (resetResponse ? 30 : (resumedResponse ? 32 : 26));
    const recordCount = firstResponse ? 25 : (resetResponse ? 2 : 1);
    return {
      ok: true,
      json: async () => ({
        columns: [unsafeName, "http.status", "nested"],
        records: Array.from({length: recordCount}, (_unused, index) => ({
          browser_sequence: start + index,
          data: {
            [unsafeName]: "safe",
            "http.status": 200,
            nested: {items: ["a", "b"], v: "null"},
            sequence: start + index,
          },
        })),
        accepted_records: recordCount,
        returned_records: recordCount,
        first_available_browser_sequence: 1,
        last_available_browser_sequence: firstResponse ? 25 : (resetResponse ? 31 : 26),
        raw_window: {
          first_browser_sequence: firstResponse ? 1 : (resetResponse || resumedResponse ? 30 : 1),
          last_browser_sequence: firstResponse ? 25 : (resetResponse ? 31 : (resumedResponse ? 32 : 26)),
          record_count: firstResponse ? 25 : (resetResponse ? 2 : (resumedResponse ? 3 : 26)),
          max_record_count: 200,
        },
        source_health: {
          unread_source_bytes: 0,
          unacknowledged_source_bytes: 0,
          in_flight_records: 0,
          records_seen: recordCount,
          records_rejected: 1,
        },
        noteworthy: {
          object_type: "stream_noteworthy_collection",
          max_retained_items: 64,
          items: [
            {
              object_type: "stream_noteworthy_source_record",
              kind: "source_record",
              source_browser_sequence: "7",
              observed_at: "2026-01-01T00:00:00+00:00",
              severity: "error",
              noteworthy_reason: "structured_severity",
              data: {level: "ERROR", message: "structured error record"},
            },
            {
              object_type: "stream_system_notice",
              kind: "system_notice",
              event: "source_continuity_uncertain",
              continuity_warning: "The JSONL source was truncated; record continuity is uncertain.",
              source_transition: "truncated",
              rejected_record_count: null,
            },
            {
              object_type: "stream_system_notice",
              kind: "source_record",
              noteworthy_reason: "structured_severity",
              severity: "error",
              data: {level: "error"},
            },
            {
              object_type: "stream_noteworthy_source_record",
              kind: "system_notice",
              event: "source_continuity_uncertain",
            },
            {
              object_type: "stream_noteworthy_source_record",
              kind: "source_record",
              noteworthy_reason: "structured_severity",
              severity: "error",
              data: {message: "ERROR only in arbitrary prose"},
            },
          ],
        },
        session_id: "stream-session",
        reset_required: resetResponse,
        lifecycle: "incomplete",
      }),
    };
  },
  Tabulator: function (_selector, receivedOptions) {
    options = receivedOptions;
    this.addData = (rows) => {
      appendedRows = rows;
    };
    this.replaceData = (rows) => {
      updatedRows = rows;
      replacementCount += 1;
    };
  },
  window: {
    PLOTSRV: {
      core: {
        updateStreamVisitComparison: () => ({
          status: "incomplete",
          exact_deltas: false,
          unavailable_reason: "continuity_uncertain",
          deltas: null,
          continuity: {
            status: "continuity_uncertain",
            warning: "The JSONL source was truncated; record continuity is uncertain.",
          },
        }),
      },
      renderers: {},
      state: {streamRefreshTimer: null, streamVisibilityListenerBound: false},
      config: {activeViewId: "logs:worker"},
    },
    setInterval: (callback) => {
      intervalCallback = callback;
      return 1;
    },
  },
  document: {
    hidden: false,
    addEventListener: (event, callback) => { eventListeners[event] = callback; },
    createElement: () => element(),
    getElementById: (id) => ({
      "stream-grid": {},
      "stream-status-inline": status,
      "stream-health-inline": healthStatus,
      "stream-lifecycle-badge": lifecycleBadge,
      "stream-since-visit-status": sinceVisitStatus,
      "stream-since-visit-details": sinceVisitDetails,
      "stream-noteworthy-status": noteworthyStatus,
      "stream-noteworthy-items": noteworthyItems,
    })[id] || null,
  },
};
vm.runInNewContext(source, context, {filename: "stream.js"});
context.window.PLOTSRV.core.loadStream().then(() => {
  if (options.nestedFieldSeparator !== false) {
    throw new Error("dotted stream fields were not configured as flat");
  }
  const unsafeColumn = options.columns[0];
  if (unsafeColumn.title !== "") {
    throw new Error("logfile-controlled header was passed as a string title");
  }
  const title = unsafeColumn.titleFormatter();
  if (title.textContent !== unsafeName) {
    throw new Error("header was not rendered through textContent");
  }
  if (options.data[0]["http.status"] !== 200) {
    throw new Error("dotted field was not retained as a flat key");
  }
  if (options.data.length !== 25 || "pagination" in options) {
    throw new Error("the bounded live window was paginated or truncated");
  }
  if (lifecycleBadge.className !== "ps-stream-badge ps-stream-badge--incomplete") {
    throw new Error("incomplete lifecycle badge was not rendered");
  }
  if (!status.textContent.includes("application state is unknown")) {
    throw new Error("incomplete lifecycle wording overstated application state");
  }
  if (!status.textContent.includes("bounded recent raw observation window")) {
    throw new Error("the bounded raw observation window was not identified");
  }
  if (!healthStatus.textContent.includes("Parser: 1 malformed or oversized")) {
    throw new Error("parse status was not rendered from bounded source health");
  }
  if (!sinceVisitStatus.textContent.includes("Exact since-last-visit comparison is incomplete") ||
      !sinceVisitStatus.textContent.includes("continuity gap while you were away") ||
      !sinceVisitStatus.textContent.includes("No zero-change conclusion is shown")) {
    throw new Error("returning-browser copy did not block a continuity-gap zero conclusion");
  }
  if (sinceVisitDetails.children[0].dataset.comparisonStatus !== "incomplete") {
    throw new Error("incomplete returning-browser comparison was not structurally marked");
  }
  if (noteworthyItems.children.length !== 2 ||
      noteworthyItems.children[0].dataset.noteworthyKind !== "source_record" ||
      noteworthyItems.children[1].dataset.noteworthyKind !== "system_notice") {
    throw new Error("source records and plotsrv system notices were not structurally distinguished");
  }
  if (!noteworthyItems.children[0].children[0].textContent.includes("recognised severity: error")) {
    throw new Error("an allowlisted structured severity was not rendered from its source field");
  }
  if (!noteworthyItems.children[1].children[0].textContent.includes("plotsrv system notice")) {
    throw new Error("plotsrv system notices were not visibly distinguished");
  }
  const nested = options.columns[2].formatter({getValue: () => options.data[0].nested});
  if (nested.textContent !== '{"items":["a","b"],"v":"null"}') {
    throw new Error("nested JSON display did not preserve scalar types");
  }
  return context.window.PLOTSRV.core.loadStream();
}).then(() => {
  if (!appendedRows || appendedRows.length !== 1 || appendedRows[0].sequence !== 26) {
    throw new Error("the incremental refresh did not append only the newest record");
  }
  if (replacementCount !== 0) {
    throw new Error("a valid cursor refresh replaced the table instead of preserving its state");
  }
  if (!requestUrls[1].includes("after=25") || !requestUrls[1].includes("session_id=stream-session")) {
    throw new Error("the second refresh did not use the known stream cursor and session");
  }
  return context.window.PLOTSRV.core.loadStream();
}).then(() => {
  if (replacementCount !== 1 || !updatedRows || updatedRows.length !== 2 || updatedRows[0].sequence !== 30) {
    throw new Error("an explicit reset did not replace the bounded local raw window");
  }
  if (!requestUrls[2].includes("after=26")) {
    throw new Error("the reset request did not begin from the last known cursor");
  }
  if (!healthStatus.textContent.includes("Cursor reset:")) {
    throw new Error("the explicit cursor reset was not communicated");
  }
  context.window.PLOTSRV.core.startStreamRefresh();
  if (!eventListeners.visibilitychange || typeof intervalCallback !== "function") {
    throw new Error("stream refresh did not bind a visibility resume handler");
  }
  context.document.hidden = true;
  eventListeners.visibilitychange();
  if (fetchCount !== 3) {
    throw new Error("hidden browser state unexpectedly requested stream data");
  }
  context.document.hidden = false;
  eventListeners.visibilitychange();
  return new Promise((resolve) => setTimeout(resolve, 0));
}).then(() => {
  if (fetchCount !== 4 || !requestUrls[3].includes("after=31")) {
    throw new Error("visible-tab resume did not request from the last known cursor");
  }
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
'''
    subprocess.run(
        ["node", "-e", script, str(stream_source)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_stream_history_picker_replaces_rows_at_every_session_boundary() -> None:
    """Stored sessions must never merge their rows with current observation."""
    stream_source = (
        Path(__file__).parents[1]
        / "src"
        / "plotsrv"
        / "static"
        / "js"
        / "renderers"
        / "stream.js"
    )
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const requestUrls = [];
let tableRows = [];
let replaceCalls = 0;

function element() {
  return {
    textContent: "",
    className: "",
    dataset: {},
    children: [],
    hidden: false,
    value: "",
    onchange: null,
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
  };
}

const elements = {
  "stream-grid": {},
  "stream-status-inline": element(),
  "stream-health-inline": element(),
  "stream-lifecycle-badge": element(),
  "stream-history-picker": element(),
  "stream-history-session-select": element(),
  "stream-history-picker-status": element(),
  "stream-since-visit-status": element(),
  "stream-since-visit-details": element(),
  "stream-noteworthy-status": element(),
  "stream-noteworthy-items": element(),
};

function streamData({session, historical, origin}) {
  return {
    columns: ["origin"],
    records: [{browser_sequence: 1, data: {origin}, observed_at: "2026-01-01T00:00:00+00:00"}],
    session_id: session,
    historical,
    lifecycle: historical ? "ended" : "live",
    durable_history: {state: "complete"},
    first_available_browser_sequence: 1,
    last_available_browser_sequence: 1,
    raw_window: {first_browser_sequence: 1, last_browser_sequence: 1, record_count: 1, max_record_count: 200},
  };
}

const context = {
  Promise,
  fetch: async (url) => {
    requestUrls.push(url);
    if (url.includes("/stream/history?") && !url.includes("session_id=")) {
      return {ok: true, json: async () => ({sessions: [
        {session_id: "stored-one", updated_at: "2026-01-01T00:00:00+00:00", durable_history: {state: "complete"}},
        {session_id: "stored-two", updated_at: "2026-01-02T00:00:00+00:00", durable_history: {state: "complete"}},
      ]})};
    }
    if (url.includes("session_id=stored-one")) {
      return {ok: true, json: async () => ({data: streamData({session: "stored-one", historical: true, origin: "stored-one"})})};
    }
    if (url.includes("session_id=stored-two")) {
      return {ok: true, json: async () => ({data: streamData({session: "stored-two", historical: true, origin: "stored-two"})})};
    }
    return {ok: true, json: async () => streamData({session: "live-now", historical: false, origin: "live-now"})};
  },
  Tabulator: function (_selector, options) {
    tableRows = options.data.slice();
    this.replaceData = (rows) => {
      replaceCalls += 1;
      tableRows = rows.slice();
    };
    this.addData = (rows) => { tableRows = tableRows.concat(rows); };
  },
  window: {
    PLOTSRV: {
      core: {},
      renderers: {},
      state: {streamRefreshTimer: null, streamVisibilityListenerBound: false},
      config: {activeViewId: "logs:history"},
    },
  },
  document: {
    hidden: false,
    addEventListener: () => {},
    createElement: () => element(),
    getElementById: (id) => elements[id] || null,
  },
};

function flush() {
  return Promise.resolve().then(() => Promise.resolve());
}

vm.runInNewContext(source, context, {filename: "stream.js"});
const core = context.window.PLOTSRV.core;
const picker = elements["stream-history-session-select"];
core.loadStream().then(flush).then(async () => {
  if (tableRows.length !== 1 || tableRows[0].origin !== "live-now") {
    throw new Error("initial current rows were not rendered");
  }
  if (!picker.children.some((option) => option.value === "")) {
    throw new Error("current observation was not offered alongside stored history");
  }
  picker.value = "stored-one";
  await picker.onchange();
  await flush();
  if (tableRows.length !== 1 || tableRows[0].origin !== "stored-one") {
    throw new Error("current rows leaked into the first historical session");
  }
  picker.value = "stored-two";
  await picker.onchange();
  await flush();
  if (tableRows.length !== 1 || tableRows[0].origin !== "stored-two") {
    throw new Error("rows leaked from one historical session into another");
  }
  if (!picker.children.some((option) => option.value === "")) {
    throw new Error("current observation disappeared while browsing history");
  }
  picker.value = "";
  await picker.onchange();
  await flush();
  if (tableRows.length !== 1 || tableRows[0].origin !== "live-now") {
    throw new Error("historical rows leaked when returning to current observation");
  }
  if (replaceCalls < 6 || !requestUrls[requestUrls.length - 1].includes("/stream/data?")) {
    throw new Error("session transitions did not replace rows and return to current observation");
  }
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
'''
    subprocess.run(
        ["node", "-e", script, str(stream_source)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_stream_view_returns_promptly_and_starts_existing_source_at_eof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "worker.jsonl"
    source.write_text('{"discarded_before_registration": true}\n', encoding="utf-8")
    received: list[JsonlRecord] = []
    providers: dict[str, Callable[..., object]] = {}

    class RecordingClient:
        def __init__(self, **_: object) -> None:
            pass

        def start(self) -> None:
            pass

        def append_batch(self, batch: JsonlBatch, **_: object) -> bool:
            received.extend(batch.records)
            return True

        def set_source_status_provider(
            self, provider: Callable[..., object] | None
        ) -> None:
            assert provider is not None
            providers["source_status"] = provider

        def set_source_health_provider(
            self, provider: Callable[..., object] | None
        ) -> None:
            assert provider is not None
            providers["source_health"] = provider

        def begin_shutdown(self) -> None:
            pass

        def stop_heartbeats(self, *, timeout_s: float) -> bool:
            return True

        def close(self, *, drain_completed: bool, timeout_s: float) -> bool:
            return drain_completed

        def health(self) -> dict[str, object]:
            return {}

    monkeypatch.setattr(stream_api, "StreamClient", RecordingClient)

    started_at = time.monotonic()
    handle = stream_api.stream_view(
        source=source,
        label="worker stream",
        client_id="caller-client",
        session_id="caller-session",
    )
    try:
        assert time.monotonic() - started_at < 0.5
        assert handle.is_observing
        assert handle.client_id == "caller-client"
        assert handle.session_id == "caller-session"
        assert handle.source_existed_at_start is True
        assert handle.initial_offset == source.stat().st_size
        source_status = providers["source_status"]()
        assert isinstance(source_status, SourceStatus)
        assert source_status.source_available is True
        source_health = providers["source_health"]()
        assert isinstance(source_health, dict)
        assert source_health["unacknowledged_source_bytes"] == 0
        assert source_health["records_rejected"] == 0

        with source.open("a", encoding="utf-8", newline="") as output:
            output.write('{"sequence": 1, "nested": {"b": 2, "a": 1}}\r\n')
            output.write('{"sequence": 2, "later_field": null}\n')

        _wait_until(lambda: len(received) == 2)
        assert [record.data for record in received] == [
            {"sequence": 1, "nested": {"b": 2, "a": 1}},
            {"sequence": 2, "later_field": None},
        ]
    finally:
        handle.stop()


def test_jsonl_follower_observes_a_file_created_after_registration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "created-later.ndjson"
    received: list[JsonlRecord] = []
    follower = JsonlFollower(
        source,
        on_record=received.append,
        poll_interval_s=0.01,
    )
    assert follower.source_existed_at_start is False
    assert follower.initial_offset == 0
    follower.start()
    try:
        source.write_text('{"sequence": 1}\n{"sequence": 2, "new_field": "yes"}\n')

        _wait_until(lambda: len(received) == 2)
        assert [record.data for record in received] == [
            {"sequence": 1},
            {"sequence": 2, "new_field": "yes"},
        ]
        assert [record.source_offset for record in received] == [0, len('{"sequence": 1}\n')]
    finally:
        follower.stop()


def test_jsonl_follower_drains_renamed_handle_before_recreated_active_path(
    tmp_path: Path,
) -> None:
    """Walk through rename-and-recreate without scanning the rotated sibling."""
    source = tmp_path / "active.jsonl"
    rotated = tmp_path / "active.jsonl.previous"
    initial = b'{"discarded_before_registration":true}\n'
    old_record = b'{"source":"renamed","sequence":1}\n'
    new_record = b'{"source":"recreated","sequence":2}\n'
    source.write_bytes(initial)
    delivered: list[JsonlBatch] = []
    follower = JsonlFollower(source, on_batch=lambda batch: delivered.append(batch) or True)
    try:
        with source.open("ab") as output:
            output.write(old_record)
        try:
            source.replace(rotated)
        except PermissionError:
            pytest.skip("the platform does not permit renaming an open source file")
        source.write_bytes(new_record)

        follower._read_available_records()
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"source": "renamed", "sequence": 1}],
            [{"source": "recreated", "sequence": 2}],
        ]
        assert delivered[0].source_offset == len(initial)
        assert delivered[1].source_offset == 0
        health = follower.health()
        assert health["rotation_state"] == "rotated"
        assert health["rotations_completed"] == 1
        assert health["continuity_warning"] is None
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_retries_old_batch_before_switching_to_recreated_path(
    tmp_path: Path,
) -> None:
    """A retained old batch must retain its identity through handover."""
    source = tmp_path / "active.jsonl"
    rotated = tmp_path / "active.jsonl.previous"
    initial = b'{"discarded_before_registration":true}\n'
    source.write_bytes(initial)
    deliveries: list[JsonlBatch] = []
    acknowledgements = iter((False, True, True))
    follower = JsonlFollower(
        source,
        on_batch=lambda batch: deliveries.append(batch) or next(acknowledgements),
    )
    try:
        with source.open("ab") as output:
            output.write(b'{"source":"renamed","sequence":1}\n')
        try:
            source.replace(rotated)
        except PermissionError:
            pytest.skip("the platform does not permit renaming an open source file")
        source.write_bytes(b'{"source":"recreated","sequence":2}\n')

        follower._read_available_records()
        follower._read_available_records()
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in deliveries] == [
            [{"source": "renamed", "sequence": 1}],
            [{"source": "renamed", "sequence": 1}],
            [{"source": "recreated", "sequence": 2}],
        ]
        assert deliveries[0].batch_id == deliveries[1].batch_id
        assert deliveries[2].batch_id != deliveries[0].batch_id
        assert deliveries[2].source_offset == 0
        assert follower.acknowledged_source_offset == source.stat().st_size
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_drains_active_path_before_atomic_replacement(
    tmp_path: Path,
) -> None:
    """A replacement source is consumed only after the retained file drains."""
    source = tmp_path / "active.jsonl"
    replacement = tmp_path / "active-replacement.jsonl"
    initial = b'{"discarded_before_registration":true}\n'
    old_record = b'{"source":"active","sequence":1}\n'
    replacement_records = (
        b'{"source":"replacement","sequence":2}\n'
        b'{"source":"replacement","sequence":3}\n'
    )
    source.write_bytes(initial)
    delivered: list[JsonlBatch] = []
    follower = JsonlFollower(source, on_batch=lambda batch: delivered.append(batch) or True)
    try:
        with source.open("ab") as output:
            output.write(old_record)
        replacement.write_bytes(replacement_records)
        try:
            replacement.replace(source)
        except PermissionError:
            pytest.skip("the platform does not permit replacing an open source file")

        follower._read_available_records()
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"source": "active", "sequence": 1}],
            [
                {"source": "replacement", "sequence": 2},
                {"source": "replacement", "sequence": 3},
            ],
        ]
        assert delivered[0].source_offset == len(initial)
        assert delivered[1].source_offset == 0
        health = follower.health()
        assert health["rotation_state"] == "rotated"
        assert health["rotations_completed"] == 1
        assert health["continuity_warning"] is None
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_marks_an_ambiguous_replacement_as_continuity_uncertain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Changing the active path during handover must remain an explicit gap."""
    source = tmp_path / "active.jsonl"
    first_replacement = tmp_path / "active-first-replacement.jsonl"
    second_replacement = tmp_path / "active-second-replacement.jsonl"
    initial = b'{"discarded_before_registration":true}\n'
    source.write_bytes(initial)
    delivered: list[JsonlBatch] = []
    follower = JsonlFollower(source, on_batch=lambda batch: delivered.append(batch) or True)
    try:
        with source.open("ab") as output:
            output.write(b'{"source":"active","sequence":1}\n')
        first_replacement.write_bytes(b'{"source":"first","sequence":2}\n')
        second_replacement.write_bytes(b'{"source":"second","sequence":3}\n')
        try:
            first_replacement.replace(source)
        except PermissionError:
            pytest.skip("the platform does not permit replacing an open source file")

        original_open = follower._open_source_handle
        replacement_changed = False

        def open_after_second_replacement(*, start_offset: int):
            nonlocal replacement_changed
            if start_offset == 0 and not replacement_changed:
                second_replacement.replace(source)
                replacement_changed = True
            return original_open(start_offset=start_offset)

        monkeypatch.setattr(follower, "_open_source_handle", open_after_second_replacement)
        follower._read_available_records()
        follower._read_available_records()
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"source": "active", "sequence": 1}],
            [{"source": "second", "sequence": 3}],
        ]
        health = follower.health()
        assert health["rotation_state"] == "rotated"
        assert health["continuity_warning"] == (
            "The JSONL source changed during rotation; record continuity is uncertain."
        )
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_publishes_warning_before_successive_replacement_records(
    tmp_path: Path,
) -> None:
    """Regression for 7d618620: C cannot precede B's loss warning."""
    source = tmp_path / "active.jsonl"
    first_replacement = tmp_path / "active-first-replacement.jsonl"
    second_replacement = tmp_path / "active-second-replacement.jsonl"
    initial = b'{"discarded_before_registration":true}\n'
    repeated_record = b'{"source":"identical"}\n'
    source.write_bytes(initial)
    delivered: list[JsonlBatch] = []
    published_statuses: list[SourceStatus] = []
    delivery_order: list[str] = []

    def publish_source_status(status: SourceStatus) -> bool:
        delivery_order.append("status")
        published_statuses.append(status)
        return True

    def accept_batch(batch: JsonlBatch) -> bool:
        delivery_order.append("batch")
        delivered.append(batch)
        return True

    follower = JsonlFollower(
        source,
        on_batch=accept_batch,
        on_source_status=publish_source_status,
    )
    try:
        with source.open("ab") as output:
            output.write(repeated_record)
        first_replacement.write_bytes(b'{"source":"first","sequence":2}\n')
        second_replacement.write_bytes(repeated_record)
        try:
            first_replacement.replace(source)
        except PermissionError:
            pytest.skip("the platform does not permit replacing an open source file")

        # The first poll observes B and drains the old descriptor. Before it
        # can hand over, active B is replaced by C. The missing B must remain
        # visible as a continuity warning even though C is stable to open.
        follower._read_available_records()
        try:
            second_replacement.replace(source)
        except PermissionError:
            pytest.skip("the platform does not permit replacing an open source file")
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"source": "identical"}],
            [{"source": "identical"}],
        ]
        health = follower.health()
        assert health["rotation_state"] == "rotated"
        assert health["continuity_warning"] == (
            "The JSONL source changed during rotation; record continuity is uncertain."
        )
        assert delivery_order == ["batch", "status", "batch"]
        assert published_statuses == [
            SourceStatus(
                source_available=True,
                source_transition="continuing",
                continuity_warning=(
                    "The JSONL source changed during rotation; record continuity is "
                    "uncertain."
                ),
            )
        ]
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_copy_truncate_restarts_conservatively_with_warning(
    tmp_path: Path,
) -> None:
    source = tmp_path / "copy-truncate.jsonl"
    source.write_bytes(b'{"discarded_before_registration":"long enough"}\n')
    delivered: list[JsonlBatch] = []
    follower = JsonlFollower(source, on_batch=lambda batch: delivered.append(batch) or True)
    try:
        with source.open("ab") as output:
            output.write(b'{"accepted":1}\n')
        follower._read_available_records()

        # This is the common copy-truncate shape: same pathname and identity,
        # but a shorter new byte sequence. The old content is unrecoverable,
        # so resume from zero and keep an explicit warning.
        source.write_bytes(b'{"after_truncate":2}\n')
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"accepted": 1}],
            [{"after_truncate": 2}],
        ]
        health = follower.health()
        assert health["rotation_state"] == "continuity_uncertain"
        assert health["continuity_warning"] == (
            "The JSONL source was truncated; record continuity is uncertain."
        )
        assert follower.acknowledged_source_offset == source.stat().st_size
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_warns_on_copy_truncate_that_regrows_before_poll(
    tmp_path: Path,
) -> None:
    """A probe detects a rewrite even when the new size exceeds the old one."""
    source = tmp_path / "rapid-copy-truncate.jsonl"
    source.write_bytes(b'{"discarded_before_registration":true}\n')
    delivered: list[JsonlBatch] = []
    published_statuses: list[SourceStatus] = []
    delivery_order: list[str] = []
    replacement_padding = "new-" * 40

    def publish_source_status(status: SourceStatus) -> bool:
        delivery_order.append("status")
        published_statuses.append(status)
        return True

    def accept_batch(batch: JsonlBatch) -> bool:
        delivery_order.append("batch")
        delivered.append(batch)
        return True

    follower = JsonlFollower(
        source,
        on_batch=accept_batch,
        on_source_status=publish_source_status,
    )
    try:
        with source.open("ab") as output:
            output.write(b'{"accepted":1,"padding":"old-old-old-old-old-old"}\n')
        follower._read_available_records()

        source.write_text(
            json.dumps({"after_regrow": 2, "padding": replacement_padding}) + "\n"
        )
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"accepted": 1, "padding": "old-old-old-old-old-old"}],
            [
                {
                    "after_regrow": 2,
                    "padding": replacement_padding,
                }
            ],
        ]
        health = follower.health()
        assert health["rotation_state"] == "continuity_uncertain"
        assert health["continuity_warning"] == (
            "The JSONL source changed near the observed offset; record continuity is "
            "uncertain."
        )
        assert delivery_order == ["batch", "status", "batch"]
        assert published_statuses == [
            SourceStatus(
                source_available=True,
                source_transition="continuing",
                continuity_warning=(
                    "The JSONL source changed near the observed offset; record "
                    "continuity is uncertain."
                ),
            )
        ]
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_warns_when_initial_eof_is_truncated_and_regrown(
    tmp_path: Path,
) -> None:
    """The registration EOF guard covers rewrites before the first batch."""
    source = tmp_path / "initial-copy-truncate.jsonl"
    source.write_bytes(b'{"old":0}\n')
    delivered: list[JsonlBatch] = []
    follower = JsonlFollower(source, on_batch=lambda batch: delivered.append(batch) or True)
    try:
        # The new source is deliberately larger than the old registration EOF,
        # so a size-only transition would incorrectly classify it as continuing.
        source.write_bytes(b'{"replacement":1}\n{"after":2}\n')
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"replacement": 1}, {"after": 2}],
        ]
        health = follower.health()
        assert health["rotation_state"] == "continuity_uncertain"
        assert health["continuity_warning"] == (
            "The JSONL source changed near the observed offset; record continuity is "
            "uncertain."
        )
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_publishes_start_race_warning_before_replacement_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression for 947a86b6: a construction race warns before delivery."""
    source = tmp_path / "initial-race.jsonl"
    replacement = tmp_path / "initial-race-replacement.jsonl"
    source.write_bytes(b'{"discarded_before_registration":"old"}\n')
    replacement.write_bytes(b'{"replacement":1}\n')
    original_open = JsonlFollower._open_source_handle
    changed = False

    def open_after_replacement(self: JsonlFollower, *, start_offset: int):
        nonlocal changed
        if not changed:
            replacement.replace(source)
            changed = True
        return original_open(self, start_offset=start_offset)

    monkeypatch.setattr(JsonlFollower, "_open_source_handle", open_after_replacement)
    delivered: list[JsonlBatch] = []
    published_statuses: list[SourceStatus] = []
    delivery_order: list[str] = []

    def publish_source_status(status: SourceStatus) -> bool:
        delivery_order.append("status")
        published_statuses.append(status)
        return True

    def accept_batch(batch: JsonlBatch) -> bool:
        delivery_order.append("batch")
        delivered.append(batch)
        return True

    follower = JsonlFollower(
        source,
        on_batch=accept_batch,
        on_source_status=publish_source_status,
    )
    try:
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"replacement": 1}],
        ]
        health = follower.health()
        assert health["rotation_state"] == "continuity_uncertain"
        assert health["continuity_warning"] == (
            "The JSONL source changed during observer start; record continuity is "
            "uncertain."
        )
        assert delivery_order == ["status", "batch"]
        assert published_statuses == [
            SourceStatus(
                source_available=True,
                source_transition="replaced",
                continuity_warning=(
                    "The JSONL source changed during observer start; record continuity "
                    "is uncertain."
                ),
            )
        ]
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_warns_before_resuming_from_replacement_after_disappearance(
    tmp_path: Path,
) -> None:
    """A missing interval prevents the returned replacement being proven whole."""
    source = tmp_path / "temporary.jsonl"
    source.write_bytes(b'{"discarded_before_registration":true}\n')
    delivered: list[JsonlBatch] = []
    published_statuses: list[SourceStatus] = []
    delivery_order: list[str] = []

    def publish_source_status(status: SourceStatus) -> bool:
        delivery_order.append("status")
        published_statuses.append(status)
        return True

    def accept_batch(batch: JsonlBatch) -> bool:
        delivery_order.append("batch")
        delivered.append(batch)
        return True

    follower = JsonlFollower(
        source,
        on_batch=accept_batch,
        on_source_status=publish_source_status,
    )
    try:
        source.unlink()
        follower._read_available_records()
        unavailable_health = follower.health()
        assert unavailable_health["source_available"] is False
        assert unavailable_health["source_transition"] == "missing"

        source.write_bytes(b'{"returned":true}\n')
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"returned": True}],
        ]
        returned_health = follower.health()
        assert returned_health["source_available"] is True
        assert returned_health["rotation_state"] == "rotated"
        assert returned_health["continuity_warning"] == (
            "The JSONL source was replaced; record continuity is uncertain."
        )
        assert delivery_order == ["status", "batch"]
        assert published_statuses == [
            SourceStatus(
                source_available=True,
                source_transition="continuing",
                continuity_warning=(
                    "The JSONL source was replaced; record continuity is uncertain."
                ),
            )
        ]
    finally:
        follower.stop()
        follower.close()


def test_source_identity_replacement_remains_uncertain_at_matching_size() -> None:
    """Identity, rather than plausible length metadata, governs replacement."""
    previous = file_source.SourceObservation(
        identity=file_source.FileIdentity(device=7, inode=11),
        size_bytes=128,
        available=True,
    )
    replacement = file_source.SourceObservation(
        identity=file_source.FileIdentity(device=7, inode=12),
        size_bytes=128,
        available=True,
    )

    transition = file_source.classify_source_transition(previous, replacement)

    assert transition.kind is file_source.SourceTransitionKind.REPLACED
    assert (
        transition.classification
        is file_source.SourceTransitionClassification.CONTINUITY_UNCERTAIN
    )
    assert transition.continuity_warning == (
        "The JSONL source was replaced; record continuity is uncertain."
    )


def test_jsonl_follower_ignores_preexisting_rotated_siblings_and_hides_source_path(
    tmp_path: Path,
) -> None:
    private_dir = tmp_path / "private-source-directory"
    private_dir.mkdir()
    source = private_dir / "active.jsonl"
    source.write_bytes(b'{"discarded_before_registration":true}\n')
    (private_dir / "active.jsonl.1").write_bytes(b'{"historical":1}\n')
    (private_dir / "active.jsonl.2.gz").write_bytes(b"not a JSONL source")
    delivered: list[JsonlBatch] = []
    follower = JsonlFollower(source, on_batch=lambda batch: delivered.append(batch) or True)
    try:
        with source.open("ab") as output:
            output.write(b'{"active":true}\n')
        follower._read_available_records()

        assert [[record.data for record in batch.records] for batch in delivered] == [
            [{"active": True}],
        ]
        follower.last_error = PermissionError(13, "denied", str(source))
        health = follower.health()
        assert health["source"] == "active.jsonl"
        assert str(private_dir) not in str(health)
        assert str(source) not in str(health)
        assert health["last_error"] == "The JSONL source cannot be read."
    finally:
        follower.stop()
        follower.close()


def test_jsonl_follower_retains_one_bounded_batch_until_acknowledged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "acknowledged.jsonl"
    first_line = b'{"sequence":1}\n'
    second_line = b'{"sequence":2}\n'
    third_line = b'{"sequence":3}\n'
    deliveries: list[JsonlBatch] = []
    acknowledgements = iter((False, True, True))
    monkeypatch.setattr(file_source, "MAX_BATCH_RECORDS", 2)

    follower = JsonlFollower(
        source,
        on_batch=lambda batch: (
            deliveries.append(batch) or next(acknowledgements)
        ),
    )
    source.write_bytes(first_line + second_line + third_line)

    follower._read_available_records()
    first_batch = deliveries[-1]
    assert [record.data for record in first_batch.records] == [
        {"sequence": 1},
        {"sequence": 2},
    ]
    assert follower.acknowledged_source_offset == 0
    assert follower.candidate_source_offset == len(first_line + second_line)

    follower._read_available_records()
    assert deliveries[-1].batch_id == first_batch.batch_id
    assert deliveries[-1].source_offset == first_batch.source_offset
    assert follower.acknowledged_source_offset == len(first_line + second_line)
    assert follower.candidate_source_offset == len(first_line + second_line)

    follower._read_available_records()
    assert [record.data for record in deliveries[-1].records] == [{"sequence": 3}]
    assert deliveries[-1].batch_id != first_batch.batch_id
    assert follower.acknowledged_source_offset == len(
        first_line + second_line + third_line
    )
    assert follower.candidate_source_offset == follower.acknowledged_source_offset


def test_stream_client_reuses_batch_identity_when_first_delivery_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = StreamRegistration(
        view_id="logs:retry",
        label="retry",
        section="logs",
        client_id="stable-client",
        session_id="stable-session",
    )
    client = StreamClient(
        host="127.0.0.1",
        port=1,
        registration=registration,
        retry_initial_delay_s=0.001,
        retry_max_delay_s=0.001,
    )
    client._registered.set()
    batch = JsonlBatch(
        batch_id="stable-batch",
        records=(
            JsonlRecord(
                data={"sequence": 1},
                source_offset=12,
                source_end_offset=27,
                observed_at=datetime.now(UTC),
            ),
        ),
        source_offset=12,
        source_end_offset=27,
    )
    registry = StreamRegistry()
    registry.register(registration)
    append_payloads: list[dict[str, object]] = []

    def request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if path == "/stream/register":
            state = registry.register(registration)
            return {"ok": True, "next_batch_sequence": state.next_batch_sequence}
        assert path == "/stream/append"
        append_payloads.append(payload)
        result = registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=str(payload["batch_id"]),
                batch_sequence=int(payload["batch_sequence"]),
                records=tuple(payload["records"]),  # type: ignore[arg-type]
            )
        )
        if len(append_payloads) == 1:
            raise OSError("response lost after request")
        return {
            "ok": True,
            "duplicate": result.duplicate,
            "next_batch_sequence": result.next_batch_sequence,
        }

    monkeypatch.setattr(client, "_request", request)

    assert client.append_batch(batch) is False
    time.sleep(0.002)
    assert client.append_batch(batch) is True

    assert [payload["session_id"] for payload in append_payloads] == [
        "stable-session",
        "stable-session",
    ]
    assert [payload["client_id"] for payload in append_payloads] == [
        "stable-client",
        "stable-client",
    ]
    assert [payload["batch_id"] for payload in append_payloads] == [
        "stable-batch",
        "stable-batch",
    ]
    assert [payload["batch_sequence"] for payload in append_payloads] == [0, 0]
    assert [row["data"] for row in registry.data(view_id=registration.view_id)["records"]] == [
        {"sequence": 1}
    ]


def test_stream_client_backoff_defers_repeat_network_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = StreamRegistration(
        view_id="logs:backoff",
        label="backoff",
        section="logs",
        client_id="stable-client",
        session_id="stable-session",
    )
    client = StreamClient(host="127.0.0.1", port=1, registration=registration)
    client._registered.set()
    batch = JsonlBatch(
        batch_id="stable-batch",
        records=(
            JsonlRecord(
                data={"sequence": 1},
                source_offset=0,
                source_end_offset=15,
                observed_at=datetime.now(UTC),
            ),
        ),
        source_offset=0,
        source_end_offset=15,
    )
    attempts = 0

    def request(_path: str, _payload: dict[str, object]) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise OSError("server unavailable")

    monkeypatch.setattr(client, "_request", request)

    assert client.append_batch(batch) is False
    assert client.retry_delay_s > 0
    assert client.append_batch(batch) is False
    assert attempts == 1


def test_stream_append_retries_idempotently_and_rejects_forward_gaps(
    client: TestClient,
) -> None:
    _register_stream(client)
    payload = {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": "logs:worker stream",
        "client_id": TEST_CLIENT_ID,
        "session_id": "test-session",
        "batch_id": "stable-batch",
        "batch_sequence": 0,
        "records": [{"sequence": 1}],
    }
    first = client.post("/stream/append", json=payload)
    assert first.status_code == 200
    repeated = client.post("/stream/append", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["accepted_records"] == 1

    forward = client.post(
        "/stream/append",
        json={**payload, "batch_id": "future", "batch_sequence": 2},
    )
    assert forward.status_code == 409
    altered_retry = client.post(
        "/stream/append",
        json={**payload, "records": [{"sequence": "altered"}]},
    )
    assert altered_retry.status_code == 409

    data = client.get("/stream/data", params={"view": "logs:worker stream"})
    assert [row["data"] for row in data.json()["records"]] == [{"sequence": 1}]
    assert data.json()["accepted_batches"] == 1
    assert data.json()["duplicate_batches"] == 1


def test_stream_request_and_batch_limits_are_enforced_on_both_sides(
    client: TestClient,
) -> None:
    _register_stream(client)
    response = client.post(
        "/stream/append",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": "logs:worker stream",
            "client_id": TEST_CLIENT_ID,
            "session_id": "test-session",
            "batch_id": "too-many",
            "batch_sequence": 0,
            "records": [{"sequence": index} for index in range(MAX_STREAM_BATCH_RECORDS + 1)],
        },
    )
    assert response.status_code == 413

    oversized_record = client.post(
        "/stream/append",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": "logs:worker stream",
            "client_id": TEST_CLIENT_ID,
            "session_id": "test-session",
            "batch_id": "too-large-record",
            "batch_sequence": 0,
            "records": [{"message": "x" * MAX_STREAM_RECORD_BYTES}],
        },
    )
    assert oversized_record.status_code == 413

    oversized_batch = client.post(
        "/stream/append",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": "logs:worker stream",
            "client_id": TEST_CLIENT_ID,
            "session_id": "test-session",
            "batch_id": "too-large-batch",
            "batch_sequence": 0,
            "records": [{"message": "x" * 60_000} for _ in range(9)],
        },
    )
    assert oversized_batch.status_code == 413

    request_too_large = client.post(
        "/stream/append",
        content=(b"{" + b'"padding":"' + b"x" * MAX_STREAM_REQUEST_BYTES + b'"}'),
        headers={"Content-Type": "application/json"},
    )
    assert request_too_large.status_code == 413

    registration = StreamRegistration(
        view_id="logs:bounded-client",
        label="bounded client",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id="test-session",
    )
    bounded_client = StreamClient(host="127.0.0.1", port=1, registration=registration)
    too_large_batch = JsonlBatch(
        batch_id="too-many",
        records=tuple(
            JsonlRecord(
                data={"sequence": index},
                source_offset=index,
                source_end_offset=index + 1,
                observed_at=datetime.now(UTC),
            )
            for index in range(MAX_STREAM_BATCH_RECORDS + 1)
        ),
        source_offset=0,
        source_end_offset=MAX_STREAM_BATCH_RECORDS + 1,
    )
    with pytest.raises(StreamBatchValidationError):
        bounded_client.append_batch(too_large_batch)

    too_large_record = JsonlBatch(
        batch_id="too-large-record",
        records=(
            JsonlRecord(
                data={"message": "x" * MAX_STREAM_RECORD_BYTES},
                source_offset=0,
                source_end_offset=MAX_STREAM_RECORD_BYTES,
                observed_at=datetime.now(UTC),
            ),
        ),
        source_offset=0,
        source_end_offset=MAX_STREAM_RECORD_BYTES,
    )
    with pytest.raises(StreamBatchValidationError):
        bounded_client.append_batch(too_large_record)


@pytest.mark.parametrize(
    "bad_line",
    (
        b'{"value":1e400}',
        b'{"value":"\\ud800"}',
    ),
    ids=("overflowing-float", "lone-surrogate"),
)
def test_batched_follower_accounts_completed_malformed_lines_and_recovers(
    bad_line: bytes, tmp_path: Path
) -> None:
    source = tmp_path / "malformed-batched.jsonl"
    received: list[JsonlBatch] = []
    errors: list[BaseException] = []
    follower = JsonlFollower(
        source,
        on_batch=lambda batch: received.append(batch) or True,
        on_error=errors.append,
    )
    source.write_bytes(bad_line + b"\n{\"after\":true}\n")

    follower._read_available_records()

    assert follower.records_rejected == 1
    assert len(errors) == 1
    assert [record.data for record in received[0].records] == [{"after": True}]
    assert follower.acknowledged_source_offset == source.stat().st_size
    assert follower.candidate_source_offset == source.stat().st_size


def test_batched_follower_accounts_completed_oversized_line_and_bounds_partial_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "oversized-batched.jsonl"
    received: list[JsonlBatch] = []
    errors: list[BaseException] = []
    monkeypatch.setattr(file_source, "MAX_JSONL_RECORD_BYTES", 32)
    monkeypatch.setattr(file_source, "MAX_JSONL_PARTIAL_LINE_BYTES", 32)
    monkeypatch.setattr(file_source, "READ_CHUNK_BYTES", 8)
    follower = JsonlFollower(
        source,
        on_batch=lambda batch: received.append(batch) or True,
        on_error=errors.append,
    )
    source.write_bytes(b"x" * 50 + b"\n{\"after\":true}\n")

    follower._read_available_records()

    assert follower.records_rejected == 1
    assert len(errors) == 1
    assert [record.data for record in received[0].records] == [{"after": True}]
    assert follower.acknowledged_source_offset == source.stat().st_size
    assert follower._partial_line == b""

    partial_source = tmp_path / "partial-batched.jsonl"
    partial = JsonlFollower(partial_source, on_batch=lambda _batch: True)
    partial_source.write_bytes(b"x" * 80)
    partial._read_available_records()

    assert partial.records_rejected == 0
    assert partial._partial_line == b""
    assert partial._oversized_partial_scan_offset == partial_source.stat().st_size
    assert partial.acknowledged_source_offset == 0


def test_follower_health_separates_acknowledged_from_accounted_source_progress(
    tmp_path: Path,
) -> None:
    source = tmp_path / "health.jsonl"
    delivered: list[JsonlBatch] = []
    acknowledgements = iter((False, True))
    follower = JsonlFollower(
        source,
        on_batch=lambda batch: delivered.append(batch) or next(acknowledgements),
    )
    source.write_bytes(b'{"bad":NaN}\n{"sequence":1}\n')

    follower._read_available_records()
    pending_health = follower.health()
    assert pending_health["records_rejected"] == 1
    assert pending_health["records_seen"] == 1
    assert pending_health["acknowledged_source_offset"] == 0
    assert pending_health["accounted_source_offset"] == len(b'{"bad":NaN}\n')
    assert pending_health["in_flight_records"] == 1
    assert pending_health["unacknowledged_source_bytes"] == source.stat().st_size

    follower._read_available_records()
    accepted_health = follower.health()
    assert accepted_health["acknowledged_source_offset"] == source.stat().st_size
    assert accepted_health["accounted_source_offset"] == source.stat().st_size
    assert accepted_health["in_flight_records"] == 0
    assert [record.data for record in delivered[0].records] == [{"sequence": 1}]


def test_busy_outage_walkthrough_keeps_backlog_in_source_and_recovers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "busy-outage.jsonl"
    registration = StreamRegistration(
        view_id="logs:busy-outage",
        label="busy outage",
        section="logs",
        client_id="busy-client",
        session_id="busy-session",
    )
    registry = StreamRegistry(max_recent_records=1_000)
    server_available = False
    client = StreamClient(
        host="127.0.0.1",
        port=1,
        registration=registration,
        retry_initial_delay_s=0.005,
        retry_max_delay_s=0.01,
    )

    def request(path: str, payload: dict[str, object]) -> dict[str, object]:
        if not server_available:
            raise OSError("temporary server outage")
        if path == "/stream/register":
            state = registry.register(registration)
            return {"ok": True, "next_batch_sequence": state.next_batch_sequence}
        assert path == "/stream/append"
        result = registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=str(payload["batch_id"]),
                batch_sequence=int(payload["batch_sequence"]),
                records=tuple(payload["records"]),  # type: ignore[arg-type]
            )
        )
        return {"ok": True, "next_batch_sequence": result.next_batch_sequence}

    client._request = request  # type: ignore[method-assign]
    follower = JsonlFollower(
        source,
        on_batch=client.append_batch,
        retry_delay=lambda: client.retry_delay_s,
    )
    source.write_bytes(b'{"sequence":1}\n')
    follower._read_available_records()

    with source.open("a", encoding="utf-8", newline="\n") as output:
        for sequence in range(2, 251):
            output.write(json.dumps({"sequence": sequence}) + "\n")

    outage_health = follower.health()
    assert outage_health["acknowledged_source_offset"] == 0
    assert outage_health["in_flight_records"] == 1
    assert outage_health["unread_source_bytes"] == source.stat().st_size
    assert client.health()["registration_failures"] == 1

    server_available = True
    deadline = time.monotonic() + 2.0
    while follower.acknowledged_source_offset < source.stat().st_size:
        assert time.monotonic() < deadline
        follower._read_available_records()
        time.sleep(max(client.retry_delay_s, 0.001))

    recovered_health = follower.health()
    records = registry.data(view_id=registration.view_id)["records"]
    assert recovered_health["unread_source_bytes"] == 0
    assert recovered_health["in_flight_records"] == 0
    assert [record["data"]["sequence"] for record in records] == list(range(1, 251))


def test_jsonl_follower_bounds_unterminated_records_and_recovers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "bounded.jsonl"
    received: list[JsonlRecord] = []
    errors: list[BaseException] = []
    monkeypatch.setattr(file_source, "READ_CHUNK_BYTES", 8)
    monkeypatch.setattr(file_source, "MAX_JSONL_RECORD_BYTES", 32)
    follower = JsonlFollower(source, on_record=received.append, on_error=errors.append)

    # The over-limit line reaches the cap across fixed reads. Its newline is
    # discarded later, after which the follower must resume at the next row.
    oversized = b"x" * 50
    source.write_bytes(oversized + b"\n{\"after\":true}\n")
    partial_sizes: list[int] = []
    for _ in range(16):
        follower._read_available_records()
        partial_sizes.append(len(follower._partial_line))

    assert max(partial_sizes) <= file_source.MAX_JSONL_RECORD_BYTES
    assert follower.records_rejected == 1
    assert len(errors) == 1
    assert [record.data for record in received] == [{"after": True}]
    assert received[0].source_offset == len(oversized) + 1


@pytest.mark.parametrize(
    "bad_line",
    (
        b'{"value":1e400}',
        b'{"value":"\\ud800"}',
        b'{"value":' + b"9" * 5000 + b"}",
        b'{"nested":' * 2_000 + b"0" + b"}" * 2_000,
    ),
    ids=("overflowing-float", "lone-surrogate", "oversized-integer", "deep-json"),
)
def test_jsonl_follower_rejects_invalid_wire_values_and_recovers_next_line(
    bad_line: bytes, tmp_path: Path
) -> None:
    source = tmp_path / "invalid-wire-value.jsonl"
    received: list[JsonlRecord] = []
    errors: list[BaseException] = []
    follower = JsonlFollower(source, on_record=received.append, on_error=errors.append)
    source.write_bytes(bad_line + b"\n{\"after\":true}\n")

    follower._read_available_records()

    assert follower.records_rejected == 1
    assert len(errors) == 1
    assert [record.data for record in received] == [{"after": True}]


@pytest.mark.parametrize(
    "raw_record",
    (
        '{"value":1e400}',
        '{"value":"\\ud800"}',
    ),
    ids=("overflowing-float", "lone-surrogate"),
)
def test_stream_append_rejects_non_wire_safe_json_before_registry_retention(
    client: TestClient, raw_record: str
) -> None:
    _register_stream(client)
    response = client.post(
        "/stream/append",
        content=(
            "{"
            f'"protocol_version":{STREAM_PROTOCOL_VERSION},'
            '"view_id":"logs:worker stream",'
            '"client_id":"test-client",'
            '"session_id":"test-session",'
            '"batch_id":"unsafe-batch",'
            '"batch_sequence":0,'
            '"records":[' + raw_record + "]}"
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422

    _append(client, batch_sequence=0, records=[{"after": True}])
    data = client.get("/stream/data", params={"view": "logs:worker stream"})
    assert data.status_code == 200
    assert [row["data"] for row in data.json()["records"]] == [{"after": True}]


@pytest.mark.parametrize(
    "unsafe_record",
    ({"value": float("inf")}, {"value": "\ud800"}),
    ids=("infinite-float", "lone-surrogate"),
)
def test_registry_and_client_reject_non_wire_safe_direct_records(
    unsafe_record: dict[str, object]
) -> None:
    registration = StreamRegistration(
        view_id="logs:strict-json",
        label="strict json",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id="test-session",
    )
    registry = StreamRegistry()
    registry.register(registration)
    append = StreamAppend(
        view_id=registration.view_id,
        client_id=registration.client_id,
        session_id=registration.session_id,
        batch_id="unsafe-batch",
        batch_sequence=0,
        records=(unsafe_record,),
    )
    with pytest.raises(StreamStateError):
        registry.append(append)
    assert registry.data(view_id=registration.view_id)["records"] == []

    client = StreamClient(host="127.0.0.1", port=1, registration=registration)
    with pytest.raises(StreamRecordValidationError):
        client.append_record(
            JsonlRecord(
                data=unsafe_record,
                source_offset=0,
                source_end_offset=1,
                observed_at=datetime.now(UTC),
            )
        )


def test_stream_registry_bounds_schema_to_current_recent_rows() -> None:
    registry = StreamRegistry(max_recent_records=2, max_recent_columns=2)
    registration = StreamRegistration(
        view_id="logs:bounded-schema",
        label="bounded schema",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id="test-session",
    )
    registry.register(registration)

    for batch_sequence, record in enumerate(
        (
            {"old": 1},
            {"current_one": 2, "current_two": 3, "over_limit": 4},
            {"later": 5},
        )
    ):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"batch-{batch_sequence}",
                batch_sequence=batch_sequence,
                records=(record,),
            )
        )

    data = registry.data(view_id=registration.view_id)
    assert data["columns"] == ["current_one", "current_two"]
    assert [row["data"] for row in data["records"]] == [
        {"current_one": 2, "current_two": 3, "over_limit": 4},
        {"later": 5},
    ]


def test_stream_instance_identity_changes_after_process_local_state_loss() -> None:
    registry = StreamRegistry()
    registration = StreamRegistration(
        view_id="logs:stream-instance",
        label="stream instance",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)
    original = registry.data(view_id=registration.view_id)["stream_instance_id"]

    registry.clear()
    registry.register(registration)
    recreated = registry.data(view_id=registration.view_id)["stream_instance_id"]

    assert isinstance(original, str) and original
    assert isinstance(recreated, str) and recreated
    assert recreated != original


def test_cumulative_counters_and_noteworthy_source_records_survive_raw_eviction() -> None:
    registry = StreamRegistry(max_recent_records=1, max_noteworthy_items=3)
    registration = StreamRegistration(
        view_id="logs:cumulative-noteworthy",
        label="cumulative noteworthy",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)

    records = (
        {"id": 1, "level": "info"},
        {"id": 2, "severity": "critical"},
        {"id": 3, "level": "ERROR", "message": "structured error"},
        {"id": 4, "severity": "fatal"},
        {"id": 5, "severity": "emergency"},
    )
    for batch_sequence, record in enumerate(records):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"batch-{batch_sequence}",
                batch_sequence=batch_sequence,
                records=(record,),
            )
        )

    data = registry.data(view_id=registration.view_id)

    # The raw window no longer contains the explicit error source record, but
    # the exact session counters and its bounded noteworthy representation do.
    assert [row["data"] for row in data["records"]] == [records[-1]]
    cumulative = data["cumulative"]
    assert cumulative["object_type"] == "stream_session_counters"
    assert cumulative["counter_schema_version"] == 2
    assert cumulative["total_records"] == "5"
    assert cumulative["recognized_severity_records"] == "4"
    assert cumulative["recognized_severity_counts"] == {
        "warning": "0",
        "emergency": "1",
        "alert": "0",
        "critical": "1",
        "fatal": "1",
        "error": "1",
    }
    assert cumulative["rejected_source_records"] == "0"
    assert cumulative["continuity_events"] == "0"
    assert cumulative["noteworthy_items"] == "12"
    assert cumulative["noteworthy_source_records"] == "9"
    assert cumulative["system_notices"] == "3"
    assert isinstance(cumulative["first_observed_at"], str)
    assert isinstance(cumulative["last_observed_at"], str)
    assert cumulative["latest_server_sequence"] == "5"
    noteworthy = data["noteworthy"]
    assert noteworthy["max_retained_items"] == 3
    assert noteworthy["retained_item_count"] == 3
    assert [item["source_browser_sequence"] for item in noteworthy["items"]] == [
        "3",
        "4",
        "5",
    ]
    assert [item["severity"] for item in noteworthy["items"]] == [
        "error",
        "fatal",
        "emergency",
    ]
    assert noteworthy["items"][0]["data"] == records[2]
    assert noteworthy["items"][0]["kind"] == "source_record"
    assert noteworthy["items"][0]["object_type"] == "stream_noteworthy_source_record"
    assert all(item["noteworthy_reason"] == "structured_severity" for item in noteworthy["items"])


def test_noteworthy_severity_never_uses_free_text_or_fuzzy_values() -> None:
    registry = StreamRegistry(max_recent_records=10)
    registration = StreamRegistration(
        view_id="logs:structured-severity-only",
        label="structured severity only",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)

    records = (
        {"message": "FATAL ERROR: alarming prose is not structured severity"},
        {"event": "critical", "description": "an error occurred"},
        {"severity": "error happened"},
        {"level": " error "},
    )
    for batch_sequence, record in enumerate(records):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"batch-{batch_sequence}",
                batch_sequence=batch_sequence,
                records=(record,),
            )
        )

    data = registry.data(view_id=registration.view_id)
    assert data["cumulative"]["total_records"] == "4"
    assert data["cumulative"]["recognized_severity_records"] == "0"
    assert data["cumulative"]["recognized_severity_counts"] == {
        "warning": "0",
        **{
            severity: "0"
            for severity in ("emergency", "alert", "critical", "fatal", "error")
        },
    }
    assert not any(
        item["noteworthy_reason"] == "structured_severity"
        for item in data["noteworthy"]["items"]
        if item["kind"] == "source_record"
    )


def test_warning_severity_uses_only_exact_conventional_structured_values() -> None:
    assert recognize_structured_severity({"severity": "warning"}) == "warning"
    assert recognize_structured_severity({"level": "WARN"}) == "warning"
    assert recognize_structured_severity({"message": "warning: error"}) is None
    assert recognize_structured_severity({"severity": "warning-ish"}) is None

    registry = StreamRegistry(max_recent_records=1, max_noteworthy_items=4)
    registration = StreamRegistration(
        view_id="logs:structured-warning",
        label="structured warning",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)
    registry.append(
        StreamAppend(
            view_id=registration.view_id,
            client_id=registration.client_id,
            session_id=registration.session_id,
            batch_id="warning",
            batch_sequence=0,
            records=({"level": "warning", "message": "structured warning"},),
        )
    )

    data = registry.data(view_id=registration.view_id)
    assert data["cumulative"]["recognized_severity_counts"]["warning"] == "1"
    assert data["noteworthy"]["items"][0]["severity"] == "warning"
    assert data["noteworthy"]["items"][0]["noteworthy_reason"] == "structured_severity"


def test_noteworthy_schema_first_values_and_clear_numeric_extrema_are_bounded() -> None:
    registry = StreamRegistry(
        max_recent_records=10,
        max_noteworthy_items=32,
        max_categorical_values=1,
    )
    registration = StreamRegistration(
        view_id="logs:noteworthy-rules",
        label="noteworthy rules",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)
    records = (
        {"status": "starting", "latency_ms": 10},
        {"status": "running", "latency_ms": 15, "new_field": "schema change"},
        {"status": "running", "latency_ms": 3},
    )
    for sequence, record in enumerate(records):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"rules-{sequence}",
                batch_sequence=sequence,
                records=(record,),
            )
        )

    data = registry.data(view_id=registration.view_id)
    items = data["noteworthy"]["items"]
    assert [item["event"] for item in items if item["kind"] == "system_notice"] == [
        "stream_schema_changed"
    ]
    first_values = [
        item
        for item in items
        if item["kind"] == "source_record"
        and item["noteworthy_reason"] == "first_low_cardinality_value"
    ]
    assert [(item["field_name"], item["field_value"]) for item in first_values] == [
        ("status", "starting")
    ]
    extrema = [
        (item["noteworthy_reason"], item["field_name"], item["field_value"])
        for item in items
        if item["kind"] == "source_record"
        and item["noteworthy_reason"] in {"numeric_minimum", "numeric_maximum"}
    ]
    assert extrema == [
        ("numeric_maximum", "latency_ms", 15),
        ("numeric_minimum", "latency_ms", 3),
    ]
    assert data["cumulative"]["noteworthy_items"] == "4"
    assert data["cumulative"]["system_notices"] == "1"


def test_system_notices_are_typed_separately_from_source_noteworthy_records() -> None:
    registry = StreamRegistry(max_noteworthy_items=4)
    registration = StreamRegistration(
        view_id="logs:system-notices",
        label="system notices",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)
    continuity_warning = (
        "The JSONL source was truncated; record continuity is uncertain."
    )
    heartbeat = StreamHeartbeat(
        view_id=registration.view_id,
        client_id=registration.client_id,
        session_id=registration.session_id,
        delivery_state="live",
        pending_delivery=False,
        source_status=SourceStatus(
            source_available=True,
            source_transition="truncated",
            continuity_warning=continuity_warning,
        ),
        source_health=SourceHealth(records_rejected=2),
    )

    registry.heartbeat(heartbeat)
    registry.heartbeat(heartbeat)  # Repeated telemetry is not a new event.

    data = registry.data(view_id=registration.view_id)
    items = data["noteworthy"]["items"]
    assert [item["kind"] for item in items] == ["system_notice", "system_notice"]
    assert [item["object_type"] for item in items] == [
        "stream_system_notice",
        "stream_system_notice",
    ]
    assert [item["event"] for item in items] == [
        "source_continuity_uncertain",
        "source_record_rejection_reported",
    ]
    assert items[0]["continuity_warning"] == continuity_warning
    assert items[1]["rejected_record_count"] == "2"
    assert all("data" not in item for item in items)
    assert data["cumulative"]["system_notices"] == "2"
    assert data["cumulative"]["noteworthy_source_records"] == "0"


def test_transient_optional_telemetry_preserves_cumulative_event_watermarks() -> None:
    """Unknown telemetry is not a reset or resolution of cumulative facts."""
    registry = StreamRegistry(max_noteworthy_items=16)
    registration = StreamRegistration(
        view_id="logs:telemetry-watermarks",
        label="telemetry watermarks",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)
    warning = "The JSONL source was truncated; record continuity is uncertain."

    def heartbeat(status: SourceStatus, health: SourceHealth) -> None:
        registry.heartbeat(
            StreamHeartbeat(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                delivery_state="live",
                pending_delivery=False,
                source_status=status,
                source_health=health,
            )
        )

    uncertain = SourceStatus(
        source_available=True,
        source_transition="truncated",
        continuity_warning=warning,
    )
    heartbeat(uncertain, SourceHealth(records_rejected=2))
    # These are the all-unknown values a temporarily unavailable optional
    # provider sends.  Neither proves that the source counter reset nor that
    # the continuity warning resolved.
    heartbeat(SourceStatus(), SourceHealth())
    heartbeat(uncertain, SourceHealth(records_rejected=2))

    data = registry.data(view_id=registration.view_id)
    assert data["cumulative"]["rejected_source_records"] == "2"
    assert data["cumulative"]["continuity_events"] == "1"
    assert [item["event"] for item in data["noteworthy"]["items"]] == [
        "source_continuity_uncertain",
        "source_record_rejection_reported",
    ]

    # A known normal source state is explicit resolution evidence.  The next
    # warning is therefore a distinct continuity event, while a true source
    # counter increase is counted once from the preserved watermark.
    heartbeat(
        SourceStatus(source_available=True, source_transition="continuing"),
        SourceHealth(records_rejected=2),
    )
    heartbeat(uncertain, SourceHealth(records_rejected=3))
    data = registry.data(view_id=registration.view_id)
    assert data["cumulative"]["rejected_source_records"] == "3"
    assert data["cumulative"]["continuity_events"] == "2"
    assert [item["event"] for item in data["noteworthy"]["items"]] == [
        "source_continuity_uncertain",
        "source_record_rejection_reported",
        "source_continuity_uncertain",
        "source_record_rejection_reported",
    ]


def test_rejection_counter_reset_counts_its_lower_new_generation_value() -> None:
    """A lower nonzero report is observed work after an explicit reset."""
    registry = StreamRegistry(max_noteworthy_items=16)
    registration = StreamRegistration(
        view_id="logs:rejection-counter-reset",
        label="rejection counter reset",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id=TEST_SESSION_ID,
    )
    registry.register(registration)

    def heartbeat(records_rejected: int) -> None:
        registry.heartbeat(
            StreamHeartbeat(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                delivery_state="live",
                pending_delivery=False,
                source_health=SourceHealth(records_rejected=records_rejected),
            )
        )

    # The second report starts a new producer counter generation.  Its one
    # reported rejection must not vanish from the cumulative session fact.
    heartbeat(2)
    heartbeat(1)
    heartbeat(2)

    data = registry.data(view_id=registration.view_id)
    assert data["cumulative"]["rejected_source_records"] == "4"
    items = data["noteworthy"]["items"]
    assert [item["event"] for item in items] == [
        "source_record_rejection_reported",
        "source_rejection_counter_reset",
        "source_record_rejection_reported",
        "source_record_rejection_reported",
    ]
    assert [item["rejected_record_count"] for item in items] == [
        "2",
        None,
        "1",
        "1",
    ]


def test_raw_retention_enforces_count_byte_and_age_bounds_into_fine_windows() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)

    def observation_clock() -> datetime:
        return observed_at

    small = {"id": 1}
    large = {"id": 4, "payload": "x" * 10}
    registry = StreamRegistry(
        max_recent_records=2,
        # After count removes id=2, the remaining small row plus this large
        # row still exceed the byte bound, proving byte eviction independently
        # of the count eviction in the same append.
        max_recent_bytes=stream_record_size(large),
        max_recent_age_s=5.0,
        fine_window_s=60,
        observation_clock=observation_clock,
    )
    registration = StreamRegistration(
        view_id="logs:raw-retention",
        label="raw retention",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id="test-session",
    )
    registry.register(registration)

    def append(batch_sequence: int, record: dict[str, object]) -> None:
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"batch-{batch_sequence}",
                batch_sequence=batch_sequence,
                records=(record,),
            )
        )

    append(0, small)
    observed_at += timedelta(seconds=1)
    append(1, {"id": 2})
    observed_at += timedelta(seconds=1)
    append(2, {"id": 3})  # count evicts id=1
    append(3, large)  # byte bound evicts id=2
    observed_at += timedelta(seconds=6)
    append(4, {"id": 5})  # age bound evicts id=3 and id=4

    data = registry.data(view_id=registration.view_id)
    state = registry._streams[registration.view_id]
    assert [row["data"] for row in data["records"]] == [{"id": 5}]
    assert state.raw_record_bytes <= registry.max_recent_bytes
    assert len(state.records) <= registry.max_recent_records
    assert data["raw_retention"] == {
        "max_record_count": 2,
        "max_record_bytes": registry.max_recent_bytes,
        "max_record_age_s": 5.0,
    }
    assert len(state.fine_windows) == 1
    fine_window = next(iter(state.fine_windows.values()))
    assert fine_window.record_count == 4
    assert fine_window.record_bytes == sum(
        stream_record_size(record)
        for record in (small, {"id": 2}, {"id": 3}, large)
    )
    assert fine_window.first_browser_sequence == 1
    assert fine_window.last_browser_sequence == 4
    assert fine_window.schema_fields == ("id", "payload")
    assert not hasattr(fine_window, "records")


def test_eviction_uses_fixed_plotsrv_observation_time_fine_windows() -> None:
    observed_at = datetime(2026, 1, 1, 12, 0, 59, tzinfo=UTC)
    registry = StreamRegistry(
        max_recent_records=1,
        max_recent_bytes=1_000,
        fine_window_s=60,
        observation_clock=lambda: observed_at,
    )
    registration = StreamRegistration(
        view_id="logs:fine-boundaries",
        label="fine boundaries",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id="test-session",
    )
    registry.register(registration)

    for batch_sequence, record in enumerate(({"id": 1}, {"id": 2}, {"id": 3})):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"batch-{batch_sequence}",
                batch_sequence=batch_sequence,
                records=(record,),
            )
        )
        if batch_sequence == 0:
            observed_at += timedelta(seconds=1)
        elif batch_sequence == 1:
            observed_at += timedelta(seconds=59)

    windows = list(registry._streams[registration.view_id].fine_windows.values())
    assert [(window.observed_from, window.observed_until) for window in windows] == [
        (
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
        ),
        (
            datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 2, tzinfo=UTC),
        ),
    ]
    assert [window.record_count for window in windows] == [1, 1]


def test_summary_merges_are_associative_and_keep_numeric_values_exact() -> None:
    limits = SummaryLimits(
        max_fields=4,
        max_categories_per_field=2,
        max_category_value_bytes=32,
    )
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)

    def window(records: list[dict[str, object]], first_sequence: int) -> SummaryWindow:
        out = SummaryWindow(
            observed_from=observed_at,
            observed_until=observed_at + timedelta(seconds=60),
            resolution_s=60,
        )
        for offset, record in enumerate(records):
            out.add_record(
                StreamRecord(
                    browser_sequence=first_sequence + offset,
                    data=record,
                    observed_at=observed_at + timedelta(seconds=offset),
                    encoded_bytes=stream_record_size(record),
                ),
                limits=limits,
            )
        return out

    first = window(
        [{"latency": 0.1, "state": "z", "message": "x" * 80}], 1
    )
    second = window([{"latency": 2, "state": "a", "payload": {"nested": 1}}], 2)
    third = window([{"latency": -1, "state": "b"}, {"state": "a"}], 3)

    left_grouped = SummaryWindow.merged(
        SummaryWindow.merged(first, second, limits=limits), third, limits=limits
    )
    right_grouped = SummaryWindow.merged(
        first, SummaryWindow.merged(second, third, limits=limits), limits=limits
    )

    assert left_grouped.fields == right_grouped.fields
    assert left_grouped.record_count == right_grouped.record_count == 4
    latency = left_grouped.fields["latency"].numeric
    assert latency is not None
    assert latency.count == 3
    assert latency.total == Fraction.from_float(0.1) + Fraction(1)
    assert latency.mean == (Fraction.from_float(0.1) + Fraction(1)) / 3
    assert latency.minimum == Fraction(-1)
    assert latency.maximum == Fraction(2)
    assert latency.first == Fraction.from_float(0.1)
    assert latency.last == Fraction(-1)

    states = left_grouped.fields["state"].categorical
    assert states is not None
    assert states.total_count == 4
    assert states.tracked_counts == {'"a"': 2, '"b"': 1}
    assert states.untracked_count == 1

    message = left_grouped.fields["message"].categorical
    assert message is not None
    assert message.total_count == 1
    assert message.tracked_counts == {}
    assert message.untracked_count == 1
    assert left_grouped.fields["payload"].non_scalar_count == 1


def test_summary_retention_compacts_to_a_fixed_bounded_shape() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    registry = StreamRegistry(
        max_recent_records=1,
        max_recent_bytes=1_000,
        fine_window_s=1,
        max_fine_summary_windows=2,
        max_coarse_summary_windows=2,
        coarse_window_factor=2,
        max_summary_fields=2,
        max_categorical_values=2,
        max_categorical_value_bytes=16,
        observation_clock=lambda: observed_at,
    )
    registration = StreamRegistration(
        view_id="logs:bounded-summaries",
        label="bounded summaries",
        section="logs",
        client_id=TEST_CLIENT_ID,
        session_id="test-session",
    )
    registry.register(registration)

    for sequence in range(30):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"batch-{sequence}",
                batch_sequence=sequence,
                records=({"value": sequence, "category": f"value-{sequence}"},),
            )
        )
        observed_at += timedelta(seconds=1)

    state = registry._streams[registration.view_id]
    summaries = [
        *state.fine_windows.values(),
        *state.coarse_windows.values(),
        *(() if state.historic_summary is None else (state.historic_summary,)),
    ]
    assert len(state.fine_windows) <= registry.max_fine_summary_windows
    assert len(state.coarse_windows) <= registry.max_coarse_summary_windows
    assert len(summaries) <= registry.max_summary_windows
    assert sum(summary.record_count for summary in summaries) == 29
    assert state.historic_summary is not None
    assert state.historic_summary.is_cumulative is True
    assert all(len(summary.fields) <= registry.summary_limits.max_fields for summary in summaries)
    assert all(
        summary.fields["category"].categorical is not None
        and len(summary.fields["category"].categorical.tracked_counts)
        <= registry.summary_limits.max_categories_per_field
        for summary in summaries
    )


def test_stream_summary_endpoint_exposes_derived_windows_separate_from_raw_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "get_stream_raw_max_records", lambda: 1)
    monkeypatch.setattr(config, "get_stream_max_categorical_values", lambda: 1)
    _register_stream(client, view_id="logs:derived-history")
    _append(
        client,
        view_id="logs:derived-history",
        batch_sequence=0,
        records=[{"latency": 3, "level": "verbose-category"}],
    )
    _append(
        client,
        view_id="logs:derived-history",
        batch_sequence=1,
        records=[{"latency": 5, "level": "other-category"}],
    )
    _append(
        client,
        view_id="logs:derived-history",
        batch_sequence=2,
        records=[{"latency": 7, "level": "most-recent-category"}],
    )

    raw = client.get("/stream/data", params={"view": "logs:derived-history"})
    summary = client.get("/stream/summary", params={"view": "logs:derived-history"})

    assert raw.status_code == 200
    assert [row["data"] for row in raw.json()["records"]] == [
        {"latency": 7, "level": "most-recent-category"}
    ]
    assert raw.json()["summary_revision"] == 2
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["protocol_version"] == STREAM_PROTOCOL_VERSION
    assert payload["object_type"] == "derived_stream_summary_collection"
    assert payload["derived"] is True
    assert "records" not in payload
    assert payload["summary_revision"] == raw.json()["summary_revision"]
    assert payload["summary_window_count"] == 1

    window = payload["windows"][0]
    assert window["object_type"] == "derived_stream_summary_window"
    assert window["derived"] is True
    assert window["tier"] == "fine"
    assert window["resolution"] == {"kind": "fixed_seconds", "seconds": 60}
    assert set(window["observation_window"]) == {"from", "until"}
    assert window["record_count"] == "2"
    assert "data" not in window
    assert window["truncation"]["untracked_field_observations"] == "0"

    fields = {field["field"]: field for field in window["fields"]}
    assert fields["latency"]["numeric"] == {
        "included_finite_count": "2",
        "sum": {"numerator": "8", "denominator": "1"},
        "mean": {"numerator": "4", "denominator": "1"},
        "minimum": {"numerator": "3", "denominator": "1"},
        "maximum": {"numerator": "5", "denominator": "1"},
        "first": {"numerator": "3", "denominator": "1"},
        "last": {"numerator": "5", "denominator": "1"},
    }
    assert fields["level"]["categorical"] == {
        "observed_scalar_count": "2",
        "max_exact_values": 1,
        "tracked_values": [{"value_json": '"other-category"', "count": "1"}],
        "untracked_observations": "1",
        "exact_per_value_counts_complete": False,
    }


@pytest.mark.integration
def test_stream_view_delivers_appended_records_to_the_live_server(tmp_path: Path) -> None:
    """Exercise the public source worker and dedicated HTTP path together."""
    port = _unused_local_port()
    base_url = f"http://127.0.0.1:{port}"
    source = tmp_path / "worker.jsonl"
    source.write_text('{"discarded_before_registration": true}\n', encoding="utf-8")
    handle = None

    start_server(host="127.0.0.1", port=port, auto_on_show=False, quiet=True)
    try:
        _wait_until(lambda: _server_is_ready(f"{base_url}/status"), timeout_s=3.0)
        handle = stream_view(
            source=source,
            label="worker stream",
            section="logs",
            host="127.0.0.1",
            port=port,
        )
        assert handle.is_observing

        with source.open("a", encoding="utf-8") as output:
            output.write('{"sequence": 1, "nested": {"a": 1}}\n')
            output.write('{"sequence": 2, "new_field": "later"}\n')

        data_url = f"{base_url}/stream/data?{urlencode({'view': handle.view_id})}"
        _wait_until(
            lambda: _stream_has_records(data_url, expected_count=2), timeout_s=3.0
        )
        payload = _read_json(data_url)
        records = payload["records"]
        assert isinstance(records, list)
        assert [record["data"]["sequence"] for record in records] == [1, 2]
        assert payload["columns"] == ["sequence", "nested", "new_field"]

        with urlopen(  # noqa: S310 - local test server
            f"{base_url}/?{urlencode({'view': handle.view_id})}", timeout=0.2
        ) as response:
            page = response.read().decode("utf-8")
        assert 'data-kind="stream"' in page
        assert 'id="stream-grid"' in page
        handle.stop()
        assert stream_registry._streams[handle.view_id].lifecycle == "ended"
        handle = None
    finally:
        if handle is not None:
            handle.stop()
        stop_server(join=True)


def _server_is_ready(url: str) -> bool:
    try:
        _read_json(url)
    except OSError:
        return False
    return True


def _stream_has_records(url: str, *, expected_count: int) -> bool:
    try:
        payload = _read_json(url)
    except OSError:
        return False
    records = payload.get("records")
    return isinstance(records, list) and len(records) == expected_count
