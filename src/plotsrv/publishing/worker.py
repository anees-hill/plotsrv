from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import asdict, replace
from typing import Any

from .. import config
from .models import PublishQueueStats, PublishTask


class PublishWorker:
    """A bounded latest-wins worker for best-effort live publishing.

    A task holds the source object until it is processed. Pending tasks are
    therefore constrained by both count and an inexpensive estimate of the
    retained object size. A newer update for the same server/view replaces the
    older pending update immediately, releasing that reference.
    """

    def __init__(
        self,
        *,
        max_pending_views: int = 32,
        max_pending_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self._max_pending_views = max(1, int(max_pending_views))
        self._max_pending_bytes = max(1, int(max_pending_bytes))
        self._pending: OrderedDict[str, PublishTask] = OrderedDict()
        self._pending_bytes = 0
        self._in_flight = 0
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopping = False
        self._condition = threading.Condition(threading.RLock())
        self._submitted = 0
        self._processed = 0
        self._coalesced = 0
        self._dropped = 0
        self._rejected = 0
        self._failed = 0
        self._last_error: str | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return

            self._stopping = False
            self._thread = threading.Thread(
                target=self._run,
                name="plotsrv-publish-worker",
                daemon=True,
            )
            self._thread.start()
            self._started = True

    def submit(self, task: PublishTask) -> bool:
        """Accept a task if it fits the configured bounded queue."""
        self.start()

        with self._condition:
            self._submitted += 1
            key = task.coalesce_key
            estimate = max(1, int(task.estimated_bytes))
            existing = self._pending.get(key)

            if estimate > self._max_pending_bytes:
                self._rejected += 1
                self._last_error = (
                    "publish task exceeds publish-settings.live.max_pending_mb"
                )
                return False

            if existing is None:
                if len(self._pending) >= self._max_pending_views:
                    self._rejected += 1
                    self._last_error = (
                        "publish queue is full: max_pending_views reached"
                    )
                    return False
                if self._pending_bytes + estimate > self._max_pending_bytes:
                    self._rejected += 1
                    self._last_error = (
                        "publish queue is full: max_pending_mb reached"
                    )
                    return False
            else:
                prospective = self._pending_bytes - max(1, existing.estimated_bytes)
                prospective += estimate
                if prospective > self._max_pending_bytes:
                    self._rejected += 1
                    self._last_error = (
                        "new publish task exceeds max_pending_mb; retained prior update"
                    )
                    return False
                self._pending.pop(key)
                self._pending_bytes -= max(1, existing.estimated_bytes)
                self._coalesced += 1
                self._dropped += 1

            queued_task = replace(
                task,
                estimated_bytes=estimate,
            )
            self._pending[key] = queued_task
            self._pending_bytes += estimate
            self._condition.notify_all()
            return True

    def flush(self, *, timeout: float) -> bool:
        """Wait for accepted pending work, without waiting indefinitely."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._pending or self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def stop(self, *, join: bool = False, timeout: float = 5.0) -> None:
        """Stop promptly, discarding work that was not flushed first."""
        with self._condition:
            if not self._started:
                return
            self._stopping = True
            self._dropped += len(self._pending)
            self._pending.clear()
            self._pending_bytes = 0
            thread = self._thread
            self._condition.notify_all()

        if join and thread is not None:
            thread.join(timeout=max(0.0, float(timeout)))

    def stats(self) -> PublishQueueStats:
        with self._condition:
            thread = self._thread
            return PublishQueueStats(
                queued=len(self._pending),
                in_flight=self._in_flight,
                pending_bytes=self._pending_bytes,
                max_pending_views=self._max_pending_views,
                max_pending_bytes=self._max_pending_bytes,
                submitted=self._submitted,
                processed=self._processed,
                coalesced=self._coalesced,
                dropped=self._dropped,
                rejected=self._rejected,
                failed=self._failed,
                last_error=self._last_error,
                running=bool(thread is not None and thread.is_alive()),
            )

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait(timeout=0.25)

                if self._stopping:
                    self._started = False
                    self._condition.notify_all()
                    return

                _, task = self._pending.popitem(last=False)
                self._pending_bytes -= max(1, task.estimated_bytes)
                self._in_flight += 1

            succeeded = False
            error: str | None = None
            try:
                succeeded = self._process_task(task)
                if not succeeded:
                    error = "publish delivery was unsuccessful"
            except Exception as exc:  # pragma: no cover - defensive worker guard
                error = f"{type(exc).__name__}: {exc}"
            finally:
                with self._condition:
                    self._in_flight -= 1
                    if succeeded:
                        self._processed += 1
                    else:
                        self._failed += 1
                        self._last_error = error
                    self._condition.notify_all()

    @staticmethod
    def _process_task(task: PublishTask) -> bool:
        # Import lazily to keep the public publisher free of an import cycle.
        from ..publisher import _run_publish_task

        return _run_publish_task(task)


_WORKER: PublishWorker | None = None
_WORKER_LOCK = threading.Lock()


def get_publish_worker() -> PublishWorker:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = PublishWorker(
                max_pending_views=config.get_publish_max_pending_views(),
                max_pending_bytes=config.get_publish_max_pending_bytes(),
            )
        return _WORKER


def flush_publish_views(*, timeout: float) -> bool:
    with _WORKER_LOCK:
        worker = _WORKER
    if worker is None:
        return True
    return worker.flush(timeout=timeout)


def stop_publish_worker(*, join: bool = False, timeout: float = 5.0) -> None:
    with _WORKER_LOCK:
        worker = _WORKER
    if worker is not None:
        worker.stop(join=join, timeout=timeout)


def get_publish_queue_stats() -> dict[str, Any]:
    with _WORKER_LOCK:
        worker = _WORKER
    if worker is None:
        return {
            "queued": 0,
            "in_flight": 0,
            "pending_bytes": 0,
            "max_pending_views": config.get_publish_max_pending_views(),
            "max_pending_bytes": config.get_publish_max_pending_bytes(),
            "submitted": 0,
            "processed": 0,
            "coalesced": 0,
            "dropped": 0,
            "rejected": 0,
            "failed": 0,
            "last_error": None,
            "running": False,
        }
    return asdict(worker.stats())


def reset_publish_worker() -> None:
    """Test/support helper: stop and forget the process-global worker."""
    global _WORKER
    with _WORKER_LOCK:
        worker = _WORKER
        _WORKER = None
    if worker is not None:
        worker.stop(join=True, timeout=1.0)
