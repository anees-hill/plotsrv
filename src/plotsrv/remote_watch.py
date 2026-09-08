"""Authenticated watch receiver: bounded hosted bytes, no filesystem instructions."""

from __future__ import annotations

import base64
import hashlib
import json
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response

from . import store
from .contracts import ViewDescriptor, SourceMetadata, bounded_text
from .ingestion import state, require_admitted, read_payload, IngestionError
from .watch_capture import (
    MAX_SOURCE_BYTES,
    MAX_WATCH_REQUEST_BYTES,
    MAX_WATCHES,
    prepare,
)

MAX_HOSTED_BYTES = 16 * 1024 * 1024
router = APIRouter()


def records():
    current = state()
    if not hasattr(current, "remote_watches"):
        current.remote_watches = {}
    return current.remote_watches


def invalid(reason="invalid_watch"):
    return IngestionError("invalid_request", 422, reason)


def _keys(obj, allowed):
    if not isinstance(obj, dict) or set(obj) - set(allowed):
        raise invalid()


def _identity(payload):
    if (
        type(payload.get("protocol_version")) is not int
        or payload["protocol_version"] != 1
    ):
        raise IngestionError("incompatible_protocol", 422, "unsupported_protocol")
    try:
        vid = bounded_text(payload.get("view_id"), "view ID", 512)
    except ValueError:
        raise invalid() from None
    require_admitted(vid)
    return vid


def register(payload):
    _keys(payload, ("protocol_version", "view_id", "client_id", "label", "section"))
    vid = _identity(payload)
    client = bounded_text(payload.get("client_id"), "client ID", 64)
    descriptor = ViewDescriptor(
        vid, payload.get("label") or vid, payload.get("section")
    )
    with store._STORE_LOCK:
        entries = records()
        old = entries.get(vid)
        if store.has_watched_file_meta(view_id=vid) or store.get_kind(vid) == "stream":
            raise IngestionError("inadmissible_view", 409, "view_kind_conflict")
        if old and old.get("session"):
            if old["client"] != client:
                raise IngestionError("inadmissible_view", 409, "watch_owner_conflict")
            return dict(ok=True, session=old["session"], generation=state().generation)
        if old is None and len(entries) >= MAX_WATCHES:
            raise IngestionError("ingestion_busy", 429, "watch_capacity")
        from .ingestion import register_catalogue

        register_catalogue([descriptor], seal=False)
        entry = old or {}
        entry.update(
            hidden=False,
            client=client,
            session=uuid4().hex,
            revision=0,
            digest=None,
            descriptor=descriptor,
        )
        entries[vid] = entry
        return dict(ok=True, session=entry["session"], generation=state().generation)


def update(request, payload):
    _keys(
        payload,
        (
            "protocol_version",
            "view_id",
            "session",
            "revision",
            "source",
            "data_b64",
            "status",
            "force",
        ),
    )
    vid = _identity(payload)
    if type(payload.get("force", False)) is not bool:
        raise invalid()
    revision = payload.get("revision")
    if type(revision) is not int or not 0 < revision < 2**53:
        raise invalid()
    status = payload.get("status", "available")
    if status not in ("available", "missing", "unreadable", "changing", "unsupported"):
        raise invalid()
    with store._STORE_LOCK:
        entry = records().get(vid)
        if (
            not entry
            or not entry.get("session")
            or entry["session"] != payload.get("session")
        ):
            raise IngestionError("inadmissible_view", 409, "watch_session_conflict")
        if revision <= entry["revision"]:
            return dict(
                ok=True,
                ignored=True,
                reason="already_accepted",
                generation=state().generation,
            )
        if status != "available":
            if payload.get("data_b64") or payload.get("source"):
                raise invalid()
            entry.update(revision=revision, status=status)
            return dict(
                ok=True,
                ignored=True,
                reason="status_only",
                generation=state().generation,
            )
        source = payload.get("source")
        _keys(
            source,
            (
                "basename",
                "source_type",
                "size_bytes",
                "mtime_ns",
                "read_scope",
                "complete",
                "encoding",
                "kind",
                "generation",
            ),
        )
        SourceMetadata(source.get("basename"), source.get("source_type"))
        if source.get("source_type") != "watch" or source.get("kind") not in (
            "auto",
            "text",
            "json",
        ):
            raise invalid()
        for key in ("size_bytes", "mtime_ns"):
            if type(source.get(key)) is not int or not 0 <= source[key] < 2**63:
                raise invalid()
        bounded_text(source.get("generation"), "source generation", 64)
        if source.get("encoding") not in ("utf-8", "utf-8-sig", "ascii", "latin-1"):
            raise invalid()
        if type(source.get("complete")) is not bool or source.get("read_scope") not in (
            "full",
            "head",
            "tail",
        ):
            raise invalid()
        encoded = payload.get("data_b64")
        if (
            not isinstance(encoded, str)
            or len(encoded) > ((MAX_SOURCE_BYTES + 2) // 3) * 4
        ):
            raise invalid()
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise invalid() from None
        if len(raw) > MAX_SOURCE_BYTES or len(raw) > source["size_bytes"]:
            raise invalid()
        if source["complete"] != (source["read_scope"] == "full") or (
            source["complete"] and len(raw) != source["size_bytes"]
        ):
            raise invalid()
        try:
            prepared, limitation = prepare(raw, source)
        except Exception:
            raise invalid("unsupported_watch_content") from None
        if (
            source["complete"]
            and limitation
            and limitation.startswith("Structured parsing")
            and "raw" in entry
        ):
            entry.update(revision=revision, status="changing")
            return dict(
                ok=True,
                ignored=True,
                reason="status_only",
                generation=state().generation,
            )
        digest = hashlib.sha256(
            raw
            + json.dumps(
                {
                    k: source[k]
                    for k in ("basename", "kind", "encoding", "read_scope", "complete")
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cost = len(raw) + len(json.dumps(prepared, ensure_ascii=False).encode())
        used = sum(e.get("cost", 0) for e in records().values()) - entry.get("cost", 0)
        if used + cost > MAX_HOSTED_BYTES:
            raise IngestionError("ingestion_busy", 429, "watch_hosted_capacity")
        unchanged = digest == entry.get("digest") and not payload.get("force", False)
        if not unchanged:
            from .app import publish

            descriptor = entry["descriptor"]
            response = publish(
                request,
                dict(
                    prepared,
                    view_id=vid,
                    label=descriptor.label,
                    section=descriptor.section,
                    publish_source="watch",
                    force=True,
                ),
                _remote_watch=True,
            )
            if response.get("ignored"):
                return response
        entry.update(
            revision=revision,
            hidden=False,
            status="available",
            source=dict(source),
            raw=raw,
            digest=digest,
            cost=cost,
            limitation=limitation,
        )
        return dict(ok=True, ignored=unchanged, generation=state().generation)


def public_meta(vid):
    with store._STORE_LOCK:
        entry = records().get(vid)
        if not entry or entry.get("hidden"):
            return None
        source = entry.get("source", {})
        complete = bool(source.get("complete") and "raw" in entry)
        query = urlencode({"view": vid})
        return dict(
            source,
            facts_origin="publisher",
            materialization="remote",
            status=entry.get("status", "waiting"),
            revision=entry.get("revision", 0),
            complete=complete,
            full_download=complete,
            source_download_url=f"/watch/source?{query}" if complete else None,
            preview_download_url=(
                f"/watch/source?{query}&preview=1" if "raw" in entry else None
            ),
            limitation=entry.get("limitation"),
            message=(
                "Complete source hosted."
                if complete
                else "Preview available; original file is not hosted here."
            ),
        )


def clear_content(vid):
    with store._STORE_LOCK:
        entry = records().get(vid)
        if entry:
            for key in ("raw", "source", "digest", "cost", "limitation"):
                entry.pop(key, None)
            entry["status"] = "waiting"
            entry["hidden"] = True


@router.post("/watch/register")
async def register_http(request: Request):
    payload = await read_payload(request, 8192)
    try:
        return register(payload)
    except ValueError as error:
        if isinstance(error, IngestionError):
            raise
        raise invalid() from None


@router.post("/watch/update")
async def update_http(request: Request):
    payload = await read_payload(request, MAX_WATCH_REQUEST_BYTES)
    from starlette.concurrency import run_in_threadpool

    try:
        return await run_in_threadpool(update, request, payload)
    except ValueError as error:
        if isinstance(error, IngestionError):
            raise
        raise invalid() from None


@router.post("/watch/close")
async def close_http(request: Request):
    payload = await read_payload(request, 8192)
    _keys(payload, ("protocol_version", "view_id", "session"))
    vid = _identity(payload)
    with store._STORE_LOCK:
        entry = records().get(vid)
        if entry and entry.get("session") == payload.get("session"):
            entry.update(session=None, status="stopped")
    return {"ok": True}


@router.get("/watch/source")
def source_download(request: Request, view: str, preview: bool = False):
    from . import config
    from .http_security import require_local_request

    if config.get_internal_read_local_only():
        require_local_request(request)
    with store._STORE_LOCK:
        entry = records().get(view, {})
        source = entry.get("source", {})
        if "raw" not in entry or (not preview and not source.get("complete")):
            raise HTTPException(
                404, "Original file is not hosted; use the available preview."
            )
        # Always attachment and opaque bytes: HTML never receives same-origin execution.
        return Response(
            entry["raw"],
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="plotsrv_'
                + ("preview" if preview else "source")
                + '.bin"',
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox; default-src 'none'",
                "X-Plotsrv-Coverage": (
                    "complete" if source.get("complete") else "preview"
                ),
                "Cache-Control": "no-store",
            },
        )
