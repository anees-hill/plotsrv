"""Best-effort publisher-process upload guard for non-loopback streams.

The budget covers estimated stream POST bytes (JSON body plus a conservative
per-request envelope) and counts attempts, including failed deliveries. It is
not a network-interface quota: TLS, retransmissions, capability handshakes,
other plotsrv features, and other processes are outside this counter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import ipaddress
import json
import threading
from urllib.parse import urlsplit
from weakref import WeakSet

from ..publishing.models import PublishTarget


REQUEST_ENVELOPE_BYTES = 1024
CONTROL_RESERVE_BYTES_PER_STREAM = 16 * 1024 * 1024


class RemoteUploadHeld(RuntimeError):
    """A retained batch must wait for the next UTC budget day."""

    def __init__(self, retry_after_s: float) -> None:
        super().__init__("remote stream upload budget reached; delivery is held until the next UTC day")
        self.retry_after_s = retry_after_s


def target_is_loopback(target: PublishTarget) -> bool:
    """Exempt only provable same-machine destinations, never a remote guess."""
    hostname = urlsplit(target.url_for("/")).hostname
    if not hostname:
        return False
    if hostname.rstrip(".").lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class RemoteUploadBudget:
    """One lock-protected UTC-day counter shared by stream clients in a process."""

    def __init__(self, maximum: int) -> None:
        if maximum < 1:
            raise ValueError("remote upload maximum must be positive")
        self.maximum = maximum
        self._day = datetime.now(UTC).date()
        self._used = 0
        self._clients: WeakSet[object] = WeakSet()
        self._lock = threading.Lock()

    def register(self, client: object) -> None:
        with self._lock:
            self._clients.add(client)

    def unregister(self, client: object) -> None:
        with self._lock:
            self._clients.discard(client)

    def reserve(self, payload: dict[str, object], *, append: bool) -> None:
        size = len(
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        ) + REQUEST_ENVELOPE_BYTES
        with self._lock:
            now = datetime.now(UTC)
            if now.date() != self._day:
                self._day = now.date()
                self._used = 0
            active_count = len(self._clients)
            reserve = min(
                self.maximum - max(1, self.maximum // 10),
                CONTROL_RESERVE_BYTES_PER_STREAM * active_count,
            )
            threshold = self.maximum - reserve if append else self.maximum
            if self._used + size > threshold:
                next_day = datetime.combine(
                    now.date() + timedelta(days=1), datetime.min.time(), UTC
                )
                raise RemoteUploadHeld(max(0.001, (next_day - now).total_seconds()))
            # Debit before sending: a timeout/retry is still a possible upload.
            self._used += size


_BUDGETS: dict[int, RemoteUploadBudget] = {}
_BUDGETS_LOCK = threading.Lock()


def shared_remote_upload_budget(maximum: int) -> RemoteUploadBudget:
    with _BUDGETS_LOCK:
        budget = _BUDGETS.get(maximum)
        if budget is None:
            budget = RemoteUploadBudget(maximum)
            _BUDGETS[maximum] = budget
        return budget
