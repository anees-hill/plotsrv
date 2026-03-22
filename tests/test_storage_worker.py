from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

import pytest

import plotsrv.storage.worker as worker_mod
from plotsrv.storage.models import SnapshotMeta


def _snap(snapshot_id: str = "20260101T000000.000000Z") -> SnapshotMeta:
    return SnapshotMeta(
        snapshot_id=snapshot_id,
        view_id="v1",
        section="sec",
        label="lab",
        kind="text",
        created_at="2026-01-01T00:00:00+00:00",
        payload_filename=f"{snapshot_id}__payload.txt",
        payload_format="text",
        size_bytes=10,
        path_payload="/tmp/payload.txt",
        path_meta="/tmp/meta.json",
        payload_exists=True,
        extra=None,
    )


def test_submit_returns_false_when_storage_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = worker_mod.StorageWorker()
    monkeypatch.setattr(worker_mod.config, "get_storage_enabled", lambda: False)

    ok = w.submit(view_id="v1", kind="text", obj="x")
    assert ok is False


def test_submit_starts_worker_and_queues_task(monkeypatch: pytest.MonkeyPatch) -> None:
    w = worker_mod.StorageWorker()
    monkeypatch.setattr(worker_mod.config, "get_storage_enabled", lambda: True)

    started = {"n": 0}

    def fake_start() -> None:
        started["n"] += 1

    monkeypatch.setattr(w, "start", fake_start)

    ok = w.submit(
        view_id="v1",
        kind="text",
        obj="hello",
        section="sec",
        label="lab",
        extra={"a": 1},
        source="watch",
    )
    assert ok is True
    assert started["n"] == 1

    item = w._queue.get_nowait()
    assert isinstance(item, worker_mod.StorageTask)
    assert item.view_id == "v1"
    assert item.kind == "text"
    assert item.obj == "hello"
    assert item.section == "sec"
    assert item.label == "lab"
    assert item.extra == {"a": 1}
    assert item.source == "watch"


def test_submit_returns_false_when_queue_full(monkeypatch: pytest.MonkeyPatch) -> None:
    w = worker_mod.StorageWorker()
    monkeypatch.setattr(worker_mod.config, "get_storage_enabled", lambda: True)
    monkeypatch.setattr(w, "start", lambda: None)

    w._queue.put_nowait(worker_mod.StorageTask(view_id="x", kind="text", obj="x"))

    ok = w.submit(view_id="v1", kind="text", obj="y")
    assert ok is False


def test_start_is_idempotent_when_thread_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    w = worker_mod.StorageWorker()

    class FakeThread:
        def is_alive(self) -> bool:
            return True

    w._started = True
    w._thread = FakeThread()  # type: ignore[assignment]

    called = {"n": 0}

    real_thread = worker_mod.threading.Thread

    class CountingThread(real_thread):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            called["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(worker_mod.threading, "Thread", CountingThread)
    w.start()

    assert called["n"] == 0


def test_stop_noop_when_not_started() -> None:
    w = worker_mod.StorageWorker()
    w.stop(join=True, timeout=0.01)  # just no exception


def test_stop_sets_event_and_joins_thread() -> None:
    w = worker_mod.StorageWorker()
    w._started = True

    class FakeThread:
        def __init__(self) -> None:
            self.join_called = False
            self.timeout: float | None = None

        def join(self, timeout: float | None = None) -> None:
            self.join_called = True
            self.timeout = timeout

    fake = FakeThread()
    w._thread = fake  # type: ignore[assignment]

    w.stop(join=True, timeout=1.25)

    assert w._stop_event.is_set() is True
    assert fake.join_called is True
    assert fake.timeout == 1.25

    item = w._queue.get_nowait()
    assert item is None


def test_stop_tolerates_queue_put_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    w = worker_mod.StorageWorker()
    w._started = True

    class FakeQueue:
        def put_nowait(self, item: Any) -> None:
            raise RuntimeError("boom")

    w._queue = FakeQueue()  # type: ignore[assignment]
    w.stop(join=False)


def test_process_task_returns_early_when_decision_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    w = worker_mod.StorageWorker()

    monkeypatch.setattr(worker_mod.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_mod, "list_snapshots", lambda **kwargs: [_snap()])
    monkeypatch.setattr(worker_mod, "estimate_payload_size_bytes", lambda **kwargs: 123)

    class Decision:
        accepted = False
        keep_last = 2

    monkeypatch.setattr(
        worker_mod, "should_store_snapshot", lambda **kwargs: Decision()
    )

    called = {"n": 0}

    def fake_write_snapshot_and_prune(**kwargs: Any) -> tuple[Any, list[Any]]:
        called["n"] += 1
        return object(), []

    monkeypatch.setattr(
        worker_mod, "write_snapshot_and_prune", fake_write_snapshot_and_prune
    )

    task = worker_mod.StorageTask(view_id="v1", kind="text", obj="hello")
    w._process_task(task)

    assert called["n"] == 0


def test_process_task_writes_snapshot_when_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    w = worker_mod.StorageWorker()

    monkeypatch.setattr(worker_mod.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_mod, "list_snapshots", lambda **kwargs: [_snap()])
    monkeypatch.setattr(worker_mod, "estimate_payload_size_bytes", lambda **kwargs: 321)

    class Decision:
        accepted = True
        keep_last = 7

    monkeypatch.setattr(
        worker_mod, "should_store_snapshot", lambda **kwargs: Decision()
    )

    calls: list[dict[str, Any]] = []

    def fake_write_snapshot_and_prune(**kwargs: Any) -> tuple[Any, list[Any]]:
        calls.append(kwargs)
        return object(), []

    monkeypatch.setattr(
        worker_mod, "write_snapshot_and_prune", fake_write_snapshot_and_prune
    )

    task = worker_mod.StorageTask(
        view_id="v1",
        kind="json",
        obj={"a": 1},
        section="sec",
        label="lab",
        extra={"source": "x"},
    )
    w._process_task(task)

    assert calls
    assert calls[0]["root_dir"] == tmp_path
    assert calls[0]["view_id"] == "v1"
    assert calls[0]["kind"] == "json"
    assert calls[0]["obj"] == {"a": 1}
    assert calls[0]["keep_last"] == 7
    assert calls[0]["section"] == "sec"
    assert calls[0]["label"] == "lab"
    assert calls[0]["extra"] == {"source": "x"}


def test_run_processes_task_then_stops_on_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = worker_mod.StorageWorker()
    processed: list[worker_mod.StorageTask] = []

    def fake_process_task(task: worker_mod.StorageTask) -> None:
        processed.append(task)
        w._stop_event.set()

    monkeypatch.setattr(w, "_process_task", fake_process_task)

    task = worker_mod.StorageTask(view_id="v1", kind="text", obj="x")
    w._queue.put_nowait(task)
    w._queue.put_nowait(None)

    w._run()

    assert processed == [task]


def test_run_continues_on_queue_empty_then_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = worker_mod.StorageWorker()

    class FakeQueue:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, timeout: float = 0.25) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise queue.Empty()
            return None

        def task_done(self) -> None:
            pass

    fake_q = FakeQueue()
    w._queue = fake_q  # type: ignore[assignment]
    w._run()

    assert fake_q.calls == 2


def test_run_swallows_process_task_exceptions_and_marks_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = worker_mod.StorageWorker()
    task = worker_mod.StorageTask(view_id="v1", kind="text", obj="x")

    class FakeQueue:
        def __init__(self) -> None:
            self.items = [task, None]
            self.done_calls = 0

        def get(self, timeout: float = 0.25) -> Any:
            return self.items.pop(0)

        def task_done(self) -> None:
            self.done_calls += 1

    fake_q = FakeQueue()
    w._queue = fake_q  # type: ignore[assignment]

    monkeypatch.setattr(
        w,
        "_process_task",
        lambda _task: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    w._run()
    assert fake_q.done_calls == 2


def test_get_storage_worker_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_mod, "_WORKER", None)
    a = worker_mod.get_storage_worker()
    b = worker_mod.get_storage_worker()
    assert a is b


def test_start_and_stop_storage_worker_wrapper_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeWorker:
        def start(self) -> None:
            calls.append(("start", {}))

        def stop(self, *, join: bool = False, timeout: float = 5.0) -> None:
            calls.append(("stop", {"join": join, "timeout": timeout}))

        def submit(self, **kwargs: Any) -> bool:
            calls.append(("submit", kwargs))
            return True

    fake = FakeWorker()
    monkeypatch.setattr(worker_mod, "get_storage_worker", lambda: fake)

    worker_mod.start_storage_worker()
    worker_mod.stop_storage_worker(join=True, timeout=1.5)
    ok = worker_mod.enqueue_snapshot(
        view_id="v1",
        kind="text",
        obj="hello",
        section="sec",
        label="lab",
        extra={"x": 1},
        source="watch",
    )

    assert ok is True
    assert calls[0] == ("start", {})
    assert calls[1] == ("stop", {"join": True, "timeout": 1.5})
    assert calls[2][0] == "submit"
    assert calls[2][1]["view_id"] == "v1"
    assert calls[2][1]["source"] == "watch"
