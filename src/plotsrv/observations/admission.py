"""One bounded in-process capture mailbox, without threads, timers or callbacks."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
import time

from .models import CaptureOptions, ObservationBudget, ObservationWork


@dataclass(slots=True)
class _Reservation:
    token: int
    view_id: str
    state: str = "capturing"
    cancelled: bool = False


class CaptureEngine:
    """Reserve downstream count/bytes before looking at the source.

    Reservations include capture, pending and in-flight work. The future worker
    must finish its lease after summary/delivery, not merely when dequeuing it.
    The publisher hot path never waits for this lock. Contended cancellation
    is reaped at the next operation; it holds only a tiny reservation, no source.
    One engine (get_capture_engine) owns the process-wide budget.
    """

    def __init__(self, budget: ObservationBudget = ObservationBudget()):
        if type(budget) is not ObservationBudget:
            raise ValueError("invalid observation budget")
        # Initialize adapters here, outside the per-call capture boundary.
        from . import adapters  # noqa: F401

        self.budget = budget
        self._lock = threading.Lock()
        self._reservations: dict[int, _Reservation] = {}
        self._pending: OrderedDict[int, ObservationWork] = OrderedDict()
        self._views: OrderedDict[str, float] = OrderedDict()
        self._next_process = 0.0
        self._next_token = 0
        self._closed = False

    def _reap(self) -> None:
        for token, reservation in tuple(self._reservations.items()):
            if reservation.state == "cancelled" or (
                self._closed and reservation.state == "pending"
            ):
                self._pending.pop(token, None)
                del self._reservations[token]

    def submit(
        self, view_id: str, source: object, options: CaptureOptions = CaptureOptions()
    ) -> str:
        """Return a fixed outcome code; failed admission never inspects source."""
        if (
            type(view_id) is not str
            or not 0 < len(view_id) <= 512
            or any(0xD800 <= ord(c) <= 0xDFFF for c in view_id)
        ):
            return "invalid_identity"
        if type(options) is not CaptureOptions:
            return "invalid_options"
        if not self._lock.acquire(blocking=False):
            return "busy"
        reservation = None
        try:
            self._reap()
            if self._closed:
                return "closed"
            now = time.monotonic()
            if now < self._next_process:
                return "process_cadence"
            if now < self._views.get(view_id, 0.0):
                return "view_cadence"
            if any(r.state == "capturing" for r in self._reservations.values()):
                return "capture_busy"
            if any(r.view_id == view_id for r in self._reservations.values()):
                return "view_pending"
            if (
                len(self._reservations) >= self.budget.max_pending
                or (len(self._reservations) + 1) * self.budget.max_output_bytes
                > self.budget.max_pending_bytes
            ):
                return "overloaded"
            if (
                view_id not in self._views
                and len(self._views) >= self.budget.max_view_ids
            ):
                oldest, expiry = next(iter(self._views.items()))
                if now < expiry:
                    return "identity_capacity"
                del self._views[oldest]
            self._next_token = (self._next_token + 1) % (2**63)
            reservation = _Reservation(self._next_token, view_id)
            self._reservations[reservation.token] = reservation
            self._next_process = now + self.budget.process_interval_s
            self._views.pop(view_id, None)
            self._views[view_id] = now + self.budget.view_interval_s
        finally:
            self._lock.release()
        try:
            from .capture import capture_detached

            envelope = capture_detached(
                source, view_id=view_id, budget=self.budget, options=options
            )
            if not self._lock.acquire(blocking=False):
                return "busy"
            try:
                if self._closed or reservation.cancelled:
                    return "closed"
                reservation.state = "pending"
                self._pending[reservation.token] = ObservationWork(
                    reservation.token, view_id, envelope
                )
                return "accepted"
            finally:
                self._lock.release()
        except Exception:
            return "capture_failed"
        finally:
            if reservation.state == "capturing":
                reservation.cancelled = True
                reservation.state = "cancelled"
                if self._lock.acquire(blocking=False):
                    try:
                        self._reap()
                    finally:
                        self._lock.release()

    def take(self) -> ObservationWork | None:
        if not self._lock.acquire(blocking=False):
            return None
        try:
            self._reap()
            if not self._pending:
                return None
            token, work = self._pending.popitem(last=False)
            self._reservations[token].state = "in_flight"
            return work
        finally:
            self._lock.release()

    def finish(self, token: int) -> bool:
        if type(token) is not int or not self._lock.acquire(blocking=False):
            return False
        try:
            self._reap()
            reservation = self._reservations.get(token)
            if reservation is None or reservation.state != "in_flight":
                return False
            del self._reservations[token]
            return True
        finally:
            self._lock.release()

    def close(self) -> None:
        self._closed = True
        if not self._lock.acquire(blocking=False):
            return
        try:
            for reservation in self._reservations.values():
                if reservation.state != "in_flight":
                    reservation.cancelled = True
            self._reap()
        finally:
            self._lock.release()

    def reopen(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._reap()
            if self._reservations:
                return False
            self._closed = False
            return True
        finally:
            self._lock.release()

    def stats(self) -> dict:
        with self._lock:
            self._reap()
            return {
                "pending": len(self._pending),
                "reserved": len(self._reservations),
                "reserved_bytes": len(self._reservations)
                * self.budget.max_output_bytes,
                "view_ids": len(self._views),
                "closed": self._closed,
            }


_ENGINE: CaptureEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_capture_engine() -> CaptureEngine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from ..config import get_observation_budget

            _ENGINE = CaptureEngine(get_observation_budget())
        return _ENGINE
