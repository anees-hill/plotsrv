"""Receiver epochs must recover delivery without weakening same-epoch retries."""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from plotsrv import config, settings, store
from plotsrv.app import app
from plotsrv.browser_updates import browser_update_hub
import plotsrv.http_streams as routes
import plotsrv.server as server
from plotsrv.storage.stream_worker import StreamStorageWorker
from plotsrv.streams.client import StreamClient
from plotsrv.streams.file_source import JsonlBatch, JsonlRecord
from plotsrv.streams.models import StreamRegistration
from plotsrv.streams.server_state import StreamRegistry
from tests.test_stream_storage import _configure_stream_storage, _write_completed_compact_session


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    settings._CTX = settings.RuntimeContext()
    settings._CONFIG_CACHE.clear()
    store.reset()
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    yield
    store.reset()
    settings._CTX = settings.RuntimeContext()
    settings._CONFIG_CACHE.clear()


def batch(number):
    return JsonlBatch(
        batch_id=f"batch-{number}",
        records=(JsonlRecord(data={"value": number}, source_offset=number * 10,
                            source_end_offset=(number + 1) * 10, observed_at=datetime.now(UTC)),),
        source_offset=number * 10, source_end_offset=(number + 1) * 10,
    )


@pytest.mark.parametrize("storage", [False, True])
@pytest.mark.parametrize("lose_ack", [False, True])
def test_pending_batch_recovers_after_receiver_restart(tmp_path, monkeypatch, storage, lose_ack):
    _configure_stream_storage(tmp_path, enabled=storage)
    registry = StreamRegistry()
    worker = StreamStorageWorker()
    workers = [worker]
    monkeypatch.setattr(routes, "stream_registry", registry)
    monkeypatch.setattr(routes, "get_stream_storage_worker", lambda: worker)
    registration = StreamRegistration(view_id="logs:restart", label="restart", section="logs",
                                      client_id="client", session_id="original-session")
    producer = StreamClient(host="127.0.0.1", port=1, registration=registration)
    changed_sessions = []
    producer.on_session_changed = changed_sessions.append
    http = TestClient(app)
    fail_delivery = False

    def request(path, payload, **kwargs):
        if fail_delivery and path == "/stream/append" and not lose_ack:
            raise OSError("receiver unavailable")
        response = http.post(path, json=payload)
        response.raise_for_status()
        if fail_delivery and path == "/stream/append":
            raise OSError("acknowledgement lost")
        return response.json()

    monkeypatch.setattr(producer, "_request", request)
    try:
        assert producer.append_batch(batch(0), force=True)
        fail_delivery = True
        assert not producer.append_batch(batch(1), force=True)
        assert producer._pending_batch_sequence == 1
        worker.stop(join=True)
        # A new process has a fresh receiver ID and no live transport state.
        registry = StreamRegistry()
        monkeypatch.setattr(routes, "stream_registry", registry)
        monkeypatch.setattr(server, "stream_registry", registry)
        monkeypatch.setattr(browser_update_hub, "instance_id", "new-receiver")
        if storage:
            assert server.restore_streams_from_storage() == 1
        worker = StreamStorageWorker()
        workers.append(worker)
        fail_delivery = False
        assert not producer.append_batch(batch(1), force=True)  # restart handshake
        assert changed_sessions == [producer.registration.session_id]
        assert producer.registration.session_id != registration.session_id
        assert producer._pending_batch_id == "batch-1"
        assert producer.append_batch(batch(1), force=True)
        assert producer.append_batch(batch(2), force=True)
        data = registry.data(view_id=registration.view_id)
        assert [row["data"]["value"] for row in data["records"]] == [1, 2]
        assert data["next_batch_sequence"] == 2
        if storage:
            old = registry.historical_data(view_id=registration.view_id,
                                           session_id=registration.session_id)
            assert old["accepted_records"] == (2 if lose_ack else 1)
            assert old["historical"] is True
    finally:
        for candidate in workers:
            candidate.stop(join=True)
        http.close()


def test_lost_ack_on_same_receiver_retries_without_new_session(monkeypatch, tmp_path):
    _configure_stream_storage(tmp_path, enabled=False)
    registry = StreamRegistry()
    monkeypatch.setattr(routes, "stream_registry", registry)
    producer = StreamClient(host="127.0.0.1", port=1, registration=StreamRegistration(
        view_id="logs:ack", label="ack", section="logs", client_id="client", session_id="session"))
    lose_ack = True
    with TestClient(app) as http:
        def request(path, payload, **kwargs):
            response = http.post(path, json=payload)
            response.raise_for_status()
            if path == "/stream/append" and lose_ack:
                raise OSError("lost ack")
            return response.json()
        monkeypatch.setattr(producer, "_request", request)
        assert not producer.append_batch(batch(0), force=True)
        lose_ack = False
        assert producer.append_batch(batch(0), force=True)
        data = registry.data(view_id="logs:ack")
        assert data["accepted_records"] == 1
        assert data["duplicate_batches"] == 1
        assert producer.registration.session_id == "session"


def test_restored_session_requires_fresh_epoch_even_without_previous_handshake(monkeypatch, tmp_path):
    root = _configure_stream_storage(tmp_path)
    _write_completed_compact_session(root)
    registry = StreamRegistry()
    monkeypatch.setattr(routes, "stream_registry", registry)
    monkeypatch.setattr(server, "stream_registry", registry)
    assert server.restore_streams_from_storage() == 1
    worker = StreamStorageWorker()
    monkeypatch.setattr(routes, "get_stream_storage_worker", lambda: worker)
    producer = StreamClient(host="127.0.0.1", port=1, registration=StreamRegistration(
        view_id="logs:restored", label="restored", section="logs",
        client_id="restore-client", session_id="restore-session"))
    try:
        with TestClient(app) as http:
            def request(path, payload, **kwargs):
                response = http.post(path, json=payload)
                response.raise_for_status()
                return response.json()
            monkeypatch.setattr(producer, "_request", request)
            assert not producer._ensure_registered(force=True)
            assert producer.registration.session_id != "restore-session"
            assert producer.append_batch(batch(0), force=True)
            assert registry.historical_data(view_id="logs:restored", session_id="restore-session")["accepted_records"] == 2
    finally:
        worker.stop(join=True)
