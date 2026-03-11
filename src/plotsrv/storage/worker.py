# src/plotsrv/storage/worker.py
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any

from .. import config
from .backend import list_snapshots, write_snapshot_and_prune
from .policy import estimate_payload_size_bytes, should_store_snapshot


@dataclass(frozen=True, slots=True)
class StorageTask:
    view_id: str
    kind: str
    obj: Any
    section: str | None = None
    label: str | None = None
    extra: dict[str, Any] | None = None


class StorageWorker:
    """
    Lightweight background worker for optional disk snapshot persistence.

    Design goals for 0.0.5:
    - best effort
    - never block live publish path
    - tolerate storage errors silently by default
    - single worker thread is sufficient
    """

    def __init__(self, *, max_queue_size: int = 1000) -> None:
        self._queue: queue.Queue[StorageTask | None] = queue.Queue(
            maxsize=max_queue_size
        )
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
    ) -> bool:
        """
        Queue a storage task.

        Returns:
        - True if accepted into queue
        - False if dropped (queue full or worker unavailable)
        """
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
        )

        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
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

            try:
                self._process_task(item)
            except Exception:
                # Best-effort persistence only in 0.0.5 foundation.
                pass
            finally:
                self._queue.task_done()

    def _process_task(self, task: StorageTask) -> None:
        root_dir = config.get_storage_root_dir()

        existing = list_snapshots(root_dir=root_dir, view_id=task.view_id)
        size_bytes = estimate_payload_size_bytes(kind=task.kind, obj=task.obj)
        decision = should_store_snapshot(
            view_id=task.view_id,
            payload_size_bytes=size_bytes,
            existing_snapshots=existing,
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
) -> bool:
    return get_storage_worker().submit(
        view_id=view_id,
        kind=kind,
        obj=obj,
        section=section,
        label=label,
        extra=extra,
    )
