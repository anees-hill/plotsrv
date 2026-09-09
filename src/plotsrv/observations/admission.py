"""One bounded in-process capture mailbox, without threads, timers or callbacks."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
import threading
import time

from .models import CaptureOptions, ObservationBudget, ObservationRoute, ObservationWork


@dataclass(slots=True)
class _Reservation:
    token: int
    view_id: str
    key: str | tuple[str, str]
    state: str = "capturing"


class CaptureEngine:
    """Reserve count/bytes before inspection, including in-flight work.

    The hot path never waits on a lock. Close requests are also checked when
    every lock owner exits, so abandoned bytes do not require another submit.
    Use get_capture_engine() for the single process-local instance; inherited
    direct instances reject work after fork rather than touching orphaned locks.
    """

    def __init__(self, budget: ObservationBudget = ObservationBudget()):
        if type(budget) is not ObservationBudget:
            raise ValueError("invalid observation budget")
        from . import adapters  # noqa: F401 -- initialization, not the hot path

        self.budget = budget
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._counts = dict(
            submitted=0,
            accepted=0,
            skipped=0,
            coalesced=0,
            dropped=0,
            processed=0,
            failed=0,
        )
        self._paused: OrderedDict[str, float] = OrderedDict()
        self._reservations: dict[int, _Reservation] = {}
        self._pending: OrderedDict[int, ObservationWork] = OrderedDict()
        self._views: OrderedDict[str | tuple[str, str], float] = OrderedDict()
        # Only IDs, never sources. FIFO retry priority prevents stable call order
        # from starving later views. A caller yields once to an absent head, then
        # may use spare tokens; an inactive view cannot block a live one forever.
        self._waiting: OrderedDict[str | tuple[str, str], None] = OrderedDict()
        self._yielded: set[str | tuple[str, str]] = set()
        self._burst = min(
            4, budget.max_pending, budget.max_pending_bytes // budget.max_output_bytes
        )
        self._tokens = float(self._burst)
        self._refilled_at = time.monotonic()
        self._next_token = 0
        self._closed = False

    def _reap(self) -> None:
        if self._closed:
            # Release payloads even if later bookkeeping allocation fails.
            self._count("dropped", len(self._pending))
            self._pending.clear()
            self._condition.notify_all()
        for token, reservation in tuple(self._reservations.items()):
            if reservation.state == "cancelled" or (
                self._closed and reservation.state == "pending"
            ):
                self._pending.pop(token, None)
                del self._reservations[token]
                self._condition.notify_all()
        if self._closed:
            self._waiting.clear()
            self._yielded.clear()

    def _release(self) -> None:
        self._lock.release()
        # Check AFTER release: close either acquires the free lock itself, or
        # its flag is seen by this owner (or the next contending owner) on exit.
        if self._closed and self._lock.acquire(blocking=False):
            try:
                self._reap()
            except Exception:
                pass  # Best effort even under allocation failure.
            finally:
                self._lock.release()

    def _admit_cadence(self, view_id: str, now: float) -> bool:
        self._tokens = min(
            self._burst,
            self._tokens
            + max(0.0, now - self._refilled_at) / self.budget.process_interval_s,
        )
        self._refilled_at = now
        if self._tokens < 1:
            self._waiting.setdefault(view_id, None)
            return False
        if self._waiting:
            head = next(iter(self._waiting))
            if view_id != head and view_id not in self._yielded:
                self._waiting.setdefault(view_id, None)
                self._yielded.add(view_id)
                return False
            if view_id == head:
                self._yielded.clear()
        self._waiting.pop(view_id, None)
        self._yielded.discard(view_id)
        self._tokens -= 1
        return True

    def _count(self, name: str, amount: int = 1) -> None:
        # Bounded, best-effort counters; telemetry cannot wait on pipeline locks.
        try:
            self._counts[name] = min(2**53 - 1, self._counts[name] + amount)
        except Exception:
            pass

    def submit(self, view_id, source, options=CaptureOptions(), *, route=None):
        self._count("submitted")
        outcome = self._submit(view_id, source, options, route=route)
        self._count("accepted" if outcome == "accepted" else "skipped")
        return outcome

    def _submit(
        self,
        view_id: str,
        source: object,
        options: CaptureOptions = CaptureOptions(),
        *,
        route: ObservationRoute | None = None,
    ) -> str:
        reservation = None
        try:
            if self._pid != os.getpid():
                return "forked_instance"
            if type(view_id) is not str or not 0 < len(view_id) <= 512:
                return "invalid_identity"
            if type(options) is not CaptureOptions or (
                route is not None and type(route) is not ObservationRoute
            ):
                return "invalid_options"
            key = view_id if route is None else (route.target_key, view_id)
            if not self._lock.acquire(blocking=False):
                return "busy"
            try:
                self._reap()
                if self._closed:
                    return "closed"
                now = time.monotonic()
                if route is not None and now < self._paused.get(key[0], 0.0):
                    return "target_paused"
                if now < self._views.get(key, 0.0):
                    return "view_cadence"
                if any(r.state == "capturing" for r in self._reservations.values()):
                    return "capture_busy"
                existing = next(
                    (r for r in self._reservations.values() if r.key == key), None
                )
                if existing is not None and (
                    route is None or existing.state != "pending"
                ):
                    return "view_pending"
                if existing is None and (
                    len(self._reservations) >= self.budget.max_pending
                    or (len(self._reservations) + 1) * self.budget.max_output_bytes
                    > self.budget.max_pending_bytes
                ):
                    return "overloaded"
                if key not in self._views:
                    if len(self._views) >= self.budget.max_view_ids:
                        oldest, expiry = next(iter(self._views.items()))
                        if now < expiry:
                            return "identity_capacity"
                        del self._views[oldest]
                        self._waiting.pop(oldest, None)
                        self._yielded.discard(oldest)
                    # Existing bounded IDs were validated at admission. Avoid
                    # rescanning long strings on every skipped hot-path call.
                    if any(0xD800 <= ord(c) <= 0xDFFF for c in view_id):
                        return "invalid_identity"
                    self._views[key] = 0.0
                if not self._admit_cadence(key, now):
                    return "process_cadence"
                self._next_token = (self._next_token + 1) % (2**63)
                if existing is None:
                    reservation = _Reservation(self._next_token, view_id, key)
                    self._reservations[reservation.token] = reservation
                else:
                    reservation = existing
                    reservation.state = "capturing"
                    self._pending.pop(reservation.token)
                    self._count("coalesced")
                    self._count("dropped")
                self._views.move_to_end(key)
                self._views[key] = now + self.budget.view_interval_s
            finally:
                self._release()

            from .capture import capture_detached

            envelope = capture_detached(
                source, view_id=view_id, budget=self.budget, options=options
            )
            if not self._lock.acquire(blocking=False):
                return "busy"
            try:
                if self._closed:
                    return "closed"
                # Change state only after both allocations succeed. Any failure
                # leaves a capturing reservation for the finally rollback.
                work = (
                    ObservationWork(reservation.token, view_id, envelope)
                    if route is None
                    else ObservationWork(reservation.token, view_id, envelope, route)
                )
                self._pending[reservation.token] = work
                reservation.state = "pending"
                self._condition.notify_all()
                return "accepted"
            finally:
                self._release()
        except Exception:
            return "capture_failed"
        finally:
            if reservation is not None and reservation.state == "capturing":
                reservation.state = "cancelled"
                if self._lock.acquire(blocking=False):
                    try:
                        self._reap()
                    except Exception:
                        pass
                    finally:
                        self._release()

    def take(self) -> ObservationWork | None:
        if self._pid != os.getpid() or not self._lock.acquire(blocking=False):
            return None
        try:
            self._reap()
            if not self._pending:
                return None
            token, work = self._pending.popitem(last=False)
            self._reservations[token].state = "in_flight"
            return work
        finally:
            self._release()

    def finish(self, token: int) -> bool:
        if (
            self._pid != os.getpid()
            or type(token) is not int
            or not self._lock.acquire(blocking=False)
        ):
            return False
        try:
            self._reap()
            reservation = self._reservations.get(token)
            if reservation is None or reservation.state != "in_flight":
                return False
            del self._reservations[token]
            self._condition.notify_all()
            return True
        finally:
            self._release()

    def wait_take(self) -> ObservationWork | None:
        """Consumer only: sleep until work or closure; no idle polling."""
        if self._pid != os.getpid():
            return None
        self._lock.acquire()
        try:
            while not self._pending and not self._closed:
                self._condition.wait()
            self._reap()
            if self._closed or not self._pending:
                return None
            token, work = self._pending.popitem(last=False)
            self._reservations[token].state = "in_flight"
            return work
        finally:
            self._release()

    def complete(
        self,
        token: int,
        *,
        succeeded: bool,
        pause_target: str | None = None,
        pause_s: float = 0,
    ) -> None:
        """Consumer-only acknowledgement; keep accounting until delivery ends."""
        if self._pid != os.getpid():
            return
        self._lock.acquire()
        try:
            self._reservations.pop(token, None)
            self._count("processed" if succeeded else "failed")
            if pause_target is not None:
                if (
                    len(self._paused) >= self.budget.max_view_ids
                    and pause_target not in self._paused
                ):
                    self._paused.popitem(last=False)
                self._paused[pause_target] = time.monotonic() + pause_s
            self._condition.notify_all()
        finally:
            self._release()

    def flush(self, timeout: float) -> bool:
        if self._pid != os.getpid():
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        if not self._lock.acquire(timeout=max(0.0, timeout)):
            return False
        try:
            while self._reservations:
                self._reap()
                if not self._reservations:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True
        finally:
            self._release()

    def close(self) -> None:
        if self._pid != os.getpid():
            return
        self._closed = True
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._reap()
        finally:
            self._release()

    def reopen(self) -> bool:
        if self._pid != os.getpid() or not self._lock.acquire(blocking=False):
            return False
        try:
            self._reap()
            if self._reservations:
                return False
            self._closed = False
            return True
        finally:
            self._release()

    def stats(self) -> dict:
        if self._pid != os.getpid():
            return {"closed": True, "reason": "forked_instance"}
        self._lock.acquire()
        try:
            self._reap()
            return {
                "pending": len(self._pending),
                "reserved": len(self._reservations),
                "reserved_bytes": len(self._reservations)
                * self.budget.max_output_bytes,
                "view_ids": len(self._views),
                "waiting_ids": len(self._waiting),
                "closed": self._closed,
                "counters": dict(self._counts),
                "counters_best_effort": True,
            }
        finally:
            self._release()


_ENGINE: CaptureEngine | None = None
_ENGINE_LOCK = threading.Lock()


def _after_fork() -> None:
    global _ENGINE, _ENGINE_LOCK
    _ENGINE = None
    _ENGINE_LOCK = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def get_capture_engine() -> CaptureEngine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from ..config import get_observation_budget

            _ENGINE = CaptureEngine(get_observation_budget())
        return _ENGINE
