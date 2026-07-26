from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

import pytest
from fastapi.testclient import TestClient

import plotsrv.publisher as publisher
import plotsrv.server as server
from plotsrv import store
from plotsrv.app import app
from plotsrv.publishing.models import PublishTarget, PublishTask
from plotsrv.publishing.worker import (
    PublishWorker,
    get_publish_queue_stats,
    reset_publish_worker,
)


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def read(self) -> bytes:
        return b"ok"


@pytest.fixture(autouse=True)
def _reset_worker() -> None:
    reset_publish_worker()
    yield
    reset_publish_worker()


def _task(
    obj: Any,
    *,
    view_id: str = "ops:status",
    target: PublishTarget | None = None,
    estimated_bytes: int = 10,
) -> PublishTask:
    return PublishTask(
        obj=obj,
        target=target or PublishTarget(kind="remote", host="127.0.0.1", port=8000),
        coalesce_view_id=view_id,
        estimated_bytes=estimated_bytes,
    )


def test_worker_coalesces_pending_updates_for_same_destination_and_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = PublishWorker(max_pending_views=2, max_pending_bytes=100)
    monkeypatch.setattr(worker, "start", lambda: None)

    assert worker.submit(_task("first", estimated_bytes=20)) is True
    assert worker.submit(_task("second", estimated_bytes=30)) is True

    stats = worker.stats()
    assert stats.queued == 1
    assert stats.pending_bytes == 30
    assert stats.coalesced == 1
    assert stats.dropped == 1
    assert next(iter(worker._pending.values())).obj == "second"


def test_worker_keeps_updates_for_different_remote_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = PublishWorker(max_pending_views=2, max_pending_bytes=100)
    monkeypatch.setattr(worker, "start", lambda: None)

    assert worker.submit(_task("first", target=PublishTarget("remote", "one", 8000)))
    assert worker.submit(_task("second", target=PublishTarget("remote", "two", 8000)))

    assert worker.stats().queued == 2
    assert worker.stats().coalesced == 0


def test_worker_rejects_new_task_when_byte_budget_would_be_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = PublishWorker(max_pending_views=2, max_pending_bytes=30)
    monkeypatch.setattr(worker, "start", lambda: None)

    assert worker.submit(_task("fits", estimated_bytes=20)) is True
    assert worker.submit(_task("too-large", view_id="ops:other", estimated_bytes=20)) is False

    stats = worker.stats()
    assert stats.queued == 1
    assert stats.rejected == 1
    assert "max_pending_mb" in (stats.last_error or "")


def test_flush_reports_timeout_then_completion() -> None:
    worker = PublishWorker(max_pending_views=2, max_pending_bytes=100)
    entered = threading.Event()
    release = threading.Event()

    def process(_task: PublishTask) -> bool:
        entered.set()
        assert release.wait(timeout=1.0)
        return True

    worker._process_task = process  # type: ignore[method-assign]
    assert worker.submit(_task("slow"))
    assert entered.wait(timeout=1.0)
    assert worker.flush(timeout=0.01) is False

    release.set()
    assert worker.flush(timeout=1.0) is True
    worker.stop(join=True, timeout=1.0)


def test_async_remote_publish_returns_before_http_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> _Response:
        captured.append(json.loads(req.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    publisher.publish_view(
        {"state": "ready"},
        label="status",
        host="127.0.0.1",
        port=8123,
        async_=True,
    )

    assert publisher.flush_views(timeout=1.0) is True
    assert captured[0]["label"] == "status"
    assert get_publish_queue_stats()["processed"] == 1


def test_async_remote_failure_does_not_raise_and_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(*args: Any, **kwargs: Any) -> None:
        raise OSError("server is down")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    publisher.publish_view("hello", label="status", host="127.0.0.1", async_=True)

    assert publisher.flush_views(timeout=1.0) is True
    stats = get_publish_queue_stats()
    assert stats["failed"] == 1
    assert stats["processed"] == 0


def test_async_local_publish_uses_worker_then_existing_local_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(server, "start_server", lambda **kwargs: calls.setdefault("start", kwargs))
    monkeypatch.setattr(
        server,
        "refresh_view",
        lambda obj, **kwargs: calls.setdefault("refresh", {"obj": obj, **kwargs}),
    )

    publisher.publish_view({"ok": True}, label="local", async_=True)

    assert publisher.flush_views(timeout=1.0) is True
    assert calls["start"]["host"] == "127.0.0.1"
    assert calls["refresh"]["obj"] == {"ok": True}


def test_view_decorator_forwards_explicit_async_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plotsrv.decorators as decorators

    calls: list[dict[str, Any]] = []

    def fake_publish_view(obj: Any, **kwargs: Any) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(decorators, "publish_view", fake_publish_view)

    @decorators.view(label="status", host="127.0.0.1", async_=True)
    def report() -> dict[str, bool]:
        return {"ok": True}

    assert report() == {"ok": True}
    assert calls[0]["async_"] is True


def test_status_exposes_publish_and_storage_queue_counters() -> None:
    store.reset()
    response = TestClient(app).get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["publish_queue"]["max_pending_views"] == 32
    assert body["storage_queue"]["max_pending_tasks"] == 32
