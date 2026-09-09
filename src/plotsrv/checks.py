"""Bounded server checks on detached scalar jobs; idle workers do not poll."""

from collections import OrderedDict, deque
from dataclasses import dataclass
from fractions import Fraction
import json
import operator
import threading
import time
from uuid import uuid4

from .checks_config import Rule
from .checks_evidence import Budget, Evidence, select, lookup
from .checks_config import scalar

MAX_JOBS = 256
MAX_PENDING_BYTES = 256 * 1024
MAX_EVENTS = 256
MAX_EVENT_BYTES = 256 * 1024
MAX_COUNTER = 2**53 - 1
EVALUATIONS_PER_SECOND = 512
BURST = 256
_OPERATORS = dict(
    eq=operator.eq,
    ne=operator.ne,
    lt=operator.lt,
    le=operator.le,
    gt=operator.gt,
    ge=operator.ge,
)


def comparable(value, threshold):
    if type(value) in (int, float, Fraction) and type(threshold) in (int, float):
        return True
    return type(value) is type(threshold) and type(value) in (str, bool)


def evaluate(rule, evidence):
    if evidence.reason or not comparable(evidence.value, rule.value):
        return "unknown", evidence.reason or "wrong_type"
    return (
        "triggered" if _OPERATORS[rule.op](evidence.value, rule.value) else "ok"
    ), None


def wire_value(value):
    if type(value) is Fraction:
        return dict(
            type="rational",
            numerator=str(value.numerator),
            denominator=value.denominator,
        )
    if type(value) is int and abs(value) > MAX_COUNTER:
        return dict(type="integer", value=str(value))
    return value


@dataclass(frozen=True, slots=True)
class Job:
    token: int
    source: str
    kind: str
    context: dict
    evidence: tuple
    size: int
    gap_epoch: tuple


class CheckEngine:
    def __init__(self, rules=(), *, generation=None, start=True):
        self.rules = tuple(rules)
        self.generation = generation or uuid4().hex
        self.by_source = {}
        for rule in self.rules:
            if rule.enabled:
                self.by_source.setdefault((rule.source, rule.kind), []).append(rule)
        self._condition = threading.Condition()
        self._pending = OrderedDict()
        self._pending_bytes = 0
        self._inflight = None
        self._idle = False
        self._closed = False
        self._thread = None
        self._tokens = float(BURST)
        self._refill = time.monotonic()
        self._latest = {}
        self._loss = {r.id: 0 for r in self.rules}
        self._lost = {r.id: 0 for r in self.rules}
        self._states = {
            r.id: dict(
                id=r.id,
                name=r.name,
                source=r.source,
                kind=r.kind,
                severity=r.severity,
                state="unknown" if r.enabled else "disabled",
                reason="awaiting_live_data" if r.enabled else "disabled",
                initialized=False,
                observed_value=None,
                evidence_scope=r.scope or "supplied_value",
                unit=r.unit,
                threshold=wire_value(r.value),
                op=r.op,
                notify=list(r.notify),
                token=0,
                input=r.input,
                path=list(r.path),
                metric=r.metric,
                selection_path=list(r.selection_path),
                loss_epoch=0,
                context=None,
            )
            for r in self.rules
        }
        self._events = deque()
        self._event_bytes = 0
        self._dirty = set()
        self._next_notice = 0.0
        self._cursor = 0
        self._coalesced = 0
        self._failed = 0
        if start and self.by_source:
            self.start()

    def start(self):
        with self._condition:
            if not self._closed and self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="plotsrv-checks", daemon=True
                )
                self._thread.start()
                if not self._pending:
                    self._condition.wait_for(
                        lambda: self._idle or self._closed, timeout=0.5
                    )

    def _gap(self, rules, token, count=1):
        # Sticky monotonic evidence gaps can be recorded even if admission cannot
        # obtain the queue lock. Counters are bounded best-effort diagnostics;
        # the per-rule token fences stale state regardless of counter precision.
        for rule in rules:
            self._loss[rule.id] = max(token, self._loss[rule.id])
            self._lost[rule.id] = min(MAX_COUNTER, self._lost[rule.id] + count)
            self._dirty.add(rule.source)

    def submit(self, source, kind, records, *, stream_context=None):
        """records is an existing bounded accepted batch, never retained here.

        Each item is (source_value, compact_receipt_context). Extraction and
        admission share fixed work/rate/byte limits; failures never escape hooks.
        """
        rules = self.by_source.get((source, kind))
        if not rules:
            return
        token = time.monotonic_ns()
        if not self._condition.acquire(False):
            self._gap(rules, token, len(records))
            return
        try:
            now = time.monotonic()
            self._tokens = min(
                BURST, self._tokens + (now - self._refill) * EVALUATIONS_PER_SECOND
            )
            self._refill = now
            deadline = time.thread_time() + 0.002
            budget = Budget(deadline=deadline)
            for position in range(len(records)):
                token = time.monotonic_ns()
                if (
                    self._closed
                    or self._tokens < len(rules)
                    or time.thread_time() >= deadline
                    or budget.remaining < 0
                ):
                    self._gap(rules, token, len(records) - position)
                    break
                key = ("state", source) if kind == "state" else ("event", object())
                old = self._pending.pop(key, None)
                if old is not None:
                    self._pending_bytes -= old.size
                    self._coalesced = min(MAX_COUNTER, self._coalesced + 1)
                    self._gap(rules, token)
                # Charge before capture, including the one in-flight job.
                reserve = 8192
                if (
                    len(self._pending) + bool(self._inflight) >= MAX_JOBS
                    or self._pending_bytes + reserve > MAX_PENDING_BYTES
                ):
                    self._gap(rules, token, len(records) - position)
                    break
                self._tokens -= len(rules)
                if stream_context is None:
                    value, context = records[position]
                else:
                    row = records[position]
                    value = row.data
                    context = dict(
                        stream_context,
                        source_revision=row.browser_sequence,
                        received_at=row.observed_at.isoformat(),
                        batch_position=position,
                    )
                evidence = tuple((rule, select(rule, value, budget)) for rule in rules)
                for rule, item in evidence:
                    if item.reason == "selection_budget":
                        self._gap([rule], token)
                context = dict(context)
                try:
                    if kind == "event":
                        event_time = lookup(value, ("timestamp",), budget)
                        if type(event_time) not in (str, int, float):
                            event_time = lookup(
                                value, ("event", "source_timestamp"), budget
                            )
                        context["source_time"] = scalar(event_time)
                        context["source_time_origin"] = "publisher_supplied"
                    elif any(rule.input == "observation" for rule in rules):
                        context["captured_at_unix_s"] = scalar(
                            lookup(value, ("captured_at_unix_s",), budget)
                        )
                except ValueError:
                    pass
                job = Job(
                    token,
                    source,
                    kind,
                    dict(context),
                    evidence,
                    reserve,
                    tuple(self._loss[r.id] for r in rules),
                )
                if kind == "state":
                    self._latest[source] = token
                self._pending[key] = job
                self._pending_bytes += reserve
            self._idle = False
            self._condition.notify()
        finally:
            self._condition.release()

    def _event(self, rule, event_type, state, job, evidence):
        if self._cursor >= MAX_COUNTER:
            self._gap([rule], time.monotonic_ns())
            return
        self._cursor = min(MAX_COUNTER, self._cursor + 1)
        event = dict(
            version=1,
            generation=self.generation,
            cursor=self._cursor,
            event_id=f"{self.generation}:{self._cursor}",
            check_id=rule.id,
            view_id=rule.source,
            kind=rule.kind,
            event_type=event_type,
            state=state,
            severity=rule.severity,
            context=job.context,
            observed_value=wire_value(evidence.value),
            threshold=wire_value(rule.value),
            evidence_scope=evidence.scope,
            unit=evidence.unit,
            inspected=evidence.inspected,
            not_inspected=evidence.not_inspected,
        )
        payload = json.dumps(
            event, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode()
        while self._events and (
            len(self._events) >= MAX_EVENTS
            or self._event_bytes + len(payload) > MAX_EVENT_BYTES
        ):
            self._event_bytes -= len(self._events.popleft())
        if len(payload) <= MAX_EVENT_BYTES:
            self._events.append(payload)
            self._event_bytes += len(payload)

    def _process(self, job):
        results = [
            (rule, evidence, *evaluate(rule, evidence))
            for rule, evidence in job.evidence
        ]
        with self._condition:
            if self._closed:
                return
            if job.kind == "state" and self._latest.get(job.source) != job.token:
                self._coalesced = min(MAX_COUNTER, self._coalesced + 1)
                return
            for index, (rule, evidence, result, reason) in enumerate(results):
                old = self._states[rule.id]
                # A later dropped state cannot be overwritten by older work.
                if job.kind == "state" and self._loss[rule.id] > job.token:
                    continue
                prior_state = (
                    old["state"]
                    if old["loss_epoch"] == job.gap_epoch[index]
                    else "unknown"
                )
                event_type = None
                if rule.kind == "event":
                    if result == "triggered":
                        event_type = "match"
                    result = "ok" if result != "unknown" else "unknown"
                elif old["initialized"] and result != prior_state:
                    if result == "triggered":
                        event_type = "triggered"
                    elif result == "ok":
                        event_type = (
                            "recovered" if prior_state == "triggered" else "available"
                        )
                    else:
                        event_type = "unavailable"
                if event_type:
                    self._event(rule, event_type, result, job, evidence)
                old.update(
                    state=result,
                    reason=reason,
                    initialized=True,
                    observed_value=wire_value(evidence.value),
                    evidence_scope=evidence.scope,
                    unit=evidence.unit,
                    inspected=evidence.inspected,
                    not_inspected=evidence.not_inspected,
                    token=job.token,
                    loss_epoch=job.gap_epoch[index],
                    context=job.context,
                )

    def _run(self):
        while True:
            notices, job = (), None
            with self._condition:
                while True:
                    if self._closed:
                        return
                    now = time.monotonic()
                    if self._dirty and now >= self._next_notice:
                        notices = tuple(self._dirty)
                        self._dirty.clear()
                        self._next_notice = now + 0.25
                        break
                    if self._pending:
                        _, job = self._pending.popitem(last=False)
                        self._inflight = job
                        break
                    # One trailing status notice while active; no idle polling.
                    self._idle = not self._dirty
                    self._condition.notify_all()
                    self._condition.wait(
                        max(0, self._next_notice - now) if self._dirty else None
                    )
            if notices:
                try:
                    from .browser_updates import browser_update_hub

                    for source in notices:
                        browser_update_hub.publish(
                            view_id=source,
                            change_type="checks",
                            metadata={"checks_generation": self.generation},
                        )
                except Exception:
                    self._failed = min(MAX_COUNTER, self._failed + 1)
                finally:
                    with self._condition:
                        self._condition.notify_all()
                continue
            try:
                self._process(job)
            except Exception:
                self._failed = min(MAX_COUNTER, self._failed + 1)
                self._gap([r for r, _ in job.evidence], time.monotonic_ns())
            finally:
                with self._condition:
                    self._pending_bytes -= job.size
                    self._inflight = None
                    self._dirty.add(job.source)
                    self._condition.notify_all()
            del job

    def flush(self, timeout=0.5):
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            if self._dirty:
                self._condition.notify()
            while (
                self._pending
                or self._inflight
                or self._dirty
                or (self._thread and not self._idle and not self._closed)
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, timeout=0.5):
        with self._condition:
            self._closed = True
            for job in self._pending.values():
                self._gap([r for r, _ in job.evidence], time.monotonic_ns())
            self._pending.clear()
            self._dirty.clear()
            self._pending_bytes = self._inflight.size if self._inflight else 0
            self._condition.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(max(0, timeout))
        return not thread or not thread.is_alive()

    def snapshot(self, source=None, *, after=0, generation=None, include_events=True):
        with self._condition:
            if self._dirty:
                self._condition.notify()
            states = []
            for rule in self.rules:
                if source is not None and rule.source != source:
                    continue
                state = dict(self._states[rule.id])
                state.pop("initialized")
                last_token = state.pop("token")
                state.pop("loss_epoch")
                state["coverage_lost"] = self._lost[rule.id]
                if rule.enabled and self._loss[rule.id] > last_token:
                    state.update(state="unknown", reason="coverage_gap")
                states.append(state)
            # Copy only bounded immutable event bytes under the worker lock.
            first_payload = self._events[0] if self._events else None
            payloads = tuple(self._events) if include_events else ()
            result = dict(
                version=1,
                generation=self.generation,
                cursor=self._cursor,
                states=states,
                queued=len(self._pending),
                pending_bytes=self._pending_bytes,
                coalesced=self._coalesced,
                failures=self._failed,
                closed=self._closed,
            )
        result["states"] = json.loads(json.dumps(states, allow_nan=False))
        events = [json.loads(payload) for payload in payloads]
        first = json.loads(first_payload)["cursor"] if first_payload else result["cursor"] + 1
        reset = generation is not None and generation != self.generation
        result.update(
            events=[
                e
                for e in events
                if (reset or e["cursor"] > after)
                and (source is None or e["view_id"] == source)
            ],
            history_gap=reset or after < first - 1,
            oldest_cursor=first,
        )
        return result


_ENGINE = None


def configure(rules, generation):
    global _ENGINE
    if _ENGINE is not None and not _ENGINE.close():
        raise ValueError("previous check worker is still stopping")
    _ENGINE = CheckEngine(rules, generation=generation)


def shutdown(timeout=0.5):
    if _ENGINE is not None:
        _ENGINE.close(timeout)


def reset():
    global _ENGINE
    if _ENGINE is not None and _ENGINE.close():
        _ENGINE = None


def current():
    return _ENGINE


def accept_state(view_id, value, *, revision, received_at, supported=True):
    engine = _ENGINE
    if engine is None or (view_id, "state") not in engine.by_source:
        return
    try:
        engine.submit(
            view_id,
            "state",
            [
                (
                    value if supported else None,
                    dict(source_revision=revision, received_at=received_at),
                )
            ],
        )
    except Exception:
        engine._gap(engine.by_source[(view_id, "state")], time.monotonic_ns())


def accept_events(view_id, records, *, session, batch_id, batch_sequence):
    engine = _ENGINE
    if engine is None or (view_id, "event") not in engine.by_source:
        return
    try:
        engine.submit(
            view_id,
            "event",
            records,
            stream_context=dict(
                session_id=session, batch_id=batch_id, batch_sequence=batch_sequence
            ),
        )
    except Exception:
        engine._gap(
            engine.by_source[(view_id, "event")], time.monotonic_ns(), len(records)
        )
