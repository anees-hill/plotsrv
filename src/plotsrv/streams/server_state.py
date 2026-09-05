"""Bounded, in-memory state for the dedicated live stream protocol."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import math
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .. import store
from .models import (
    StreamAppend,
    StreamBatchValidationError,
    StreamClose,
    StreamHeartbeat,
    StreamRecordValidationError,
    StreamRegistration,
    SourceHealth,
    SourceStatus,
    StreamRecord,
    StreamSchema,
    RECOGNIZED_SEVERITIES,
    normalize_checkpoint_identifier,
    recognize_structured_severity,
    stream_batch_fingerprint,
    stream_record_size,
    validate_source_health,
    validate_source_status,
    validate_stream_batch,
    validate_stream_record,
)
from .summaries import SummaryLimits, SummaryWindow


MAX_RECENT_STREAM_RECORDS = 200
MAX_RECENT_STREAM_BYTES = 8 * 1024 * 1024
MAX_RECENT_STREAM_COLUMNS = 200
DEFAULT_FINE_WINDOW_S = 60
DEFAULT_MAX_FINE_SUMMARY_WINDOWS = 32
DEFAULT_MAX_COARSE_SUMMARY_WINDOWS = 24
DEFAULT_COARSE_WINDOW_FACTOR = 60
DEFAULT_MAX_SUMMARY_FIELDS = 64
DEFAULT_MAX_CATEGORICAL_VALUES = 16
DEFAULT_MAX_CATEGORICAL_VALUE_BYTES = 128
DEFAULT_MAX_NOTEWORTHY_ITEMS = 64
DEFAULT_HEARTBEAT_TIMEOUT_S = 3.0
_OBSERVATION_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Automatic non-severity retention remains deliberately narrow.  These are
# conventional top-level categorical fields that are normally low-cardinality;
# arbitrary IDs, prose, nested values, and field names merely resembling these
# names never qualify.  The per-field value cap is the existing configured
# categorical bound, so this state remains small independently of raw rows.
NOTEWORTHY_LOW_CARDINALITY_FIELDS = frozenset(
    ("level", "severity", "status", "state", "kind", "event", "type")
)
# Numeric extrema are only useful when the source has made the unit or measure
# clear in the field name.  Keep this fixed rather than trying to infer metrics
# from arbitrary numeric values such as IDs or timestamps.
NOTEWORTHY_NUMERIC_EXTREMUM_FIELDS = frozenset(
    (
        "duration",
        "duration_ms",
        "elapsed_ms",
        "latency",
        "latency_ms",
        "size_bytes",
        "payload_bytes",
        "request_bytes",
        "response_bytes",
        "count",
        "rate",
        "temperature",
    )
)

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


class RetiredStreamSessionError(StreamConflictError):
    """A stored observation cannot be reused as a live transport epoch."""


@dataclass(frozen=True, slots=True)
class RawRetentionPolicy:
    """All hard limits that apply simultaneously to recent source records."""

    max_records: int
    max_bytes: int
    max_age_s: float | None = None

    def __post_init__(self) -> None:
        if self.max_records < 1:
            raise ValueError("max_recent_records must be at least one")
        if self.max_bytes < 1:
            raise ValueError("max_recent_bytes must be at least one")
        if self.max_age_s is not None and self.max_age_s <= 0:
            raise ValueError("max_recent_age_s must be greater than zero")

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "max_record_count": self.max_records,
            "max_record_bytes": self.max_bytes,
            "max_record_age_s": self.max_age_s,
        }


@dataclass(slots=True)
class SessionCounters:
    """Exact per-producer-session counters independent of raw retention.

    Counter values are emitted as decimal strings because a browser's native
    number type cannot safely represent every valid long-running session
    count.  The fixed severity vocabulary keeps both server state and future
    browser checkpoints bounded.
    """

    total_records: int = 0
    recognized_severity_records: int = 0
    recognized_severity_counts: dict[str, int] = field(
        default_factory=lambda: {severity: 0 for severity in RECOGNIZED_SEVERITIES}
    )
    # The built-in JSONL observer increments this only for malformed,
    # oversized, or otherwise invalid completed source records.  A custom
    # producer can report the same protocol fact without revealing source text.
    rejected_source_records: int = 0
    continuity_events: int = 0
    noteworthy_items: int = 0
    noteworthy_source_records: int = 0
    system_notices: int = 0
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    latest_server_sequence: int = 0

    def add_source_record(
        self,
        severity: str | None,
        *,
        observed_at: datetime,
        server_sequence: int,
    ) -> None:
        self.total_records += 1
        if self.first_observed_at is None:
            self.first_observed_at = observed_at
        self.last_observed_at = observed_at
        self.latest_server_sequence = server_sequence
        if severity is None:
            return
        self.recognized_severity_records += 1
        self.recognized_severity_counts[severity] += 1

    def add_rejected_source_records(self, count: int) -> None:
        self.rejected_source_records += count

    def add_noteworthy_item(self, item: NoteworthyItem) -> None:
        self.noteworthy_items += 1
        if isinstance(item, NoteworthySourceRecord):
            self.noteworthy_source_records += 1
            return
        self.system_notices += 1
        if item.event in {"source_continuity_uncertain", "source_continuity_transition"}:
            self.continuity_events += 1

    def as_browser_dict(self) -> dict[str, Any]:
        return {
            "object_type": "stream_session_counters",
            "counter_schema_version": 2,
            "total_records": str(self.total_records),
            "recognized_severity_records": str(self.recognized_severity_records),
            "recognized_severity_counts": {
                severity: str(self.recognized_severity_counts[severity])
                for severity in RECOGNIZED_SEVERITIES
            },
            "rejected_source_records": str(self.rejected_source_records),
            "continuity_events": str(self.continuity_events),
            "noteworthy_items": str(self.noteworthy_items),
            "noteworthy_source_records": str(self.noteworthy_source_records),
            "system_notices": str(self.system_notices),
            "first_observed_at": (
                None if self.first_observed_at is None else self.first_observed_at.isoformat()
            ),
            "last_observed_at": (
                None if self.last_observed_at is None else self.last_observed_at.isoformat()
            ),
            "latest_server_sequence": str(self.latest_server_sequence),
        }


@dataclass(slots=True)
class DurableHistoryState:
    """Truthful best-effort persistence state, separate from live transport."""

    persistence_enabled: bool = False
    pending_writes: int = 0
    completed_writes: int = 0
    rejected_writes: int = 0
    failed_writes: int = 0
    incomplete: bool = False
    last_error: str | None = None
    last_persisted_at: datetime | None = None

    def as_browser_dict(self) -> dict[str, Any]:
        if not self.persistence_enabled:
            state = "disabled"
        elif self.incomplete:
            state = "incomplete"
        elif self.pending_writes:
            state = "pending"
        elif self.completed_writes:
            state = "complete"
        else:
            state = "not_persisted"
        return {
            "state": state,
            "persistence_enabled": self.persistence_enabled,
            "pending_writes": self.pending_writes,
            "completed_writes": self.completed_writes,
            "rejected_writes": self.rejected_writes,
            "failed_writes": self.failed_writes,
            "last_error": self.last_error,
            "last_persisted_at": (
                None
                if self.last_persisted_at is None
                else self.last_persisted_at.isoformat()
            ),
        }


@dataclass(frozen=True, slots=True)
class NoteworthySourceRecord:
    """A retained source row selected by one deterministic noteworthy rule."""

    noteworthy_sequence: int
    record: StreamRecord
    reason: str
    severity: str | None = None
    field_name: str | None = None
    field_value: Any | None = None

    def as_browser_dict(self) -> dict[str, Any]:
        return {
            "object_type": "stream_noteworthy_source_record",
            "kind": "source_record",
            "noteworthy_sequence": str(self.noteworthy_sequence),
            "source_browser_sequence": str(self.record.browser_sequence),
            "observed_at": self.record.observed_at.isoformat(),
            "noteworthy_reason": self.reason,
            "severity": self.severity,
            "field_name": self.field_name,
            "field_value": deepcopy(self.field_value),
            "data": deepcopy(self.record.data),
        }


@dataclass(frozen=True, slots=True)
class SystemNotice:
    """A plotsrv observation, deliberately distinct from a source row."""

    noteworthy_sequence: int
    observed_at: datetime
    event: str
    source_transition: str | None = None
    continuity_warning: str | None = None
    rejected_record_count: int | None = None
    schema_revision: int | None = None

    def as_browser_dict(self) -> dict[str, Any]:
        return {
            "object_type": "stream_system_notice",
            "kind": "system_notice",
            "noteworthy_sequence": str(self.noteworthy_sequence),
            "observed_at": self.observed_at.isoformat(),
            "event": self.event,
            "source_transition": self.source_transition,
            "continuity_warning": self.continuity_warning,
            "rejected_record_count": (
                None
                if self.rejected_record_count is None
                else str(self.rejected_record_count)
            ),
            "schema_revision": self.schema_revision,
        }


NoteworthyItem = NoteworthySourceRecord | SystemNotice


@dataclass(slots=True)
class StreamViewState:
    registration: StreamRegistration
    # This process-local incarnation changes whenever the registry loses and
    # recreates state, even when a producer happens to reuse its own session
    # ID. Browsers must treat that as an unavailable comparison rather than
    # subtracting counters from two different in-memory sessions.
    stream_instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    records: deque[StreamRecord] = field(default_factory=deque)
    raw_record_bytes: int = 0
    schema: StreamSchema = field(default_factory=StreamSchema)
    # The resolution is part of the key so a live configuration change cannot
    # accidentally coalesce windows that have different fixed boundaries.
    fine_windows: dict[tuple[int, datetime], SummaryWindow] = field(
        default_factory=dict
    )
    coarse_windows: dict[tuple[int, datetime], SummaryWindow] = field(
        default_factory=dict
    )
    # A single explicit oldest aggregate gives indefinitely long streams a
    # fixed retained shape after the bounded fixed-resolution tiers fill up.
    historic_summary: SummaryWindow | None = None
    summary_revision: int = 0
    cumulative: SessionCounters = field(default_factory=SessionCounters)
    noteworthy: deque[NoteworthyItem] = field(default_factory=deque)
    noteworthy_revision: int = 0
    next_noteworthy_sequence: int = 1
    last_continuity_notice: tuple[str, str | None] | None = None
    # This is an accounting watermark, deliberately independent of the last
    # browser-visible health payload.  Optional telemetry may be absent for a
    # heartbeat, which must not make a later unchanged cumulative producer
    # value look newly observed.
    last_records_rejected_watermark: int | None = None
    noteworthy_first_values: dict[str, set[str]] = field(default_factory=dict)
    noteworthy_numeric_extrema: dict[str, tuple[int | float, int | float]] = field(
        default_factory=dict
    )
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
    durable_history: DurableHistoryState = field(default_factory=DurableHistoryState)
    # Restored compact history intentionally remains browser-shaped. The
    # storage format is an immutable observational record, not sufficient
    # internal state to resume compaction or one producer transport session.
    restored_compact: bool = False
    restored_summary_windows: tuple[dict[str, Any], ...] = ()
    restored_noteworthy_items: tuple[dict[str, Any], ...] = ()
    # A restored session is browseable history, never a current transport
    # owner.  It may be selected as the default presentation after restart,
    # but a later live registration always replaces that current presentation
    # without deleting the historical record.
    historical: bool = False
    historical_updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class StreamAppendResult:
    view_id: str
    batch_sequence: int
    accepted_records: int
    duplicate: bool
    next_batch_sequence: int
    accepted_raw_records: tuple[StreamRecord, ...] = ()


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
        max_recent_bytes: int = MAX_RECENT_STREAM_BYTES,
        max_recent_age_s: float | None = None,
        max_recent_columns: int = MAX_RECENT_STREAM_COLUMNS,
        fine_window_s: int = DEFAULT_FINE_WINDOW_S,
        max_fine_summary_windows: int = DEFAULT_MAX_FINE_SUMMARY_WINDOWS,
        max_coarse_summary_windows: int = DEFAULT_MAX_COARSE_SUMMARY_WINDOWS,
        coarse_window_factor: int = DEFAULT_COARSE_WINDOW_FACTOR,
        max_summary_fields: int = DEFAULT_MAX_SUMMARY_FIELDS,
        max_categorical_values: int = DEFAULT_MAX_CATEGORICAL_VALUES,
        max_categorical_value_bytes: int = DEFAULT_MAX_CATEGORICAL_VALUE_BYTES,
        max_noteworthy_items: int = DEFAULT_MAX_NOTEWORTHY_ITEMS,
        heartbeat_timeout_s: float = DEFAULT_HEARTBEAT_TIMEOUT_S,
        monotonic_clock: Callable[[], float] = time.monotonic,
        observation_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_recent_columns < 1:
            raise ValueError("max_recent_columns must be at least one")
        if fine_window_s < 1:
            raise ValueError("fine_window_s must be at least one")
        if max_fine_summary_windows < 1:
            raise ValueError("max_fine_summary_windows must be at least one")
        if max_coarse_summary_windows < 1:
            raise ValueError("max_coarse_summary_windows must be at least one")
        if coarse_window_factor < 2:
            raise ValueError("coarse_window_factor must be at least two")
        if max_noteworthy_items < 1:
            raise ValueError("max_noteworthy_items must be at least one")
        if heartbeat_timeout_s <= 0:
            raise ValueError("heartbeat_timeout_s must be greater than zero")
        self.raw_retention = RawRetentionPolicy(
            max_records=int(max_recent_records),
            max_bytes=int(max_recent_bytes),
            max_age_s=max_recent_age_s,
        )
        self.max_recent_columns = int(max_recent_columns)
        self.fine_window_s = int(fine_window_s)
        self.max_fine_summary_windows = int(max_fine_summary_windows)
        self.max_coarse_summary_windows = int(max_coarse_summary_windows)
        self.coarse_window_factor = int(coarse_window_factor)
        self.summary_limits = SummaryLimits(
            max_fields=int(max_summary_fields),
            max_categories_per_field=int(max_categorical_values),
            max_category_value_bytes=int(max_categorical_value_bytes),
        )
        self.max_noteworthy_items = int(max_noteworthy_items)
        self.heartbeat_timeout_s = float(heartbeat_timeout_s)
        self._monotonic_clock = monotonic_clock
        self._observation_clock = observation_clock
        self._streams: dict[str, StreamViewState] = {}
        self._historical_streams: dict[str, dict[str, StreamViewState]] = {}
        self._history_catalogue_revisions: dict[str, int] = {}
        self._lock = threading.RLock()

    @property
    def max_recent_records(self) -> int:
        """Compatibility view of the record component of raw retention."""
        return self.raw_retention.max_records

    @property
    def max_recent_bytes(self) -> int:
        """Maximum canonical bytes retained by any one raw stream window."""
        return self.raw_retention.max_bytes

    @property
    def max_recent_age_s(self) -> float | None:
        """Optional observation-time age limit for recent raw records."""
        return self.raw_retention.max_age_s

    @property
    def max_summary_windows(self) -> int:
        """Fixed maximum count of fine, coarse, and historic summaries."""
        return self.max_fine_summary_windows + self.max_coarse_summary_windows + 1

    def register(self, registration: StreamRegistration) -> StreamViewState:
        """Register a logical view, idempotently for its current session."""
        with self._lock:
            now_monotonic = self._monotonic_clock()
            if registration.session_id in self._historical_streams.get(registration.view_id, {}):
                raise RetiredStreamSessionError("stored stream session requires a new transport epoch")
            current = self._streams.get(registration.view_id)
            if current is not None:
                self._expire_state_if_needed(current, now_monotonic)
                self._enforce_raw_retention(current, self._observed_now())
                if current.registration == registration and not current.historical:
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
                    icon_key="stream",
                )
            except store.ViewOwnershipError as error:
                raise StreamConflictError(str(error)) from error

            state = StreamViewState(
                registration=registration,
                last_heartbeat_monotonic=now_monotonic,
            )
            self._record_source_status(state, registration.source_status)
            self._record_source_health(state, registration.source_health)
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
            self._enforce_raw_retention(state, self._observed_now())
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

            observed_at = self._observed_now()
            accepted_raw_records: list[StreamRecord] = []
            for data in append.records:
                # The route gives JSON-native dictionaries. Copy them before
                # retention so registry state cannot be mutated by the caller.
                row = StreamRecord(
                    browser_sequence=state.next_browser_sequence,
                    data=deepcopy(data),
                    observed_at=observed_at,
                    encoded_bytes=stream_record_size(data),
                )
                state.records.append(row)
                accepted_raw_records.append(row)
                state.raw_record_bytes += row.encoded_bytes
                state.next_browser_sequence += 1
                state.accepted_records += 1
                severity = recognize_structured_severity(row.data)
                state.cumulative.add_source_record(
                    severity,
                    observed_at=row.observed_at,
                    server_sequence=row.browser_sequence,
                )
                if severity is not None:
                    self._retain_noteworthy_source_record(
                        state,
                        row,
                        reason="structured_severity",
                        severity=severity,
                    )
                self._retain_noteworthy_first_appearances(state, row)
                self._retain_noteworthy_numeric_extrema(state, row)
                # Enforce after every accepted record, rather than once at
                # batch end, so a valid 100-record append cannot grow the
                # retained raw window beyond a hard policy in between rows.
                self._enforce_raw_retention(state, observed_at)

            state.last_batch_id = append.batch_id
            state.last_batch_fingerprint = batch_fingerprint
            state.last_batch_record_count = len(append.records)
            state.accepted_batches += 1
            state.next_batch_sequence += 1
            self._record_activity(state, lifecycle=LIVE, pending_delivery=False)
            store.record_data_arrival(
                view_id=append.view_id,
                received_at=observed_at.isoformat(),
                count=len(append.records),
                source="stream",
            )
            return StreamAppendResult(
                view_id=append.view_id,
                batch_sequence=append.batch_sequence,
                accepted_records=len(append.records),
                duplicate=False,
                next_batch_sequence=state.next_batch_sequence,
                accepted_raw_records=tuple(accepted_raw_records),
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
            self._enforce_raw_retention(state, self._observed_now())
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
            self._enforce_raw_retention(state, self._observed_now())
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
                if state.historical:
                    # Persisted rows are a fixed historical representation.
                    # Runtime display limits must not silently mutate them.
                    continue
                self._expire_state_if_needed(state, now_monotonic)
                self._enforce_raw_retention(state, self._observed_now())

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
            if not state.historical:
                self._expire_state_if_needed(state, self._monotonic_clock())
                self._enforce_raw_retention(state, self._observed_now())
            return self._data_for_state(
                state=state,
                view_id=view_id,
                after=after,
                session_id=session_id,
                limit=limit,
            )

    def historical_sessions(self, *, view_id: str) -> list[dict[str, Any]]:
        """List restored sessions for one logical view, newest first.

        The current process-local session is deliberately not included here:
        callers use this collection to select persisted history, not to infer
        that a producer is still live.
        """
        with self._lock:
            states = self._historical_streams.get(view_id)
            if not states:
                if view_id in self._streams:
                    return []
                raise UnknownStreamError("stream history has not been restored")
            sessions = [
                self._historical_session_dict(state)
                for state in states.values()
            ]
            return sorted(
                sessions,
                key=lambda session: (
                    str(session.get("updated_at") or ""),
                    str(session.get("session_id") or ""),
                ),
                reverse=True,
            )

    def current_session_id(self, *, view_id: str) -> str | None:
        """Return the live transport identity, excluding restored fallbacks."""
        with self._lock:
            state = self._streams.get(view_id)
            return (
                None
                if state is None or state.historical
                else state.registration.session_id
            )

    def session_is_current(self, *, view_id: str, session_id: str) -> bool:
        with self._lock:
            state = self._streams.get(view_id)
            return (
                state is not None
                and not state.historical
                and state.registration.session_id == session_id
            )

    def history_catalogue_revision(self, *, view_id: str) -> int:
        with self._lock:
            return self._history_catalogue_revisions.get(view_id, 0)

    def reconcile_historical_sessions(
        self, *, view_id: str, retained_session_ids: set[str]
    ) -> bool:
        """Drop in-memory history which bounded storage no longer exposes."""
        with self._lock:
            states = self._historical_streams.get(view_id)
            if not states:
                return False
            removed = set(states).difference(retained_session_ids)
            for session_id in removed:
                states.pop(session_id, None)
            if not states:
                self._historical_streams.pop(view_id, None)
            current = self._streams.get(view_id)
            if current is not None and current.historical and (
                current.registration.session_id in removed
            ):
                if states:
                    self._streams[view_id] = max(
                        states.values(),
                        key=lambda item: item.historical_updated_at or "",
                    )
                else:
                    self._streams.pop(view_id, None)
            if removed:
                self._history_catalogue_revisions[view_id] = (
                    self._history_catalogue_revisions.get(view_id, 0) + 1
                )
            return bool(removed)

    def historical_data(
        self,
        *,
        view_id: str,
        session_id: str,
        after: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return one restored session without consulting a live owner."""
        with self._lock:
            state = self._historical_streams.get(view_id, {}).get(session_id)
            if state is None:
                raise UnknownStreamError("historical stream session was not found")
            return self._data_for_state(
                state=state,
                view_id=view_id,
                after=after,
                session_id=session_id,
                limit=limit,
            )

    def _data_for_state(
        self,
        *,
        state: StreamViewState,
        view_id: str,
        after: int | None,
        session_id: str | None,
        limit: int | None,
    ) -> dict[str, Any]:
        """Build one browser data payload for a current or historical state."""
        raw_window_rows = list(state.records)
        first_available = (
            raw_window_rows[0].browser_sequence
            if raw_window_rows
            else state.next_browser_sequence
        )
        last_available = state.next_browser_sequence - 1
        reset_required = False
        reset_reason: str | None = None

        if session_id is not None and session_id != state.registration.session_id:
            # Browser sequences begin anew for a superseding producer session.
            # The client identifies its session on every incremental poll so
            # equal sequence numbers cannot be mistaken for continuity.
            reset_required = True
            reset_reason = "session_changed"
            rows = raw_window_rows
        elif after is None:
            # Preserve the established initial-load behaviour: an optional
            # limit selects the newest requested portion of a bounded window.
            rows = raw_window_rows[-limit:] if limit is not None else raw_window_rows
        elif after < first_available - 1:
            reset_required = True
            reset_reason = "cursor_aged_out"
            rows = raw_window_rows
        elif after > last_available:
            # A cursor beyond this session cannot establish safe continuity.
            reset_required = True
            reset_reason = "cursor_ahead_of_window"
            rows = raw_window_rows
        else:
            rows = [row for row in raw_window_rows if row.browser_sequence > after]
            # An after-cursor limit keeps the oldest new rows so it never skips
            # the omitted middle of a session.
            if limit is not None:
                rows = rows[:limit]

        returned_record_bytes = sum(row.encoded_bytes for row in rows)
        return {
            "view_id": view_id,
            "label": state.registration.label,
            "section": state.registration.section,
            "client_id": state.registration.client_id,
            "session_id": state.registration.session_id,
            "stream_instance_id": state.stream_instance_id,
            "historical": state.historical,
            "historical_updated_at": state.historical_updated_at,
            **self._status_dict(state),
            "columns": list(state.schema.columns),
            "schema_revision": state.schema.revision,
            "summary_revision": state.summary_revision,
            "cumulative": state.cumulative.as_browser_dict(),
            "noteworthy": self._noteworthy_browser_dict(state),
            "durable_history": state.durable_history.as_browser_dict(),
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
            "max_returned_record_bytes": self.max_recent_bytes,
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
            "raw_retention": self.raw_retention.as_dict(),
        }

    @staticmethod
    def _historical_session_dict(state: StreamViewState) -> dict[str, Any]:
        """Return intentionally non-live menu metadata for one restored state."""
        return {
            "view_id": state.registration.view_id,
            "session_id": state.registration.session_id,
            "label": state.registration.label,
            "section": state.registration.section,
            "updated_at": state.historical_updated_at,
            "lifecycle": state.lifecycle,
            "historical": True,
            "durable_history": state.durable_history.as_browser_dict(),
            "raw_record_count": len(state.records),
        }

    def summary(self, *, view_id: str) -> dict[str, Any]:
        """Return derived compact history in a shape distinct from raw rows."""
        with self._lock:
            state = self._streams.get(view_id)
            if state is None:
                raise UnknownStreamError("stream view has not been registered")
            if not state.historical:
                self._expire_state_if_needed(state, self._monotonic_clock())
                self._enforce_raw_retention(state, self._observed_now())
            return self._summary_for_state(state=state, view_id=view_id)

    def historical_summary(self, *, view_id: str, session_id: str) -> dict[str, Any]:
        """Return derived compact history for one restored session only."""
        with self._lock:
            state = self._historical_streams.get(view_id, {}).get(session_id)
            if state is None:
                raise UnknownStreamError("historical stream session was not found")
            return self._summary_for_state(state=state, view_id=view_id)

    def _summary_for_state(
        self, *, state: StreamViewState, view_id: str
    ) -> dict[str, Any]:
        windows = self._summary_windows_browser_list(state)
        return {
            "object_type": "derived_stream_summary_collection",
            "derived": True,
            "view_id": view_id,
            "session_id": state.registration.session_id,
            "historical": state.historical,
            "summary_revision": state.summary_revision,
            "summary_window_count": len(windows),
            "summary_retention": {
                "max_fine_windows": self.max_fine_summary_windows,
                "max_coarse_windows": self.max_coarse_summary_windows,
                "max_retained_windows": self.max_summary_windows,
                "coarse_window_factor": self.coarse_window_factor,
                "max_fields_per_window": self.summary_limits.max_fields,
                "max_categories_per_field": (
                    self.summary_limits.max_categories_per_field
                ),
                "max_categorical_value_bytes": (
                    self.summary_limits.max_category_value_bytes
                ),
            },
            "windows": windows,
        }

    def status(self, *, view_id: str) -> dict[str, Any]:
        """Return the current transport observation without application claims."""
        with self._lock:
            state = self._streams.get(view_id)
            if state is None:
                raise UnknownStreamError("stream view has not been registered")
            if not state.historical:
                self._expire_state_if_needed(state, self._monotonic_clock())
                self._enforce_raw_retention(state, self._observed_now())
            return {
                "view_id": view_id,
                "client_id": state.registration.client_id,
                "session_id": state.registration.session_id,
                **self._status_dict(state),
                "durable_history": state.durable_history.as_browser_dict(),
            }

    def browser_update_metadata(self, *, view_id: str) -> dict[str, Any]:
        """Return the small, stable state represented by one browser notice."""
        with self._lock:
            state = self._streams.get(view_id)
            if state is None:
                raise UnknownStreamError("stream view has not been registered")
            if not state.historical:
                self._expire_state_if_needed(state, self._monotonic_clock())
                self._enforce_raw_retention(state, self._observed_now())
            return {
                "kind": "stream",
                "session_id": state.registration.session_id,
                "next_browser_sequence": state.next_browser_sequence,
                "schema_revision": state.schema.revision,
                "summary_revision": state.summary_revision,
                "noteworthy_revision": state.noteworthy_revision,
                "lifecycle": state.lifecycle,
                "pending_delivery": state.pending_delivery,
                "source_status": {
                    "source_available": state.source_status.source_available,
                    "source_transition": state.source_status.source_transition,
                    "continuity_warning": state.source_status.continuity_warning,
                },
                "source_health": state.source_health.as_dict(),
            }

    def set_persistence_enabled(self, *, view_id: str, enabled: bool) -> None:
        """Reflect the master storage setting without changing live state."""
        with self._lock:
            state = self._streams.get(view_id)
            if state is None:
                raise UnknownStreamError("stream view has not been registered")
            state.durable_history.persistence_enabled = bool(enabled)

    def restore_compact_session(
        self,
        *,
        stored_metadata: Mapping[str, Any],
        summary_windows: Sequence[Mapping[str, Any]],
        noteworthy_items: Sequence[Mapping[str, Any]],
        raw_records: Sequence[Mapping[str, Any]] = (),
        history_incomplete_reason: str | None = None,
        replace_existing: bool = False,
    ) -> bool:
        """Restore bounded compact history without reviving a live producer.

        A storage record can describe the last accepted lifecycle as live or
        retrying when a process ended abruptly. On restore it becomes a
        disconnected or incomplete *historical* session, never a new owner of
        a live transport. Explicitly retained raw blocks are accepted only
        after storage-level identity validation and remain historical data.
        """
        try:
            envelope = dict(stored_metadata)
            compact = envelope.get("metadata")
            if not isinstance(compact, Mapping):
                raise ValueError("compact metadata is missing")
            if envelope.get("view_id") != compact.get("view_id") or envelope.get(
                "session_id"
            ) != compact.get("session_id"):
                raise ValueError("compact metadata identity is inconsistent")
            if compact.get("protocol_version") != 4:
                raise ValueError("stream protocol version is unsupported")

            registration = StreamRegistration(
                view_id=normalize_checkpoint_identifier(
                    compact.get("view_id"), "view_id"
                ),
                label=_stored_nonempty_text(compact.get("label"), "label"),
                section=_stored_nonempty_text(compact.get("section"), "section"),
                client_id=normalize_checkpoint_identifier(
                    compact.get("client_id"), "client_id"
                ),
                session_id=normalize_checkpoint_identifier(
                    compact.get("session_id"), "session_id"
                ),
            )
            source_status = SourceStatus(
                source_available=compact.get("source_available"),
                source_transition=compact.get("source_transition", "unknown"),
                continuity_warning=compact.get("continuity_warning"),
            )
            validate_source_status(source_status)
            raw_health = compact.get("source_health")
            if not isinstance(raw_health, Mapping):
                raise ValueError("source health is missing")
            source_health = SourceHealth(
                unread_source_bytes=raw_health.get("unread_source_bytes"),
                unacknowledged_source_bytes=raw_health.get(
                    "unacknowledged_source_bytes"
                ),
                in_flight_records=raw_health.get("in_flight_records"),
                records_seen=raw_health.get("records_seen"),
                records_rejected=raw_health.get("records_rejected"),
            )
            validate_source_health(source_health)

            raw_schema = compact.get("schema")
            if not isinstance(raw_schema, Mapping):
                raise ValueError("stream schema is missing")
            raw_columns = raw_schema.get("columns")
            if (
                not isinstance(raw_columns, Sequence)
                or isinstance(raw_columns, (str, bytes, bytearray))
                or len(raw_columns) > self.max_recent_columns
                or not all(isinstance(column, str) for column in raw_columns)
            ):
                raise ValueError("stream schema columns are invalid")
            schema = StreamSchema(
                columns=tuple(raw_columns),
                revision=_stored_nonnegative_int(
                    raw_schema.get("revision"), "schema revision"
                ),
            )

            raw_cumulative = compact.get("cumulative")
            if not isinstance(raw_cumulative, Mapping):
                raise ValueError("session counters are missing")
            severity_counts = {
                severity: _stored_nonnegative_int(
                    _stored_mapping(raw_cumulative, "recognized_severity_counts").get(
                        severity
                    ),
                    f"recognised {severity} count",
                )
                for severity in RECOGNIZED_SEVERITIES
            }
            recognized = _stored_nonnegative_int(
                raw_cumulative.get("recognized_severity_records"),
                "recognised severity records",
            )
            if sum(severity_counts.values()) != recognized:
                raise ValueError("recognised severity counters are inconsistent")
            cumulative = SessionCounters(
                total_records=_stored_nonnegative_int(
                    raw_cumulative.get("total_records"), "total records"
                ),
                recognized_severity_records=recognized,
                recognized_severity_counts=severity_counts,
                rejected_source_records=_stored_nonnegative_int(
                    raw_cumulative.get("rejected_source_records"),
                    "rejected source records",
                ),
                continuity_events=_stored_nonnegative_int(
                    raw_cumulative.get("continuity_events"), "continuity events"
                ),
                noteworthy_items=_stored_nonnegative_int(
                    raw_cumulative.get("noteworthy_items"), "noteworthy items"
                ),
                noteworthy_source_records=_stored_nonnegative_int(
                    raw_cumulative.get("noteworthy_source_records"),
                    "noteworthy source records",
                ),
                system_notices=_stored_nonnegative_int(
                    raw_cumulative.get("system_notices"), "system notices"
                ),
                first_observed_at=_stored_optional_datetime(
                    raw_cumulative.get("first_observed_at"), "first observed at"
                ),
                last_observed_at=_stored_optional_datetime(
                    raw_cumulative.get("last_observed_at"), "last observed at"
                ),
                latest_server_sequence=_stored_nonnegative_int(
                    raw_cumulative.get("latest_server_sequence"),
                    "latest server sequence",
                ),
            )

            durable = _restored_durable_history(
                raw_history=_stored_mapping(compact, "durable_history"),
                updated_at=_stored_required_datetime(
                    envelope.get("updated_at"), "storage update time"
                ),
            )
            if history_incomplete_reason is not None:
                reason = _stored_nonempty_text(
                    history_incomplete_reason, "historical persistence error"
                )
                # A retained raw block that cannot be validated is not
                # indistinguishable from deliberately omitted raw history.
                # Keep the compact state browseable, but never present its
                # observed history as complete.
                durable.incomplete = True
                durable.failed_writes = max(1, durable.failed_writes)
                durable.last_error = reason
            stored_lifecycle = compact.get("lifecycle")
            if stored_lifecycle not in {
                LIVE,
                RETRYING,
                ENDED,
                DISCONNECTED,
                INCOMPLETE,
            }:
                raise ValueError("stream lifecycle is invalid")
            pending_delivery = compact.get("pending_delivery")
            if not isinstance(pending_delivery, bool):
                raise ValueError("pending delivery is invalid")
            restored_lifecycle = (
                INCOMPLETE
                if stored_lifecycle in _ACTIVE_LIFECYCLES and pending_delivery
                else DISCONNECTED
                if stored_lifecycle in _ACTIVE_LIFECYCLES
                else stored_lifecycle
            )
            restored_summaries = _restored_items(
                summary_windows,
                label="summary windows",
                maximum=self.max_summary_windows,
            )
            restored_noteworthy = _restored_items(
                noteworthy_items,
                label="noteworthy items",
                maximum=self.max_noteworthy_items,
            )
            restored_raw_records = _restored_raw_records(raw_records)
            last_heartbeat_at = _stored_required_datetime(
                compact.get("last_heartbeat_at"), "last heartbeat at"
            )
            state = StreamViewState(
                registration=registration,
                schema=schema,
                summary_revision=_stored_nonnegative_int(
                    compact.get("summary_revision"), "summary revision"
                ),
                cumulative=cumulative,
                noteworthy_revision=_stored_nonnegative_int(
                    compact.get("noteworthy_revision"), "noteworthy revision"
                ),
                next_batch_sequence=_stored_nonnegative_int(
                    compact.get("next_batch_sequence"), "next batch sequence"
                ),
                next_browser_sequence=max(
                    1,
                    _stored_nonnegative_int(
                        compact.get("next_browser_sequence"),
                        "next browser sequence",
                    ),
                ),
                accepted_records=_stored_nonnegative_int(
                    compact.get("accepted_records"), "accepted records"
                ),
                accepted_batches=_stored_nonnegative_int(
                    compact.get("accepted_batches"), "accepted batches"
                ),
                lifecycle=restored_lifecycle,
                last_heartbeat_at=last_heartbeat_at,
                last_heartbeat_monotonic=self._monotonic_clock(),
                pending_delivery=pending_delivery,
                explicitly_closed=True,
                source_status=source_status,
                source_health=source_health,
                durable_history=durable,
                restored_compact=True,
                restored_summary_windows=restored_summaries,
                restored_noteworthy_items=restored_noteworthy,
                historical=True,
                historical_updated_at=str(envelope["updated_at"]),
            )
            state.records.extend(restored_raw_records)
            state.raw_record_bytes = sum(
                record.encoded_bytes for record in restored_raw_records
            )
            state.last_records_rejected_watermark = source_health.records_rejected
        except (TypeError, ValueError, StreamRecordValidationError) as error:
            raise StreamStateError(f"stored stream session is invalid: {error}") from error

        return self._add_historical_state(state, replace_existing=replace_existing)

    def restore_incomplete_marker(
        self,
        *,
        view_id: str,
        session_id: str,
        recorded_at: str,
        last_error: str,
        replace_existing: bool = False,
    ) -> bool:
        """Restore a marker-only persistence gap as visible history.

        The hard storage ceiling may leave only a small durable-gap marker.
        Its absent compact payload must not make that observed session vanish
        or appear complete after restart.
        """
        try:
            normalized_view_id = normalize_checkpoint_identifier(view_id, "view_id")
            normalized_session_id = normalize_checkpoint_identifier(
                session_id, "session_id"
            )
            restored_at = _stored_required_datetime(recorded_at, "gap recording time")
            reason = _stored_nonempty_text(last_error, "historical persistence error")
            section, label = _marker_catalogue_text(normalized_view_id)
            registration = StreamRegistration(
                view_id=normalized_view_id,
                label=label,
                section=section,
                client_id="restored-gap-marker",
                session_id=normalized_session_id,
            )
            state = StreamViewState(
                registration=registration,
                schema=StreamSchema(),
                lifecycle=INCOMPLETE,
                last_heartbeat_at=restored_at,
                last_heartbeat_monotonic=self._monotonic_clock(),
                pending_delivery=True,
                explicitly_closed=True,
                durable_history=DurableHistoryState(
                    persistence_enabled=True,
                    failed_writes=1,
                    incomplete=True,
                    last_error=reason,
                    last_persisted_at=restored_at,
                ),
                restored_compact=True,
                historical=True,
                historical_updated_at=restored_at.isoformat(),
            )
        except (TypeError, ValueError, StreamRecordValidationError) as error:
            raise StreamStateError(
                f"stored stream persistence gap is invalid: {error}"
            ) from error
        return self._add_historical_state(state, replace_existing=replace_existing)

    def _add_historical_state(
        self, state: StreamViewState, *, replace_existing: bool = False
    ) -> bool:
        """Register one restored state without granting it a live owner role."""
        registration = state.registration
        with self._lock:
            historical = self._historical_streams.setdefault(registration.view_id, {})
            existing = historical.get(registration.session_id)
            if existing is not None and not replace_existing:
                return False
            try:
                store.register_view(
                    view_id=registration.view_id,
                    label=registration.label,
                    section=registration.section,
                    kind="stream",
                    icon_key="stream",
                )
            except store.ViewOwnershipError as error:
                raise StreamConflictError(str(error)) from error
            historical[registration.session_id] = state
            changed = existing is None or (
                existing.historical_updated_at != state.historical_updated_at
                or len(existing.records) != len(state.records)
                or existing.lifecycle != state.lifecycle
            )
            if changed:
                self._history_catalogue_revisions[registration.view_id] = (
                    self._history_catalogue_revisions.get(registration.view_id, 0) + 1
                )
            current = self._streams.get(registration.view_id)
            # Preserve today's lightweight logical view catalogue while making
            # every retained session separately addressable through history.
            # The newest restored state is only a historical presentation
            # fallback; it is not a live transport owner and a real producer
            # registration supersedes it below in ``register``.
            if current is None or (
                current.historical
                and (current.historical_updated_at or "")
                < (state.historical_updated_at or "")
            ):
                self._streams[registration.view_id] = state
        return changed

    def begin_persistence(self, *, view_id: str, session_id: str) -> None:
        """Record independent-worker admission before its task can complete."""
        with self._lock:
            state = self._owned_state_for_session(view_id=view_id, session_id=session_id)
            state.durable_history.persistence_enabled = True
            state.durable_history.pending_writes += 1

    def reject_persistence(
        self, *, view_id: str, session_id: str, reason: str
    ) -> None:
        """Keep live observation running while making a durable gap visible."""
        with self._lock:
            state = self._owned_state_for_session(view_id=view_id, session_id=session_id)
            history = state.durable_history
            history.persistence_enabled = True
            history.pending_writes = max(0, history.pending_writes - 1)
            history.rejected_writes += 1
            history.incomplete = True
            history.last_error = reason

    def cancel_persistence(self, *, view_id: str, session_id: str) -> None:
        """Cancel admission if global storage was disabled mid-submission."""
        with self._lock:
            state = self._owned_state_for_session(view_id=view_id, session_id=session_id)
            history = state.durable_history
            history.pending_writes = max(0, history.pending_writes - 1)
            history.persistence_enabled = False

    def complete_persistence(
        self,
        *,
        view_id: str,
        session_id: str,
        success: bool,
        error: str | None,
    ) -> None:
        """Accept a background result only for the still-current session."""
        with self._lock:
            state = self._streams.get(view_id)
            if state is None or state.registration.session_id != session_id:
                return
            history = state.durable_history
            history.pending_writes = max(0, history.pending_writes - 1)
            if success:
                history.completed_writes += 1
                history.last_persisted_at = self._observed_now()
                return
            history.failed_writes += 1
            history.incomplete = True
            history.last_error = error or "stream persistence failed"

    def persistence_snapshot(
        self,
        *,
        view_id: str,
        session_id: str,
        raw_records: tuple[StreamRecord, ...] = (),
        raw_block_id: str | None = None,
    ) -> dict[str, Any]:
        """Copy bounded compact state for the independent persistence worker.

        This intentionally excludes the live raw window.  A caller can add
        only the newly accepted batch as ``raw_records`` when raw persistence
        was explicitly enabled, avoiding a silent whole-window raw archive.
        """
        with self._lock:
            state = self._owned_state_for_session(view_id=view_id, session_id=session_id)
            self._expire_state_if_needed(state, self._monotonic_clock())
            self._enforce_raw_retention(state, self._observed_now())
            metadata = {
                "protocol_version": 4,
                "view_id": state.registration.view_id,
                "label": state.registration.label,
                "section": state.registration.section,
                "client_id": state.registration.client_id,
                "session_id": state.registration.session_id,
                "stream_instance_id": state.stream_instance_id,
                **self._status_dict(state),
                "schema": {
                    "columns": list(state.schema.columns),
                    "revision": state.schema.revision,
                },
                "summary_revision": state.summary_revision,
                "noteworthy_revision": state.noteworthy_revision,
                "cumulative": state.cumulative.as_browser_dict(),
                "accepted_records": state.accepted_records,
                "accepted_batches": state.accepted_batches,
                "next_browser_sequence": state.next_browser_sequence,
                "next_batch_sequence": state.next_batch_sequence,
                "durable_history": state.durable_history.as_browser_dict(),
            }
            return {
                "view_id": state.registration.view_id,
                "session_id": state.registration.session_id,
                "client_id": state.registration.client_id,
                "metadata": metadata,
                "summary_windows": self._summary_windows_browser_list(state),
                "noteworthy_items": [
                    item.as_browser_dict() for item in state.noteworthy
                ],
                "raw_block_id": raw_block_id,
                "raw_records": [
                    {
                        "browser_sequence": record.browser_sequence,
                        "observed_at": record.observed_at.isoformat(),
                        "data": deepcopy(record.data),
                    }
                    for record in raw_records
                ],
            }

    def clear(self) -> None:
        """Clear stream state for process-local tests and controlled shutdowns."""
        with self._lock:
            self._streams.clear()
            self._historical_streams.clear()
            self._history_catalogue_revisions.clear()

    def _owned_state_for_session(
        self, *, view_id: str, session_id: str
    ) -> StreamViewState:
        state = self._streams.get(view_id)
        if state is None:
            raise UnknownStreamError("stream view has not been registered")
        if state.registration.session_id != session_id:
            raise StreamConflictError("stream session does not own this stream view")
        return state

    def set_raw_retention(
        self,
        *,
        max_recent_records: int,
        max_recent_bytes: int,
        max_recent_age_s: float | None,
        fine_window_s: int,
    ) -> None:
        """Apply configured bounds and immediately evict rows they disallow."""
        if fine_window_s < 1:
            raise ValueError("fine_window_s must be at least one")
        policy = RawRetentionPolicy(
            max_records=int(max_recent_records),
            max_bytes=int(max_recent_bytes),
            max_age_s=max_recent_age_s,
        )
        with self._lock:
            self.raw_retention = policy
            self.fine_window_s = int(fine_window_s)
            now = self._observed_now()
            for state in self._streams.values():
                if state.historical:
                    continue
                self._enforce_raw_retention(state, now)

    def set_summary_retention(
        self,
        *,
        max_fine_summary_windows: int,
        max_coarse_summary_windows: int,
        coarse_window_factor: int,
        max_summary_fields: int,
        max_categorical_values: int,
        max_categorical_value_bytes: int,
    ) -> None:
        """Apply bounded deterministic compaction settings to every stream."""
        if max_fine_summary_windows < 1:
            raise ValueError("max_fine_summary_windows must be at least one")
        if max_coarse_summary_windows < 1:
            raise ValueError("max_coarse_summary_windows must be at least one")
        if coarse_window_factor < 2:
            raise ValueError("coarse_window_factor must be at least two")
        limits = SummaryLimits(
            max_fields=int(max_summary_fields),
            max_categories_per_field=int(max_categorical_values),
            max_category_value_bytes=int(max_categorical_value_bytes),
        )
        with self._lock:
            if (
                self.max_fine_summary_windows == int(max_fine_summary_windows)
                and self.max_coarse_summary_windows == int(max_coarse_summary_windows)
                and self.coarse_window_factor == int(coarse_window_factor)
                and self.summary_limits == limits
            ):
                return
            self.max_fine_summary_windows = int(max_fine_summary_windows)
            self.max_coarse_summary_windows = int(max_coarse_summary_windows)
            self.coarse_window_factor = int(coarse_window_factor)
            self.summary_limits = limits
            for state in self._streams.values():
                if state.restored_compact:
                    state.restored_summary_windows = state.restored_summary_windows[
                        -self.max_summary_windows :
                    ]
                    continue
                # These two auxiliary noteworthy classifiers share the same
                # categorical bound and fixed field vocabularies.  Rebound
                # their retained classifier state alongside summaries so a
                # live configuration reduction cannot leave hidden excess
                # state behind.
                state.noteworthy_first_values = {
                    field_name: set(sorted(values)[: limits.max_categories_per_field])
                    for field_name, values in state.noteworthy_first_values.items()
                }
                state.fine_windows = {
                    key: window.rebounded(limits=limits)
                    for key, window in state.fine_windows.items()
                }
                state.coarse_windows = {
                    key: window.rebounded(limits=limits)
                    for key, window in state.coarse_windows.items()
                }
                if state.historic_summary is not None:
                    state.historic_summary = state.historic_summary.rebounded(
                        limits=limits
                    )
                self._compact_summary_windows(state)
                if (
                    state.fine_windows
                    or state.coarse_windows
                    or state.historic_summary is not None
                ):
                    state.summary_revision += 1

    def set_noteworthy_retention(self, *, max_noteworthy_items: int) -> None:
        """Apply the bounded noteworthy-item limit to every active stream."""
        if max_noteworthy_items < 1:
            raise ValueError("max_noteworthy_items must be at least one")
        with self._lock:
            maximum = int(max_noteworthy_items)
            if self.max_noteworthy_items == maximum:
                return
            self.max_noteworthy_items = maximum
            for state in self._streams.values():
                if state.restored_compact:
                    state.restored_noteworthy_items = state.restored_noteworthy_items[
                        -maximum:
                    ]
                    continue
                prior_length = len(state.noteworthy)
                self._enforce_noteworthy_retention(state)
                if len(state.noteworthy) != prior_length:
                    state.noteworthy_revision += 1

    def _recent_columns(self, records: deque[StreamRecord]) -> tuple[str, ...]:
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
                    return tuple(columns)
        return tuple(columns)

    def _enforce_raw_retention(
        self, state: StreamViewState, observed_now: datetime
    ) -> None:
        """Evict oldest raw rows until every configured hard bound is met."""
        while state.records and self._raw_bounds_exceeded(state, observed_now):
            evicted = state.records.popleft()
            state.raw_record_bytes -= evicted.encoded_bytes
            self._add_to_fine_window(state, evicted)
        self._refresh_schema(state)

    def _raw_bounds_exceeded(
        self, state: StreamViewState, observed_now: datetime
    ) -> bool:
        if len(state.records) > self.max_recent_records:
            return True
        if state.raw_record_bytes > self.max_recent_bytes:
            return True
        max_age_s = self.max_recent_age_s
        if max_age_s is None:
            return False
        oldest = state.records[0]
        return observed_now - oldest.observed_at >= timedelta(seconds=max_age_s)

    def _add_to_fine_window(
        self, state: StreamViewState, record: StreamRecord
    ) -> None:
        window_start = self._fine_window_start(record.observed_at)
        window_key = (self.fine_window_s, window_start)
        window = state.fine_windows.get(window_key)
        if window is None:
            window = SummaryWindow(
                observed_from=window_start,
                observed_until=window_start + timedelta(seconds=self.fine_window_s),
                resolution_s=self.fine_window_s,
            )
            state.fine_windows[window_key] = window
        window.add_record(record, limits=self.summary_limits)
        self._compact_summary_windows(state)
        state.summary_revision += 1

    def _fine_window_start(self, observed_at: datetime) -> datetime:
        """Floor an observation to a UTC fixed-width fine-window boundary."""
        return self._window_start(observed_at, resolution_s=self.fine_window_s)

    @staticmethod
    def _window_start(observed_at: datetime, *, resolution_s: int) -> datetime:
        """Floor an observation to a UTC fixed-width window boundary."""
        since_epoch = observed_at - _OBSERVATION_EPOCH
        whole_seconds = since_epoch.days * 86_400 + since_epoch.seconds
        start_seconds = (whole_seconds // resolution_s) * resolution_s
        return _OBSERVATION_EPOCH + timedelta(seconds=start_seconds)

    def _compact_summary_windows(self, state: StreamViewState) -> None:
        """Move oldest derived bins through bounded deterministic resolutions."""
        while len(state.fine_windows) > self.max_fine_summary_windows:
            fine_key, fine = min(
                state.fine_windows.items(),
                key=lambda item: (item[1].observed_from, item[0]),
            )
            del state.fine_windows[fine_key]
            self._add_to_coarse_window(state, fine)

        while len(state.coarse_windows) > self.max_coarse_summary_windows:
            coarse_key, coarse = min(
                state.coarse_windows.items(),
                key=lambda item: (item[1].observed_from, item[0]),
            )
            del state.coarse_windows[coarse_key]
            if state.historic_summary is None:
                state.historic_summary = SummaryWindow.merged(
                    SummaryWindow(
                        observed_from=coarse.observed_from,
                        observed_until=coarse.observed_until,
                        resolution_s=None,
                    ),
                    coarse,
                    limits=self.summary_limits,
                    observed_from=coarse.observed_from,
                    observed_until=coarse.observed_until,
                    resolution_s=None,
                )
            else:
                state.historic_summary = SummaryWindow.merged(
                    state.historic_summary,
                    coarse,
                    limits=self.summary_limits,
                    observed_from=min(
                        state.historic_summary.observed_from, coarse.observed_from
                    ),
                    observed_until=max(
                        state.historic_summary.observed_until, coarse.observed_until
                    ),
                    resolution_s=None,
                )

    def _add_to_coarse_window(
        self, state: StreamViewState, fine: SummaryWindow
    ) -> None:
        assert fine.resolution_s is not None
        resolution_s = fine.resolution_s * self.coarse_window_factor
        observed_from = self._window_start(
            fine.observed_from, resolution_s=resolution_s
        )
        observed_until = observed_from + timedelta(seconds=resolution_s)
        coarse_key = (resolution_s, observed_from)
        coarse = state.coarse_windows.get(coarse_key)
        if coarse is None:
            coarse = SummaryWindow(
                observed_from=observed_from,
                observed_until=observed_until,
                resolution_s=resolution_s,
            )
        state.coarse_windows[coarse_key] = SummaryWindow.merged(
            coarse,
            fine,
            limits=self.summary_limits,
            observed_from=observed_from,
            observed_until=observed_until,
            resolution_s=resolution_s,
        )

    def _refresh_schema(self, state: StreamViewState) -> None:
        if state.restored_compact:
            # A compact restored session has intentionally no raw rows. Keep
            # its persisted schema rather than treating that empty window as a
            # schema change.
            return
        columns = self._recent_columns(state.records)
        if columns == state.schema.columns:
            return
        previous_revision = state.schema.revision
        state.schema = StreamSchema(
            columns=columns,
            revision=previous_revision + 1,
        )
        # The initial schema establishes the view rather than changing one.
        # Later bounded-window additions and removals are explicit plotsrv
        # metadata events, never synthetic source rows.
        if previous_revision:
            self._emit_system_notice(
                state,
                event="stream_schema_changed",
                schema_revision=state.schema.revision,
            )

    def _retain_noteworthy_source_record(
        self,
        state: StreamViewState,
        record: StreamRecord,
        *,
        reason: str,
        severity: str | None = None,
        field_name: str | None = None,
        field_value: Any | None = None,
    ) -> None:
        item = NoteworthySourceRecord(
            noteworthy_sequence=state.next_noteworthy_sequence,
            record=record,
            reason=reason,
            severity=severity,
            field_name=field_name,
            field_value=field_value,
        )
        self._retain_noteworthy_item(state, item)

    def _retain_noteworthy_first_appearances(
        self, state: StreamViewState, record: StreamRecord
    ) -> None:
        """Retain bounded first values for explicit low-cardinality fields."""
        for field_name, value in record.data.items():
            if field_name not in NOTEWORTHY_LOW_CARDINALITY_FIELDS:
                continue
            if value is not None and type(value) not in (str, bool):
                continue
            value_json = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if len(value_json.encode("utf-8")) > self.summary_limits.max_category_value_bytes:
                continue
            seen = state.noteworthy_first_values.setdefault(field_name, set())
            if value_json in seen or len(seen) >= self.summary_limits.max_categories_per_field:
                continue
            seen.add(value_json)
            self._retain_noteworthy_source_record(
                state,
                record,
                reason="first_low_cardinality_value",
                field_name=field_name,
                field_value=value,
            )

    def _retain_noteworthy_numeric_extrema(
        self, state: StreamViewState, record: StreamRecord
    ) -> None:
        """Retain new extrema only for fixed, unit-clear numeric fields."""
        for field_name, value in record.data.items():
            if field_name not in NOTEWORTHY_NUMERIC_EXTREMUM_FIELDS:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                continue
            extrema = state.noteworthy_numeric_extrema.get(field_name)
            if extrema is None:
                # The first value establishes a comparison point; treating it
                # as both a minimum and maximum would add no useful signal.
                state.noteworthy_numeric_extrema[field_name] = (value, value)
                continue
            minimum, maximum = extrema
            if value < minimum:
                state.noteworthy_numeric_extrema[field_name] = (value, maximum)
                self._retain_noteworthy_source_record(
                    state,
                    record,
                    reason="numeric_minimum",
                    field_name=field_name,
                    field_value=value,
                )
            elif value > maximum:
                state.noteworthy_numeric_extrema[field_name] = (minimum, value)
                self._retain_noteworthy_source_record(
                    state,
                    record,
                    reason="numeric_maximum",
                    field_name=field_name,
                    field_value=value,
                )

    def _emit_system_notice(
        self,
        state: StreamViewState,
        *,
        event: str,
        source_transition: str | None = None,
        continuity_warning: str | None = None,
        rejected_record_count: int | None = None,
        schema_revision: int | None = None,
    ) -> None:
        """Retain a structured plotsrv observation, never a synthetic row."""
        item = SystemNotice(
            noteworthy_sequence=state.next_noteworthy_sequence,
            observed_at=self._observed_now(),
            event=event,
            source_transition=source_transition,
            continuity_warning=continuity_warning,
            rejected_record_count=rejected_record_count,
            schema_revision=schema_revision,
        )
        self._retain_noteworthy_item(state, item)

    def _retain_noteworthy_item(
        self, state: StreamViewState, item: NoteworthyItem
    ) -> None:
        state.cumulative.add_noteworthy_item(item)
        state.noteworthy.append(item)
        state.next_noteworthy_sequence += 1
        self._enforce_noteworthy_retention(state)
        state.noteworthy_revision += 1

    def _enforce_noteworthy_retention(self, state: StreamViewState) -> None:
        while len(state.noteworthy) > self.max_noteworthy_items:
            # Structured severities remain discoverable when ordinary schema,
            # categorical-first, or extrema items arrive around them.  Within
            # one priority, remove the oldest item deterministically.
            discarded = min(
                state.noteworthy,
                key=lambda item: (
                    self._noteworthy_retention_priority(item),
                    item.noteworthy_sequence,
                ),
            )
            state.noteworthy.remove(discarded)

    @staticmethod
    def _noteworthy_retention_priority(item: NoteworthyItem) -> int:
        if isinstance(item, NoteworthySourceRecord):
            return 3 if item.reason == "structured_severity" else 1
        return 2

    def _noteworthy_browser_dict(self, state: StreamViewState) -> dict[str, Any]:
        """Return typed source records and system notices in append order."""
        if state.restored_compact:
            return {
                "object_type": "stream_noteworthy_collection",
                "noteworthy_revision": state.noteworthy_revision,
                "max_retained_items": self.max_noteworthy_items,
                "retained_item_count": len(state.restored_noteworthy_items),
                "items": deepcopy(list(state.restored_noteworthy_items)),
            }
        return {
            "object_type": "stream_noteworthy_collection",
            "noteworthy_revision": state.noteworthy_revision,
            "max_retained_items": self.max_noteworthy_items,
            "retained_item_count": len(state.noteworthy),
            "items": [item.as_browser_dict() for item in state.noteworthy],
        }

    def _summary_windows_browser_list(
        self, state: StreamViewState
    ) -> list[dict[str, Any]]:
        """Build the bounded derived windows used by API and persistence."""
        if state.restored_compact:
            return deepcopy(list(state.restored_summary_windows))
        windows: list[dict[str, Any]] = []
        if state.historic_summary is not None:
            windows.append(
                state.historic_summary.as_browser_dict(
                    tier="cumulative", limits=self.summary_limits
                )
            )
        windows.extend(
            window.as_browser_dict(tier="coarse", limits=self.summary_limits)
            for _, window in sorted(
                state.coarse_windows.items(),
                key=lambda item: (item[1].observed_from, item[0]),
            )
        )
        windows.extend(
            window.as_browser_dict(tier="fine", limits=self.summary_limits)
            for _, window in sorted(
                state.fine_windows.items(),
                key=lambda item: (item[1].observed_from, item[0]),
            )
        )
        return windows

    def _observed_now(self) -> datetime:
        now = self._observation_clock()
        if now.tzinfo is None:
            raise ValueError("observation_clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

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

    def _record_source_status(self, state: StreamViewState, status: SourceStatus) -> None:
        """Record source state and emit only explicit continuity observations."""
        state.source_status = status
        event: str | None = None
        notice_key: tuple[str, str | None] | None = None
        if status.continuity_warning is not None:
            event = "source_continuity_uncertain"
            notice_key = (event, status.continuity_warning)
        elif status.source_transition in {"replaced", "truncated"}:
            event = "source_continuity_transition"
            notice_key = (event, status.source_transition)

        if notice_key is None:
            # Provider failure and legacy telemetry both arrive as an unknown
            # status.  They are not evidence that a previous continuity
            # warning resolved, so retain the accounting/deduplication
            # watermark through them.  An explicit available normal state is
            # sufficient resolution evidence and lets a later identical
            # warning become a new observed event.
            if (
                status.source_available is True
                and status.source_transition in {"initial", "continuing", "appeared"}
                and status.continuity_warning is None
            ):
                state.last_continuity_notice = None
            return
        if notice_key == state.last_continuity_notice:
            return
        state.last_continuity_notice = notice_key
        self._emit_system_notice(
            state,
            event=event,
            source_transition=status.source_transition,
            continuity_warning=status.continuity_warning,
        )

    def _record_source_health(self, state: StreamViewState, health: SourceHealth) -> None:
        """Surface new source-rejection facts without deriving source prose."""
        state.source_health = health
        current_rejected = health.records_rejected
        if current_rejected is None:
            return
        previous_rejected = state.last_records_rejected_watermark
        if previous_rejected is None:
            increase = current_rejected
        elif current_rejected > previous_rejected:
            increase = current_rejected - previous_rejected
        elif current_rejected < previous_rejected:
            # A producer explicitly supplied a lower cumulative value, which
            # is reset evidence.  It also reports this new generation's
            # already-observed rejections, so add the full lower value before
            # retaining the new watermark.  Absence above intentionally does
            # not reset it.
            increase = current_rejected
            self._emit_system_notice(state, event="source_rejection_counter_reset")
        else:
            return
        state.last_records_rejected_watermark = current_rejected
        if increase:
            state.cumulative.add_rejected_source_records(increase)
            self._emit_system_notice(
                state,
                # A JSONL parse failure is one producer rejection, but this
                # generic protocol telemetry does not prove every custom
                # producer's rejection reason.  Keep the system claim exact.
                event="source_record_rejection_reported",
                rejected_record_count=increase,
            )

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


def _stored_nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing")
    return value.strip()


def _stored_mapping(value: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    nested = value.get(label)
    if not isinstance(nested, Mapping):
        raise ValueError(f"{label} is missing")
    return nested


def _stored_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} is invalid")
    if isinstance(value, int):
        integer = value
    elif isinstance(value, str) and value.isdecimal():
        integer = int(value)
    else:
        raise ValueError(f"{label} is invalid")
    if integer < 0:
        raise ValueError(f"{label} is invalid")
    return integer


def _stored_required_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} is invalid")
    return parsed.astimezone(UTC)


def _stored_optional_datetime(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    return _stored_required_datetime(value, label)


def _restored_items(
    values: Sequence[Mapping[str, Any]], *, label: str, maximum: int
) -> tuple[dict[str, Any], ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ValueError(f"{label} are invalid")
    copied: list[dict[str, Any]] = []
    for value in values[-maximum:]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} are invalid")
        copied.append(deepcopy(dict(value)))
    return tuple(copied)


def _restored_raw_records(
    values: Sequence[Mapping[str, Any]],
) -> tuple[StreamRecord, ...]:
    """Rebuild only explicitly persisted raw browser rows from storage."""
    if isinstance(values, (str, bytes, bytearray)):
        raise ValueError("raw records are invalid")
    records: list[StreamRecord] = []
    sequences: set[int] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError("raw records are invalid")
        data = value.get("data")
        if not isinstance(data, Mapping):
            raise ValueError("raw records are invalid")
        copied_data = deepcopy(dict(data))
        try:
            validate_stream_record(copied_data)
        except StreamRecordValidationError as error:
            raise ValueError("raw records are invalid") from error
        browser_sequence = _stored_nonnegative_int(
            value.get("browser_sequence"), "raw browser sequence"
        )
        if browser_sequence < 1 or browser_sequence in sequences:
            raise ValueError("raw browser sequence is invalid")
        sequences.add(browser_sequence)
        records.append(
            StreamRecord(
                browser_sequence=browser_sequence,
                data=copied_data,
                observed_at=_stored_required_datetime(
                    value.get("observed_at"), "raw observed at"
                ),
                encoded_bytes=stream_record_size(copied_data),
            )
        )
    return tuple(sorted(records, key=lambda record: record.browser_sequence))


def _marker_catalogue_text(view_id: str) -> tuple[str, str]:
    """Derive safe catalogue text when a durable gap lacks compact metadata."""
    section, separator, label = view_id.partition(":")
    if separator and section.strip() and label.strip():
        return section.strip(), label.strip()
    return "streams", view_id


def _restored_durable_history(
    *, raw_history: Mapping[str, Any], updated_at: datetime
) -> DurableHistoryState:
    state = raw_history.get("state")
    if state not in {"complete", "incomplete"}:
        raise ValueError("durable history is incomplete")
    error = raw_history.get("last_error")
    if error is not None and not isinstance(error, str):
        raise ValueError("durable history error is invalid")
    return DurableHistoryState(
        persistence_enabled=True,
        completed_writes=1 if state == "complete" else 0,
        rejected_writes=_stored_nonnegative_int(
            raw_history.get("rejected_writes", 0), "rejected persistence writes"
        ),
        failed_writes=_stored_nonnegative_int(
            raw_history.get("failed_writes", 0), "failed persistence writes"
        ),
        incomplete=state == "incomplete",
        last_error=error,
        last_persisted_at=updated_at,
    )


stream_registry = StreamRegistry()
