"""HTTP routes for the dedicated versioned stream protocol."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from . import config, store
from .browser_updates import browser_update_hub
from .http_security import require_local_request
from .storage.streams import FileStreamStorageBackend
from .storage.stream_worker import (
    get_stream_storage_worker,
    schedule_stream_persistence_incomplete,
)
from .streams.models import (
    MAX_STREAM_REQUEST_BYTES,
    STREAM_PROTOCOL_VERSION,
    SourceHealth,
    SourceStatus,
    StreamAppend,
    StreamBatchValidationError,
    StreamClose,
    StreamHeartbeat,
    StreamRecord,
    StreamRecordValidationError,
    StreamRegistration,
    validate_source_status,
    validate_source_health,
    validate_stream_batch,
    normalize_checkpoint_identifier,
)
from .streams.server_state import (
    StreamConflictError,
    StreamStateError,
    UnknownStreamError,
    stream_registry,
)


router = APIRouter()


def notify_stream_browser(view_id: str, *, change_type: str = "stream") -> None:
    """Publish a de-duplicated notification for meaningful stream state."""
    metadata = stream_registry.browser_update_metadata(view_id=view_id)
    fingerprint = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    browser_update_hub.publish(
        view_id=view_id,
        change_type=change_type,
        metadata=metadata,
        fingerprint=fingerprint,
    )


def notify_stream_history_browser(view_id: str, *, session_id: str) -> None:
    """Invalidate only the stored-run selector for browsers on this view."""
    browser_update_hub.publish(
        view_id=view_id,
        change_type="stream_history",
        metadata={
            "kind": "stream",
            "session_id": session_id,
            "history_catalogue_changed": True,
        },
    )


def _stream_history_capability(view_id: str) -> dict[str, Any]:
    if not config.get_storage_enabled():
        return {
            "enabled": False,
            "state": "unavailable",
            "reason": "storage_disabled",
            "message": (
                "Stored runs are unavailable because plotsrv disk storage "
                "is disabled in configuration."
            ),
        }
    if not config.get_storage_stream_enabled(view_id):
        return {
            "enabled": False,
            "state": "unavailable",
            "reason": "stream_storage_disabled",
            "message": "Stored runs are disabled for this stream view.",
        }
    return {
        "enabled": True,
        "state": "enabled",
        "reason": None,
        "message": "Stored runs are available for this stream view.",
    }


def _refresh_stored_stream_history(view_id: str) -> list[dict[str, Any]]:
    """Reconcile one view's bounded in-memory history with durable storage."""
    if not config.get_storage_stream_enabled(view_id):
        return []

    backend = FileStreamStorageBackend(root_dir=config.get_storage_root_dir())
    current_session_id = stream_registry.current_session_id(view_id=view_id)
    retained_session_ids: set[str] = set()

    for session in backend.list_compact_sessions(view_id=view_id):
        if session.session_id == current_session_id:
            continue
        try:
            history_incomplete_reason: str | None = None
            try:
                raw_records = backend.load_raw_records(
                    view_id=view_id, session_id=session.session_id
                )
            except LookupError:
                raw_records = ()
                history_incomplete_reason = (
                    "Explicitly retained raw history could not be validated; "
                    "those raw observations are unavailable."
                )
            stream_registry.restore_compact_session(
                stored_metadata=session.metadata,
                summary_windows=session.summary_windows,
                noteworthy_items=session.noteworthy_items,
                raw_records=raw_records,
                history_incomplete_reason=history_incomplete_reason,
                replace_existing=True,
            )
            retained_session_ids.add(session.session_id)
        except StreamStateError:
            continue

    for gap in backend.list_marker_only_sessions(view_id=view_id):
        if gap.session_id == current_session_id:
            continue
        try:
            stream_registry.restore_incomplete_marker(
                view_id=gap.view_id,
                session_id=gap.session_id,
                recorded_at=gap.recorded_at,
                last_error=gap.last_error,
                replace_existing=True,
            )
            retained_session_ids.add(gap.session_id)
        except StreamStateError:
            continue

    stream_registry.reconcile_historical_sessions(
        view_id=view_id,
        retained_session_ids=retained_session_ids,
    )
    return stream_registry.historical_sessions(view_id=view_id)


def _complete_stream_persistence(
    *, view_id: str, session_id: str, success: bool, error: str | None
) -> None:
    stream_registry.complete_persistence(
        view_id=view_id,
        session_id=session_id,
        success=success,
        error=error,
    )
    if success and not stream_registry.session_is_current(
        view_id=view_id, session_id=session_id
    ):
        notify_stream_history_browser(view_id, session_id=session_id)


def _submit_stream_persistence(
    *,
    view_id: str,
    session_id: str,
    raw_block_id: str | None = None,
    raw_records: tuple[StreamRecord, ...] = (),
) -> None:
    """Best-effort persistence that never changes stream protocol acceptance.

    Stream state has already been accepted by the registry before this helper
    runs. Its only job is to hand a compact, bounded copy to the stream-only
    worker. Thus a full queue, validation problem, or failed write is visible
    through ``durable_history`` but cannot turn a successful append, heartbeat,
    or close into a failed live-observation request.
    """
    if not config.get_storage_stream_enabled(view_id):
        # Global storage is the master opt-in. The registry state is otherwise
        # deliberately untouched so storage-disabled streams have neither
        # pending persistence work nor stream-content files.
        stream_registry.set_persistence_enabled(view_id=view_id, enabled=False)
        return

    raw_enabled = config.get_storage_stream_raw_enabled(view_id)
    try:
        stream_registry.begin_persistence(view_id=view_id, session_id=session_id)
        snapshot = stream_registry.persistence_snapshot(
            view_id=view_id,
            session_id=session_id,
            raw_records=raw_records if raw_enabled else (),
            raw_block_id=raw_block_id if raw_enabled else None,
        )
        submission = get_stream_storage_worker().submit(
            view_id=snapshot["view_id"],
            session_id=snapshot["session_id"],
            client_id=snapshot["client_id"],
            metadata=snapshot["metadata"],
            summary_windows=snapshot["summary_windows"],
            noteworthy_items=snapshot["noteworthy_items"],
            raw_block_id=snapshot["raw_block_id"],
            raw_records=snapshot["raw_records"],
            on_complete=lambda success, error: _complete_stream_persistence(
                view_id=view_id,
                session_id=session_id,
                success=success,
                error=error,
            ),
        )
    except Exception as error:
        # This boundary also protects a malformed storage configuration or an
        # unexpected snapshot-copy error from breaking live stream protocol
        # handling. The exception text is intentionally concise because it is
        # exposed to the browser as persistence health.
        stream_registry.reject_persistence(
            view_id=view_id,
            session_id=session_id,
            reason=f"stream persistence submission failed: {type(error).__name__}: {error}",
        )
        _schedule_stream_persistence_gap(
            view_id=view_id,
            session_id=session_id,
            reason=f"stream persistence submission failed: {type(error).__name__}: {error}",
        )
        return

    if not submission.accepted:
        if submission.enabled:
            reason = submission.reason or "stream persistence was not admitted"
            stream_registry.reject_persistence(
                view_id=view_id,
                session_id=session_id,
                reason=reason,
            )
            _schedule_stream_persistence_gap(
                view_id=view_id,
                session_id=session_id,
                reason=reason,
            )
        else:
            # Storage can be disabled between the initial opt-in check and
            # admission. It is not a durable gap, just a cancelled attempt.
            stream_registry.cancel_persistence(
                view_id=view_id,
                session_id=session_id,
            )


def _schedule_stream_persistence_gap(
    *, view_id: str, session_id: str, reason: str
) -> None:
    """Keep marker scheduling from changing an accepted live request."""
    try:
        schedule_stream_persistence_incomplete(
            view_id=view_id,
            session_id=session_id,
            reason=reason,
        )
    except Exception:
        # The registry was marked incomplete first. This final containment also
        # protects the HTTP boundary from an injected/custom scheduler failure.
        pass


def _require_protocol_version(payload: dict[str, Any]) -> None:
    version = payload.get("protocol_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise HTTPException(
            status_code=422,
            detail="stream protocol_version must be an integer",
        )
    if version != STREAM_PROTOCOL_VERSION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unsupported stream protocol_version {version}; "
                f"expected {STREAM_PROTOCOL_VERSION}"
            ),
        )


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=422,
            detail=f"stream {field} must be a non-empty string",
        )
    return value.strip()


def _required_stream_identity(payload: dict[str, Any], field: str) -> str:
    """Read an identity that can safely participate in browser checkpoints."""
    try:
        return normalize_checkpoint_identifier(payload.get(field), field)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"stream {error}") from error


def _required_batch_sequence(payload: dict[str, Any]) -> int:
    value = payload.get("batch_sequence")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HTTPException(
            status_code=422,
            detail="stream batch_sequence must be a non-negative integer",
        )
    return value


def _required_bool(payload: dict[str, Any], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"stream {field} must be a boolean")
    return value


def _source_status(payload: dict[str, Any]) -> SourceStatus:
    """Read optional source facts without admitting raw OS errors."""
    status = SourceStatus(
        source_available=payload.get("source_available"),
        source_transition=payload.get("source_transition", "unknown"),
        continuity_warning=payload.get("continuity_warning"),
    )
    try:
        validate_source_status(status)
    except StreamRecordValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return status


def _source_health(payload: dict[str, Any]) -> SourceHealth:
    """Read optional fixed source telemetry without admitting raw diagnostics."""
    raw_health = payload.get("source_health")
    if raw_health is None:
        health = SourceHealth()
    elif type(raw_health) is dict:
        health = SourceHealth(
            unread_source_bytes=raw_health.get("unread_source_bytes"),
            unacknowledged_source_bytes=raw_health.get("unacknowledged_source_bytes"),
            in_flight_records=raw_health.get("in_flight_records"),
            records_seen=raw_health.get("records_seen"),
            records_rejected=raw_health.get("records_rejected"),
        )
    else:
        raise HTTPException(status_code=422, detail="stream source_health must be an object")
    try:
        validate_source_health(health)
    except StreamRecordValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return health


def _configure_heartbeat_timeout() -> None:
    """Apply current stream timing and raw-retention configuration per request."""
    stream_registry.set_heartbeat_timeout_s(config.get_stream_heartbeat_timeout_s())
    stream_registry.set_raw_retention(
        max_recent_records=config.get_stream_raw_max_records(),
        max_recent_bytes=config.get_stream_raw_max_bytes(),
        max_recent_age_s=config.get_stream_raw_max_age_s(),
        fine_window_s=config.get_stream_fine_window_s(),
    )
    stream_registry.set_summary_retention(
        max_fine_summary_windows=config.get_stream_max_fine_summary_windows(),
        max_coarse_summary_windows=config.get_stream_max_coarse_summary_windows(),
        coarse_window_factor=config.get_stream_coarse_window_factor(),
        max_summary_fields=config.get_stream_max_summary_fields(),
        max_categorical_values=config.get_stream_max_categorical_values(),
        max_categorical_value_bytes=config.get_stream_max_categorical_value_bytes(),
    )
    stream_registry.set_noteworthy_retention(
        max_noteworthy_items=config.get_stream_max_noteworthy_items(),
    )


async def _read_bounded_payload(request: Request) -> dict[str, Any]:
    """Read a JSON object without allowing a chunked request to grow memory."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="stream content-length must be an integer",
            ) from error
        if declared_length < 0 or declared_length > MAX_STREAM_REQUEST_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "stream request exceeds the "
                    f"{MAX_STREAM_REQUEST_BYTES}-byte limit"
                ),
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_STREAM_REQUEST_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "stream request exceeds the "
                    f"{MAX_STREAM_REQUEST_BYTES}-byte limit"
                ),
            )
        body.extend(chunk)

    try:
        payload = json.loads(body)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422,
            detail="stream request body must be valid JSON",
        ) from error
    if type(payload) is not dict:
        raise HTTPException(status_code=422, detail="stream request body must be an object")
    return payload


def _raise_state_error(error: StreamStateError) -> None:
    if isinstance(error, UnknownStreamError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, StreamConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/stream/register")
async def register_stream(request: Request) -> dict[str, Any]:
    """Create or confirm a logical stream view for one observation session."""
    if config.get_control_local_only():
        require_local_request(request)
    payload = await _read_bounded_payload(request)
    _require_protocol_version(payload)
    _configure_heartbeat_timeout()
    registration = StreamRegistration(
        protocol_version=STREAM_PROTOCOL_VERSION,
        view_id=_required_stream_identity(payload, "view_id"),
        label=_required_text(payload, "label"),
        section=_required_text(payload, "section"),
        client_id=_required_stream_identity(payload, "client_id"),
        session_id=_required_stream_identity(payload, "session_id"),
        source_status=_source_status(payload),
        source_health=_source_health(payload),
    )
    previous_session_id = stream_registry.current_session_id(
        view_id=registration.view_id
    )
    try:
        state = stream_registry.register(registration)
    except StreamStateError as error:
        _raise_state_error(error)

    _submit_stream_persistence(
        view_id=registration.view_id,
        session_id=registration.session_id,
    )

    current_active = store.get_active_view_id()
    known_view_ids = {view.view_id for view in store.list_views()}
    if current_active not in known_view_ids:
        store.set_active_view(registration.view_id)

    notify_stream_browser(registration.view_id)
    if previous_session_id and previous_session_id != registration.session_id:
        notify_stream_history_browser(
            registration.view_id,
            session_id=previous_session_id,
        )

    return {
        "ok": True,
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": registration.view_id,
        "client_id": registration.client_id,
        "session_id": registration.session_id,
        "next_batch_sequence": state.next_batch_sequence,
    }


@router.post("/stream/append")
async def append_stream(request: Request) -> dict[str, Any]:
    """Append an ordered JSON-object batch without entering snapshot publishing."""
    if config.get_control_local_only():
        require_local_request(request)
    payload = await _read_bounded_payload(request)
    _require_protocol_version(payload)
    _configure_heartbeat_timeout()
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise HTTPException(
            status_code=422,
            detail="stream records must be a non-empty list of JSON objects",
        )
    if not all(isinstance(record, dict) for record in raw_records):
        raise HTTPException(
            status_code=422,
            detail="stream records must contain only JSON objects",
        )
    try:
        validate_stream_batch(raw_records)
    except StreamBatchValidationError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except StreamRecordValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    append = StreamAppend(
        protocol_version=STREAM_PROTOCOL_VERSION,
        view_id=_required_stream_identity(payload, "view_id"),
        client_id=_required_stream_identity(payload, "client_id"),
        session_id=_required_stream_identity(payload, "session_id"),
        batch_id=_required_text(payload, "batch_id"),
        batch_sequence=_required_batch_sequence(payload),
        records=tuple(raw_records),
        source_status=_source_status(payload),
        source_health=_source_health(payload),
    )
    try:
        result = stream_registry.append(append)
    except StreamStateError as error:
        _raise_state_error(error)

    # Persist only the newly accepted source batch as an optional immutable raw
    # block. Compact state is submitted for every accepted protocol state
    # change, but raw persistence stays disabled unless explicitly configured.
    _submit_stream_persistence(
        view_id=result.view_id,
        session_id=append.session_id,
        raw_block_id=(
            f"batch-{result.batch_sequence:020d}"
            if not result.duplicate and result.accepted_raw_records
            else None
        ),
        raw_records=result.accepted_raw_records,
    )
    notify_stream_browser(result.view_id)

    return {
        "ok": True,
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": result.view_id,
        "client_id": append.client_id,
        "session_id": append.session_id,
        "batch_sequence": result.batch_sequence,
        "accepted_records": result.accepted_records,
        "duplicate": result.duplicate,
        "next_batch_sequence": result.next_batch_sequence,
    }


@router.post("/stream/heartbeat")
async def heartbeat_stream(request: Request) -> dict[str, Any]:
    """Renew producer observation without claiming an application exit state."""
    if config.get_control_local_only():
        require_local_request(request)
    payload = await _read_bounded_payload(request)
    _require_protocol_version(payload)
    _configure_heartbeat_timeout()
    heartbeat = StreamHeartbeat(
        protocol_version=STREAM_PROTOCOL_VERSION,
        view_id=_required_stream_identity(payload, "view_id"),
        client_id=_required_stream_identity(payload, "client_id"),
        session_id=_required_stream_identity(payload, "session_id"),
        delivery_state=_required_text(payload, "delivery_state"),
        pending_delivery=_required_bool(payload, "pending_delivery"),
        source_status=_source_status(payload),
        source_health=_source_health(payload),
    )
    try:
        result = stream_registry.heartbeat(heartbeat)
    except StreamStateError as error:
        _raise_state_error(error)
    _submit_stream_persistence(
        view_id=result.view_id,
        session_id=heartbeat.session_id,
    )
    notify_stream_browser(result.view_id)
    return {
        "ok": True,
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": result.view_id,
        "lifecycle": result.lifecycle,
    }


@router.post("/stream/close")
async def close_stream(request: Request) -> dict[str, Any]:
    """Record one explicit bounded-stop outcome for the accepted session."""
    if config.get_control_local_only():
        require_local_request(request)
    payload = await _read_bounded_payload(request)
    _require_protocol_version(payload)
    _configure_heartbeat_timeout()
    close = StreamClose(
        protocol_version=STREAM_PROTOCOL_VERSION,
        view_id=_required_stream_identity(payload, "view_id"),
        client_id=_required_stream_identity(payload, "client_id"),
        session_id=_required_stream_identity(payload, "session_id"),
        drain_completed=_required_bool(payload, "drain_completed"),
    )
    try:
        result = stream_registry.close(close)
    except StreamStateError as error:
        _raise_state_error(error)
    _submit_stream_persistence(
        view_id=result.view_id,
        session_id=close.session_id,
    )
    notify_stream_browser(result.view_id)
    return {
        "ok": True,
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "view_id": result.view_id,
        "lifecycle": result.lifecycle,
    }


@router.get("/stream/data")
def get_stream_data(
    view: str = Query(min_length=1),
    after: int | None = Query(default=None, ge=0),
    session_id: str | None = Query(default=None, min_length=1),
    limit: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """Expose the bounded raw window or records after a browser cursor."""
    _configure_heartbeat_timeout()
    try:
        data = stream_registry.data(
            view_id=view,
            after=after,
            session_id=session_id,
            limit=limit,
        )
    except StreamStateError as error:
        _raise_state_error(error)
    return {"protocol_version": STREAM_PROTOCOL_VERSION, **data}


@router.get("/stream/history")
def get_stream_history(
    view: str = Query(min_length=1),
    session_id: str | None = Query(default=None, min_length=1),
    after: int | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """Expose restored sessions through a path distinct from live observation.

    Without ``session_id`` this is a lightweight chooser catalogue. With one,
    it returns the compact historical session and its derived summaries. A
    historical selection never resolves through the process-local current
    owner, so a new producer cannot make an old session appear live.
    """
    _configure_heartbeat_timeout()
    try:
        if session_id is None:
            capability = _stream_history_capability(view)
            if capability["enabled"]:
                sessions = _refresh_stored_stream_history(view)
            else:
                # Preserve the route's unknown-view 404 while deliberately
                # hiding any stale process-local history when storage is off.
                stream_registry.historical_sessions(view_id=view)
                sessions = []
            return {
                "protocol_version": STREAM_PROTOCOL_VERSION,
                "object_type": "stream_historical_session_collection",
                "historical": True,
                "view_id": view,
                "revision": stream_registry.history_catalogue_revision(view_id=view),
                "capability": capability,
                "sessions": sessions,
            }
        if config.get_storage_stream_enabled(view):
            _refresh_stored_stream_history(view)
        data = stream_registry.historical_data(
            view_id=view,
            session_id=session_id,
            after=after,
            limit=limit,
        )
        summary = stream_registry.historical_summary(
            view_id=view, session_id=session_id
        )
    except StreamStateError as error:
        _raise_state_error(error)
    return {
        "protocol_version": STREAM_PROTOCOL_VERSION,
        "object_type": "stream_historical_session",
        "historical": True,
        "view_id": view,
        "session_id": session_id,
        "data": data,
        "summary": summary,
    }


@router.get("/stream/status")
def get_stream_status(view: str = Query(min_length=1)) -> dict[str, Any]:
    """Return lifecycle status for a stream observer, never app-process status."""
    _configure_heartbeat_timeout()
    try:
        status = stream_registry.status(view_id=view)
    except StreamStateError as error:
        _raise_state_error(error)
    return {"protocol_version": STREAM_PROTOCOL_VERSION, **status}


@router.get("/stream/summary")
def get_stream_summary(view: str = Query(min_length=1)) -> dict[str, Any]:
    """Expose derived compact history separately from recent source rows."""
    _configure_heartbeat_timeout()
    try:
        summary = stream_registry.summary(view_id=view)
    except StreamStateError as error:
        _raise_state_error(error)
    return {"protocol_version": STREAM_PROTOCOL_VERSION, **summary}
