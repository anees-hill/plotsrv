"""Independent bounded admission for optional stream persistence.

This worker must never share the ordinary snapshot/latest queue: a noisy
stream's compact snapshots and explicitly enabled raw blocks have their own
task and byte budgets.  It reports every rejection or write failure through a
per-task callback, allowing the live stream registry to remain available while
honestly marking its durable history incomplete.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import json
import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .. import config
from .streams import FileStreamStorageBackend, RawBlockPolicy, StreamStoragePolicy


_DRAIN_SENTINEL = object()


@dataclass(frozen=True, slots=True)
class StreamStorageTask:
    """One bounded, self-contained persistence observation."""

    view_id: str
    session_id: str
    client_id: str
    metadata: dict[str, Any]
    summary_windows: tuple[dict[str, Any], ...]
    noteworthy_items: tuple[dict[str, Any], ...]
    raw_block_id: str | None
    raw_records: tuple[dict[str, Any], ...]
    estimated_bytes: int
    on_complete: Callable[[bool, str | None], None]


@dataclass(frozen=True, slots=True)
class StreamStorageSubmission:
    """Admission outcome, distinct from eventual best-effort write success."""

    accepted: bool
    enabled: bool
    reason: str | None = None


class StreamStorageWorker:
    """Separate bounded worker for compact stream and optional raw persistence."""

    def __init__(
        self,
        *,
        max_queue_size: int | None = None,
        max_pending_bytes: int | None = None,
    ) -> None:
        queue_size = (
            config.get_storage_stream_max_pending_tasks()
            if max_queue_size is None
            else max_queue_size
        )
        # Keep one control slot beyond the public task capacity.  This makes
        # it possible to put a drain sentinel behind a full admitted task
        # queue without letting the sentinel consume an admission slot.
        self._max_pending_tasks = max(1, int(queue_size))
        self._queue: queue.Queue[StreamStorageTask | object] = queue.Queue(
            maxsize=self._max_pending_tasks + 1
        )
        self._max_pending_bytes = max(
            1,
            int(
                config.get_storage_stream_max_pending_bytes()
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
        self._stopping = False
        self._drain_sentinel_enqueued = False
        self._restart_requested = False
        self._outstanding_tasks: dict[int, StreamStorageTask] = {}
        self._shutdown_timeout_task_ids: set[int] = set()
        # One re-entrant lifecycle lock covers admission, thread start, and
        # shutdown.  In particular, submit() does not release it between
        # queueing an accepted task and registering a started worker.
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._stopping:
                return
            self._start_worker_locked()

    def open_admission(self) -> bool:
        """Explicitly begin a later server lifecycle after a completed drain.

        submit() deliberately never reopens a stopped worker by itself: that
        would let a request racing normal shutdown become accepted after
        admission had closed.  Server startup makes the lifecycle boundary
        explicit through this method instead.
        """
        with self._lock:
            if not self._stopping:
                return True
            if self._thread is not None or not self._queue.empty():
                # A new server lifecycle may already be starting while a
                # bounded prior drain finishes.  Reopen only after its
                # sentinel is consumed; no old task can cross that boundary.
                self._restart_requested = True
                return False
            self._stopping = False
            self._drain_sentinel_enqueued = False
            return True

    def stop(self, *, join: bool = False, timeout: float = 5.0) -> None:
        """Close admission and drain every task accepted before shutdown.

        The drain sentinel is appended only after admission is closed.  Since
        its queue slot is reserved, it remains strictly behind every accepted
        task even when the task admission budget is full.  A later lifecycle
        can reuse this worker only after that sentinel has been consumed.
        """
        with self._lock:
            self._stopping = True
            self._restart_requested = False
            # Production admission always starts a worker before it returns.
            # This fallback also drains work staged by test fixtures or a
            # recoverable start interruption rather than abandoning it.
            if self._thread is None and not self._queue.empty():
                self._start_worker_locked()
            if self._thread is not None:
                self._enqueue_drain_sentinel_locked()
            thread = self._thread
        if join and thread is not None:
            try:
                thread.join(timeout=timeout)
            except RuntimeError:
                # A failed Thread.start() must never turn normal cleanup into
                # a second failure. submit() rolls its task back before it can
                # leave this state, but tolerate a manually injected or
                # interpreter-level unstarted thread too.
                with self._lock:
                    if self._thread is thread:
                        self._thread = None
                        self._started = False
                        self._drain_sentinel_enqueued = False
                return
            if thread.is_alive():
                self._mark_shutdown_timeout_incomplete()

    def submit(
        self,
        *,
        view_id: str,
        session_id: str,
        client_id: str,
        metadata: Mapping[str, Any],
        summary_windows: Sequence[Mapping[str, Any]],
        noteworthy_items: Sequence[Mapping[str, Any]],
        raw_block_id: str | None,
        raw_records: Sequence[Mapping[str, Any]],
        on_complete: Callable[[bool, str | None], None],
    ) -> StreamStorageSubmission:
        """Admit a bounded snapshot without affecting ordinary storage work."""
        if not config.get_storage_stream_enabled(view_id):
            return StreamStorageSubmission(accepted=False, enabled=False)

        try:
            task = StreamStorageTask(
                view_id=view_id,
                session_id=session_id,
                client_id=client_id,
                metadata=deepcopy(dict(metadata)),
                summary_windows=tuple(deepcopy(dict(item)) for item in summary_windows),
                noteworthy_items=tuple(
                    deepcopy(dict(item)) for item in noteworthy_items
                ),
                raw_block_id=raw_block_id,
                raw_records=tuple(deepcopy(dict(item)) for item in raw_records),
                estimated_bytes=_estimate_stream_task_bytes(
                    metadata=metadata,
                    summary_windows=summary_windows,
                    noteworthy_items=noteworthy_items,
                    raw_block_id=raw_block_id,
                    raw_records=raw_records,
                ),
                on_complete=on_complete,
            )
        except (TypeError, ValueError) as error:
            return StreamStorageSubmission(
                accepted=False,
                enabled=True,
                reason=f"stream persistence snapshot is invalid: {error}",
            )

        estimate = max(1, task.estimated_bytes)
        with self._lock:
            if self._stopping:
                self._rejected += 1
                self._last_error = "stream persistence worker is stopping"
                return StreamStorageSubmission(
                    accepted=False, enabled=True, reason=self._last_error
                )
            self._submitted += 1
            if estimate > self._max_pending_bytes:
                self._rejected += 1
                self._last_error = (
                    "stream persistence task exceeds "
                    "storage-settings.streams.max_pending_mb"
                )
                return StreamStorageSubmission(
                    accepted=False, enabled=True, reason=self._last_error
                )
            if self._pending_bytes + estimate > self._max_pending_bytes:
                self._rejected += 1
                self._last_error = "stream persistence queue byte budget reached"
                return StreamStorageSubmission(
                    accepted=False, enabled=True, reason=self._last_error
                )
            if self._queue.qsize() >= self._max_pending_tasks:
                self._rejected += 1
                self._last_error = "stream persistence queue task budget reached"
                return StreamStorageSubmission(
                    accepted=False,
                    enabled=True,
                    reason=self._last_error,
                )
            self._pending_bytes += estimate
            try:
                # start() is called below while this same lifecycle lock is
                # held.  Thus stop() cannot return after seeing this accepted
                # item but before a worker has been started for it.
                self._queue.put_nowait(task)
            except queue.Full:
                self._pending_bytes = max(0, self._pending_bytes - estimate)
                self._rejected += 1
                self._last_error = "stream persistence queue task budget reached"
                return StreamStorageSubmission(
                    accepted=False,
                    enabled=True,
                    reason="stream persistence queue task budget reached",
                )

            self._outstanding_tasks[id(task)] = task
            try:
                self.start()
            except Exception as error:
                # The task is not admitted until a worker has successfully
                # started for it.  Thread.start() can fail, and retaining the
                # queued copy in that case would poison later shutdown and
                # falsely advertise persistence as pending.
                self._rollback_start_failure_locked(task=task, estimate=estimate)
                self._rejected += 1
                self._last_error = (
                    "stream persistence worker failed to start: "
                    f"{type(error).__name__}: {error}"
                )
                return StreamStorageSubmission(
                    accepted=False,
                    enabled=True,
                    reason=self._last_error,
                )
        return StreamStorageSubmission(accepted=True, enabled=True)

    def stats(self) -> dict[str, Any]:
        """Expose stream admission independently from ordinary storage stats."""
        with self._lock:
            thread = self._thread
            return {
                "queued": self._queue.qsize(),
                "pending_bytes": self._pending_bytes,
                "max_pending_tasks": self._max_pending_tasks,
                "max_pending_bytes": self._max_pending_bytes,
                "submitted": self._submitted,
                "processed": self._processed,
                "rejected": self._rejected,
                "failed": self._failed,
                "last_error": self._last_error,
                "running": bool(thread is not None and thread.is_alive()),
            }

    def _run(self) -> None:
        try:
            while True:
                task = self._queue.get()
                if task is _DRAIN_SENTINEL:
                    self._queue.task_done()
                    return
                assert isinstance(task, StreamStorageTask)
                with self._lock:
                    self._pending_bytes = max(
                        0, self._pending_bytes - max(0, task.estimated_bytes)
                    )
                try:
                    self._process_task(task)
                except Exception as error:
                    message = f"{type(error).__name__}: {error}"
                    _mark_stream_persistence_incomplete(
                        view_id=task.view_id,
                        session_id=task.session_id,
                        reason=message,
                    )
                    with self._lock:
                        self._failed += 1
                        self._last_error = message
                    _notify(task, success=False, error=message)
                else:
                    with self._lock:
                        self._processed += 1
                    _notify(task, success=True, error=None)
                finally:
                    with self._lock:
                        self._outstanding_tasks.pop(id(task), None)
                        self._shutdown_timeout_task_ids.discard(id(task))
                    self._queue.task_done()
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                    self._started = False
                    # The sentinel has been consumed before reaching this
                    # point; no later lifecycle can inherit stale control
                    # work from this one.
                    self._drain_sentinel_enqueued = False
                    if self._restart_requested:
                        self._stopping = False
                        self._restart_requested = False

    def _start_worker_locked(self) -> None:
        """Start a worker while the lifecycle lock prevents stop races."""
        if self._thread is not None and self._thread.is_alive():
            return
        thread = threading.Thread(
            target=self._run,
            name="plotsrv-stream-storage-worker",
            daemon=True,
        )
        self._thread = thread
        # Kept as a small private seam for the deterministic lifecycle race
        # regression.  It deliberately executes while _lock is held.
        try:
            self._before_worker_start_locked()
            thread.start()
        except Exception:
            if self._thread is thread:
                self._thread = None
                self._started = False
            raise
        self._started = True

    def _before_worker_start_locked(self) -> None:
        """Private no-op seam used to prove admission/start atomicity."""

    def _enqueue_drain_sentinel_locked(self) -> None:
        if self._drain_sentinel_enqueued:
            return
        try:
            self._queue.put_nowait(_DRAIN_SENTINEL)
        except queue.Full as error:  # pragma: no cover - reserved control slot
            raise RuntimeError("stream persistence drain control slot was lost") from error
        self._drain_sentinel_enqueued = True

    def _rollback_start_failure_locked(
        self, *, task: StreamStorageTask, estimate: int
    ) -> None:
        """Undo the just-enqueued task after its worker could not start.

        Queue removal is safe here because submit() still owns the lifecycle
        lock and _start_worker_locked() failed before a worker could consume
        this task.  Queue's own mutex keeps its unfinished-task accounting
        consistent with the removal.
        """
        removed = False
        with self._queue.mutex:
            try:
                self._queue.queue.remove(task)
            except ValueError:
                pass
            else:
                removed = True
                self._queue.unfinished_tasks = max(0, self._queue.unfinished_tasks - 1)
                if self._queue.unfinished_tasks == 0:
                    self._queue.all_tasks_done.notify_all()
                self._queue.not_full.notify()
        if removed:
            self._pending_bytes = max(0, self._pending_bytes - estimate)
        self._outstanding_tasks.pop(id(task), None)
        self._shutdown_timeout_task_ids.discard(id(task))
        self._submitted = max(0, self._submitted - 1)

    def _mark_shutdown_timeout_incomplete(self) -> None:
        """Report a timed-out drain without extending its caller's budget.

        A worker can be stalled while it owns the shared file-backend
        transaction lock.  Marker persistence uses that lock too, so doing it
        synchronously after ``Thread.join(timeout=...)`` would make the public
        timeout a lie.  Live state is notified now; a separate daemon performs
        the best-effort durable invalidation once the lock becomes available.
        """
        with self._lock:
            # The worker may still finish after this marker is written.  The
            # marker is intentionally irreversible for the session, so a
            # later stale compact snapshot cannot misrepresent the gap.
            outstanding = tuple(
                task
                for task_id, task in self._outstanding_tasks.items()
                if task_id not in self._shutdown_timeout_task_ids
            )
            self._shutdown_timeout_task_ids.update(id(task) for task in outstanding)
        if not outstanding:
            return
        for task in outstanding:
            _notify(
                task,
                success=False,
                error="stream persistence shutdown drain timed out",
            )
            schedule_stream_persistence_incomplete(
                view_id=task.view_id,
                session_id=task.session_id,
                reason="stream persistence shutdown drain timed out",
            )

    def _process_task(self, task: StreamStorageTask) -> None:
        storage_policy = _stream_storage_policy(task.view_id)
        backend = FileStreamStorageBackend(root_dir=config.get_storage_root_dir())
        raw_enabled = config.get_storage_stream_raw_enabled(task.view_id)
        raw_policy = (
            RawBlockPolicy(
                max_blocks=config.get_storage_stream_raw_max_blocks(task.view_id),
                max_bytes=config.get_storage_stream_raw_max_bytes(task.view_id),
                max_age_s=config.get_storage_stream_raw_max_age_s(task.view_id),
            )
            if raw_enabled
            else None
        )
        backend.enforce_view_retention(
            view_id=task.view_id,
            policy=storage_policy,
            raw_policy=raw_policy,
        )
        if raw_enabled and task.raw_records:
            assert task.raw_block_id is not None
            backend.write_raw_block(
                view_id=task.view_id,
                session_id=task.session_id,
                block_id=task.raw_block_id,
                records=task.raw_records,
                raw_policy=raw_policy,
                storage_policy=storage_policy,
            )

        metadata = deepcopy(task.metadata)
        history = metadata.get("durable_history")
        history_dict = dict(history) if isinstance(history, Mapping) else {}
        previously_incomplete = history_dict.get("state") == "incomplete"
        history_dict.update(
            {
                "state": "incomplete" if previously_incomplete else "complete",
                "persistence_enabled": True,
                "raw_persistence": "enabled" if raw_enabled else "disabled",
            }
        )
        metadata["durable_history"] = history_dict
        backend.write_compact_session(
            view_id=task.view_id,
            session_id=task.session_id,
            client_id=task.client_id,
            metadata=metadata,
            summary_windows=task.summary_windows,
            noteworthy_items=task.noteworthy_items,
            policy=storage_policy,
        )


def _notify(task: StreamStorageTask, *, success: bool, error: str | None) -> None:
    try:
        task.on_complete(success, error)
    except Exception:
        # A visibility callback must never kill the worker and prevent later
        # stream observations from reaching storage.
        pass


class StreamPersistenceGapMarkerScheduler:
    """Bounded, coalescing asynchronous persistence-gap writer.

    Marker writes intentionally share the file backend's transaction lock. A
    rejected live request must not wait behind that lock, but allowing one
    daemon per rejection would make storage trouble create unbounded threads.
    This scheduler keeps at most one marker attempt per session and one worker
    thread. A marker is irreversible, so repeated failures for an in-flight or
    pending session coalesce without weakening durable completeness.
    """

    def __init__(self, *, max_pending: int | None = None) -> None:
        self._configured_max_pending = max_pending
        self._pending: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._inflight: set[tuple[str, str]] = set()
        self._thread: threading.Thread | None = None
        self._scheduled = 0
        self._coalesced = 0
        self._rejected = 0
        self._start_failures = 0
        self._worker_starts = 0
        self._lock = threading.RLock()

    def schedule(self, *, view_id: str, session_id: str, reason: str) -> bool:
        """Queue one best-effort marker without ever raising to transport code."""
        key = (view_id, session_id)
        with self._lock:
            self._scheduled += 1
            if key in self._pending:
                self._pending[key] = reason
                self._coalesced += 1
                return True
            if key in self._inflight:
                self._coalesced += 1
                return True
            if len(self._pending) + len(self._inflight) >= self._max_pending:
                self._rejected += 1
                return False
            self._pending[key] = reason
            if self._thread is not None:
                return True
            thread = threading.Thread(
                target=self._run,
                name="plotsrv-stream-storage-gap-marker",
                daemon=True,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception:
                if self._thread is thread:
                    self._thread = None
                self._pending.pop(key, None)
                self._start_failures += 1
                return False
            self._worker_starts += 1
            return True

    @property
    def _max_pending(self) -> int:
        configured = self._configured_max_pending
        if configured is None:
            configured = config.get_storage_stream_max_pending_tasks()
        return max(1, int(configured))

    def stats(self) -> dict[str, int | bool]:
        """Expose bounded scheduler state for diagnostics and regressions."""
        with self._lock:
            return {
                "pending": len(self._pending),
                "inflight": len(self._inflight),
                "max_pending": self._max_pending,
                "scheduled": self._scheduled,
                "coalesced": self._coalesced,
                "rejected": self._rejected,
                "start_failures": self._start_failures,
                "worker_starts": self._worker_starts,
                "running": bool(self._thread is not None and self._thread.is_alive()),
            }

    def _run(self) -> None:
        current = threading.current_thread()
        while True:
            with self._lock:
                if not self._pending:
                    if self._thread is current:
                        self._thread = None
                    return
                (view_id, session_id), reason = self._pending.popitem(last=False)
                key = (view_id, session_id)
                self._inflight.add(key)
            try:
                _mark_stream_persistence_incomplete(
                    view_id=view_id,
                    session_id=session_id,
                    reason=reason,
                )
            finally:
                with self._lock:
                    self._inflight.discard(key)


_GAP_MARKER_SCHEDULER = StreamPersistenceGapMarkerScheduler()


def mark_stream_persistence_incomplete(
    *, view_id: str, session_id: str, reason: str
) -> None:
    """Best-effort durable gap marker shared by admission and worker failures."""
    _mark_stream_persistence_incomplete(
        view_id=view_id,
        session_id=session_id,
        reason=reason,
    )


def schedule_stream_persistence_incomplete(
    *, view_id: str, session_id: str, reason: str
) -> bool:
    """Schedule a durable gap without making an accepted request await I/O.

    The live registry has already recorded the failure before this function is
    called. Marker writes share the backend transaction lock with compact
    storage, so request-side callers must not wait behind a slow disk write.
    A single bounded scheduler coalesces repeated gaps instead of allocating a
    daemon thread for every rejected submission.
    """
    try:
        return _GAP_MARKER_SCHEDULER.schedule(
            view_id=view_id,
            session_id=session_id,
            reason=reason,
        )
    except Exception:
        # Scheduling is strictly best effort. The caller has already made the
        # live durable-history state incomplete and must never fail a protocol
        # request because even marker-thread construction is unavailable.
        return False


def _mark_stream_persistence_incomplete(
    *, view_id: str, session_id: str, reason: str
) -> None:
    try:
        if not config.get_storage_stream_enabled(view_id):
            return
        FileStreamStorageBackend(
            root_dir=config.get_storage_root_dir()
        ).mark_session_incomplete(
            view_id=view_id,
            session_id=session_id,
            reason=reason,
            policy=_stream_storage_policy(view_id),
        )
    except Exception:
        # The live registry still exposes the failure. If the storage root is
        # unavailable there is no safe way to promise durable failure state.
        pass


def _stream_storage_policy(view_id: str) -> StreamStoragePolicy:
    """Resolve the same bounded compact policy for writes and gap markers."""
    return StreamStoragePolicy(
        summary_retention=config.get_storage_stream_summary_retention(view_id),
        noteworthy_keep_last=config.get_storage_stream_noteworthy_keep_last(view_id),
        keep_last_sessions=config.get_storage_stream_keep_last_sessions(view_id),
        max_bytes_per_view=config.get_storage_stream_max_bytes_per_view(view_id),
    )


def _estimate_stream_task_bytes(
    *,
    metadata: Mapping[str, Any],
    summary_windows: Sequence[Mapping[str, Any]],
    noteworthy_items: Sequence[Mapping[str, Any]],
    raw_block_id: str | None,
    raw_records: Sequence[Mapping[str, Any]],
) -> int:
    """Use exact JSON encoding so the separate queue has a real byte bound."""
    payload = {
        "metadata": metadata,
        "summary_windows": summary_windows,
        "noteworthy_items": noteworthy_items,
        "raw_block_id": raw_block_id,
        "raw_records": raw_records,
    }
    return max(
        1,
        len(
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ),
    )


_WORKER: StreamStorageWorker | None = None
_WORKER_LOCK = threading.Lock()


def get_stream_storage_worker() -> StreamStorageWorker:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = StreamStorageWorker()
        return _WORKER


def open_stream_storage_admission() -> bool:
    """Open stream persistence only at an explicit server lifecycle boundary."""
    return get_stream_storage_worker().open_admission()


def stop_stream_storage_worker(*, join: bool = False, timeout: float = 5.0) -> None:
    get_stream_storage_worker().stop(join=join, timeout=timeout)


def get_stream_storage_queue_stats() -> dict[str, Any]:
    return get_stream_storage_worker().stats()
