from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import signal
import socket
import subprocess
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
    MAX_STREAM_RECORD_BYTES,
    MAX_STREAM_REQUEST_BYTES,
    STREAM_PROTOCOL_VERSION,
    StreamAppend,
    StreamBatchValidationError,
    StreamClose,
    StreamHeartbeat,
    StreamRegistration,
    StreamRecordValidationError,
    SourceStatus,
)
from plotsrv.streams.server_state import StreamRegistry, StreamStateError, stream_registry
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
    assert 'id="table-search-input"' in page.text
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
    assert "visibilitychange" in stream_source
    assert "refreshVisibleStream" in stream_source
    assert ".setColumns(" not in stream_source


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
const status = {textContent: ""};
const healthStatus = {textContent: ""};
const lifecycleBadge = {textContent: "", className: ""};
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
    PLOTSRV: {core: {}, renderers: {}, state: {streamRefreshTimer: null, streamVisibilityListenerBound: false}, config: {activeViewId: "logs:worker"}},
    setInterval: (callback) => {
      intervalCallback = callback;
      return 1;
    },
  },
  document: {
    hidden: false,
    addEventListener: (event, callback) => { eventListeners[event] = callback; },
    createElement: () => ({textContent: ""}),
    getElementById: (id) => id === "stream-grid" ? {} : (id === "stream-status-inline" ? status : (id === "stream-health-inline" ? healthStatus : (id === "stream-lifecycle-badge" ? lifecycleBadge : null))),
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
