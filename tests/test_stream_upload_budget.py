from __future__ import annotations

from datetime import UTC, datetime

import pytest

from plotsrv import config, store
from plotsrv.publishing.models import PublishTarget
from plotsrv.streams.client import StreamClient
from plotsrv.streams.file_source import JsonlBatch, JsonlRecord
from plotsrv.streams.models import StreamHeartbeat, StreamRegistration
from plotsrv.streams.server_state import StreamRegistry, StreamStateError
from plotsrv.streams.upload_budget import (
    RemoteUploadBudget,
    RemoteUploadHeld,
    target_is_loopback,
)


@pytest.fixture(autouse=True)
def reset_stream_store() -> None:
    store.reset()
    yield
    store.reset()


def _batch() -> JsonlBatch:
    record = JsonlRecord(
        data={"message": "new log line"},
        source_offset=0,
        source_end_offset=20,
        observed_at=datetime.now(UTC),
    )
    return JsonlBatch(
        batch_id="batch-0", records=(record,), source_offset=0, source_end_offset=20
    )


def _registration() -> StreamRegistration:
    return StreamRegistration(
        view_id="logs:budget",
        label="budget",
        section="logs",
        client_id="client",
        session_id="session",
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:8000", True),
        ("http://[::1]:8000", True),
        ("http://localhost:8000", True),
        ("https://demo.plotsrv.com", False),
        ("http://192.168.1.1:8000", False),
    ],
)
def test_only_provable_loopback_targets_are_exempt(url: str, expected: bool) -> None:
    assert target_is_loopback(PublishTarget(kind="remote", base_url=url)) is expected


def test_remote_budget_holds_record_delivery_but_leaves_control_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plotsrv.publishing.transport as transport
    import plotsrv.streams.client as client_module

    budget = RemoteUploadBudget(6_000)
    monkeypatch.setattr(config, "get_stream_remote_upload_max_bytes_per_day", lambda: 6_000)
    monkeypatch.setattr(client_module, "shared_remote_upload_budget", lambda maximum: budget)
    sent: list[tuple[str, dict[str, object]]] = []

    def request(_target, path, payload, **_kwargs):
        sent.append((path, payload))
        if path == "/stream/register":
            return {"ok": True, "next_batch_sequence": 0, "server_instance_id": "receiver"}
        if path == "/stream/heartbeat":
            return {"ok": True, "lifecycle": payload["delivery_state"]}
        if path == "/stream/close":
            return {"ok": True, "lifecycle": "incomplete"}
        raise AssertionError("a held batch must not be uploaded")

    monkeypatch.setattr(transport, "request_json", request)
    client = StreamClient(destination="https://demo.plotsrv.com", registration=_registration())
    try:
        assert client.append_batch(_batch(), force=True) is False
        assert client.health()["upload_held"] is True
        assert client.health()["remote_upload_budget_applies"] is True
        assert client.retry_delay_s > 0
        assert client.heartbeat_once() is True
        assert sent[-1][0] == "/stream/heartbeat"
        assert sent[-1][1]["delivery_state"] == "held"
        assert sent[-1][1]["pending_delivery"] is True
        assert all(path != "/stream/append" for path, _ in sent)
    finally:
        client.close(drain_completed=False, timeout_s=1.0)


def test_remote_budget_counts_attempts_and_enforces_total_control_ceiling() -> None:
    budget = RemoteUploadBudget(6_000)
    class Client:
        pass
    client = Client()
    budget.register(client)
    with pytest.raises(RemoteUploadHeld):
        budget.reserve({"data": "x" * 500}, append=True)
    accepted = 0
    while True:
        try:
            budget.reserve({"control": True}, append=False)
        except RemoteUploadHeld:
            break
        accepted += 1
    assert 1 <= accepted <= 6
    budget.unregister(client)


def test_remote_budget_is_shared_across_two_active_stream_clients() -> None:
    budget = RemoteUploadBudget(20 * 1024 * 1024)
    class Client:
        pass
    first, second = Client(), Client()
    budget.register(first)
    budget.reserve({"record": "x" * (3 * 1024 * 1024)}, append=True)
    budget.register(second)
    with pytest.raises(RemoteUploadHeld):
        budget.reserve({"record": "next"}, append=True)


def test_loopback_url_does_not_consume_remote_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plotsrv.publishing.transport as transport

    monkeypatch.setattr(config, "get_stream_remote_upload_max_bytes_per_day", lambda: 1)
    sent: list[str] = []

    def request(_target, path, payload, **_kwargs):
        sent.append(path)
        if path == "/stream/register":
            return {"ok": True, "next_batch_sequence": 0, "server_instance_id": "receiver"}
        if path == "/stream/append":
            return {"ok": True, "next_batch_sequence": 1}
        if path == "/stream/close":
            return {"ok": True, "lifecycle": "ended"}
        raise AssertionError(path)

    monkeypatch.setattr(transport, "request_json", request)
    client = StreamClient(destination="http://127.0.0.1:8000", registration=_registration())
    try:
        assert client.append_batch(_batch(), force=True) is True
        assert client.health()["remote_upload_budget_applies"] is False
        assert sent == ["/stream/register", "/stream/append"]
    finally:
        client.close(drain_completed=True, timeout_s=1.0)


def test_server_held_lifecycle_requires_pending_delivery_and_expires() -> None:
    now = [100.0]
    registry = StreamRegistry(heartbeat_timeout_s=5.0, monotonic_clock=lambda: now[0])
    registration = _registration()
    registry.register(registration)
    heartbeat = StreamHeartbeat(
        view_id=registration.view_id,
        client_id=registration.client_id,
        session_id=registration.session_id,
        delivery_state="held",
        pending_delivery=True,
    )
    assert registry.heartbeat(heartbeat).lifecycle == "held"
    assert registry.status(view_id=registration.view_id)["lifecycle"] == "held"
    with pytest.raises(StreamStateError, match="pending delivery"):
        registry.heartbeat(
            StreamHeartbeat(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                delivery_state="held",
                pending_delivery=False,
            )
        )
    now[0] += 5.1
    registry.expire_stale_sessions()
    assert registry.status(view_id=registration.view_id)["lifecycle"] == "incomplete"
