# src/plotsrv/storage/worker.py
from __future__ import annotations

import queue
import sys
import threading
from dataclasses import dataclass
from typing import Any

from .. import config
from .backend import list_snapshots, write_snapshot_and_prune
from .latest import FileLatestStateBackend
from .policy import (
    estimate_payload_size_bytes,
    is_file_backed_watch_storage_task,
    should_store_snapshot,
)


@dataclass(frozen=True, slots=True)
class StorageTask:
    view_id: str
    kind: str
    obj: Any
    section: str | None = None
    label: str | None = None
    extra: dict[str, Any] | None = None
    source: str | None = None
    estimated_bytes: int = 0


class StorageWorker:
    """
    Lightweight background worker for optional disk persistence.

    Handles both:
    - latest live-state persistence
    - historical snapshots
    """

    def __init__(
        self,
        *,
        max_queue_size: int | None = None,
        max_pending_bytes: int | None = None,
    ) -> None:
        queue_size = (
            config.get_storage_max_pending_tasks()
            if max_queue_size is None
            else max_queue_size
        )
        self._queue: queue.Queue[StorageTask | None] = queue.Queue(
            maxsize=max(1, int(queue_size))
        )
        self._max_pending_bytes = max(
            1,
            int(
                config.get_storage_max_pending_bytes()
                if max_pending_bytes is None
                else max_pending_bytes
            ),
        )
        self._pending_bytes = 0
        self._submitted = 0
        self._processed = 0
        self._rejected = 0
        self._failed = 0
        self._last_error: str | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._started and self._thread is not None and self._thread.is_alive():
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="plotsrv-storage-worker",
                daemon=True,
            )
            self._thread.start()
            self._started = True

    def stop(self, *, join: bool = False, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._started:
                return

            self._stop_event.set()
            try:
                self._queue.put_nowait(None)
            except Exception:
                pass

            t = self._thread

        if join and t is not None:
            t.join(timeout=timeout)

    def submit(
        self,
        *,
        view_id: str,
        kind: str,
        obj: Any,
        section: str | None = None,
        label: str | None = None,
        extra: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> bool:
        if not config.get_storage_enabled():
            return False

        self.start()

        task = StorageTask(
            view_id=view_id,
            kind=kind,
            obj=obj,
            section=section,
            label=label,
            extra=extra,
            source=source,
            estimated_bytes=_estimate_storage_task_bytes(obj),
        )

        estimate = max(1, task.estimated_bytes)
        with self._lock:
            self._submitted += 1
            if estimate > self._max_pending_bytes:
                self._rejected += 1
                self._last_error = (
                    "storage task exceeds storage-settings.max_pending_mb"
                )
                return False
            if self._pending_bytes + estimate > self._max_pending_bytes:
                self._rejected += 1
                self._last_error = "storage queue byte budget reached"
                return False
            self._pending_bytes += estimate

        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            with self._lock:
                self._pending_bytes = max(0, self._pending_bytes - estimate)
                self._rejected += 1
                self._last_error = "storage queue task budget reached"
            return False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            with self._lock:
                self._pending_bytes = max(
                    0,
                    self._pending_bytes - max(0, item.estimated_bytes),
                )

            try:
                self._process_task(item)
                with self._lock:
                    self._processed += 1
            except Exception as exc:
                # Best-effort persistence only in this 0.0.5 version for now.
                with self._lock:
                    self._failed += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"
            finally:
                self._queue.task_done()

    def stats(self) -> dict[str, Any]:
        """Return inspectable admission and processing counters."""
        with self._lock:
            thread = self._thread
            return {
                "queued": self._queue.qsize(),
                "pending_bytes": self._pending_bytes,
                "max_pending_tasks": self._queue.maxsize,
                "max_pending_bytes": self._max_pending_bytes,
                "submitted": self._submitted,
                "processed": self._processed,
                "rejected": self._rejected,
                "failed": self._failed,
                "last_error": self._last_error,
                "running": bool(thread is not None and thread.is_alive()),
            }

    def _process_task(self, task: StorageTask) -> None:
        if is_file_backed_watch_storage_task(
            source=task.source,
            extra=task.extra,
        ):
            return

        root_dir = config.get_storage_root_dir()

        if config.get_storage_latest_enabled():
            latest_backend = FileLatestStateBackend(root_dir=root_dir)
            latest_backend.write_latest(
                view_id=task.view_id,
                kind=task.kind,
                obj=task.obj,
                section=task.section,
                label=task.label,
                extra=task.extra,
            )

        existing = list_snapshots(root_dir=root_dir, view_id=task.view_id)
        size_bytes = estimate_payload_size_bytes(kind=task.kind, obj=task.obj)
        decision = should_store_snapshot(
            view_id=task.view_id,
            payload_size_bytes=size_bytes,
            existing_snapshots=existing,
            source=task.source,
        )

        if not decision.accepted:
            return

        write_snapshot_and_prune(
            root_dir=root_dir,
            view_id=task.view_id,
            kind=task.kind,
            obj=task.obj,
            keep_last=decision.keep_last,
            section=task.section,
            label=task.label,
            extra=task.extra,
        )


_WORKER: StorageWorker | None = None
_WORKER_LOCK = threading.Lock()


def get_storage_worker() -> StorageWorker:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = StorageWorker()
        return _WORKER


def start_storage_worker() -> None:
    get_storage_worker().start()


def stop_storage_worker(*, join: bool = False, timeout: float = 5.0) -> None:
    get_storage_worker().stop(join=join, timeout=timeout)


def enqueue_snapshot(
    *,
    view_id: str,
    kind: str,
    obj: Any,
    section: str | None = None,
    label: str | None = None,
    extra: dict[str, Any] | None = None,
    source: str | None = None,
) -> bool:
    return get_storage_worker().submit(
        view_id=view_id,
        kind=kind,
        obj=obj,
        section=section,
        label=label,
        extra=extra,
        source=source,
    )


def get_storage_queue_stats() -> dict[str, Any]:
    return get_storage_worker().stats()


def _estimate_storage_task_bytes(obj: Any) -> int:
    """Estimate retained source memory without serialising or copying it."""
    if isinstance(obj, (bytes, bytearray)):
        return max(1, len(obj))
    if isinstance(obj, str):
        return max(1, len(obj) * 4)

    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            return max(1, int(obj.memory_usage(index=True, deep=True).sum()))
    except Exception:
        pass

    try:
        return max(1, int(sys.getsizeof(obj)))
    except Exception:
        return 1
