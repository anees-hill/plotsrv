"""Bounded, in-memory state for the dedicated live stream protocol."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import threading
import time
from collections.abc import Callable
from typing import Any

from .. import store
from .models import (
    MAX_STREAM_RECORD_BYTES,
    StreamAppend,
    StreamBatchValidationError,
    StreamClose,
    StreamHeartbeat,
    StreamRecordValidationError,
    StreamRegistration,
    SourceHealth,
    SourceStatus,
    stream_batch_fingerprint,
    stream_record_size,
    validate_stream_batch,
)


MAX_RECENT_STREAM_RECORDS = 200
MAX_RECENT_STREAM_COLUMNS = 200
DEFAULT_HEARTBEAT_TIMEOUT_S = 3.0

LIVE = "live"
RETRYING = "retrying"
ENDED = "ended"
DISCONNECTED = "disconnected"
INCOMPLETE = "incomplete"
_ACTIVE_LIFECYCLES = frozenset((LIVE, RETRYING))


class StreamStateError(ValueError):
    """A client-visible stream-protocol state error."""


class UnknownStreamError(StreamStateError):
    """An append or data request named no registered logical stream."""


class StreamConflictError(StreamStateError):
    """A session or ordered batch conflicts with current stream state."""


@dataclass(frozen=True, slots=True)
class StreamRow:
    """One bounded server record with a server-owned browser sequence."""

    browser_sequence: int
    data: dict[str, Any]
    observed_at: datetime


@dataclass(slots=True)
class StreamViewState:
    registration: StreamRegistration
    records: deque[StreamRow] = field(
        default_factory=lambda: deque(maxlen=MAX_RECENT_STREAM_RECORDS)
    )
    columns: list[str] = field(default_factory=list)
    schema_revision: int = 0
    next_batch_sequence: int = 0
    next_browser_sequence: int = 1
    accepted_records: int = 0
    accepted_batches: int = 0
    duplicate_batches: int = 0
    last_batch_id: str | None = None
    last_batch_fingerprint: str | None = None
    last_batch_record_count: int = 0
    lifecycle: str = LIVE
    last_heartbeat_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_monotonic: float = 0.0
    pending_delivery: bool = False
    explicitly_closed: bool = False
    source_status: SourceStatus = field(default_factory=SourceStatus)
    source_health: SourceHealth = field(default_factory=SourceHealth)


@dataclass(frozen=True, slots=True)
class StreamAppendResult:
    view_id: str
    batch_sequence: int
    accepted_records: int
    duplicate: bool
    next_batch_sequence: int


@dataclass(frozen=True, slots=True)
class StreamLifecycleResult:
    """The accepted server lifecycle state for one producer control message."""

    view_id: str
    lifecycle: str


class StreamRegistry:
    """Registry of logical streams with bounded raw rows and schema metadata."""

    def __init__(
        self,
        *,
        max_recent_records: int = MAX_RECENT_STREAM_RECORDS,
        max_recent_columns: int = MAX_RECENT_STREAM_COLUMNS,
        heartbeat_timeout_s: float = DEFAULT_HEARTBEAT_TIMEOUT_S,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_recent_records < 1:
            raise ValueError("max_recent_records must be at least one")
        if max_recent_columns < 1:
            raise ValueError("max_recent_columns must be at least one")
        if heartbeat_timeout_s <= 0:
            raise ValueError("heartbeat_timeout_s must be greater than zero")
        self.max_recent_records = int(max_recent_records)
        self.max_recent_columns = int(max_recent_columns)
        self.heartbeat_timeout_s = float(heartbeat_timeout_s)
        self._monotonic_clock = monotonic_clock
        self._streams: dict[str, StreamViewState] = {}
        self._lock = threading.RLock()

    def register(self, registration: StreamRegistration) -> StreamViewState:
        """Register a logical view, idempotently for its current session."""
        with self._lock:
            now_monotonic = self._monotonic_clock()
            current = self._streams.get(registration.view_id)
            if current is not None:
                self._expire_state_if_needed(current, now_monotonic)
                if current.registration == registration:
                    self._record_source_status(current, registration.source_status)
                    self._record_source_health(current, registration.source_health)
                    return current
                if (
                    current.registration.client_id == registration.client_id
                    and current.registration.session_id == registration.session_id
                ):
                    raise StreamConflictError(
                        "same-session registration must retain its original "
                        "stream metadata"
                    )
                if current.lifecycle in _ACTIVE_LIFECYCLES:
                    raise StreamConflictError(
                        "a different active producer session already owns this "
                        "stream view"
                    )

            # Do this only after checking the in-memory owner.  In particular,
            # a same-session retry must not mutate label/section metadata, and
            # a competing session must not get a chance to mutate it before
            # its conflict is reported.
            try:
                store.register_view(
                    view_id=registration.view_id,
                    label=registration.label,
                    section=registration.section,
                    kind="stream",
                    icon_key="table",
                )
            except store.ViewOwnershipError as error:
                raise StreamConflictError(str(error)) from error

            state = StreamViewState(
                registration=registration,
                records=deque(maxlen=self.max_recent_records),
                last_heartbeat_monotonic=now_monotonic,
                source_status=registration.source_status,
                source_health=registration.source_health,
            )
            self._streams[registration.view_id] = state

        # The reservation above only creates logical view/menu metadata;
        # stream rows remain isolated from store.set_table(), publish(),
        # storage, and PublishWorker.
        return state

    def append(self, append: StreamAppend) -> StreamAppendResult:
        """Append a single ordered batch, retaining only the recent raw window."""
        with self._lock:
            state = self._streams.get(append.view_id)
            if state is None:
                raise UnknownStreamError("stream view has not been registered")
            self._expire_state_if_needed(state, self._monotonic_clock())
            if state.registration.client_id != append.client_id:
                raise StreamConflictError(
                    "append client does not own this stream view"
                )
            if state.registration.session_id != append.session_id:
                raise StreamConflictError(
                    "append session does not own this stream view"
                )
            if state.explicitly_closed:
                raise StreamConflictError(
                    f"append session has already closed as {state.lifecycle}"
                )
            self._record_source_status(state, append.source_status)
            self._record_source_health(state, append.source_health)

            # Validate the complete batch before mutating sequence or retained
            # state so one non-serializable record cannot leave a partial
            # append behind or poison the browser data response.
            try:
                validate_stream_batch(append.records)
            except (StreamBatchValidationError, StreamRecordValidationError) as error:
                raise StreamStateError(str(error)) from error

            batch_fingerprint = stream_batch_fingerprint(append.records)
            if (
                append.batch_sequence == state.next_batch_sequence - 1
                and append.batch_id == state.last_batch_id
            ):
                if batch_fingerprint != state.last_batch_fingerprint:
                    raise StreamConflictError(
                        "idempotent batch retry does not match the accepted batch"
                    )
                state.duplicate_batches += 1
                self._record_activity(state, lifecycle=LIVE, pending_delivery=False)
                return StreamAppendResult(
                    view_id=append.view_id,
                    batch_sequence=append.batch_sequence,
                    accepted_records=state.last_batch_record_count,
                    duplicate=True,
                    next_batch_sequence=state.next_batch_sequence,
                )

            if append.batch_sequence != state.next_batch_sequence:
                raise StreamConflictError(
                    "append batch sequence does not match the next expected sequence"
                )

            for data in append.records:
                # The route gives JSON-native dictionaries. Copy them before
                # retention so registry state cannot be mutated by the caller.
                row = StreamRow(
                    browser_sequence=state.next_browser_sequence,
                    data=deepcopy(data),
                    observed_at=datetime.now(UTC),
                )
                state.records.append(row)
                state.next_browser_sequence += 1
                state.accepted_records += 1

            # Keep schema metadata tied to the retained row window. This
            # means columns whose last row is evicted disappear, and the
            # explicit cap prevents one current record from growing browser
            # column definitions without bound.
            columns = self._recent_columns(state.records)
            if columns != state.columns:
                state.columns = columns
                state.schema_revision += 1

            state.last_batch_id = append.batch_id
            state.last_batch_fingerprint = batch_fingerprint
            state.last_batch_record_count = len(append.records)
            state.accepted_batches += 1
            state.next_batch_sequence += 1
            self._record_activity(state, lifecycle=LIVE, pending_delivery=False)
            return StreamAppendResult(
                view_id=append.view_id,
                batch_sequence=append.batch_sequence,
                accepted_records=len(append.records),
                duplicate=False,
                next_batch_sequence=state.next_batch_sequence,
            )

    def heartbeat(self, heartbeat: StreamHeartbeat) -> StreamLifecycleResult:
        """Accept one truthful producer liveness observation for a session."""
        if heartbeat.delivery_state not in _ACTIVE_LIFECYCLES:
            raise StreamStateError(
                "stream heartbeat delivery_state must be 'live' or 'retrying'"
            )
        with self._lock:
            state = self._owned_state(
                view_id=heartbeat.view_id,
                client_id=heartbeat.client_id,
                session_id=heartbeat.session_id,
            )
            self._expire_state_if_needed(state, self._monotonic_clock())
            if state.explicitly_closed:
                raise StreamConflictError(
                    f"heartbeat session has already closed as {state.lifecycle}"
                )
            self._record_source_status(state, heartbeat.source_status)
            self._record_source_health(state, heartbeat.source_health)
            self._record_activity(
                state,
                lifecycle=heartbeat.delivery_state,
                pending_delivery=heartbeat.pending_delivery,
            )
            return StreamLifecycleResult(
                view_id=heartbeat.view_id,
                lifecycle=state.lifecycle,
            )

    def close(self, close: StreamClose) -> StreamLifecycleResult:
        """Record an explicit bounded-stop outcome without inferring app exit."""
        with self._lock:
            state = self._owned_state(
                view_id=close.view_id,
                client_id=close.client_id,
                session_id=close.session_id,
            )
            if state.explicitly_closed:
                return StreamLifecycleResult(
                    view_id=close.view_id,
                    lifecycle=state.lifecycle,
                )
            self._record_activity(
                state,
                lifecycle=ENDED if close.drain_completed else INCOMPLETE,
                pending_delivery=not close.drain_completed,
            )
            state.explicitly_closed = True
            return StreamLifecycleResult(
                view_id=close.view_id,
                lifecycle=state.lifecycle,
            )

    def expire_stale_sessions(self) -> None:
        """Mark missing observers without asserting a clean producer end."""
        with self._lock:
            now_monotonic = self._monotonic_clock()
            for state in self._streams.values():
                self._expire_state_if_needed(state, now_monotonic)

    def set_heartbeat_timeout_s(self, timeout_s: float) -> None:
        """Update the local expiry window used by this process-wide registry."""
        if timeout_s <= 0:
            raise ValueError("heartbeat timeout must be greater than zero")
        with self._lock:
            self.heartbeat_timeout_s = float(timeout_s)

    def data(
        self,
        *,
        view_id: str,
        after: int | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return a bounded raw window or the records following a valid cursor.

        ``after`` is the last server-owned browser sequence received by the
        caller.  It is valid through the sequence immediately before the
        retained window, so a browser that has seen the evicted predecessor
        can still safely receive the complete current window.  A cursor
        outside that range cannot establish continuity and therefore returns
        the current bounded window with an explicit reset requirement.
        """
        with self._lock:
            state = self._streams.get(view_id)
            if state is None:
                raise UnknownStreamError("stream view has not been registered")
            self._expire_state_if_needed(state, self._monotonic_clock())

            raw_window_rows = list(state.records)
            first_available = (
                raw_window_rows[0].browser_sequence
                if raw_window_rows
                else state.next_browser_sequence
            )
            last_available = state.next_browser_sequence - 1
            reset_required = False
            reset_reason: str | None = None

            if (
                session_id is not None
                and session_id != state.registration.session_id
            ):
                # Browser sequences begin anew for a superseding producer
                # session.  The client identifies its session on every
                # incremental poll so equal sequence numbers cannot be
                # mistaken for a continuous stream.
                reset_required = True
                reset_reason = "session_changed"
                rows = raw_window_rows
            elif after is None:
                # Retain the old optional-limit behaviour for initial loads:
                # it selects the newest requested portion of the raw window.
                rows = raw_window_rows
                if limit is not None:
                    rows = rows[-limit:]
            elif after < first_available - 1:
                reset_required = True
                reset_reason = "cursor_aged_out"
                rows = raw_window_rows
            elif after > last_available:
                # A cursor beyond the current session's sequence is also not
                # safe to treat as a no-op: it may be from a replaced server
                # or session, so make the required table replacement explicit.
                reset_required = True
                reset_reason = "cursor_ahead_of_window"
                rows = raw_window_rows
            else:
                rows = [
                    row for row in raw_window_rows if row.browser_sequence > after
                ]
                # An after-cursor limit must keep the oldest new records;
                # taking the tail would silently skip the omitted middle.
                if limit is not None:
                    rows = rows[:limit]

            returned_record_bytes = sum(stream_record_size(row.data) for row in rows)

            return {
                "view_id": view_id,
                "label": state.registration.label,
                "section": state.registration.section,
                "client_id": state.registration.client_id,
                "session_id": state.registration.session_id,
                **self._status_dict(state),
                "columns": list(state.columns),
                "schema_revision": state.schema_revision,
                "records": [
                    {
                        "browser_sequence": row.browser_sequence,
                        "data": deepcopy(row.data),
                        "observed_at": row.observed_at.isoformat(),
                    }
                    for row in rows
                ],
                "accepted_records": state.accepted_records,
                "accepted_batches": state.accepted_batches,
                "duplicate_batches": state.duplicate_batches,
                "returned_records": len(rows),
                "returned_record_bytes": returned_record_bytes,
                "max_returned_records": self.max_recent_records,
                "max_returned_record_bytes": (
                    self.max_recent_records * MAX_STREAM_RECORD_BYTES
                ),
                "first_available_browser_sequence": first_available,
                "last_available_browser_sequence": last_available,
                "next_browser_sequence": state.next_browser_sequence,
                "next_batch_sequence": state.next_batch_sequence,
                "requested_after_browser_sequence": after,
                "reset_required": reset_required,
                "reset_reason": reset_reason,
                "raw_window": {
                    "first_browser_sequence": first_available,
                    "last_browser_sequence": last_available,
                    "record_count": len(raw_window_rows),
                    "max_record_count": self.max_recent_records,
                },
            }

    def status(self, *, view_id: str) -> dict[str, Any]:
        """Return the current transport observation without application claims."""
        with self._lock:
            state = self._streams.get(view_id)
            if state is None:
                raise UnknownStreamError("stream view has not been registered")
            self._expire_state_if_needed(state, self._monotonic_clock())
            return {
                "view_id": view_id,
                "client_id": state.registration.client_id,
                "session_id": state.registration.session_id,
                **self._status_dict(state),
            }

    def clear(self) -> None:
        """Clear stream state for process-local tests and controlled shutdowns."""
        with self._lock:
            self._streams.clear()

    def _recent_columns(self, records: deque[StreamRow]) -> list[str]:
        """Return first-seen fields from current records within the schema cap."""
        columns: list[str] = []
        seen: set[str] = set()
        for row in records:
            for field in row.data:
                if field in seen:
                    continue
                columns.append(field)
                seen.add(field)
                if len(columns) >= self.max_recent_columns:
                    return columns
        return columns

    def _owned_state(
        self,
        *,
        view_id: str,
        client_id: str,
        session_id: str,
    ) -> StreamViewState:
        state = self._streams.get(view_id)
        if state is None:
            raise UnknownStreamError("stream view has not been registered")
        if state.registration.client_id != client_id:
            raise StreamConflictError("stream client does not own this stream view")
        if state.registration.session_id != session_id:
            raise StreamConflictError("stream session does not own this stream view")
        return state

    @staticmethod
    def _status_dict(state: StreamViewState) -> dict[str, Any]:
        return {
            "lifecycle": state.lifecycle,
            "last_heartbeat_at": state.last_heartbeat_at.isoformat(),
            "pending_delivery": state.pending_delivery,
            "source_available": state.source_status.source_available,
            "source_transition": state.source_status.source_transition,
            "continuity_warning": state.source_status.continuity_warning,
            "source_health": state.source_health.as_dict(),
        }

    @staticmethod
    def _record_source_status(state: StreamViewState, status: SourceStatus) -> None:
        state.source_status = status

    @staticmethod
    def _record_source_health(state: StreamViewState, health: SourceHealth) -> None:
        state.source_health = health

    def _record_activity(
        self,
        state: StreamViewState,
        *,
        lifecycle: str,
        pending_delivery: bool,
    ) -> None:
        state.lifecycle = lifecycle
        state.pending_delivery = pending_delivery
        state.last_heartbeat_monotonic = self._monotonic_clock()
        state.last_heartbeat_at = datetime.now(UTC)

    def _expire_state_if_needed(
        self, state: StreamViewState, now_monotonic: float
    ) -> None:
        if state.lifecycle not in _ACTIVE_LIFECYCLES:
            return
        if now_monotonic - state.last_heartbeat_monotonic < self.heartbeat_timeout_s:
            return
        state.lifecycle = INCOMPLETE if state.pending_delivery else DISCONNECTED


stream_registry = StreamRegistry()
