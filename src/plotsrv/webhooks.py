"""Optional, bounded, server-side POST delivery. No durable outbox or publisher work."""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from .http_transport import open_http

MAX_ITEMS = 64
MAX_BYTES = 256 * 1024
MAX_PAYLOAD = 8 * 1024
MAX_COUNTER = 2**53 - 1
REQUEST_TIMEOUT = 2.0
MAX_ATTEMPTS = 3
MAX_AGE = 60.0
PERMANENT_PAUSE = 300.0
MIN_SPACING = 0.2


def stamp():
    return datetime.now(timezone.utc).isoformat()


def increment(row, key, amount=1):
    row[key] = min(MAX_COUNTER, row.get(key, 0) + amount)


@dataclass(frozen=True, slots=True)
class Outcome:
    category: str
    status: int | None = None
    retryable: bool = False
    retry_after: float = 0


def retry_after(value):
    if not value or len(value) > 64:
        return 0
    try:
        if value.isdecimal():
            return min(30, int(value))
        return max(0, min(30, parsedate_to_datetime(value).timestamp() - time.time()))
    except (ValueError, TypeError, OverflowError):
        return 0


def post(destination, payload, event_id):
    """Read headers only, under a 16 KiB wire-read cap; discard response bodies."""
    headers = dict(destination.headers)
    headers.update(
        {
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
            "Idempotency-Key": event_id,
            "X-Plotsrv-Event-Id": event_id,
        }
    )
    try:
        request = urllib.request.Request(
            destination.url, data=payload, headers=headers, method="POST"
        )
        with open_http(
            request,
            timeout=REQUEST_TIMEOUT,
            use_environment_proxy=False,
            read_limit=16 * 1024,
        ) as response:
            code = response.status
        return (
            Outcome("delivered", code)
            if 200 <= code < 300
            else Outcome("http_permanent", code)
        )
    except urllib.error.HTTPError as error:
        code = error.code
        hint = retry_after(error.headers.get("Retry-After"))
        error.close()
        retryable = code in (408, 425, 429) or 500 <= code < 600
        return Outcome(
            (
                "redirect_refused"
                if 300 <= code < 400
                else "http_retryable" if retryable else "http_permanent"
            ),
            code,
            retryable,
            hint,
        )
    except Exception as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        if isinstance(reason, ssl.SSLError):
            return Outcome("tls_failure")
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return Outcome("timeout", retryable=True)
        if isinstance(reason, (ValueError, UnicodeError)):
            return Outcome("response_or_configuration_limit")
        return Outcome("network_unavailable", retryable=True)


def encode(rule, event, suppressed, dashboard):
    context = event.get("context") or {}
    body = dict(
        version=1,
        event_id=event["event_id"],
        generation=event["generation"],
        cursor=event["cursor"],
        view_id=rule.source,
        check_id=rule.id,
        check_name=rule.name,
        kind=rule.kind,
        event_type=event["event_type"],
        severity=event["severity"],
        previous_state=event["previous_state"],
        current_state=event["state"],
        received_at=context.get("received_at"),
        source_time=context.get("source_time"),
        source_time_origin=context.get("source_time_origin"),
        captured_at_unix_s=context.get("captured_at_unix_s"),
        observed_value=event["observed_value"],
        condition=dict(op=rule.op, threshold=event["threshold"]),
        evidence_scope=event["evidence_scope"],
        unit=event["unit"],
        coverage=dict(
            inspected=event["inspected"],
            not_inspected=event["not_inspected"],
            lost=event["coverage_lost"],
        ),
        suppressed_since_previous=suppressed,
    )
    if dashboard:
        body["dashboard_url"] = dashboard + "?view=" + quote(rule.source, safe="")
    payload = json.dumps(
        body, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode()
    if len(payload) > MAX_PAYLOAD:
        return None
    return payload


@dataclass(slots=True)
class Delivery:
    pair: tuple
    body: bytes
    event_id: str
    created: float
    due: float
    attempts: int = 0


class WebhookDispatcher:
    def __init__(self, config, rules, *, on_change=None, sender=post):
        self.destinations = {d.name: d for d in config.destinations}
        self.config = config
        self.pairs = {(r.id, name): r for r in rules if r.enabled for name in r.notify}
        if any(name not in self.destinations for _, name in self.pairs):
            raise ValueError("unresolved webhook destination")
        self._condition = threading.Condition()
        self._queue = []
        self._bytes = 0
        self._inflight = None
        self._accepting = True
        self._stop = False
        self._thread = None
        self._sender = sender
        self._on_change = on_change
        self._last_cursor = {p: 0 for p in self.pairs}
        self._cooldown = {p: 0.0 for p in self.pairs}
        self._suppressed = {p: 0 for p in self.pairs}
        self._next_destination = {name: 0.0 for name in self.destinations}
        self._paused = {name: 0.0 for name in self.destinations}
        self._next_send = 0.0
        self._diagnostics = {
            p: dict(
                destination=p[1],
                state="idle",
                delivered=0,
                suppressed=0,
                dropped=0,
                duplicates=0,
                failures=0,
                last_failure=None,
                last_event_id=None,
                last_status=None,
                last_attempt_at=None,
                attempts=0,
            )
            for p in self.pairs
        }
        if self.pairs:
            self._thread = threading.Thread(
                target=self._run, name="plotsrv-webhooks", daemon=True
            )
            self._thread.start()

    def submit(self, rule, event):
        # Called by the checks worker, never ingestion. Contention drops, not waits.
        if not self._condition.acquire(blocking=False):
            for name in rule.notify:
                row = self._diagnostics.get((rule.id, name))
                if row is not None:
                    increment(row, "dropped")
            return
        try:
            now = time.monotonic()
            for name in rule.notify:
                pair = (rule.id, name)
                if pair not in self.pairs:
                    continue
                row = self._diagnostics[pair]
                if event["cursor"] <= self._last_cursor[pair]:
                    increment(row, "duplicates")
                    continue
                self._last_cursor[pair] = event["cursor"]
                if not self._accepting or now < self._paused[name]:
                    row["state"] = "paused" if self._accepting else "closed"
                    increment(row, "dropped")
                    continue
                if rule.kind == "event" and now < self._cooldown[pair]:
                    increment(row, "suppressed")
                    self._suppressed[pair] = min(
                        MAX_COUNTER, self._suppressed[pair] + 1
                    )
                    continue
                if (
                    len(self._queue) >= MAX_ITEMS
                    or self._bytes + MAX_PAYLOAD > MAX_BYTES
                ):
                    increment(row, "dropped")
                    continue
                body = encode(
                    rule, event, self._suppressed[pair], self.config.dashboard_url
                )
                if body is None or self._bytes + len(body) > MAX_BYTES:
                    increment(row, "dropped")
                    row["last_failure"] = "payload_limit"
                    continue
                self._queue.append(Delivery(pair, body, event["event_id"], now, now))
                self._bytes += len(body)
                self._cooldown[pair] = now + self.config.event_cooldown_s
                self._suppressed[pair] = 0
                row["state"] = "queued"
            self._condition.notify_all()
        except Exception:
            # No record, secret or URL in diagnostics and no exception back to checks.
            for name in rule.notify:
                row = self._diagnostics.get((rule.id, name))
                if row is not None:
                    increment(row, "dropped")
                    row["last_failure"] = "preparation_failed"
        finally:
            self._condition.release()

    def _remove(self, job):
        self._queue.remove(job)
        self._bytes -= len(job.body)

    def _run(self):
        while True:
            with self._condition:
                while True:
                    if self._stop:
                        return
                    now = time.monotonic()
                    selected, earliest, pairs = None, None, set()
                    for job in list(self._queue):
                        row = self._diagnostics[job.pair]
                        if now - job.created >= MAX_AGE:
                            increment(row, "dropped")
                            row.update(state="dropped", last_failure="expired")
                            self._remove(job)
                            continue
                        if job.pair in pairs:
                            continue
                        pairs.add(job.pair)
                        due = max(
                            job.due,
                            self._next_destination[job.pair[1]],
                            self._next_send,
                        )
                        if due <= now:
                            selected = job
                            break
                        earliest = min(earliest or due, due, job.created + MAX_AGE)
                    if selected is not None:
                        break
                    self._condition.notify_all()
                    self._condition.wait(
                        max(0, earliest - now) if earliest is not None else None
                    )
                self._inflight = job = selected
                job.attempts += 1
                row = self._diagnostics[job.pair]
                row.update(
                    state="delivering",
                    last_event_id=job.event_id,
                    last_attempt_at=stamp(),
                    attempts=job.attempts,
                )
            # All socket/DNS/HTTP work is outside both checks and dispatcher locks.
            try:
                result = self._sender(
                    self.destinations[job.pair[1]], job.body, job.event_id
                )
            except Exception:
                result = Outcome("delivery_failed", retryable=True)
            with self._condition:
                now = time.monotonic()
                name = job.pair[1]
                row = self._diagnostics[job.pair]
                row["last_status"] = result.status
                self._next_send = now + MIN_SPACING
                self._next_destination[name] = now + MIN_SPACING
                if result.category == "delivered":
                    increment(row, "delivered")
                    row.update(state="delivered", last_failure=None)
                    self._remove(job)
                else:
                    increment(row, "failures")
                    row.update(state="failed", last_failure=result.category)
                    if result.retryable:
                        delay = max(min(2 ** (job.attempts - 1), 4), result.retry_after)
                        self._next_destination[name] = now + delay
                        if job.attempts < MAX_ATTEMPTS and not self._stop:
                            job.due = now + delay
                            row["state"] = "retrying"
                        else:
                            self._remove(job)
                    else:
                        self._paused[name] = now + PERMANENT_PAUSE
                        for pending in list(self._queue):
                            if pending.pair[1] == name:
                                if pending is not job:
                                    increment(
                                        self._diagnostics[pending.pair], "dropped"
                                    )
                                    self._diagnostics[pending.pair]["state"] = "paused"
                                self._remove(pending)
                        row["state"] = "paused"
                self._inflight = None
                self._condition.notify_all()
            if self._on_change:
                try:
                    self._on_change(self.pairs[job.pair].source)
                except Exception:
                    pass
            del job, selected
            pending = None

    def snapshot(self, check_id):
        with self._condition:
            now = time.monotonic()
            return [
                dict(
                    row,
                    queued=sum(j.pair == pair for j in self._queue),
                    paused_for_s=max(0, self._paused[pair[1]] - now),
                )
                for pair, row in self._diagnostics.items()
                if pair[0] == check_id
            ]

    def flush(self, timeout=0.5):
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            while self._queue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def close(self, timeout=0.5):
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            self._accepting = False
            # Release the bound engine callback, including when native DNS stalls.
            self._on_change = None
            self._condition.notify_all()
        # Reserve a small part of the caller's budget for the worker to exit
        # after dropping work whose retry cannot finish during the drain.
        exit_budget = min(0.05, max(0, timeout) * 0.2)
        self.flush(max(0, deadline - time.monotonic() - exit_budget))
        with self._condition:
            self._stop = True
            for job in list(self._queue):
                if job is not self._inflight:
                    increment(self._diagnostics[job.pair], "dropped")
                    self._diagnostics[job.pair].update(
                        state="dropped", last_failure="shutdown"
                    )
                    self._remove(job)
            self._condition.notify_all()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(max(0, deadline - time.monotonic()))
        return not self._thread or not self._thread.is_alive()
