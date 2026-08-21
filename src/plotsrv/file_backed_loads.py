from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from . import config


class FileBackedLoadBusyError(RuntimeError):
    """Raised when every configured file-backed preview slot is occupied."""


class _FileBackedLoadController:
    """
    Process-wide admission controller for expensive file-backed previews.

    FastAPI runs normal ``def`` endpoints in a thread pool, so a plain global
    counter would race. This controller intentionally has no payload cache: a
    completed request releases all request-only Python objects before another
    client starts materialising a large CSV.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._in_flight = 0
        self._admitted = 0
        self._busy = 0
        self._completed = 0

    def acquire(self) -> _FileBackedLoadLease:
        """Reserve one slot until a caller explicitly releases it."""
        limit = config.get_watch_active_load_max_concurrent()
        timeout_s = config.get_watch_active_load_wait_timeout_s()
        deadline = time.monotonic() + timeout_s

        with self._condition:
            while self._in_flight >= limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._busy += 1
                    raise FileBackedLoadBusyError(
                        "File-backed watch preview is busy. Try again in a moment."
                    )
                self._condition.wait(timeout=remaining)
            self._in_flight += 1
            self._admitted += 1
        return _FileBackedLoadLease(self)

    def _release(self) -> None:
        with self._condition:
            self._in_flight = max(0, self._in_flight - 1)
            self._completed += 1
            self._condition.notify()

    @contextmanager
    def slot(self) -> Iterator[None]:
        lease = self.acquire()
        try:
            yield
        finally:
            lease.release()

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                "active": self._in_flight,
                "max_concurrent": config.get_watch_active_load_max_concurrent(),
                "admitted": self._admitted,
                "busy": self._busy,
                "completed": self._completed,
            }

    def reset_for_tests(self) -> None:
        with self._condition:
            self._in_flight = 0
            self._admitted = 0
            self._busy = 0
            self._completed = 0
            self._condition.notify_all()


class _FileBackedLoadLease:
    """An idempotent admission token for a streamed HTTP response."""

    def __init__(self, controller: _FileBackedLoadController) -> None:
        self._controller = controller
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._controller._release()


_FILE_BACKED_LOADS = _FileBackedLoadController()


@contextmanager
def file_backed_load_slot() -> Iterator[None]:
    """Acquire one bounded file-backed materialisation slot."""
    with _FILE_BACKED_LOADS.slot():
        yield


def acquire_file_backed_load_slot() -> _FileBackedLoadLease:
    """Reserve a file-backed load slot for the life of a streamed response."""
    return _FILE_BACKED_LOADS.acquire()


def get_file_backed_load_stats() -> dict[str, int]:
    """Return small operational counters; no request payload is retained."""
    return _FILE_BACKED_LOADS.stats()
