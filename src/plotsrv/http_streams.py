"""HTTP routes for the dedicated versioned stream protocol."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from . import config, store
from .http_security import require_local_request
from .streams.models import (
    MAX_STREAM_REQUEST_BYTES,
    STREAM_PROTOCOL_VERSION,
    SourceHealth,
    SourceStatus,
    StreamAppend,
    StreamBatchValidationError,
    StreamClose,
    StreamHeartbeat,
    StreamRecordValidationError,
    StreamRegistration,
    validate_source_status,
    validate_source_health,
    validate_stream_batch,
)
from .streams.server_state import (
    StreamConflictError,
    StreamStateError,
    UnknownStreamError,
    stream_registry,
)


router = APIRouter()


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
    """Keep server expiry configuration local to every stream request."""
    stream_registry.set_heartbeat_timeout_s(config.get_stream_heartbeat_timeout_s())


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
        view_id=_required_text(payload, "view_id"),
        label=_required_text(payload, "label"),
        section=_required_text(payload, "section"),
        client_id=_required_text(payload, "client_id"),
        session_id=_required_text(payload, "session_id"),
        source_status=_source_status(payload),
        source_health=_source_health(payload),
    )
    try:
        state = stream_registry.register(registration)
    except StreamStateError as error:
        _raise_state_error(error)

    current_active = store.get_active_view_id()
    known_view_ids = {view.view_id for view in store.list_views()}
    if current_active not in known_view_ids:
        store.set_active_view(registration.view_id)

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
        view_id=_required_text(payload, "view_id"),
        client_id=_required_text(payload, "client_id"),
        session_id=_required_text(payload, "session_id"),
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
        view_id=_required_text(payload, "view_id"),
        client_id=_required_text(payload, "client_id"),
        session_id=_required_text(payload, "session_id"),
        delivery_state=_required_text(payload, "delivery_state"),
        pending_delivery=_required_bool(payload, "pending_delivery"),
        source_status=_source_status(payload),
        source_health=_source_health(payload),
    )
    try:
        result = stream_registry.heartbeat(heartbeat)
    except StreamStateError as error:
        _raise_state_error(error)
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
        view_id=_required_text(payload, "view_id"),
        client_id=_required_text(payload, "client_id"),
        session_id=_required_text(payload, "session_id"),
        drain_completed=_required_bool(payload, "drain_completed"),
    )
    try:
        result = stream_registry.close(close)
    except StreamStateError as error:
        _raise_state_error(error)
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


@router.get("/stream/status")
def get_stream_status(view: str = Query(min_length=1)) -> dict[str, Any]:
    """Return lifecycle status for a stream observer, never app-process status."""
    _configure_heartbeat_timeout()
    try:
        status = stream_registry.status(view_id=view)
    except StreamStateError as error:
        _raise_state_error(error)
    return {"protocol_version": STREAM_PROTOCOL_VERSION, **status}
