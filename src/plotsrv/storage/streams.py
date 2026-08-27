"""Bounded, summary-first file storage for observed stream sessions.

This module owns only the stable v1 on-disk representation.  It deliberately
does not observe streams, enqueue background work, or restore a live transport
session; those concerns remain with the stream registry and its future
admission worker.  Keeping this boundary small makes a storage failure
recoverable without changing live observation.

Layout (components are slugged and hash-suffixed to avoid collisions)::

    <storage-root>/streams/
      <logical-view>/
        <session>/
          session.json
          summaries.jsonl                # first generation
          noteworthy.jsonl               # first generation
          summaries-<generation>.jsonl   # replacement generation, if any
          noteworthy-<generation>.jsonl  # replacement generation, if any
          durable-history-incomplete.json  # only after a durable gap
          raw/                 # created only by an explicit raw opt-in

The first generation uses the short documented JSONL names.  Later replacements
stage immutable generation-suffixed files and atomically publish their names in
``session.json``.  A metadata write occurs last, and every compact file carries
the same committed generation identifier; a mixed crash generation is rejected
rather than restored. This is stream *observation* history, not an audit log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import threading
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from . import backend as storage_backend


STREAM_STORAGE_FORMAT_VERSION = 1
STREAM_STORAGE_DIRECTORY = "streams"
_SESSION_METADATA_NAME = "session.json"
_SUMMARIES_NAME = "summaries.jsonl"
_NOTEWORTHY_NAME = "noteworthy.jsonl"
_INCOMPLETE_MARKER_NAME = "durable-history-incomplete.json"
_COMPACT_FILE_NAMES = (
    _SESSION_METADATA_NAME,
    _SUMMARIES_NAME,
    _NOTEWORTHY_NAME,
)

# Multiple worker and request-side backend instances can target one root at
# once.  Retention planning, cleanup, and the following atomic replacement
# must share one transaction lock across those instances; an instance-local
# lock permits concurrent writers to both admit against the same old view.
_ROOT_TRANSACTION_LOCKS: dict[Path, threading.RLock] = {}
_ROOT_TRANSACTION_LOCKS_GUARD = threading.Lock()


class StreamStorageError(RuntimeError):
    """Base error for a rejected or failed compact stream write."""


class StreamStorageValidationError(StreamStorageError):
    """The proposed compact session state does not fit the v1 format."""


class StreamStorageCapacityError(StreamStorageError):
    """The hard per-view byte ceiling would be exceeded by this write."""


def _transaction_lock_for_root(root_dir: Path) -> threading.RLock:
    """Return the shared stream-storage transaction lock for one root."""
    with _ROOT_TRANSACTION_LOCKS_GUARD:
        lock = _ROOT_TRANSACTION_LOCKS.get(root_dir)
        if lock is None:
            lock = threading.RLock()
            _ROOT_TRANSACTION_LOCKS[root_dir] = lock
        return lock


@dataclass(frozen=True, slots=True)
class RawBlockPolicy:
    """Finite retention applied simultaneously to explicit raw blocks."""

    max_blocks: int
    max_bytes: int
    max_age_s: int | None = None

    def __post_init__(self) -> None:
        if self.max_blocks < 1:
            raise ValueError("max_blocks must be at least one")
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be at least one")
        if self.max_age_s is not None and self.max_age_s < 1:
            raise ValueError("max_age_s must be at least one when configured")


@dataclass(frozen=True, slots=True)
class StreamStoragePolicy:
    """Every bounded retention setting used by one compact session write."""

    summary_retention: int
    noteworthy_keep_last: int
    keep_last_sessions: int
    max_bytes_per_view: int

    def __post_init__(self) -> None:
        for field_name in (
            "summary_retention",
            "noteworthy_keep_last",
            "keep_last_sessions",
            "max_bytes_per_view",
        ):
            if getattr(self, field_name) < 1:
                raise ValueError(f"{field_name} must be at least one")


@dataclass(frozen=True, slots=True)
class StreamSessionPaths:
    """Resolved files for a single logical view/session pair."""

    view_dir: Path
    session_dir: Path
    metadata: Path
    summaries: Path
    noteworthy: Path
    raw_dir: Path
    incomplete_marker: Path


@dataclass(frozen=True, slots=True)
class CompactSessionWrite:
    """Result metadata for one successful compact, raw-free session write."""

    paths: StreamSessionPaths
    summary_count: int
    noteworthy_count: int
    byte_count: int
    pruned_session_count: int


@dataclass(frozen=True, slots=True)
class RawBlockWrite:
    """Result metadata for one explicitly enabled bounded raw block."""

    path: Path
    record_count: int
    byte_count: int
    pruned_block_count: int


@dataclass(frozen=True, slots=True)
class StoredStreamSession:
    """One validated, compact-only stream session loaded from v1 storage.

    Raw blocks are intentionally excluded. A restored session is observation
    history, not a resumed transport or a full source-log replay.
    """

    metadata: dict[str, Any]
    summary_windows: tuple[dict[str, Any], ...]
    noteworthy_items: tuple[dict[str, Any], ...]

    @property
    def view_id(self) -> str:
        return str(self.metadata["view_id"])

    @property
    def session_id(self) -> str:
        return str(self.metadata["session_id"])

    @property
    def updated_at(self) -> str:
        return str(self.metadata.get("updated_at") or "")


@dataclass(frozen=True, slots=True)
class StoredStreamGap:
    """One validated durable-gap marker with no loadable compact session.

    A hard byte ceiling can preserve this small irreversibility marker after
    evicting a much larger compact payload.  It is still useful historical
    evidence: restoration presents it as an incomplete session instead of
    silently making the session disappear.
    """

    view_id: str
    session_id: str
    recorded_at: str
    last_error: str


@dataclass(frozen=True, slots=True)
class StoredStreamView:
    """One logical stream-storage view for store command presentation.

    The filesystem components are deliberately opaque and collision-safe, so
    store tooling reports identities recovered from versioned metadata rather
    than exposing those implementation paths.
    """

    view_id: str
    session_count: int
    total_bytes: int
    last_updated_at: str | None
    raw_block_count: int
    incomplete_session_count: int


@dataclass(frozen=True, slots=True)
class _RawBlockCandidate:
    path: Path
    size_bytes: int
    expired: bool


class FileStreamStorageBackend:
    """Dedicated v1 file backend for bounded compact stream state.

    The backend is intentionally lazy: constructing it or asking for paths
    does not create ``streams/``.  Therefore a storage-disabled server that
    never submits a stream write leaves no stream-content directory behind.
    """

    def __init__(self, *, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()
        self._lock = _transaction_lock_for_root(self.root_dir)

    @property
    def streams_root(self) -> Path:
        """The dedicated stream root, without creating it as a side effect."""
        return self.root_dir / STREAM_STORAGE_DIRECTORY

    def session_paths(self, *, view_id: str, session_id: str) -> StreamSessionPaths:
        """Return collision-safe layout paths without writing anything."""
        view_component = _path_component(view_id, label="view_id")
        session_component = _path_component(session_id, label="session_id")
        view_dir = self.streams_root / view_component
        session_dir = view_dir / session_component
        return StreamSessionPaths(
            view_dir=view_dir,
            session_dir=session_dir,
            metadata=session_dir / _SESSION_METADATA_NAME,
            summaries=session_dir / _SUMMARIES_NAME,
            noteworthy=session_dir / _NOTEWORTHY_NAME,
            raw_dir=session_dir / "raw",
            incomplete_marker=session_dir / _INCOMPLETE_MARKER_NAME,
        )

    def write_compact_session(
        self,
        *,
        view_id: str,
        session_id: str,
        client_id: str,
        metadata: Mapping[str, Any],
        summary_windows: Sequence[Mapping[str, Any]],
        noteworthy_items: Sequence[Mapping[str, Any]],
        policy: StreamStoragePolicy,
    ) -> CompactSessionWrite:
        """Atomically replace the bounded raw-free state for one session.

        ``summary_windows`` and ``noteworthy_items`` are always tail-trimmed
        before serialisation.  The complete view is checked against its hard
        byte ceiling before existing stream history is pruned.  This method
        deliberately never creates ``raw/`` and rejects summary objects that
        look like raw row collections.
        """
        _require_identity(view_id, "view_id")
        _require_identity(session_id, "session_id")
        _require_identity(client_id, "client_id")
        compact_metadata = _compact_mapping(metadata, kind="session metadata")
        summaries = _bounded_mappings(
            summary_windows,
            limit=policy.summary_retention,
            kind="summary",
            reject_raw=True,
        )
        noteworthy = _bounded_mappings(
            noteworthy_items,
            limit=policy.noteworthy_keep_last,
            kind="noteworthy",
            reject_raw=False,
        )
        paths = self.session_paths(view_id=view_id, session_id=session_id)
        written_at = datetime.now(UTC).isoformat()
        generation_id = uuid.uuid4().hex
        summary_bytes = _jsonl_bytes(
            kind="summary",
            view_id=view_id,
            session_id=session_id,
            written_at=written_at,
            generation_id=generation_id,
            items=summaries,
        )
        noteworthy_bytes = _jsonl_bytes(
            kind="noteworthy",
            view_id=view_id,
            session_id=session_id,
            written_at=written_at,
            generation_id=generation_id,
            items=noteworthy,
        )
        with self._lock:
            previous_summaries, previous_noteworthy = self._active_compact_paths(paths)
            had_committed_metadata = paths.metadata.exists()
            # An initial compact write retains the documented v1 names.  A
            # replacement writes immutable generation files and publishes them
            # by atomically replacing session.json.  Until that final commit,
            # the previous metadata and its files remain loadable.
            if had_committed_metadata:
                summaries_path = paths.session_dir / f"summaries-{generation_id}.jsonl"
                noteworthy_path = paths.session_dir / f"noteworthy-{generation_id}.jsonl"
            else:
                summaries_path = paths.summaries
                noteworthy_path = paths.noteworthy
            metadata_bytes = _json_bytes(
                {
                    "object_type": "plotsrv_stream_session",
                    "storage_format": "plotsrv.stream-storage",
                    "storage_format_version": STREAM_STORAGE_FORMAT_VERSION,
                    "view_id": view_id,
                    "session_id": session_id,
                    "client_id": client_id,
                    "updated_at": written_at,
                    "compact_state": {
                        "summaries_filename": summaries_path.name,
                        "summary_count": len(summaries),
                        "noteworthy_filename": noteworthy_path.name,
                        "noteworthy_count": len(noteworthy),
                        "generation_id": generation_id,
                        "raw_persistence": "not_written_by_compact_storage",
                    },
                    "metadata": compact_metadata,
                },
                indent=2,
            )
            session_dirs, raw_paths = self._plan_bounded_replacement(
                paths=paths,
                policy=policy,
                replacement_bytes=(
                    len(metadata_bytes) + len(summary_bytes) + len(noteworthy_bytes)
                ),
                replaced_files=(
                    paths.metadata,
                    previous_summaries,
                    previous_noteworthy,
                ),
            )
            # Stage both generation files before metadata publishes them.  On
            # an I/O failure, the previous metadata still points at its prior
            # complete generation and retained historical sessions have not
            # been touched.  The small temporary overage is bounded to this
            # transaction; successful commits immediately run the planned
            # retention cleanup below.
            try:
                storage_backend._write_bytes_atomic(summaries_path, summary_bytes)
                storage_backend._write_bytes_atomic(noteworthy_path, noteworthy_bytes)
                # Metadata is the sole generation commit record and is written
                # last.  A mixed crash generation is therefore never restored.
                storage_backend._write_bytes_atomic(paths.metadata, metadata_bytes)
            except Exception:
                # Candidate files are not referenced until metadata commits;
                # remove them best-effort without ever deleting the prior
                # loadable generation.  An initial write has no committed
                # metadata, so its conventional filenames are candidates too;
                # remove that incomplete directory rather than mistaking the
                # fallback names for an older generation.
                if had_committed_metadata:
                    for candidate in (summaries_path, noteworthy_path):
                        candidate.unlink(missing_ok=True)
                elif paths.session_dir.exists():
                    _remove_session_directory(paths.session_dir, paths.view_dir)
                raise

            # Only a durable metadata commit permits retention to discard old
            # sessions, raw blocks, and the superseded compact generation.
            self._apply_cleanup(session_dirs=session_dirs, raw_paths=raw_paths)
            for previous in (previous_summaries, previous_noteworthy):
                if previous not in (summaries_path, noteworthy_path):
                    previous.unlink(missing_ok=True)

            return CompactSessionWrite(
                paths=paths,
                summary_count=len(summaries),
                noteworthy_count=len(noteworthy),
                byte_count=self._view_byte_count(paths.view_dir),
                pruned_session_count=len(session_dirs),
            )

    def mark_session_incomplete(
        self,
        *,
        view_id: str,
        session_id: str,
        reason: str,
        policy: StreamStoragePolicy,
    ) -> None:
        """Persist an irreversible durable-history gap when possible.

        Queue rejection or a later worker failure can happen after an older
        compact snapshot has already been admitted.  This small independent
        marker prevents that stale snapshot from being restored as complete.
        It intentionally remains for the session: one missed observation means
        the observed history can never become an authoritative complete log.
        """
        _require_identity(view_id, "view_id")
        _require_identity(session_id, "session_id")
        text = str(reason).strip() or "stream persistence was incomplete"
        if len(text) > 1_024:
            text = text[:1_024]
        paths = self.session_paths(view_id=view_id, session_id=session_id)
        marker = {
            "object_type": "plotsrv_stream_durable_history_gap",
            "storage_format": "plotsrv.stream-storage",
            "storage_format_version": STREAM_STORAGE_FORMAT_VERSION,
            "view_id": view_id,
            "session_id": session_id,
            "state": "incomplete",
            "recorded_at": datetime.now(UTC).isoformat(),
            "last_error": text,
        }
        marker_bytes = _json_bytes(marker, indent=2)
        with self._lock:
            try:
                session_dirs, raw_paths = self._plan_bounded_replacement(
                    paths=paths,
                    policy=policy,
                    replacement_bytes=len(marker_bytes),
                    replaced_files=(paths.incomplete_marker,),
                    allow_target_session_eviction=True,
                )
            except StreamStorageCapacityError:
                # If even the minimal marker cannot fit, retaining a stale
                # complete session would be worse than dropping it.  Remove
                # the target (and apply the current bound to older history)
                # so restart can never falsely restore that session as
                # complete.  There is intentionally no marker-only directory
                # when the configured cap cannot contain the marker itself.
                if paths.session_dir.exists():
                    _remove_session_directory(paths.session_dir, paths.view_dir)
                self._prune_view_sessions(
                    view_dir=paths.view_dir,
                    keep_last_sessions=policy.keep_last_sessions,
                    protected_session=None,
                )
                self._enforce_view_byte_limit(
                    view_dir=paths.view_dir,
                    maximum=policy.max_bytes_per_view,
                    protected_session=None,
                )
                return
            target_evicted = paths.session_dir in session_dirs
            if target_evicted:
                # The compact target itself must go before the marker can fit.
                # Once removed it can no longer be restored as complete even
                # if the following marker write encounters an I/O failure.
                _remove_session_directory(paths.session_dir, paths.view_dir)
                session_dirs = [
                    session_dir
                    for session_dir in session_dirs
                    if session_dir != paths.session_dir
                ]
                try:
                    storage_backend._write_bytes_atomic(
                        paths.incomplete_marker, marker_bytes
                    )
                except Exception:
                    # The stale target has already been invalidated above.
                    raise
                self._apply_cleanup(session_dirs=session_dirs, raw_paths=raw_paths)
                return

            # Publish the irreversible gap before pruning unrelated retained
            # history.  If this write itself fails, remove the target compact
            # state so an older complete snapshot cannot be restart-restored.
            try:
                storage_backend._write_bytes_atomic(paths.incomplete_marker, marker_bytes)
            except Exception:
                if paths.session_dir.exists():
                    _remove_session_directory(paths.session_dir, paths.view_dir)
                raise
            self._apply_cleanup(session_dirs=session_dirs, raw_paths=raw_paths)

    def enforce_view_retention(
        self,
        *,
        view_id: str,
        policy: StreamStoragePolicy,
        raw_policy: RawBlockPolicy | None = None,
    ) -> int:
        """Apply current session and hard-byte retention to existing history.

        This is used at startup as well as before writes.  If limits were
        lowered while plotsrv was offline, stale raw blocks are removed first,
        then oldest complete sessions; keeping a stale over-limit tree forever
        is worse than dropping bounded observational history.
        """
        _require_identity(view_id, "view_id")
        view_dir = self.streams_root / _path_component(view_id, label="view_id")
        with self._lock:
            # A process can stop after compact candidates are staged but before
            # metadata commits them.  Discard those candidates before any
            # retention decision so an uncommitted directory can never evict a
            # loadable prior session merely by looking newer or larger.
            pruned = self._discard_uncommitted_compact_state(view_dirs=(view_dir,))
            pruned += self._prune_view_sessions(
                view_dir=view_dir,
                keep_last_sessions=policy.keep_last_sessions,
                protected_session=None,
            )
            pruned += self._prune_view_raw_blocks(
                view_dir=view_dir,
                raw_policy=raw_policy,
            )
            return pruned + self._enforce_view_byte_limit(
                view_dir=view_dir,
                maximum=policy.max_bytes_per_view,
                protected_session=None,
            )

    def discard_uncommitted_compact_state(self) -> int:
        """Remove crash-left compact candidates before startup retention.

        Compact candidates are intentionally written before ``session.json``
        commits them.  They are never observed as durable history until that
        metadata replacement succeeds, so recovery must remove candidate-only
        directories and superseded compact files before applying session or
        byte limits.  This is distinct from ordinary retention: it never drops
        a metadata-committed or valid gap-marked session.
        """
        with self._lock:
            if not self.streams_root.exists():
                return 0
            view_dirs = tuple(
                path for path in self.streams_root.iterdir() if path.is_dir()
            )
            return self._discard_uncommitted_compact_state(view_dirs=view_dirs)

    def read_session_metadata(
        self, *, view_id: str, session_id: str
    ) -> dict[str, Any]:
        """Read one complete v1 metadata file without restoring stream state."""
        paths = self.session_paths(view_id=view_id, session_id=session_id)
        try:
            raw = json.loads(paths.metadata.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise LookupError(f"Stored stream session not found: {session_id}") from error
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise LookupError(f"Stored stream session metadata is invalid: {session_id}") from error
        if not isinstance(raw, dict) or raw.get("storage_format_version") != STREAM_STORAGE_FORMAT_VERSION:
            raise LookupError(f"Stored stream session format is unsupported: {session_id}")
        return raw

    def load_compact_session(
        self, *, view_id: str, session_id: str
    ) -> StoredStreamSession:
        """Load a complete v1 compact session without reading raw blocks.

        Every JSONL envelope repeats the logical view and session identities,
        so a stale or manually misplaced file cannot be associated with a
        different session merely because it shares a generated directory.
        """
        metadata = self.read_session_metadata(view_id=view_id, session_id=session_id)
        if metadata.get("view_id") != view_id or metadata.get("session_id") != session_id:
            raise LookupError("Stored stream session identity does not match its path")
        if not isinstance(metadata.get("metadata"), dict):
            raise LookupError("Stored stream session compact metadata is invalid")
        compact_state = metadata.get("compact_state")
        if not isinstance(compact_state, Mapping):
            raise LookupError("Stored stream session compact state is invalid")
        written_at = metadata.get("updated_at")
        if not isinstance(written_at, str) or not written_at:
            raise LookupError("Stored stream session update time is invalid")
        generation_id = compact_state.get("generation_id")
        if generation_id is not None and (
            not isinstance(generation_id, str) or not generation_id
        ):
            raise LookupError("Stored stream session generation is invalid")
        summary_count = _compact_count(compact_state.get("summary_count"), "summary")
        noteworthy_count = _compact_count(
            compact_state.get("noteworthy_count"), "noteworthy"
        )
        paths = self.session_paths(view_id=view_id, session_id=session_id)
        summaries_path = _compact_filename_path(
            paths.session_dir,
            compact_state.get("summaries_filename"),
            fallback=paths.summaries,
            required_prefix="summaries",
        )
        noteworthy_path = _compact_filename_path(
            paths.session_dir,
            compact_state.get("noteworthy_filename"),
            fallback=paths.noteworthy,
            required_prefix="noteworthy",
        )
        summaries = self._read_compact_jsonl(
            path=summaries_path,
            kind="summary",
            view_id=view_id,
            session_id=session_id,
            written_at=written_at,
            generation_id=generation_id,
            expected_count=summary_count,
        )
        noteworthy = self._read_compact_jsonl(
            path=noteworthy_path,
            kind="noteworthy",
            view_id=view_id,
            session_id=session_id,
            written_at=written_at,
            generation_id=generation_id,
            expected_count=noteworthy_count,
        )
        self._apply_incomplete_marker(
            metadata=metadata,
            path=paths.incomplete_marker,
            view_id=view_id,
            session_id=session_id,
        )
        return StoredStreamSession(
            metadata=metadata,
            summary_windows=tuple(summaries),
            noteworthy_items=tuple(noteworthy),
        )

    def list_compact_sessions(self) -> list[StoredStreamSession]:
        """List valid compact sessions newest-first, skipping damaged files.

        Startup restoration is best effort just like storage writes. A corrupt
        session must not prevent another view's bounded history from loading.
        """
        if not self.streams_root.exists():
            return []
        sessions: list[StoredStreamSession] = []
        for metadata_path in self.streams_root.glob(f"*/*/{_SESSION_METADATA_NAME}"):
            try:
                raw = json.loads(metadata_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    continue
                view_id = raw.get("view_id")
                session_id = raw.get("session_id")
                if not isinstance(view_id, str) or not isinstance(session_id, str):
                    continue
                expected = self.session_paths(
                    view_id=view_id, session_id=session_id
                ).metadata
                if expected != metadata_path:
                    continue
                sessions.append(
                    self.load_compact_session(
                        view_id=view_id, session_id=session_id
                    )
                )
            except (LookupError, OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(
            sessions,
            key=lambda session: (session.updated_at, session.view_id, session.session_id),
            reverse=True,
        )

    def list_marker_only_sessions(self) -> list[StoredStreamGap]:
        """List valid durable gaps that have no loadable compact counterpart.

        A valid marker is stronger evidence than a stale or damaged compact
        payload.  If a compact session cannot be loaded, restore the marker as
        a visibly incomplete historical session rather than losing the fact
        that persistence was incomplete at the configured byte ceiling.
        """
        if not self.streams_root.exists():
            return []
        gaps: list[StoredStreamGap] = []
        for marker_path in self.streams_root.glob(
            f"*/*/{_INCOMPLETE_MARKER_NAME}"
        ):
            try:
                gap = self._read_stored_gap(marker_path)
                paths = self.session_paths(
                    view_id=gap.view_id, session_id=gap.session_id
                )
                if paths.incomplete_marker != marker_path:
                    continue
                try:
                    self.load_compact_session(
                        view_id=gap.view_id, session_id=gap.session_id
                    )
                except LookupError:
                    gaps.append(gap)
            except (
                LookupError,
                OSError,
                StreamStorageValidationError,
                ValueError,
                json.JSONDecodeError,
            ):
                continue
        return sorted(
            gaps,
            key=lambda gap: (gap.recorded_at, gap.view_id, gap.session_id),
            reverse=True,
        )

    def load_raw_records(
        self, *, view_id: str, session_id: str
    ) -> tuple[dict[str, Any], ...]:
        """Load explicitly retained raw segments for one validated session.

        Compact restoration deliberately works without raw blocks.  This
        separate opt-in reader lets the historical browser expose the bounded
        segments that were explicitly persisted, while rejecting a malformed
        segment rather than mistaking it for source data.
        """
        _require_identity(view_id, "view_id")
        _require_identity(session_id, "session_id")
        paths = self.session_paths(view_id=view_id, session_id=session_id)
        if not paths.raw_dir.is_dir():
            return ()
        records: list[dict[str, Any]] = []
        for raw_path in sorted(paths.raw_dir.glob("*.jsonl")):
            try:
                block_id = raw_path.stem
                _require_block_id(block_id)
                lines = raw_path.read_text(encoding="utf-8").splitlines()
            except (OSError, StreamStorageValidationError) as error:
                raise LookupError("Stored stream raw history is invalid") from error
            for line in lines:
                try:
                    envelope = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError) as error:
                    raise LookupError("Stored stream raw history is invalid") from error
                if (
                    not isinstance(envelope, Mapping)
                    or envelope.get("storage_format_version")
                    != STREAM_STORAGE_FORMAT_VERSION
                    or envelope.get("storage_kind") != "raw_record"
                    or envelope.get("view_id") != view_id
                    or envelope.get("session_id") != session_id
                    or envelope.get("block_id") != block_id
                    or not isinstance(envelope.get("payload"), Mapping)
                ):
                    raise LookupError("Stored stream raw history is invalid")
                records.append(dict(envelope["payload"]))
        return tuple(records)

    def stored_view_ids(self) -> list[str]:
        """Discover logical view identities without loading compact payloads."""
        if not self.streams_root.exists():
            return []
        view_ids: set[str] = set()
        for name in (_SESSION_METADATA_NAME, _INCOMPLETE_MARKER_NAME):
            for metadata_path in self.streams_root.glob(f"*/*/{name}"):
                try:
                    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        continue
                    view_id = raw.get("view_id")
                    session_id = raw.get("session_id")
                    if not isinstance(view_id, str) or not isinstance(session_id, str):
                        continue
                    paths = self.session_paths(view_id=view_id, session_id=session_id)
                    expected = (
                        paths.metadata
                        if name == _SESSION_METADATA_NAME
                        else paths.incomplete_marker
                    )
                    if expected != metadata_path:
                        continue
                    view_ids.add(view_id)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        return sorted(view_ids)

    def get_storage_stats(self) -> dict[str, Any]:
        """Return bounded stream-tree accounting for ``plotsrv store stats``.

        Byte accounting includes every physical file below the dedicated
        stream namespace, including raw blocks, incomplete markers, and a
        malformed/orphaned entry.  That makes the number an honest measure of
        disk use even when a damaged session cannot be restored or listed.
        """
        with self._lock:
            views = self._stored_stream_views()
            return {
                "root_dir": str(self.root_dir),
                "view_count": len(views),
                "session_count": sum(view.session_count for view in views),
                "total_bytes": self._directory_byte_count(self.streams_root),
            }

    def list_stored_views(self) -> list[StoredStreamView]:
        """Return per-logical-view stream storage summaries for CLI tooling."""
        with self._lock:
            return self._stored_stream_views()

    def delete_all_for_view(self, *, view_id: str) -> int:
        """Delete only one logical view's dedicated stream-storage subtree.

        Snapshot and latest storage use sibling namespaces and are never
        reached by this operation.
        """
        _require_identity(view_id, "view_id")
        view_dir = self.streams_root / _path_component(view_id, label="view_id")
        with self._lock:
            removed = self._directory_file_count(view_dir)
            if view_dir.is_dir():
                shutil.rmtree(view_dir)
            self._remove_empty_streams_root()
            return removed

    def delete_all(self) -> int:
        """Delete every file in the dedicated stream-storage namespace only."""
        with self._lock:
            if not self.streams_root.is_dir():
                return 0
            removed = self._directory_file_count(self.streams_root)
            for child in tuple(self.streams_root.iterdir()):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            self._remove_empty_streams_root()
            return removed

    def write_raw_block(
        self,
        *,
        view_id: str,
        session_id: str,
        block_id: str,
        records: Sequence[Mapping[str, Any]],
        raw_policy: RawBlockPolicy,
        storage_policy: StreamStoragePolicy,
    ) -> RawBlockWrite:
        """Persist one accepted batch only after explicit raw opt-in.

        Blocks are immutable-by-name (the same batch retry atomically replaces
        the same name), and all count, raw-byte, optional-age, and total-view
        byte limits are planned before the new file is written.  Compact files
        are never discarded to make room for raw rows.
        """
        _require_identity(view_id, "view_id")
        _require_identity(session_id, "session_id")
        _require_block_id(block_id)
        raw_records = _bounded_raw_records(records)
        paths = self.session_paths(view_id=view_id, session_id=session_id)
        payload = _raw_jsonl_bytes(
            view_id=view_id,
            session_id=session_id,
            block_id=block_id,
            records=raw_records,
        )
        target = paths.raw_dir / f"{block_id}.jsonl"
        if len(payload) > raw_policy.max_bytes:
            raise StreamStorageCapacityError(
                "raw stream block exceeds its configured raw byte limit "
                f"({len(payload)} > {raw_policy.max_bytes})"
            )

        with self._lock:
            # Do not prune an already durable raw block before this immutable
            # candidate commits.  The following plan accounts for the whole
            # current view and can reject an over-limit replacement without
            # sacrificing old blocks on a candidate-write failure.
            prior_target_bytes = _file_size(target)
            candidates = self._view_raw_block_candidates(
                view_dir=paths.view_dir,
                exclude=target,
                max_age_s=raw_policy.max_age_s,
            )
            retained, discarded = _retain_raw_candidates(
                candidates,
                new_name=target.name,
                new_size=len(payload),
                max_blocks=raw_policy.max_blocks,
                max_bytes=raw_policy.max_bytes,
            )
            view_bytes = self._view_byte_count(paths.view_dir)
            projected = view_bytes - prior_target_bytes + len(payload)
            for candidate in discarded:
                projected -= candidate.size_bytes

            # The view cap covers compact state and raw blocks together.  It
            # can require a stricter raw prune than the raw-specific policy.
            while projected > storage_policy.max_bytes_per_view and retained:
                oldest = retained.pop(0)
                discarded.append(oldest)
                projected -= oldest.size_bytes
            if projected > storage_policy.max_bytes_per_view:
                raise StreamStorageCapacityError(
                    "raw stream block would exceed the configured hard "
                    f"per-view byte limit ({projected} > "
                    f"{storage_policy.max_bytes_per_view})"
                )

            storage_backend._write_bytes_atomic(target, payload)
            # The immutable replacement is durable before any retained raw
            # block is removed.  A candidate-write error therefore leaves the
            # previous bounded history intact; an interruption leaves a
            # boundedly recoverable temporary overage for normal retention to
            # reconcile at the next transaction or restart.
            for candidate in discarded:
                try:
                    candidate.path.unlink()
                except FileNotFoundError:
                    pass
            return RawBlockWrite(
                path=target,
                record_count=len(raw_records),
                byte_count=len(payload),
                pruned_block_count=len(discarded),
            )

    def _prune_old_sessions(
        self, *, paths: StreamSessionPaths, keep_last_sessions: int
    ) -> int:
        """Retain the current plus the newest configured older sessions."""
        return self._prune_view_sessions(
            view_dir=paths.view_dir,
            keep_last_sessions=keep_last_sessions,
            protected_session=paths.session_dir,
        )

    def _stored_stream_views(self) -> list[StoredStreamView]:
        """Build CLI summaries from valid v1 identities under one lock."""
        views: list[StoredStreamView] = []
        for view_id in self.stored_view_ids():
            view_dir = self.streams_root / _path_component(view_id, label="view_id")
            session_count = 0
            raw_block_count = 0
            incomplete_session_count = 0
            updated_values: list[str] = []
            if view_dir.is_dir():
                for session_dir in view_dir.iterdir():
                    if not session_dir.is_dir():
                        continue
                    descriptor = self._stored_session_descriptor(
                        view_id=view_id, session_dir=session_dir
                    )
                    if descriptor is None:
                        continue
                    session_count += 1
                    if descriptor["updated_at"] is not None:
                        updated_values.append(descriptor["updated_at"])
                    if descriptor["incomplete"]:
                        incomplete_session_count += 1
                    raw_dir = session_dir / "raw"
                    if raw_dir.is_dir():
                        raw_block_count += sum(
                            1 for path in raw_dir.glob("*.jsonl") if path.is_file()
                        )
            views.append(
                StoredStreamView(
                    view_id=view_id,
                    session_count=session_count,
                    total_bytes=self._directory_byte_count(view_dir),
                    last_updated_at=max(updated_values, default=None),
                    raw_block_count=raw_block_count,
                    incomplete_session_count=incomplete_session_count,
                )
            )
        return sorted(views, key=lambda view: view.view_id.lower())

    def _read_stored_gap(self, marker_path: Path) -> StoredStreamGap:
        """Read one marker-only restoration record after strict attribution."""
        try:
            raw = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise LookupError("Stored durable-history gap marker is invalid") from error
        if (
            not isinstance(raw, Mapping)
            or raw.get("object_type") != "plotsrv_stream_durable_history_gap"
            or raw.get("storage_format") != "plotsrv.stream-storage"
            or raw.get("storage_format_version") != STREAM_STORAGE_FORMAT_VERSION
            or raw.get("state") != "incomplete"
            or not isinstance(raw.get("view_id"), str)
            or not isinstance(raw.get("session_id"), str)
            or not isinstance(raw.get("recorded_at"), str)
            or not raw["recorded_at"]
        ):
            raise LookupError("Stored durable-history gap marker is invalid")
        try:
            _require_identity(raw["view_id"], "view_id")
            _require_identity(raw["session_id"], "session_id")
        except StreamStorageValidationError as error:
            raise LookupError("Stored durable-history gap marker is invalid") from error
        error = raw.get("last_error")
        return StoredStreamGap(
            view_id=raw["view_id"],
            session_id=raw["session_id"],
            recorded_at=raw["recorded_at"],
            last_error=(
                error
                if isinstance(error, str) and error
                else "stream persistence was incomplete"
            ),
        )

    def _stored_session_descriptor(
        self, *, view_id: str, session_dir: Path
    ) -> dict[str, Any] | None:
        """Read enough metadata to attribute one physical session directory."""
        candidate_files = (
            (session_dir / _SESSION_METADATA_NAME, "updated_at"),
            (session_dir / _INCOMPLETE_MARKER_NAME, "recorded_at"),
        )
        for candidate, timestamp_key in candidate_files:
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(raw, Mapping):
                continue
            session_id = raw.get("session_id")
            if (
                raw.get("storage_format_version") != STREAM_STORAGE_FORMAT_VERSION
                or raw.get("view_id") != view_id
                or not isinstance(session_id, str)
            ):
                continue
            try:
                expected = self.session_paths(
                    view_id=view_id, session_id=session_id
                ).session_dir
            except StreamStorageValidationError:
                continue
            if expected != session_dir:
                continue
            timestamp = raw.get(timestamp_key)
            compact = raw.get("metadata")
            durable = compact.get("durable_history") if isinstance(compact, Mapping) else None
            return {
                "updated_at": timestamp if isinstance(timestamp, str) else None,
                "incomplete": (
                    candidate.name == _INCOMPLETE_MARKER_NAME
                    or raw.get("state") == "incomplete"
                    or (isinstance(durable, Mapping) and durable.get("state") == "incomplete")
                    or self._has_valid_incomplete_marker(session_dir)
                ),
            }
        return None

    def _remove_empty_streams_root(self) -> None:
        try:
            self.streams_root.rmdir()
        except (FileNotFoundError, OSError):
            pass

    def _prune_view_sessions(
        self,
        *,
        view_dir: Path,
        keep_last_sessions: int,
        protected_session: Path | None,
    ) -> int:
        if not view_dir.exists():
            return 0
        sessions = [path for path in view_dir.iterdir() if path.is_dir()]
        sessions.sort(key=self._session_order_key, reverse=True)
        if protected_session is not None:
            sessions = [path for path in sessions if path != protected_session]
            keep = max(0, keep_last_sessions - 1)
        else:
            keep = keep_last_sessions
        discarded = sessions[keep:]
        for session_dir in discarded:
            _remove_session_directory(session_dir, view_dir)
        return len(discarded)

    def _enforce_view_byte_limit(
        self,
        *,
        view_dir: Path,
        maximum: int,
        protected_session: Path | None,
    ) -> int:
        """Remove oldest raw blocks, then sessions, until the view fits."""
        if not view_dir.exists():
            return 0
        pruned = 0
        raw_blocks: list[Path] = []
        for session_dir in view_dir.iterdir():
            if session_dir.is_dir():
                raw_blocks.extend(session_dir.glob("raw/*.jsonl"))
        raw_blocks.sort(key=_path_age_key)
        while self._view_byte_count(view_dir) > maximum and raw_blocks:
            raw_blocks.pop(0).unlink(missing_ok=True)
            pruned += 1

        sessions = [path for path in view_dir.iterdir() if path.is_dir()]
        sessions.sort(key=self._session_order_key)
        for session_dir in sessions:
            if self._view_byte_count(view_dir) <= maximum:
                break
            if protected_session is not None and session_dir == protected_session:
                continue
            _remove_session_directory(session_dir, view_dir)
            pruned += 1
        return pruned

    def _prune_view_raw_blocks(
        self,
        *,
        view_dir: Path,
        raw_policy: RawBlockPolicy | None,
    ) -> int:
        """Apply current raw opt-in policy to every retained session in a view."""
        if not view_dir.exists():
            return 0
        blocks = self._view_raw_blocks(view_dir)
        if raw_policy is None:
            for path in blocks:
                path.unlink(missing_ok=True)
            return len(blocks)

        now = datetime.now(UTC)
        retained: list[Path] = []
        discarded: list[Path] = []
        for path in blocks:
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            except OSError:
                discarded.append(path)
                continue
            if (
                raw_policy.max_age_s is not None
                and now - modified_at >= timedelta(seconds=raw_policy.max_age_s)
            ):
                discarded.append(path)
            else:
                retained.append(path)
        while len(retained) > raw_policy.max_blocks:
            discarded.append(retained.pop(0))
        retained_bytes = sum(_file_size(path) for path in retained)
        while retained and retained_bytes > raw_policy.max_bytes:
            removed = retained.pop(0)
            retained_bytes -= _file_size(removed)
            discarded.append(removed)
        for path in discarded:
            path.unlink(missing_ok=True)
        return len(discarded)

    @staticmethod
    def _view_raw_blocks(view_dir: Path) -> list[Path]:
        blocks: list[Path] = []
        for session_dir in view_dir.iterdir():
            if session_dir.is_dir():
                blocks.extend(session_dir.glob("raw/*.jsonl"))
        blocks.sort(key=_path_age_key)
        return blocks

    @staticmethod
    def _session_order_key(session_dir: Path) -> tuple[str, str]:
        for name, timestamp_field in (
            (_SESSION_METADATA_NAME, "updated_at"),
            (_INCOMPLETE_MARKER_NAME, "recorded_at"),
        ):
            try:
                raw = json.loads((session_dir / name).read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get(timestamp_field), str):
                    return (raw[timestamp_field], session_dir.name)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        try:
            return (
                datetime.fromtimestamp(session_dir.stat().st_mtime, UTC).isoformat(),
                session_dir.name,
            )
        except OSError:
            return ("", session_dir.name)

    def _plan_bounded_replacement(
        self,
        *,
        paths: StreamSessionPaths,
        policy: StreamStoragePolicy,
        replacement_bytes: int,
        replaced_files: Sequence[Path],
        allow_target_session_eviction: bool = False,
    ) -> tuple[list[Path], list[Path]]:
        """Plan retention and capacity cleanup without mutating storage.

        The caller applies the returned cleanup only after the candidate
        replacement is known to fit.  This keeps a rejected new session from
        deleting valid compact history simply because it would have been
        outside the configured retention window after a successful write.
        """
        view_dir = paths.view_dir
        sessions = (
            [path for path in view_dir.iterdir() if path.is_dir()]
            if view_dir.exists()
            else []
        )
        sessions.sort(key=self._session_order_key, reverse=True)
        other_sessions = [path for path in sessions if path != paths.session_dir]
        session_dirs = other_sessions[max(0, policy.keep_last_sessions - 1) :]
        removed_sessions = set(session_dirs)

        projected = self._view_byte_count(view_dir)
        projected -= sum(self._directory_byte_count(path) for path in session_dirs)
        projected -= sum(_file_size(path) for path in replaced_files)
        projected += replacement_bytes

        remaining_sessions = [
            path for path in sessions if path not in removed_sessions
        ]
        raw_paths = [
            path
            for session_dir in remaining_sessions
            for path in session_dir.glob("raw/*.jsonl")
        ]
        raw_paths.sort(key=_path_age_key)
        discarded_raw: list[Path] = []
        while projected > policy.max_bytes_per_view and raw_paths:
            raw_path = raw_paths.pop(0)
            discarded_raw.append(raw_path)
            projected -= _file_size(raw_path)

        capacity_sessions = sorted(
            (
                path
                for path in remaining_sessions
                if path != paths.session_dir
            ),
            key=self._session_order_key,
        )
        while projected > policy.max_bytes_per_view and capacity_sessions:
            session_dir = capacity_sessions.pop(0)
            session_dirs.append(session_dir)
            # A raw block selected above may be inside this session.  Its
            # bytes have already been removed from the projection, so avoid
            # subtracting them a second time when planning directory removal.
            removed_raw_bytes = sum(
                _file_size(path)
                for path in discarded_raw
                if path.is_relative_to(session_dir)
            )
            projected -= self._directory_byte_count(session_dir) - removed_raw_bytes

        if (
            projected > policy.max_bytes_per_view
            and allow_target_session_eviction
            and paths.session_dir.exists()
        ):
            # A gap marker is the durable evidence that observed history is
            # incomplete.  If its own near-ceiling compact snapshot leaves no
            # room for that evidence, preserve the bounded gap marker and
            # discard the now-unrestorable compact payload for this session.
            # The marker write below recreates the directory atomically.
            session_dirs.append(paths.session_dir)
            replaced_bytes = sum(_file_size(path) for path in replaced_files)
            removed_raw_bytes = sum(
                _file_size(path)
                for path in discarded_raw
                if path.is_relative_to(paths.session_dir)
            )
            projected -= (
                self._directory_byte_count(paths.session_dir)
                - replaced_bytes
                - removed_raw_bytes
            )

        if projected > policy.max_bytes_per_view:
            raise StreamStorageCapacityError(
                "stream persistence replacement would exceed the configured hard "
                f"per-view byte limit ({projected} > {policy.max_bytes_per_view})"
            )
        return session_dirs, discarded_raw

    @staticmethod
    def _apply_cleanup(
        *, session_dirs: Sequence[Path], raw_paths: Sequence[Path]
    ) -> None:
        """Apply a previously validated bounded-cleanup plan."""
        for session_dir in session_dirs:
            _remove_session_directory(session_dir, session_dir.parent)
        for raw_path in raw_paths:
            raw_path.unlink(missing_ok=True)

    @staticmethod
    def _directory_byte_count(directory: Path) -> int:
        if not directory.exists():
            return 0
        return sum(
            _file_size(path) for path in directory.rglob("*") if path.is_file()
        )

    @staticmethod
    def _directory_file_count(directory: Path) -> int:
        if not directory.exists():
            return 0
        return sum(1 for path in directory.rglob("*") if path.is_file())

    @staticmethod
    def _view_byte_count(view_dir: Path) -> int:
        if not view_dir.exists():
            return 0
        total = 0
        for path in view_dir.rglob("*"):
            if path.is_file():
                total += _file_size(path)
        return total

    @staticmethod
    def _raw_block_candidates(
        *, raw_dir: Path, exclude: Path, max_age_s: int | None
    ) -> list[_RawBlockCandidate]:
        if not raw_dir.exists():
            return []
        now = datetime.now(UTC)
        candidates: list[_RawBlockCandidate] = []
        for path in raw_dir.glob("*.jsonl"):
            if path == exclude:
                continue
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            except OSError:
                continue
            if max_age_s is not None and now - modified_at >= timedelta(seconds=max_age_s):
                candidates.append(
                    _RawBlockCandidate(path=path, size_bytes=_file_size(path), expired=True)
                )
                continue
            candidates.append(
                _RawBlockCandidate(path=path, size_bytes=_file_size(path), expired=False)
            )
        candidates.sort(key=lambda item: (item.path.stat().st_mtime_ns, item.path.name))
        return candidates

    @classmethod
    def _view_raw_block_candidates(
        cls, *, view_dir: Path, exclude: Path, max_age_s: int | None
    ) -> list[_RawBlockCandidate]:
        """Collect raw eviction candidates across every retained session.

        Raw policy is per logical view, not per transport session.  A newer
        session therefore cannot retain one extra block merely because its
        target ``raw/`` directory is different from the older session's.
        """
        if not view_dir.exists():
            return []
        candidates: list[_RawBlockCandidate] = []
        for session_dir in view_dir.iterdir():
            if session_dir.is_dir():
                candidates.extend(
                    cls._raw_block_candidates(
                        raw_dir=session_dir / "raw",
                        exclude=exclude,
                        max_age_s=max_age_s,
                    )
                )
        candidates.sort(key=lambda item: _path_age_key(item.path))
        return candidates

    @staticmethod
    def _active_compact_paths(paths: StreamSessionPaths) -> tuple[Path, Path]:
        """Return the metadata-referenced compact generation safely.

        Older v1 stores omit generation filenames and therefore continue to
        use the original root-level names.  A malformed metadata file falls
        back to those names; it is not trusted to direct cleanup outside its
        own generated session directory.
        """
        summaries = paths.summaries
        noteworthy = paths.noteworthy
        try:
            raw = json.loads(paths.metadata.read_text(encoding="utf-8"))
            compact = raw.get("compact_state") if isinstance(raw, Mapping) else None
            if isinstance(compact, Mapping):
                summaries = _compact_filename_path(
                    paths.session_dir,
                    compact.get("summaries_filename"),
                    fallback=summaries,
                    required_prefix="summaries",
                )
                noteworthy = _compact_filename_path(
                    paths.session_dir,
                    compact.get("noteworthy_filename"),
                    fallback=noteworthy,
                    required_prefix="noteworthy",
                )
        except (LookupError, OSError, ValueError, json.JSONDecodeError):
            pass
        return summaries, noteworthy

    def _discard_uncommitted_compact_state(self, *, view_dirs: Sequence[Path]) -> int:
        """Remove compact files that no committed session metadata can use.

        Callers hold the shared root transaction lock.  A valid gap marker is
        sufficient to retain a marker-only session, while a compact session
        must have identity-matching metadata with safe active JSONL names.
        Everything else is an uncommitted write attempt and is removed before
        retention can mistake it for a newer historical session.
        """
        removed = 0
        for view_dir in view_dirs:
            if not view_dir.exists():
                continue
            for session_dir in tuple(path for path in view_dir.iterdir() if path.is_dir()):
                committed = self._committed_compact_paths(session_dir)
                marker_valid = self._has_valid_incomplete_marker(session_dir)
                if committed is None and not marker_valid:
                    try:
                        _remove_session_directory(session_dir, view_dir)
                    except FileNotFoundError:
                        pass
                    else:
                        removed += 1
                    continue

                active_paths = set(committed or ())
                for prefix in ("summaries", "noteworthy"):
                    for candidate in session_dir.glob(f"{prefix}*.jsonl"):
                        if candidate not in active_paths:
                            try:
                                candidate.unlink()
                            except FileNotFoundError:
                                continue
                            removed += 1
        return removed

    def _committed_compact_paths(
        self, session_dir: Path
    ) -> tuple[Path, Path] | None:
        """Validate committed metadata enough to protect its active files."""
        metadata_path = session_dir / _SESSION_METADATA_NAME
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (
                not isinstance(raw, Mapping)
                or raw.get("storage_format_version") != STREAM_STORAGE_FORMAT_VERSION
                or not isinstance(raw.get("view_id"), str)
                or not isinstance(raw.get("session_id"), str)
                or not isinstance(raw.get("metadata"), Mapping)
                or not isinstance(raw.get("compact_state"), Mapping)
            ):
                return None
            paths = self.session_paths(
                view_id=raw["view_id"], session_id=raw["session_id"]
            )
            if paths.session_dir != session_dir:
                return None
            compact = raw["compact_state"]
            return (
                _compact_filename_path(
                    session_dir,
                    compact.get("summaries_filename"),
                    fallback=paths.summaries,
                    required_prefix="summaries",
                ),
                _compact_filename_path(
                    session_dir,
                    compact.get("noteworthy_filename"),
                    fallback=paths.noteworthy,
                    required_prefix="noteworthy",
                ),
            )
        except (
            LookupError,
            OSError,
            StreamStorageValidationError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None

    def _has_valid_incomplete_marker(self, session_dir: Path) -> bool:
        """Whether a marker-only directory represents a known durable gap."""
        marker_path = session_dir / _INCOMPLETE_MARKER_NAME
        try:
            raw = json.loads(marker_path.read_text(encoding="utf-8"))
            if (
                not isinstance(raw, Mapping)
                or raw.get("storage_format_version") != STREAM_STORAGE_FORMAT_VERSION
                or raw.get("state") != "incomplete"
                or not isinstance(raw.get("view_id"), str)
                or not isinstance(raw.get("session_id"), str)
            ):
                return False
            return self.session_paths(
                view_id=raw["view_id"], session_id=raw["session_id"]
            ).session_dir == session_dir
        except (
            OSError,
            StreamStorageValidationError,
            ValueError,
            json.JSONDecodeError,
        ):
            return False

    @staticmethod
    def _read_compact_jsonl(
        *,
        path: Path,
        kind: str,
        view_id: str,
        session_id: str,
        written_at: str,
        generation_id: str | None,
        expected_count: int,
    ) -> list[dict[str, Any]]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise LookupError(f"Stored stream {kind} history is missing") from error

        items: list[dict[str, Any]] = []
        for line in lines:
            try:
                envelope = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise LookupError(f"Stored stream {kind} history is invalid") from error
            if (
                not isinstance(envelope, dict)
                or envelope.get("storage_format_version") != STREAM_STORAGE_FORMAT_VERSION
                or envelope.get("storage_kind") != kind
                or envelope.get("view_id") != view_id
                or envelope.get("session_id") != session_id
                or envelope.get("written_at") != written_at
                or envelope.get("generation_id") != generation_id
                or not isinstance(envelope.get("payload"), dict)
            ):
                raise LookupError(f"Stored stream {kind} history is invalid")
            payload = dict(envelope["payload"])
            if kind == "summary" and ("records" in payload or "data" in payload):
                raise LookupError("Stored stream summary must not contain raw records")
            items.append(payload)
        if len(items) != expected_count:
            raise LookupError(f"Stored stream {kind} history count is inconsistent")
        return items

    @staticmethod
    def _apply_incomplete_marker(
        *,
        metadata: dict[str, Any],
        path: Path,
        view_id: str,
        session_id: str,
    ) -> None:
        try:
            marker = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise LookupError("Stored durable-history gap marker is invalid") from error
        if (
            not isinstance(marker, dict)
            or marker.get("storage_format_version") != STREAM_STORAGE_FORMAT_VERSION
            or marker.get("view_id") != view_id
            or marker.get("session_id") != session_id
            or marker.get("state") != "incomplete"
        ):
            raise LookupError("Stored durable-history gap marker is invalid")
        compact = metadata["metadata"]
        assert isinstance(compact, dict)
        prior = compact.get("durable_history")
        history = dict(prior) if isinstance(prior, Mapping) else {}
        history.update(
            {
                "state": "incomplete",
                "persistence_enabled": True,
                "last_error": marker.get("last_error")
                if isinstance(marker.get("last_error"), str)
                else "stream persistence was incomplete",
            }
        )
        compact["durable_history"] = history


def _path_component(value: str, *, label: str) -> str:
    """Create a bounded readable filesystem component without identity loss."""
    _require_identity(value, label)
    slug = storage_backend._slug_view_id(value)
    # Keep room for the collision-resistant suffix under common filesystem
    # component limits even when public identities reach their 512-char cap.
    slug = slug[:96].rstrip("._-") or "stream"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{slug}--{digest}"


def _require_identity(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StreamStorageValidationError(f"{label} must be a non-empty string")
    if "\x00" in value:
        raise StreamStorageValidationError(f"{label} must not contain NUL")


def _compact_mapping(value: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StreamStorageValidationError(f"{kind} must be a mapping")
    copied = dict(value)
    # The worker must pass compact state rather than the raw window returned by
    # ``StreamRegistry.data``.  This guard makes an accidental API mix-up a
    # visible persistence failure instead of silent raw persistence.
    if "records" in copied:
        raise StreamStorageValidationError(f"{kind} must not contain raw records")
    _json_bytes(copied)
    return copied


def _bounded_mappings(
    values: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    kind: str,
    reject_raw: bool,
) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise StreamStorageValidationError(f"{kind} values must be a sequence of mappings")
    retained: list[dict[str, Any]] = []
    for value in values[-limit:]:
        if not isinstance(value, Mapping):
            raise StreamStorageValidationError(f"{kind} entries must be mappings")
        copied = dict(value)
        if reject_raw and ("records" in copied or "data" in copied):
            raise StreamStorageValidationError(
                "summary entries must be derived state, not raw source rows"
            )
        _json_bytes(copied)
        retained.append(copied)
    return retained


def _bounded_raw_records(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise StreamStorageValidationError("raw block records must be a sequence of mappings")
    records: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise StreamStorageValidationError("raw block records must be mappings")
        copied = dict(value)
        if not isinstance(copied.get("data"), Mapping):
            raise StreamStorageValidationError("raw block records must contain data mappings")
        if not isinstance(copied.get("browser_sequence"), int):
            raise StreamStorageValidationError(
                "raw block records must contain integer browser_sequence values"
            )
        if not isinstance(copied.get("observed_at"), str):
            raise StreamStorageValidationError(
                "raw block records must contain observed_at strings"
            )
        _json_bytes(copied)
        records.append(copied)
    return records


def _require_block_id(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise StreamStorageValidationError("raw block_id must be a non-empty string")
    if len(value) > 80 or any(character not in "0123456789abcdefghijklmnopqrstuvwxyz-" for character in value):
        raise StreamStorageValidationError("raw block_id must be a bounded lowercase identifier")


def _retain_raw_candidates(
    candidates: Sequence[_RawBlockCandidate],
    *,
    new_name: str,
    new_size: int,
    max_blocks: int,
    max_bytes: int,
) -> tuple[list[_RawBlockCandidate], list[_RawBlockCandidate]]:
    """Return raw files retained and pruned after adding one newest block."""
    retained = [candidate for candidate in candidates if not candidate.expired]
    discarded = [candidate for candidate in candidates if candidate.expired]

    # The new block is conceptually newest.  Evict older on-disk blocks before
    # writing so persistence never creates an unbounded raw backlog.
    while len(retained) + 1 > max_blocks:
        discarded.append(retained.pop(0))
    retained_bytes = sum(candidate.size_bytes for candidate in retained)
    while retained and retained_bytes + new_size > max_bytes:
        removed = retained.pop(0)
        retained_bytes -= removed.size_bytes
        discarded.append(removed)
    return retained, discarded


def _jsonl_bytes(
    *,
    kind: str,
    view_id: str,
    session_id: str,
    written_at: str,
    generation_id: str,
    items: Sequence[Mapping[str, Any]],
) -> bytes:
    lines = [
        json.dumps(
            {
                "storage_format_version": STREAM_STORAGE_FORMAT_VERSION,
                "storage_kind": kind,
                "view_id": view_id,
                "session_id": session_id,
                "written_at": written_at,
                "generation_id": generation_id,
                "payload": item,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for item in items
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _raw_jsonl_bytes(
    *,
    view_id: str,
    session_id: str,
    block_id: str,
    records: Sequence[Mapping[str, Any]],
) -> bytes:
    lines = [
        json.dumps(
            {
                "storage_format_version": STREAM_STORAGE_FORMAT_VERSION,
                "storage_kind": "raw_record",
                "view_id": view_id,
                "session_id": session_id,
                "block_id": block_id,
                "payload": record,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for record in records
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            separators=None if indent is not None else (",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise StreamStorageValidationError("stream compact state must be JSON-native") from error


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size) if path.is_file() else 0
    except OSError:
        return 0


def _compact_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LookupError(f"Stored stream {label} count is invalid")
    return value


def _compact_filename_path(
    session_dir: Path,
    value: object,
    *,
    fallback: Path,
    required_prefix: str,
) -> Path:
    """Resolve one metadata-declared compact filename inside its session.

    Version-one metadata originally named the fixed root files and newer
    replacement generations use a hash-suffixed filename.  Accept only a bare
    JSONL filename with the expected logical kind, retaining both compatibility
    and cleanup-path safety.
    """
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise LookupError("Stored compact filename is invalid")
    candidate = Path(value)
    if (
        candidate.name != value
        or not value.endswith(".jsonl")
        or not value.startswith(required_prefix)
    ):
        raise LookupError("Stored compact filename is invalid")
    return session_dir / value


def _path_age_key(path: Path) -> tuple[int, str]:
    try:
        return (path.stat().st_mtime_ns, path.name)
    except OSError:
        return (0, path.name)


def _remove_session_directory(session_dir: Path, view_dir: Path) -> None:
    """Delete one generated session directory, never a caller-provided path."""
    try:
        session_dir.relative_to(view_dir)
    except ValueError as error:  # pragma: no cover - defensive invariant
        raise StreamStorageValidationError("session path escapes stream view") from error
    shutil.rmtree(session_dir)
