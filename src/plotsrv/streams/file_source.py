"""Incremental source following for JSON Lines files.

This module intentionally knows nothing about plotsrv's snapshot publisher or
HTTP application.  It turns a source file into ordered, complete JSON-object
records; the dedicated stream client introduced alongside the stream protocol
owns their delivery.
"""

from __future__ import annotations

import json
import logging
import math
import os
import stat as stat_module
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, NoReturn
from uuid import uuid4

from .models import (
    MAX_STREAM_BATCH_BYTES,
    MAX_STREAM_BATCH_RECORDS,
    MAX_STREAM_RECORD_BYTES,
    stream_record_size,
    validate_stream_record,
    SourceStatus,
)


logger = logging.getLogger(__name__)

_JSONL_SUFFIXES = frozenset({".jsonl", ".ndjson"})

# The follower deliberately drains a source over several polls rather than
# allocating everything appended since its last turn.  A too-large line is
# rejected and discarded through its next newline so a later valid record can
# still be observed.
READ_CHUNK_BYTES = 64 * 1024
MAX_JSONL_RECORD_BYTES = MAX_STREAM_RECORD_BYTES
MAX_JSONL_PARTIAL_LINE_BYTES = MAX_STREAM_RECORD_BYTES
MAX_BATCH_RECORDS = MAX_STREAM_BATCH_RECORDS
MAX_BATCH_BYTES = MAX_STREAM_BATCH_BYTES
CONTINUITY_PROBE_BYTES = 128


class SourceTransitionKind(str, Enum):
    """Portable observations about the active JSONL path.

    These values describe what a caller can establish from repeated ``stat``
    calls.  They intentionally say nothing about named rotated siblings: the
    follower only ever observes its configured active path.
    """

    INITIAL = "initial"
    CONTINUING = "continuing"
    REPLACED = "replaced"
    TRUNCATED = "truncated"
    MISSING = "missing"
    APPEARED = "appeared"


class SourceTransitionClassification(str, Enum):
    """The only continuity outcome a source observation can currently have.

    ``SourceTransitionKind`` retains the physical pathname event for local
    diagnostics.  This classification instead says what the follower can
    honestly claim about record continuity after that observation.  It is
    deliberately source-local state, not a stream lifecycle or protocol type.
    """

    PROVABLY_CONTINUOUS = "provably_continuous"
    UNAVAILABLE = "unavailable"
    CONTINUITY_UNCERTAIN = "continuity_uncertain"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """The stable identity fields available through a portable file stat."""

    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """A path-level source snapshot without exposing the source path itself."""

    identity: FileIdentity | None
    size_bytes: int | None
    available: bool

    @classmethod
    def missing(cls) -> SourceObservation:
        return cls(identity=None, size_bytes=None, available=False)


@dataclass(frozen=True, slots=True)
class SourceTransition:
    """One transition between two configured-path source observations."""

    kind: SourceTransitionKind
    previous: SourceObservation | None
    current: SourceObservation
    classification: SourceTransitionClassification

    @property
    def continuity_warning(self) -> str | None:
        """Return a safe warning when observation cannot prove continuity."""
        if self.kind is SourceTransitionKind.TRUNCATED:
            return "The JSONL source was truncated; record continuity is uncertain."
        if self.kind is SourceTransitionKind.REPLACED:
            return "The JSONL source was replaced; record continuity is uncertain."
        return None


@dataclass(slots=True)
class _OpenJsonlSource:
    """One open source descriptor retained across active-path changes."""

    file: BinaryIO
    observation: SourceObservation


def observe_jsonl_source(source: Path) -> SourceObservation:
    """Snapshot the configured path with only portable file operations.

    A missing path is an expected transient state for a follower.  Other
    operating-system failures are deliberately left to the caller so local
    logs retain diagnostic detail while any public state can be sanitised.
    """
    try:
        source_stat = source.stat()
    except FileNotFoundError:
        return SourceObservation.missing()

    return _source_observation_from_stat(source_stat)


def _source_observation_from_stat(source_stat: Any) -> SourceObservation:
    """Create a source observation from either ``stat`` or ``fstat`` data."""
    if not stat_module.S_ISREG(source_stat.st_mode):
        return SourceObservation.missing()
    return SourceObservation(
        identity=_file_identity_from_stat(source_stat),
        size_bytes=max(0, int(source_stat.st_size)),
        available=True,
    )


def classify_source_transition(
    previous: SourceObservation | None,
    current: SourceObservation,
) -> SourceTransition:
    """Classify a portable active-path observation transition.

    A replacement is reported only when both observations provide a usable
    device/inode pair.  A size decrease on a continuing or unidentifiable
    path is conservatively reported as truncation instead of assuming that
    continuity can be reconstructed.
    """
    if previous is None:
        kind = SourceTransitionKind.INITIAL
    elif not current.available:
        kind = SourceTransitionKind.MISSING
    elif not previous.available:
        kind = SourceTransitionKind.APPEARED
    elif (
        current.identity is not None
        and previous.identity is not None
        and current.identity != previous.identity
    ):
        kind = SourceTransitionKind.REPLACED
    elif (
        current.size_bytes is not None
        and previous.size_bytes is not None
        and current.size_bytes < previous.size_bytes
    ):
        kind = SourceTransitionKind.TRUNCATED
    else:
        kind = SourceTransitionKind.CONTINUING
    if kind is SourceTransitionKind.MISSING:
        classification = SourceTransitionClassification.UNAVAILABLE
    elif kind in (SourceTransitionKind.REPLACED, SourceTransitionKind.TRUNCATED):
        classification = SourceTransitionClassification.CONTINUITY_UNCERTAIN
    else:
        classification = SourceTransitionClassification.PROVABLY_CONTINUOUS
    return SourceTransition(
        kind=kind,
        previous=previous,
        current=current,
        classification=classification,
    )


def _file_identity_from_stat(source_stat: Any) -> FileIdentity | None:
    """Extract a usable device/inode pair without platform-specific APIs."""
    device = getattr(source_stat, "st_dev", None)
    inode = getattr(source_stat, "st_ino", None)
    if (
        isinstance(device, bool)
        or not isinstance(device, int)
        or device < 0
        or isinstance(inode, bool)
        or not isinstance(inode, int)
        or inode <= 0
    ):
        return None
    return FileIdentity(device=device, inode=inode)


def _same_file_identity(
    first: SourceObservation,
    second: SourceObservation,
) -> bool:
    """Whether portable metadata can prove two observations are one file."""
    return (
        first.identity is not None
        and second.identity is not None
        and first.identity == second.identity
    )


def _different_file_identity(
    first: SourceObservation,
    second: SourceObservation,
) -> bool:
    """Whether portable metadata can prove that two observations differ."""
    return (
        first.identity is not None
        and second.identity is not None
        and first.identity != second.identity
    )


def _reject_nonstandard_json_constant(constant: str) -> NoReturn:
    """Reject values accepted by Python but excluded by the JSON grammar."""
    raise json.JSONDecodeError(
        f"non-standard JSON constant {constant!r}",
        constant,
        0,
    )


def _parse_finite_json_float(value: str) -> float:
    """Convert a JSON number without admitting an overflowing infinity."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON float must be finite")
    return parsed


@dataclass(frozen=True, slots=True)
class JsonlRecord:
    """One valid source record with plotsrv observation metadata kept separate."""

    data: dict[str, Any]
    source_offset: int
    source_end_offset: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class JsonlBatch:
    """One bounded, retained source batch awaiting server acknowledgement.

    The batch ID is assigned when the candidate source range is first read and
    travels with it for every delivery attempt.  Source progress therefore
    remains tied to the batch acknowledgement rather than to an HTTP attempt.
    """

    batch_id: str
    records: tuple[JsonlRecord, ...]
    source_offset: int
    source_end_offset: int


RecordCallback = Callable[[JsonlRecord], None]
BatchCallback = Callable[[JsonlBatch], bool]
RetryDelayCallback = Callable[[], float]
ErrorCallback = Callable[[BaseException], None]
SourceStatusCallback = Callable[[SourceStatus], bool]


def resolve_jsonl_source(source: str | Path) -> Path:
    """Resolve a JSONL source without requiring it to exist yet."""
    path = Path(source).expanduser().resolve(strict=False)
    suffix = path.suffix.lower()
    if suffix not in _JSONL_SUFFIXES:
        accepted = ", ".join(sorted(_JSONL_SUFFIXES))
        raise ValueError(f"stream source must use one of {accepted}; got {path.name!r}")

    if path.exists() and not path.is_file():
        raise ValueError(f"stream source must be a regular file: {path.name!r}")

    return path


class JsonlFollower:
    """Follow appended, complete JSON-object records in a daemon thread.

    The initial byte position is captured during construction rather than in
    the worker.  Consequently an existing source starts at its registration
    EOF even if records are appended before the worker receives CPU time.  A
    missing source instead retains offset zero until it is created.
    """

    def __init__(
        self,
        source: str | Path,
        *,
        on_record: RecordCallback | None = None,
        on_batch: BatchCallback | None = None,
        on_source_status: SourceStatusCallback | None = None,
        retry_delay: RetryDelayCallback | None = None,
        on_error: ErrorCallback | None = None,
        poll_interval_s: float = 0.1,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be greater than zero")

        self.source = resolve_jsonl_source(source)
        if on_record is not None and on_batch is not None:
            raise ValueError("use either on_record or on_batch, not both")

        self.on_record = on_record
        self.on_batch = on_batch
        # The stream client uses this to acknowledge a warning heartbeat
        # before this follower lets a post-transition batch reach /append.
        # It is deliberately a callback over the existing SourceStatus
        # surface, not a second lifecycle protocol.
        self.on_source_status = on_source_status
        self.retry_delay = retry_delay
        self.on_error = on_error
        self.poll_interval_s = float(poll_interval_s)
        self.observation_started_at = datetime.now(UTC)

        initial_observation = observe_jsonl_source(self.source)
        self.initial_offset = initial_observation.size_bytes or 0
        self.source_existed_at_start = initial_observation.available

        self._read_offset = self.initial_offset
        self._line_start_offset = self.initial_offset
        self._partial_line = b""
        self._discarding_oversize_line = False
        self._acknowledged_source_offset = self.initial_offset
        self._accounted_source_offset = self.initial_offset
        self._candidate_source_offset = self.initial_offset
        self._in_flight_batch: JsonlBatch | None = None
        self._oversized_partial_line_start: int | None = None
        self._oversized_partial_scan_offset: int | None = None
        self._source_offset_lock = threading.Lock()
        self._source_state_lock = threading.Lock()
        self._source_observation = initial_observation
        self._last_available_observation = (
            initial_observation if initial_observation.available else None
        )
        self._source_transition = classify_source_transition(None, initial_observation)
        self._continuity_warning: str | None = None
        self._continuity_classification = self._source_transition.classification
        # A replacement begins as uncertain until the retained predecessor
        # is drained and the descriptor opened for its successor is verified
        # against the observation. This is separate from a proven ambiguity,
        # which remains sticky for the observation session.
        self._continuity_verification_pending = False
        self._continuity_uncertain = False
        # A continuity warning is not merely included opportunistically in a
        # later append payload.  Its generation must first be acknowledged by
        # the existing source-status transport before a batch is accepted.
        self._continuity_warning_generation = 0
        self._published_continuity_warning_generation = 0
        self._continuity_probe: tuple[int, bytes] | None = None
        self._active_source: _OpenJsonlSource | None = None
        self._rotation_pending = False
        # Remember the pathname target first observed while the retained
        # descriptor is being drained. If it changes before handover, the
        # intermediate source could not have been read.
        self._pending_replacement_observation: SourceObservation | None = None
        self._truncation_pending = False
        self._rotation_state = (
            "stable" if initial_observation.available else "awaiting_active_source"
        )
        self._rotations_completed = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self.last_error: BaseException | None = None
        self.records_seen = 0
        self.records_rejected = 0

        # Retain the descriptor from registration onward. A later rename of
        # the configured pathname still leaves this descriptor readable on
        # platforms that support ordinary rename-and-recreate rotation.
        if initial_observation.available:
            self._active_source = self._open_source_handle(
                start_offset=self.initial_offset
            )
            if (
                self._active_source is not None
                and _different_file_identity(
                    initial_observation, self._active_source.observation
                )
            ):
                # The active pathname changed after initial stat but before
                # opening its descriptor. The old EOF is no longer a safe
                # starting point for the newly opened source.
                self._active_source.file.seek(0)
                self.initial_offset = 0
                self._reset_source_offsets()
                self._record_continuity_warning(
                    "The JSONL source changed during observer start; record "
                    "continuity is uncertain."
                )
                self._rotation_state = "continuity_uncertain"
            elif self._active_source is not None:
                # Seed the committed-byte guard at registration EOF. A writer
                # can copy-truncate and refill past that offset before the
                # first follower poll, so there may be no accepted batch yet
                # from which to build the guard.
                self._capture_continuity_probe(self.initial_offset)

    @property
    def is_running(self) -> bool:
        """Whether the background source worker is currently alive."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def acknowledged_source_offset(self) -> int:
        """Last source byte whose batch was accepted by the server."""
        with self._source_offset_lock:
            return self._acknowledged_source_offset

    @property
    def candidate_source_offset(self) -> int:
        """End of the single batch retained while awaiting acknowledgement."""
        with self._source_offset_lock:
            return self._candidate_source_offset

    @property
    def accounted_source_offset(self) -> int:
        """Source progress including completed non-deliverable JSONL lines."""
        with self._source_offset_lock:
            return self._accounted_source_offset

    def health(self) -> dict[str, object]:
        """Return a bounded, browser-safe source/delivery backlog summary."""
        observation, transition, continuity_warning = self._observe_source_state()
        with self._source_offset_lock:
            acknowledged = self._acknowledged_source_offset
            accounted = self._accounted_source_offset
            candidate = self._candidate_source_offset
            in_flight = self._in_flight_batch
        source_size = observation.size_bytes or 0
        active_source_size = self._active_source_size()
        tracked_source_size = (
            source_size if active_source_size is None else active_source_size
        )
        return {
            # This summary can be returned by embedding applications. Never
            # expose the server's absolute source path through that surface.
            "source": _source_label(self.source),
            "source_size_bytes": source_size,
            "active_source_size_bytes": active_source_size,
            "source_available": observation.available,
            "source_transition": transition.kind.value,
            "continuity_warning": continuity_warning,
            "rotation_state": self._rotation_state,
            "rotations_completed": self._rotations_completed,
            "unread_source_bytes": max(0, tracked_source_size - accounted),
            "unacknowledged_source_bytes": max(0, tracked_source_size - acknowledged),
            "acknowledged_source_offset": acknowledged,
            "accounted_source_offset": accounted,
            "candidate_source_offset": candidate,
            "in_flight_records": 0 if in_flight is None else len(in_flight.records),
            "records_seen": self.records_seen,
            "records_rejected": self.records_rejected,
            "last_error": _safe_source_error_text(self.last_error),
        }

    def source_status(self) -> SourceStatus:
        """Return only safe lifecycle facts for the browser stream protocol."""
        health = self.health()
        return SourceStatus(
            source_available=health["source_available"],  # type: ignore[arg-type]
            source_transition=health["source_transition"],  # type: ignore[arg-type]
            continuity_warning=health["continuity_warning"],  # type: ignore[arg-type]
        )

    def start(self) -> None:
        """Start the daemon follower exactly once."""
        with self._thread_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run,
                name=f"plotsrv-stream:{self.source.name}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout: float | None = None) -> bool:
        """Stop local observation and report whether the worker has joined."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()

    def close(self) -> bool:
        """Close the retained descriptor after the follower has stopped."""
        if self.is_running:
            return False
        active_source = self._active_source
        if active_source is None:
            return True
        self._active_source = None
        self._close_source_handle(active_source)
        return True

    def drain(
        self,
        *,
        timeout_s: float,
        on_batch: BatchCallback | None = None,
    ) -> bool:
        """Attempt a bounded, synchronous final delivery through source EOF.

        The follower still retains only one source batch at a time.  A failed
        acknowledgement ends the attempt rather than creating an in-memory
        backlog, and an unfinished source line remains an incomplete
        observation rather than a fabricated clean end.
        """
        if timeout_s <= 0:
            return self._is_drained()
        callback = self.on_batch if on_batch is None else on_batch
        if callback is None:
            return self._is_drained()
        deadline = time.monotonic() + timeout_s
        while True:
            if self._is_drained():
                return True
            if time.monotonic() >= deadline:
                return False
            acknowledged = self._deliver_candidate_batch(on_batch=callback)
            if not acknowledged:
                return self._is_drained()

    def _is_drained(self) -> bool:
        with self._source_offset_lock:
            pending = self._in_flight_batch is not None
            accounted = self._accounted_source_offset
        observation, _, _ = self._observe_source_state()
        active_source = self._ensure_active_source(observation)
        if self._rotation_pending:
            # The replacement must not make a drained predecessor look like
            # a complete overall source before we have switched to it.
            return False
        if active_source is None:
            return not pending
        try:
            source_size = max(0, int(os.fstat(active_source.file.fileno()).st_size))
        except OSError as error:
            self._report_error(error)
            return False
        return not pending and source_size <= accounted

    def _observe_source_state(
        self,
    ) -> tuple[SourceObservation, SourceTransition, str | None]:
        """Update the active-path state using the portable observation helpers."""
        try:
            observation = observe_jsonl_source(self.source)
        except OSError as error:
            # Do not let an OS message (which can contain the full source
            # path) reach the health surface. The detailed exception remains
            # available to the local callback and process logger.
            self._report_error(error)
            observation = SourceObservation.missing()

        with self._source_state_lock:
            previous = self._source_observation
            returned_after_unavailability = (
                not previous.available and observation.available
            )
            comparison_previous = previous
            if (
                returned_after_unavailability
                and self._last_available_observation is not None
            ):
                # A return after disappearance can still prove a replacement
                # or truncation relative to the last known active file.
                comparison_previous = self._last_available_observation

            transition = classify_source_transition(comparison_previous, observation)
            if (
                not previous.available
                and observation.available
                and transition.kind is SourceTransitionKind.CONTINUING
            ):
                transition = SourceTransition(
                    kind=SourceTransitionKind.APPEARED,
                    previous=previous,
                    current=observation,
                    classification=SourceTransitionClassification.PROVABLY_CONTINUOUS,
                )

            self._source_observation = observation
            if observation.available:
                self._last_available_observation = observation
            self._source_transition = transition
            self._apply_observed_transition_classification(transition)
            if (
                returned_after_unavailability
                and transition.kind is SourceTransitionKind.REPLACED
            ):
                # A missing pathname creates an observation gap. Even if the
                # returned descriptor can be verified against this one sample,
                # the path may have referenced unobserved content while it was
                # absent, so a later handover cannot claim continuity.
                self._mark_continuity_uncertain(
                    "The JSONL source was replaced; record continuity is uncertain."
                )
            if (
                transition.kind is not SourceTransitionKind.TRUNCATED
                and self._continuity_probe_changed(observation)
            ):
                self._truncation_pending = True
                self._mark_continuity_uncertain(
                    "The JSONL source changed near the observed offset; record "
                    "continuity is uncertain."
                )
            if transition.kind is SourceTransitionKind.TRUNCATED:
                self._truncation_pending = True
            return observation, transition, self._visible_continuity_warning()

    def _apply_observed_transition_classification(
        self,
        transition: SourceTransition,
    ) -> None:
        """Classify an observation without inferring proof from later polling.

        A replaced pathname is initially uncertain, rather than continuous:
        only the handover verifier can resolve that provisional state. A
        truncation and every detected skipped target are permanently
        uncertain, while a missing active pathname is currently unavailable.
        """
        classification = transition.classification
        if classification is SourceTransitionClassification.UNAVAILABLE:
            self._continuity_classification = classification
            return

        if self._continuity_uncertain:
            self._continuity_classification = (
                SourceTransitionClassification.CONTINUITY_UNCERTAIN
            )
            return

        if classification is SourceTransitionClassification.CONTINUITY_UNCERTAIN:
            warning = transition.continuity_warning
            assert warning is not None
            self._continuity_classification = classification
            self._continuity_warning = warning
            if transition.kind is SourceTransitionKind.REPLACED:
                self._continuity_verification_pending = True
            else:
                self._mark_continuity_uncertain(warning)
            return

        if self._continuity_verification_pending:
            # A readable target or a later growing size cannot establish
            # continuity. Keep the original replacement uncertain until the
            # retained predecessor and successor descriptor are verified.
            self._continuity_classification = (
                SourceTransitionClassification.CONTINUITY_UNCERTAIN
            )
            return

        self._continuity_classification = classification
        self._continuity_warning = None

    def _mark_continuity_uncertain(self, warning: str) -> None:
        """Record a proven ambiguity that cannot be cleared by later I/O."""
        self._continuity_warning = warning
        self._continuity_classification = (
            SourceTransitionClassification.CONTINUITY_UNCERTAIN
        )
        self._continuity_verification_pending = False
        self._continuity_uncertain = True
        self._continuity_warning_generation += 1

    def _visible_continuity_warning(self) -> str | None:
        """Expose a warning exactly when the current outcome is uncertain."""
        if (
            self._continuity_classification
            is SourceTransitionClassification.CONTINUITY_UNCERTAIN
        ):
            return self._continuity_warning
        return None

    def _publish_pending_continuity_warning(self) -> bool:
        """Acknowledge an explicit warning before delivering a later batch.

        A status request is separate from the append that eventually admits
        records.  If it cannot be acknowledged, the retained source batch is
        left in place and delivery retries it only after the warning has been
        published.  Normal verified rename/recreate handover never marks a
        warning generation, so it keeps its existing direct batch flow.
        """
        with self._source_state_lock:
            generation = self._continuity_warning_generation
            if generation <= self._published_continuity_warning_generation:
                return True
            callback = self.on_source_status
            if callback is None:
                # Standalone follower users have no browser transport to
                # update. The stream integration always supplies this hook.
                return True
            warning = self._visible_continuity_warning()
            if warning is None:
                return True
            status = SourceStatus(
                source_available=self._source_observation.available,
                source_transition=self._source_transition.kind.value,
                continuity_warning=warning,
            )

        try:
            acknowledged = callback(status)
        except Exception as error:
            self._report_error(error)
            return False
        if acknowledged is not True:
            return False

        with self._source_state_lock:
            self._published_continuity_warning_generation = max(
                self._published_continuity_warning_generation,
                generation,
            )
        return True

    def _open_source_handle(self, *, start_offset: int) -> _OpenJsonlSource | None:
        """Open the configured active path and retain its descriptor."""
        try:
            source_file = self.source.open("rb")
            opened_observation = _source_observation_from_stat(
                os.fstat(source_file.fileno())
            )
            if not opened_observation.available:
                source_file.close()
                return None
            source_file.seek(start_offset)
        except OSError as error:
            self._report_error(error)
            return None
        return _OpenJsonlSource(file=source_file, observation=opened_observation)

    def _ensure_active_source(
        self,
        observation: SourceObservation,
    ) -> _OpenJsonlSource | None:
        """Keep the current descriptor until a proven replacement is drained."""
        active_source = self._active_source
        if active_source is None:
            if not observation.available:
                self._rotation_state = "awaiting_active_source"
                return None
            active_source = self._open_source_handle(start_offset=self._read_offset)
            if active_source is not None:
                self._active_source = active_source
                self._rotation_state = "stable"
            return active_source

        if not observation.available:
            if not self._rotation_pending:
                self._rotation_state = "active_path_unavailable"
            return active_source

        if self._rotation_pending:
            self._track_pending_replacement(observation)

        if _same_file_identity(active_source.observation, observation):
            if self._truncation_pending and self._in_flight_batch is None:
                self._reset_after_truncation()
            return active_source

        if _different_file_identity(active_source.observation, observation):
            self._rotation_pending = True
            self._track_pending_replacement(observation)
            self._rotation_state = "draining_previous_source"
        return active_source

    def _track_pending_replacement(self, observation: SourceObservation) -> None:
        """Retain the first pending target and expose a skipped target gap."""
        pending = self._pending_replacement_observation
        if pending is not None and not _same_file_identity(pending, observation):
            # The old descriptor remains safe to drain, but a previously
            # observed replacement was itself replaced before we could open
            # it. Do not let a later successful handover imply completeness.
            self._record_continuity_warning(
                "The JSONL source changed during rotation; record continuity is "
                "uncertain."
            )
        self._pending_replacement_observation = observation

    def _reset_after_truncation(self) -> None:
        """Resume a same-file copy-truncate from byte zero with a warning."""
        self._truncation_pending = False
        self._rotation_state = "continuity_uncertain"
        self._reset_source_offsets()

    def _continuity_probe_changed(self, observation: SourceObservation) -> bool:
        """Detect a truncate-and-regrow rewrite that a size sample misses."""
        probe = self._continuity_probe
        active_source = self._active_source
        if (
            probe is None
            or active_source is None
            or not observation.available
            or not _same_file_identity(active_source.observation, observation)
        ):
            return False
        probe_offset, expected = probe
        if observation.size_bytes is None or observation.size_bytes < probe_offset:
            return False
        try:
            with self.source.open("rb") as source_file:
                source_file.seek(probe_offset)
                return source_file.read(len(expected)) != expected
        except OSError as error:
            self._report_error(error)
            return False

    def _capture_continuity_probe(self, source_end_offset: int) -> None:
        """Retain a tiny committed-byte sentinel for same-file rewrites."""
        active_source = self._active_source
        if active_source is None or source_end_offset <= 0:
            self._continuity_probe = None
            return
        start_offset = max(0, source_end_offset - CONTINUITY_PROBE_BYTES)
        try:
            active_source.file.seek(start_offset)
            sentinel = active_source.file.read(source_end_offset - start_offset)
        except OSError as error:
            self._report_error(error)
            return
        if len(sentinel) == source_end_offset - start_offset:
            self._continuity_probe = (start_offset, sentinel)

    def _switch_to_current_source(self) -> bool:
        """Switch only after an explicit predecessor and target verification."""
        if not self._rotation_pending or self._in_flight_batch is not None:
            return False

        active_source = self._active_source
        if active_source is None:
            return False
        if not self._predecessor_is_drained(active_source):
            # In particular, do not discard a partial old-file line merely
            # because the new pathname has become readable.
            return False
        observation, _, _ = self._observe_source_state()
        if not observation.available:
            self._rotation_state = "awaiting_replacement_source"
            return False
        self._track_pending_replacement(observation)
        if _same_file_identity(active_source.observation, observation):
            # The path returned to the retained source before a handover.
            self._rotation_pending = False
            self._pending_replacement_observation = None
            self._rotation_state = "stable"
            return False
        if not _different_file_identity(active_source.observation, observation):
            self._record_continuity_warning(
                "The JSONL source identity could not be verified during rotation; "
                "record continuity is uncertain."
            )
            return False

        replacement_source = self._open_source_handle(start_offset=0)
        if replacement_source is None:
            return False
        if not self._handover_target_is_verified(
            predecessor=active_source.observation,
            observed=observation,
            opened=replacement_source.observation,
        ):
            self._close_source_handle(replacement_source)
            self._record_continuity_warning(
                "The JSONL source changed during rotation; record continuity is "
                "uncertain."
            )
            return False

        self._active_source = replacement_source
        self._rotation_pending = False
        self._pending_replacement_observation = None
        self._rotation_state = "rotated"
        self._rotations_completed += 1
        self._reset_source_offsets()
        self._confirm_provably_continuous_handover()
        self._close_source_handle(active_source)
        return True

    def _predecessor_is_drained(self, active_source: _OpenJsonlSource) -> bool:
        """Verify no unaccounted complete source bytes precede a handover."""
        try:
            source_size = max(0, int(os.fstat(active_source.file.fileno()).st_size))
        except OSError as error:
            self._report_error(error)
            return False

        if self.on_batch is None:
            return self._read_offset >= source_size
        with self._source_offset_lock:
            return self._accounted_source_offset >= source_size

    @staticmethod
    def _handover_target_is_verified(
        *,
        predecessor: SourceObservation,
        observed: SourceObservation,
        opened: SourceObservation,
    ) -> bool:
        """Require identity proof for both sides of a replacement handover."""
        return _different_file_identity(predecessor, observed) and _same_file_identity(
            observed,
            opened,
        )

    def _reset_source_offsets(self) -> None:
        """Start source accounting at byte zero for a newly opened file."""
        self._read_offset = 0
        self._line_start_offset = 0
        self._partial_line = b""
        self._discarding_oversize_line = False
        self._oversized_partial_line_start = None
        self._oversized_partial_scan_offset = None
        self._continuity_probe = None
        with self._source_offset_lock:
            self._acknowledged_source_offset = 0
            self._accounted_source_offset = 0
            self._candidate_source_offset = 0

    def _close_source_handle(self, source: _OpenJsonlSource) -> None:
        try:
            source.file.close()
        except OSError as error:
            self._report_error(error)

    def _active_source_size(self) -> int | None:
        active_source = self._active_source
        if active_source is None:
            return None
        try:
            return max(0, int(os.fstat(active_source.file.fileno()).st_size))
        except OSError as error:
            self._report_error(error)
            return None

    def _record_continuity_warning(self, warning: str) -> None:
        with self._source_state_lock:
            self._mark_continuity_uncertain(warning)

    def _confirm_provably_continuous_handover(self) -> None:
        """Resolve only a verified replacement that has no observed loss."""
        with self._source_state_lock:
            if self._continuity_uncertain:
                # A replacement can become readable and fully drain after a
                # skipped target or start/open race. That does not prove the
                # earlier missing records were ever observed.
                self._continuity_classification = (
                    SourceTransitionClassification.CONTINUITY_UNCERTAIN
                )
                return
            self._continuity_verification_pending = False
            self._continuity_classification = (
                SourceTransitionClassification.PROVABLY_CONTINUOUS
            )
            self._continuity_warning = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._read_available_records()
            except FileNotFoundError:
                # A source absent at registration is intentionally normal.
                self._observe_source_state()
            except OSError as exc:
                self._report_error(exc)

            retry_delay = 0.0
            if self.on_batch is not None and self.retry_delay is not None:
                try:
                    retry_delay = max(0.0, self.retry_delay())
                except Exception as error:
                    self._report_error(error)
            self._stop_event.wait(max(self.poll_interval_s, retry_delay))

    def _read_available_records(self) -> None:
        observation, _, _ = self._observe_source_state()
        active_source = self._ensure_active_source(observation)
        if active_source is None:
            return
        if self.on_batch is not None:
            self._deliver_candidate_batch()
            return

        self._read_active_records()

    def _read_active_records(self) -> None:
        """Read one direct-callback chunk from the retained active descriptor."""
        for _ in range(2):
            active_source = self._active_source
            if active_source is None:
                return
            source_file = active_source.file
            source_file.seek(self._read_offset)
            chunk = source_file.read(READ_CHUNK_BYTES)
            if chunk:
                break
            if not self._switch_to_current_source():
                return
        else:
            return

        self._read_offset += len(chunk)
        if self._discarding_oversize_line:
            newline = chunk.find(b"\n")
            if newline < 0:
                self._line_start_offset += len(chunk)
                return

            # Everything through this newline belongs to the oversized
            # record already rejected when it crossed the fixed buffer limit.
            self._line_start_offset += newline + 1
            self._discarding_oversize_line = False
            records = chunk[newline + 1 :]
        else:
            records = self._partial_line + chunk

        while True:
            newline = records.find(b"\n")
            if newline < 0:
                if len(records) > min(
                    MAX_JSONL_RECORD_BYTES,
                    MAX_JSONL_PARTIAL_LINE_BYTES,
                ):
                    self._reject_oversize_record()
                    # Advance the offset through bytes no longer retained so
                    # that the first subsequent complete line gets its real
                    # source position when a later chunk supplies a newline.
                    self._line_start_offset += len(records)
                    self._partial_line = b""
                    self._discarding_oversize_line = True
                    return
                self._partial_line = records
                return

            raw_line = records[:newline]
            source_start = self._line_start_offset
            self._line_start_offset += newline + 1
            records = records[newline + 1 :]

            if len(raw_line) > MAX_JSONL_RECORD_BYTES:
                self._reject_oversize_record()
                continue

            if raw_line.endswith(b"\r"):
                raw_line = raw_line[:-1]
            if not raw_line.strip():
                continue

            self._emit_record(
                raw_line,
                source_start=source_start,
                source_end=self._line_start_offset,
            )

    def _emit_record(self, raw_line: bytes, *, source_start: int, source_end: int) -> None:
        try:
            decoded = raw_line.decode("utf-8")
            # Python's decoder accepts NaN and Infinity by default even though
            # neither is a JSON value.  A stream source must retain only JSON
            # objects so malformed records are rejected without stopping the
            # follower.
            data = json.loads(
                decoded,
                parse_constant=_reject_nonstandard_json_constant,
                parse_float=_parse_finite_json_float,
            )
            validate_stream_record(data)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            # ValueError covers JSONDecodeError, Python's configured integer
            # conversion limit, and strict stream-wire validation. A deeply
            # nested but otherwise valid line can raise RecursionError inside
            # the standard decoder. In every case this one line is rejected
            # and the already-extracted following lines continue normally.
            self.records_rejected += 1
            self._report_error(exc)
            return

        record = JsonlRecord(
            data=data,
            source_offset=source_start,
            source_end_offset=source_end,
            observed_at=datetime.now(UTC),
        )
        self.records_seen += 1

        self._capture_continuity_probe(source_end)

        if self.on_record is None:
            return

        try:
            self.on_record(record)
        except Exception as exc:
            # Source observation must continue if a future transport callback
            # encounters an error. Delivery acknowledgement is intentionally a
            # later stream-protocol concern.
            self._report_error(exc)

    def _deliver_candidate_batch(
        self,
        *,
        on_batch: BatchCallback | None = None,
    ) -> bool:
        """Deliver one retained batch and advance only on acknowledgement.

        Batch mode intentionally does not scan past the candidate batch.  Any
        later logfile growth therefore remains in the source file while a
        delivery is pending, rather than becoming a process-memory queue.
        """
        batch = self._in_flight_batch
        if batch is None:
            batch = self._build_candidate_batch()
            if batch is None and self._switch_to_current_source():
                batch = self._build_candidate_batch()
            if batch is None:
                return False
            with self._source_offset_lock:
                self._candidate_source_offset = batch.source_end_offset
            self._in_flight_batch = batch

        try:
            if not self._publish_pending_continuity_warning():
                return False
            callback = self.on_batch if on_batch is None else on_batch
            if callback is None:
                return False
            acknowledged = callback(batch)
        except Exception as error:
            self._report_error(error)
            return False

        if acknowledged is not True:
            # A false result is the normal backpressure signal from the
            # transport while its bounded retry window is active.
            return False

        with self._source_offset_lock:
            self._acknowledged_source_offset = batch.source_end_offset
            self._accounted_source_offset = batch.source_end_offset
            self._candidate_source_offset = batch.source_end_offset
        self._in_flight_batch = None
        self._capture_continuity_probe(batch.source_end_offset)
        return True

    def _build_candidate_batch(self) -> JsonlBatch | None:
        """Read at most one bounded batch from accounted source progress."""
        active_source = self._active_source
        if active_source is None:
            return None
        with self._source_offset_lock:
            source_offset = self._accounted_source_offset

        accounted_source_offset = source_offset
        records: list[JsonlRecord] = []
        batch_bytes = 0
        source_end_offset = source_offset
        line_limit = min(MAX_JSONL_RECORD_BYTES, MAX_JSONL_PARTIAL_LINE_BYTES)
        source_file = active_source.file
        source_file.seek(source_offset)
        while len(records) < MAX_BATCH_RECORDS:
            line_offset = source_end_offset
            if self._oversized_partial_line_start == line_offset:
                line_end_offset = self._finish_oversized_partial_line(
                    source_file,
                    line_start_offset=line_offset,
                )
                if line_end_offset is None:
                    break
                self._reject_oversize_record()
                source_end_offset = line_end_offset
                if not records:
                    accounted_source_offset = source_end_offset
                continue

            raw_line = source_file.readline(line_limit + 1)
            if not raw_line:
                break
            if len(raw_line) > line_limit:
                if raw_line.endswith(b"\n"):
                    line_end_offset = line_offset + len(raw_line)
                else:
                    line_end_offset = self._finish_oversized_partial_line(
                        source_file,
                        line_start_offset=line_offset,
                    )
                    if line_end_offset is None:
                        break
                self._reject_oversize_record()
                source_end_offset = line_end_offset
                if not records:
                    accounted_source_offset = source_end_offset
                continue
            if not raw_line.endswith(b"\n"):
                # Retain neither a partial record nor a growing in-memory
                # buffer. A completed oversized record is handled separately
                # above once its newline arrives.
                break

            line_end_offset = line_offset + len(raw_line)
            decoded_line = raw_line[:-1]
            if decoded_line.endswith(b"\r"):
                decoded_line = decoded_line[:-1]
            if not decoded_line.strip():
                source_end_offset = line_end_offset
                if not records:
                    accounted_source_offset = source_end_offset
                continue

            try:
                record_data = self._parse_record(decoded_line)
            except (UnicodeDecodeError, ValueError, RecursionError) as error:
                # A completed malformed line cannot receive a server
                # acknowledgement, so account it once and continue to the
                # following source record.
                self.records_rejected += 1
                self._report_error(error)
                source_end_offset = line_end_offset
                if not records:
                    accounted_source_offset = source_end_offset
                continue

            record_bytes = stream_record_size(record_data)
            if records and batch_bytes + record_bytes > MAX_BATCH_BYTES:
                break

            records.append(
                JsonlRecord(
                    data=record_data,
                    source_offset=line_offset,
                    source_end_offset=line_end_offset,
                    observed_at=datetime.now(UTC),
                )
            )
            batch_bytes += record_bytes
            source_end_offset = line_end_offset

        if accounted_source_offset > source_offset:
            self._advance_accounted_source_offset(accounted_source_offset)
            source_offset = accounted_source_offset

        if not records:
            return None
        self.records_seen += len(records)
        return JsonlBatch(
            batch_id=uuid4().hex,
            records=tuple(records),
            source_offset=source_offset,
            source_end_offset=source_end_offset,
        )

    def _finish_oversized_partial_line(
        self,
        source_file: Any,
        *,
        line_start_offset: int,
    ) -> int | None:
        """Find an oversized line's newline without retaining its contents."""
        if self._oversized_partial_line_start == line_start_offset:
            scan_offset = self._oversized_partial_scan_offset
        else:
            scan_offset = int(source_file.tell())
            self._oversized_partial_line_start = line_start_offset

        assert scan_offset is not None
        source_file.seek(scan_offset)
        while True:
            chunk = source_file.read(READ_CHUNK_BYTES)
            if not chunk:
                self._oversized_partial_scan_offset = scan_offset
                return None
            newline = chunk.find(b"\n")
            if newline >= 0:
                line_end_offset = scan_offset + newline + 1
                source_file.seek(line_end_offset)
                self._oversized_partial_line_start = None
                self._oversized_partial_scan_offset = None
                return line_end_offset
            scan_offset += len(chunk)

    def _advance_accounted_source_offset(self, source_offset: int) -> None:
        """Commit a non-deliverable completed source line exactly once."""
        with self._source_offset_lock:
            if source_offset <= self._accounted_source_offset:
                return
            self._accounted_source_offset = source_offset
            self._candidate_source_offset = source_offset
        self._capture_continuity_probe(source_offset)

    def _parse_record(self, raw_line: bytes) -> dict[str, Any]:
        decoded = raw_line.decode("utf-8")
        # Python's decoder accepts NaN and Infinity by default even though
        # neither is a JSON value.  A stream source must retain only JSON
        # objects so malformed records do not reach the transport.
        data = json.loads(
            decoded,
            parse_constant=_reject_nonstandard_json_constant,
            parse_float=_parse_finite_json_float,
        )
        validate_stream_record(data)
        return data

    def _reject_oversize_record(self) -> None:
        self.records_rejected += 1
        self._report_error(
            ValueError(
                "JSONL source record exceeds the "
                f"{MAX_JSONL_RECORD_BYTES}-byte temporary limit"
            )
        )

    def _report_error(self, error: BaseException) -> None:
        self.last_error = error
        if self.on_error is not None:
            try:
                self.on_error(error)
                return
            except Exception:
                pass
        logger.debug(
            "Unable to process JSONL stream record from %s",
            self.source,
            exc_info=error,
        )


def _source_label(source: Path) -> str:
    """Return a bounded basename suitable for source-status metadata."""
    label = source.name.strip()
    return label[:128] or "JSONL source"


def _safe_source_error_text(error: BaseException | None) -> str | None:
    """Return a browser-safe source diagnostic without raw OS details."""
    if error is None:
        return None
    if isinstance(error, FileNotFoundError):
        return "The JSONL source is temporarily unavailable."
    if isinstance(error, PermissionError):
        return "The JSONL source cannot be read."
    if isinstance(error, OSError):
        return "The JSONL source could not be read."
    if isinstance(
        error,
        (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError),
    ):
        return "A JSONL source record was rejected."
    return "The JSONL source could not be processed."
