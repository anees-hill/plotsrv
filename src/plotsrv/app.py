# src/plotsrv/app.py
from __future__ import annotations

import asyncio
import base64
import json
import logging
import shutil
import stat
import time
from html import escape as escape_html
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import store, config
from . import html as html_mod
from .browser_updates import BrowserUpdateCapacityError, browser_update_hub
from .ui_config import get_ui_settings
from .renderers import register_default_renderers
from .renderers.registry import render_any
from .render_cache import cache_rendered_artifact, get_cached_rendered_artifact
from .storage.worker import enqueue_snapshot, get_storage_queue_stats
from .storage.stream_worker import get_stream_storage_queue_stats
from .storage.backend import list_snapshots
from .publishing.worker import get_publish_queue_stats
from .http_publish import (
    _publish_source_label,
    _raise_publish_rejection,
    _record_publish_rejection_artifact,
    _validate_artifact_size,
)
from .http_security import require_local_request
from .ingestion import (IngestionError, IngestionMiddleware, ingestion_lifespan,
    read_payload, require_admitted, MAX_PUBLISH_REQUEST_BYTES, router as ingestion_router)
from .http_snapshots import (
    _latest_snapshot_is_live_equivalent,
    _load_snapshot_or_404,
    _render_plot_snapshot_html,
    _render_table_snapshot_html,
    _snapshot_summary_dict,
    _storage_root,
)
from .http_streams import router as stream_router
from .streams.server_state import stream_registry, UnknownStreamError
from .runtime import (
    FileBackedLoadBusyError,
    acquire_file_backed_load_slot,
    file_backed_load_slot,
    get_file_backed_load_stats,
    read_file_backed_artifact_preview,
    read_file_backed_csv_preview,
    watched_file_user_error,
)


logger = logging.getLogger(__name__)


def _build_app() -> FastAPI:
    docs_enabled = config.get_docs_enabled()
    openapi_enabled = config.get_openapi_enabled()

    return FastAPI(
        lifespan=ingestion_lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if openapi_enabled else None,
    )


app = _build_app()
register_default_renderers()
app.include_router(stream_router)
app.include_router(ingestion_router)
from .remote_watch import router as remote_watch_router
app.include_router(remote_watch_router)
app.add_middleware(IngestionMiddleware)


@app.exception_handler(IngestionError)
async def ingestion_error_handler(request: Request, error: IngestionError):
    return error.response()


@app.get("/updates")
async def browser_updates(
    request: Request,
    view: str = Query(min_length=1),
    since: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """Stream bounded change notices; view payloads stay on existing routes."""
    last_event_id = request.headers.get("last-event-id")
    if last_event_id and last_event_id.isdecimal():
        since = max(since, int(last_event_id))
    try:
        subscription = browser_update_hub.subscribe(
            view_id=view,
            since=since,
            loop=asyncio.get_running_loop(),
        )
    except BrowserUpdateCapacityError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    async def events():
        try:
            yield "retry: 2000\n\n"
            # Always announce the receiver epoch, even when a reconnect's old
            # Last-Event-ID exceeds this process's new revision counter.
            ready = json.dumps({
                **browser_update_hub.reconnect_update(view).as_dict(),
                "server_instance_id": browser_update_hub.instance_id,
            }, separators=(",", ":"))
            yield f"event: update\ndata: {ready}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(subscription.queue.get(), timeout=20)
                except TimeoutError:
                    # Stream liveness can change solely through elapsed time.
                    # Evaluate it beside the SSE heartbeat without introducing
                    # another browser polling route; fingerprinting suppresses
                    # duplicate notices across multiple connected clients.
                    try:
                        if store.get_kind(view) == "stream":
                            from .http_streams import notify_stream_browser

                            notify_stream_browser(view)
                    except Exception:
                        pass
                    # A named event remains payload-free but lets browser code
                    # distinguish a healthy, idle SSE connection from one
                    # silently stalled by a proxy or a suspended network.
                    yield "event: keepalive\ndata: {}\n\n"
                    continue
                payload = json.dumps({
                    **event.as_dict(),
                    "server_instance_id": browser_update_hub.instance_id,
                }, separators=(",", ":"))
                yield f"id: {event.revision}\nevent: update\ndata: {payload}\n\n"
        finally:
            browser_update_hub.unsubscribe(subscription)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

# Static files shipped inside plotsrv package (logo, etc.)
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_ASSETS_CACHE_DIR = STATIC_DIR / "_runtime_assets"


def _ensure_assets_mount() -> None:
    """
    Mount /assets using a dedicated cache directory containing only explicitly
    configured asset files (for example logo/favicon), not their whole parents.
    """
    ui = get_ui_settings()

    asset_files: list[Path] = []
    if ui.assets_dir is not None:
        # backwards compatibility: if assets_dir is actually a file, use it
        if ui.assets_dir.exists() and ui.assets_dir.is_file():
            asset_files.append(ui.assets_dir)
    for asset_file in getattr(ui, "asset_files", ()):
        if (
            asset_file.exists()
            and asset_file.is_file()
            and asset_file not in asset_files
        ):
            asset_files.append(asset_file)

    # Rebuild cache dir
    if not asset_files:
        return

    _ASSETS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for src in asset_files:
        dst = _ASSETS_CACHE_DIR / src.name
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)

    existing = app.router.routes
    for route in existing:
        if getattr(route, "path", None) == "/assets":
            current_dir = getattr(getattr(route, "app", None), "directory", None)
            if current_dir == str(_ASSETS_CACHE_DIR):
                return

    app.mount("/assets", StaticFiles(directory=str(_ASSETS_CACHE_DIR)), name="assets")


def _render_artifact_response(
    *,
    view_id: str,
    obj: Any,
    kind_hint: str,
    meta: dict[str, Any] | None = None,
    snapshot_id: str | None = None,
    observation_context=None,
) -> dict[str, Any]:
    if (
        kind_hint == "json"
        and type(obj) is dict
        and obj.get("type") == "plotsrv_observation"
    ):
        from .observations.rendering import render_observation
        entries, pruned = observation_context or ([], False)
        from .ingestion import state as ingestion_state
        descriptor = ingestion_state().descriptors.get(view_id)
        from .descriptions import source_description

        meta_view = store._VIEW_META.get(view_id)
        description = source_description(
            view_id,
            (
                meta_view.description
                if meta_view
                else descriptor.description if descriptor else None
            ),
        )
        if description and snapshot_id is not None:
            description = (
                "Current source description (not stored with this snapshot): "
                + description
            )
        rr = render_observation(
            obj,
            view_id=view_id,
            entries=entries,
            pruned=pruned,
            snapshot=snapshot_id is not None,
            description=description,
            storage_message=(
                _snapshot_capability(view_id)["message"]
                if snapshot_id is None
                else None
            ),
        )
    else:
        rr = render_any(
            obj,
            view_id=view_id,
            kind_hint=kind_hint,
            source_info=(meta or {}).get("source_info"),
        )

    out_meta: dict[str, Any] = {}
    out_meta.update(rr.meta or {})

    if meta:
        out_meta.update(meta)

    out: dict[str, Any] = {
        "view_id": view_id,
        "kind": rr.kind,
        "html": rr.html,
        "mime": rr.mime,
        "truncation": (
            None
            if rr.truncation is None
            else {
                "truncated": rr.truncation.truncated,
                "reason": rr.truncation.reason,
                "details": rr.truncation.details,
            }
        ),
        "meta": out_meta,
    }

    if snapshot_id is not None:
        out["snapshot_id"] = snapshot_id

    return out


def _current_observation_context(*, view_id, obj, kind_hint, revision, blocking=True):
    """Share the bounded revision-aware evidence used by live and captured views."""
    if (
        kind_hint == "json"
        and type(obj) is dict
        and obj.get("type") == "plotsrv_observation"
    ):
        from .observations.history import read

        return read(view_id, revision=revision, blocking=blocking)
    return None


def _render_current_artifact_response(
    *,
    view_id: str,
    obj: Any,
    kind_hint: str,
    meta: dict[str, Any] | None = None,
    revision: int | None = None,
) -> dict[str, Any]:
    """Render an in-memory current artifact, reusing its current revision."""
    if revision is None:
        revision = store.get_render_revision(view_id=view_id)
    cached = get_cached_rendered_artifact(view_id=view_id, revision=revision)
    if cached is not None:
        return cached

    observation_context = _current_observation_context(
        view_id=view_id, obj=obj, kind_hint=kind_hint, revision=revision
    )
    rendered = _render_artifact_response(
        view_id=view_id,
        obj=obj,
        kind_hint=kind_hint,
        meta=meta,
        observation_context=observation_context,
    )
    return cache_rendered_artifact(
        view_id=view_id,
        revision=revision,
        response=rendered,
    )


def _watched_file_raw_url(*, view_id: str, download: bool = False) -> str:
    query = urlencode({"view": view_id, "download": "1" if download else "0"})
    return f"/watched-file/raw?{query}"


def _watched_file_source_meta(*, view_id: str) -> dict[str, str]:
    return {
        "source_url": _watched_file_raw_url(view_id=view_id),
        "source_download_url": _watched_file_raw_url(view_id=view_id, download=True),
    }


def _public_watched_file_meta(meta: store.WatchedFileMeta) -> dict[str, Any]:
    """Return watched-file metadata that is safe to send to browser clients.

    The absolute source path and low-level read error belong in server logs. A
    browser only needs the file kind and the limits that shape its preview.
    """
    return {
        "file_kind": meta.file_kind,
        "read_mode": meta.read_mode,
        "encoding": meta.encoding,
        "materialization": meta.materialization,
        "size_bytes": meta.size_bytes,
        "mtime_ns": meta.mtime_ns,
        "max_bytes": meta.max_bytes,
        "last_checked_at": meta.last_checked_at,
        "last_read_at": meta.last_read_at,
    }


def _watched_file_media_type(meta: store.WatchedFileMeta) -> str:
    kind = meta.file_kind
    return {
        "csv": "text/csv",
        "json": "application/json",
        "markdown": "text/markdown",
        "ini": "text/plain",
        "toml": "application/toml",
        "yaml": "application/yaml",
        "html": "text/html",
        "image": {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }.get(Path(meta.path).suffix.lower(), "application/octet-stream"),
    }.get(kind, "text/plain")


def _registered_watched_file_or_404(*, view_id: str) -> tuple[store.WatchedFileMeta, Path]:
    """Resolve a raw source only from registered watch metadata."""
    try:
        meta = store.get_watched_file_meta(view_id=view_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="No watched file is registered for this view.") from e

    path = Path(meta.path).expanduser()
    try:
        info = path.lstat()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="The watched source file no longer exists.") from e
    except OSError as e:
        raise HTTPException(status_code=404, detail="The watched source file cannot be read.") from e

    if not stat.S_ISREG(info.st_mode):
        raise HTTPException(status_code=409, detail="The watched source is no longer a regular file.")

    return meta, path


def _watched_file_raw_response(
    *,
    view_id: str,
    download: bool,
) -> FileResponse:
    meta, path = _registered_watched_file_or_404(view_id=view_id)
    headers = {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path,
        media_type=_watched_file_media_type(meta),
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
        headers=headers,
    )


def _file_backed_load_busy_http_exception() -> HTTPException:
    retry_after = max(1, int(config.get_watch_active_load_wait_timeout_s()) + 1)
    return HTTPException(
        status_code=503,
        detail="This file-backed preview is temporarily busy. Retry shortly.",
        headers={"Retry-After": str(retry_after)},
    )


def _render_file_backed_image_response(
    *,
    view_id: str,
    meta: store.WatchedFileMeta,
) -> dict[str, Any]:
    source_url = _watched_file_raw_url(view_id=view_id)
    html = (
        "<div class='plotsrv-file-image'>"
        f"<img src='{escape_html(source_url, quote=True)}' "
        "style='max-width:100%;height:auto' alt='Watched image' />"
        "</div>"
    )
    return {
        "view_id": view_id,
        "kind": "image",
        "html": html,
        "mime": "text/html",
        "truncation": None,
        "meta": {
            "file_backed": True,
            "watch": True,
            **_public_watched_file_meta(meta),
            "source": "file_backed_stream",
            **_watched_file_source_meta(view_id=view_id),
        },
    }


def _render_file_backed_html_stream_response(
    *,
    view_id: str,
    meta: store.WatchedFileMeta,
) -> dict[str, Any]:
    """Render unsanitised file-backed HTML without putting the file in JSON."""
    source_url = _watched_file_raw_url(view_id=view_id)
    # An empty sandbox is deliberately stronger than the normal in-memory HTML
    # iframe default: no scripts, forms, popups, or same-origin access are
    # granted to a raw on-disk report.
    sandbox = config.get_html_sandbox().strip()
    html = (
        "<div class='plotsrv-html-iframe-wrap' data-plotsrv-html-frame='file-backed'>"
        f"<iframe class='plotsrv-html-iframe' sandbox='{escape_html(sandbox, quote=True)}' "
        f"src='{escape_html(source_url, quote=True)}' referrerpolicy='no-referrer'></iframe>"
        "</div>"
    )
    return {
        "view_id": view_id,
        "kind": "html",
        "html": html,
        "mime": "text/html",
        "truncation": None,
        "meta": {
            "file_backed": True,
            "watch": True,
            **_public_watched_file_meta(meta),
            "mode": "file_backed_sandboxed_iframe",
            "sandbox": sandbox,
            "source": "file_backed_stream",
            **_watched_file_source_meta(view_id=view_id),
        },
    }


def _file_backed_error_text(
    *,
    title: str,
    error: BaseException | str,
    view_id: str,
    meta: store.WatchedFileMeta | None,
) -> str:
    logger.warning(
        "File-backed watched view failed (view_id=%s, path=%s, operation=%s): %s",
        view_id,
        None if meta is None else meta.path,
        title,
        error,
    )
    return watched_file_user_error(error)


def _render_file_backed_error_response(
    *,
    view_id: str,
    title: str,
    error: BaseException | str,
    meta: store.WatchedFileMeta | None,
    status_code: int | None = None,
) -> dict[str, Any]:
    error_text = _file_backed_error_text(
        title=title,
        error=error,
        view_id=view_id,
        meta=meta,
    )

    if meta is not None:
        try:
            store.mark_error(error_text, view_id=view_id)
        except Exception:
            pass

    out = _render_artifact_response(
        view_id=view_id,
        obj=error_text,
        kind_hint="watch_error",
        meta={
            "file_backed": True,
            "watch": True,
            "error": True,
            "status_code": status_code,
            **({} if meta is None else _public_watched_file_meta(meta)),
        },
    )
    out["status_code"] = status_code
    return out


def _render_file_backed_artifact_response(*, view_id: str) -> dict[str, Any]:
    try:
        meta = store.get_watched_file_meta(view_id=view_id)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail="No file-backed watched artifact is available.",
        )

    if meta.materialization != "file":
        raise HTTPException(
            status_code=404,
            detail="Watched file is not file-backed.",
        )

    if meta.file_kind == "csv":
        raise HTTPException(
            status_code=404,
            detail="File-backed CSV views are served by /table/data.",
        )

    if meta.file_kind == "image":
        return _render_file_backed_image_response(view_id=view_id, meta=meta)

    if meta.file_kind == "html" and not config.get_html_sanitize():
        return _render_file_backed_html_stream_response(view_id=view_id, meta=meta)

    try:
        with file_backed_load_slot():
            preview = read_file_backed_artifact_preview(meta)
    except FileBackedLoadBusyError:
        raise _file_backed_load_busy_http_exception()
    except FileNotFoundError as e:
        return _render_file_backed_error_response(
            view_id=view_id,
            title="file-backed artifact read failed",
            error=e,
            meta=meta,
            status_code=404,
        )
    except TypeError as e:
        return _render_file_backed_error_response(
            view_id=view_id,
            title="file-backed artifact preview failed",
            error=e,
            meta=meta,
            status_code=400,
        )
    except Exception as e:
        return _render_file_backed_error_response(
            view_id=view_id,
            title="file-backed artifact preview failed",
            error=e,
            meta=meta,
            status_code=500,
        )

    return _render_artifact_response(
        view_id=view_id,
        obj=preview.artifact,
        kind_hint=preview.artifact_kind,
        meta={
            "file_backed": True,
            "watch": True,
            **_public_watched_file_meta(meta),
            "preview_bytes": len(preview.raw),
            "source_info": preview.source_info,
            **_watched_file_source_meta(view_id=view_id),
        },
    )


def _watched_file_meta_dict(view_id: str) -> dict[str, Any] | None:
    from .remote_watch import public_meta
    remote = public_meta(view_id)
    if remote is not None:
        return remote
    if not store.has_watched_file_meta(view_id=view_id):
        return None

    try:
        meta = store.get_watched_file_meta(view_id=view_id)
    except LookupError:
        return None

    return _public_watched_file_meta(meta)


def _snapshot_capability(view_id: str) -> dict[str, Any]:
    """Describe whether ordinary snapshots can be used for a view.

    This is deliberately separate from the history result: an empty snapshot
    list is a successful, enabled state, while streams and file-backed watched
    views expose their own bounded/source-backed history models.
    """
    kind = store.get_kind(view_id)
    status_data = store.get_status(view_id=view_id)
    watched_file = _watched_file_meta_dict(view_id)
    source = "watch" if watched_file is not None else str(
        status_data.get("publish_source") or "normal"
    )
    storage_enabled = config.get_storage_enabled()

    base: dict[str, Any] = {
        "name": "snapshots",
        "enabled": False,
        "storage_enabled": storage_enabled,
        "admitted": False,
        "state": "unavailable",
        "reason": None,
        "message": "Snapshots are unavailable for this view.",
        "source": source,
        "kind": kind,
    }

    if kind == "stream":
        base.update(
            reason="stream_sessions",
            message="Streams use bounded stored sessions rather than snapshots.",
        )
        return base

    materialization = str((watched_file or {}).get("materialization") or "")
    if watched_file is not None and materialization.lower() == "file":
        base.update(
            reason="file_backed_source",
            message="File-backed watched views use the source file rather than snapshots.",
        )
        return base

    if not storage_enabled:
        base.update(
            reason="storage_disabled",
            message="Snapshot storage has not been enabled for this instance.",
        )
        return base

    if not config.get_storage_view_enabled(view_id, source=source):
        if source == "watch":
            message = "Snapshot storage is not enabled for this watched view."
            reason = "watch_storage_not_admitted"
        else:
            message = "Snapshot storage is not enabled for this view."
            reason = "view_storage_not_admitted"
        base.update(reason=reason, message=message)
        return base

    base.update(
        enabled=True,
        admitted=True,
        state="enabled",
        reason=None,
        message="Snapshots are available for this view.",
    )
    return base


@app.get("/checks")
def check_status(request: Request, view: str | None = None, after: int = 0,
                 generation: str | None = None) -> dict[str, object]:
    if config.get_status_local_only():
        require_local_request(request)
    if not 0 <= after <= 2**53 - 1 or generation is not None and len(generation) > 64:
        raise HTTPException(status_code=422, detail="Invalid check cursor")
    from .ingestion import state as ingestion_state
    ingestion_state()
    from .checks import current
    return current().snapshot(view, after=after, generation=generation)


@app.get("/status")
def status(request: Request, view: str | None = None) -> dict[str, object]:
    if config.get_status_local_only():
        require_local_request(request)

    vid = view or store.get_active_view_id()
    s = store.get_status(view_id=vid)
    s.update(store.get_service_info())
    s["publish_queue"] = get_publish_queue_stats()
    s["storage_queue"] = get_storage_queue_stats()
    # Stream persistence has its own budget and must remain inspectable apart
    # from existing latest/snapshot storage admission.
    s["stream_storage_queue"] = get_stream_storage_queue_stats()
    s["file_backed_loads"] = get_file_backed_load_stats()
    s["view_id"] = vid
    s["view_menu_revision"] = store.get_view_menu_revision()
    s["freshness"] = store.get_freshness(view_id=vid)
    from .checks import current as current_checks
    checks = current_checks()
    s["checks"] = checks.snapshot(vid, include_events=False) if checks else None

    kind = store.get_kind(vid)
    activity = store.get_data_activity(view_id=vid)
    # Activity is process-local. A marker becomes a link only after the storage
    # worker has completed its write, and only while that snapshot is retained.
    if kind != "stream":
        from .storage.backend import _view_dir

        snapshots_enabled = _snapshot_capability(vid)["enabled"]
        view_dir = _view_dir(_storage_root(), vid) if snapshots_enabled else None
        for event in activity["events"]:
            snapshot_id = event.get("snapshot_id")
            if snapshot_id and (
                view_dir is None
                or not (view_dir / (snapshot_id + "__meta.json")).is_file()
            ):
                event.pop("snapshot_id", None)
    activity["represents"] = (
        "accepted_stream_records" if kind == "stream" else "published_updates"
    )
    activity["retention_note"] = (
        "Bounded activity observed during this plotsrv process lifetime; "
        "it does not survive restart."
    )
    events = activity.get("events")
    s["data_activity"] = activity
    s["last_data_arrival_at"] = (
        events[-1].get("received_at")
        if isinstance(events, list) and events and isinstance(events[-1], dict)
        else None
    )

    watched_file = _watched_file_meta_dict(vid)
    if watched_file and watched_file.get("materialization") == "remote":
        s["stream_status"] = None
        s["data_source"] = {
            "type": "remote_watch",
            "label": "Remote watched file — " + str(watched_file.get("status", "waiting")),
        }
    elif kind == "stream":
        try:
            s["stream_status"] = stream_registry.status(view_id=vid)
        except UnknownStreamError:
            s["stream_status"] = None
        s["data_source"] = {"type": "stream", "label": "Stream producer"}
    elif store.has_watched_file_meta(view_id=vid):
        materialization = str(
            (_watched_file_meta_dict(vid) or {}).get("materialization") or "memory"
        )
        s["stream_status"] = None
        s["data_source"] = {
            "type": "watched_file",
            "label": (
                "Watched file (source-backed)"
                if materialization == "file"
                else "Watched file"
            ),
        }
    else:
        s["stream_status"] = None
        s["data_source"] = {"type": "publish", "label": "Python/API publish"}

    watched_file = _watched_file_meta_dict(vid)
    s["watched_file"] = watched_file
    s["is_watched_file"] = watched_file is not None
    s["materialization"] = (
        watched_file.get("materialization") if watched_file is not None else None
    )

    return s


@app.get("/history/navigation")
def get_history_navigation(
    request: Request,
    view: str | None = None,
    selected: str | None = None,
    before: str | None = None,
    limit: int = 50,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    from .storage.navigation import NavigationUnavailable, navigation_page

    if config.get_history_local_only():
        require_local_request(request)
    vid = view or store.get_active_view_id()
    capability = _snapshot_capability(vid)
    if not capability["enabled"]:
        return {
            "view_id": vid,
            "capability": capability,
            "result": "unavailable",
            "snapshots": [],
            "count": 0,
            "older": None,
            "newer": None,
        }
    try:
        page = navigation_page(
            root_dir=_storage_root(),
            view_id=vid,
            selected=selected,
            before=before,
            limit=limit,
            start=start,
            end=end,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid snapshot navigation query"
        ) from exc
    except (NavigationUnavailable, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Snapshot metadata navigation is unavailable or exceeds its read budget.",
        ) from exc
    return {
        **page,
        "view_id": vid,
        "capability": capability,
        "result": "available" if page["count"] else "empty",
    }


@app.get("/history/month")
def get_history_month(request: Request, month: str, view: str | None = None):
    from datetime import datetime, timezone
    from .storage.navigation import navigation_page, NavigationUnavailable
    if config.get_history_local_only():
        require_local_request(request)
    vid = view or store.get_active_view_id()
    capability = _snapshot_capability(vid)
    if not capability["enabled"]:
        return {"capability": capability, "days": {}}
    try:
        if len(month) != 7:
            raise ValueError()
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        page = navigation_page(root_dir=_storage_root(), view_id=vid, limit=1,
                               start=start.isoformat(), end=end.isoformat(), days=True)
    except ValueError as exc:
        raise HTTPException(400, "Invalid UTC calendar month") from exc
    except (NavigationUnavailable, OSError) as exc:
        raise HTTPException(503, "Calendar metadata is unavailable or exceeds its read budget.") from exc
    return {"capability": capability, "timezone": "UTC", "month": month, "days": page["days"]}


@app.get("/compare/latest")
def get_compare_latest(request: Request, view: str | None = None):
    from .compare import capture_latest
    if config.get_history_local_only() or config.get_status_local_only():
        require_local_request(request)
    vid = view or store.get_active_view_id()
    if not _snapshot_capability(vid)["enabled"]:
        raise HTTPException(409, "Snapshot comparison is unavailable for this view.")
    try:
        return capture_latest(vid)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(409, "Latest could not be captured coherently. Choose Latest again.") from exc


@app.get("/history")
def get_history(request: Request, view: str | None = None) -> dict[str, Any]:
    if config.get_history_local_only():
        require_local_request(request)

    vid = view or store.get_active_view_id()
    snaps = list_snapshots(root_dir=_storage_root(), view_id=vid)

    snapshots_out: list[dict[str, Any]] = []
    for i, snap in enumerate(snaps):
        is_latest = i == 0
        snapshots_out.append(
            _snapshot_summary_dict(
                snap,
                is_latest=is_latest,
                is_live_equivalent=(
                    is_latest
                    and _latest_snapshot_is_live_equivalent(view_id=vid, snap=snap)
                ),
            )
        )

    capability = _snapshot_capability(vid)
    result = "unavailable" if not capability["enabled"] else (
        "available" if snapshots_out else "empty"
    )

    return {
        "view_id": vid,
        "count": len(snaps),
        "snapshots": snapshots_out,
        "capability": capability,
        "result": result,
    }


@app.get("/plot")
def get_plot(
    download: bool = False,
    view: str | None = None,
    snapshot: str | None = None,
) -> Response:
    """
    Return the current plot PNG for a view, or a historical snapshot if requested.
    """
    vid = view or store.get_active_view_id()

    if snapshot:
        loaded = _load_snapshot_or_404(view_id=vid, snapshot_id=snapshot)
        if str(loaded.meta.kind).strip().lower() != "plot":
            raise HTTPException(
                status_code=400,
                detail=f"Snapshot {snapshot!r} is not a plot snapshot.",
            )
        png = loaded.obj
        if not isinstance(png, (bytes, bytearray)):
            raise HTTPException(
                status_code=500,
                detail="Stored plot snapshot payload was not valid PNG bytes.",
            )
    else:
        try:
            png = store.get_plot(view_id=vid)
        except LookupError:
            raise HTTPException(
                status_code=404, detail="No plot has been published yet."
            )

    headers: dict[str, str] = {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
    }
    if download:
        filename = f"plotsrv_plot_{snapshot}.png" if snapshot else "plotsrv_plot.png"
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(bytes(png), media_type="image/png", headers=headers)


@app.get("/watched-file/raw")
def get_watched_file_raw(
    request: Request,
    download: bool = False,
    view: str | None = None,
) -> FileResponse:
    """
    Stream the original source of a registered live watched-file view.

    The route deliberately accepts a view id, never a filesystem path. It is
    also intentionally live-only: historical exports remain snapshot-based.
    """
    if config.get_internal_read_local_only():
        require_local_request(request)

    view_id = view or store.get_active_view_id()
    return _watched_file_raw_response(view_id=view_id, download=download)


def _table_response_limits(limit: int | None) -> tuple[int | None, int | None]:
    row_limit = config.get_table_truncate_rows()
    col_limit = config.get_table_truncate_columns()

    if limit is not None:
        if row_limit is None:
            row_limit = limit
        else:
            row_limit = min(row_limit, limit)

    return row_limit, col_limit


def _table_response_df(df: pd.DataFrame, *, limit: int | None) -> pd.DataFrame:
    row_limit, col_limit = _table_response_limits(limit)

    out = df

    if col_limit is not None:
        out = out.iloc[:, : max(1, int(col_limit))]

    if row_limit is not None:
        out = out.head(max(1, int(row_limit)))

    return out


def _table_data_response_from_df(
    df: pd.DataFrame,
    *,
    limit: int | None,
    total_rows: int | None = None,
    total_rows_known: bool = True,
    loaded_rows: int | None = None,
    returned_rows: int | None = None,
    meta: dict[str, Any] | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    rows_df = _table_response_df(df, limit=limit)
    columns = list(rows_df.columns)
    rows = rows_df.to_dict(orient="records")

    resolved_total_rows = total_rows if total_rows_known else None
    if total_rows_known and resolved_total_rows is None:
        resolved_total_rows = len(df)
    resolved_loaded_rows = loaded_rows if loaded_rows is not None else len(df)
    resolved_returned_rows = returned_rows if returned_rows is not None else len(rows)

    out: dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "total_rows": resolved_total_rows,
        "total_rows_known": total_rows_known,
        "loaded_rows": resolved_loaded_rows,
        "returned_rows": resolved_returned_rows,
    }

    if meta:
        out["meta"] = meta

    if snapshot_id is not None:
        out["snapshot_id"] = snapshot_id

    return out


def _file_backed_table_error_response(
    *,
    view_id: str,
    title: str,
    error: BaseException | str,
    meta: store.WatchedFileMeta | None,
    status_code: int | None = None,
) -> dict[str, Any]:
    error_text = _file_backed_error_text(
        title=title,
        error=error,
        view_id=view_id,
        meta=meta,
    )

    if meta is not None:
        try:
            store.mark_error(error_text, view_id=view_id)
        except Exception:
            pass

    return {
        "columns": ["plotsrv_error"],
        "rows": [{"plotsrv_error": error_text}],
        "total_rows": 1,
        "returned_rows": 1,
        "meta": {
            "file_backed": True,
            "watch": True,
            "error": True,
            "artifact_kind": "watch_error",
            "status_code": status_code,
            **({} if meta is None else _public_watched_file_meta(meta)),
        },
    }


def _file_backed_csv_table_data_response(
    *,
    view_id: str,
    limit: int | None,
) -> Response:
    try:
        meta = store.get_watched_file_meta(view_id=view_id)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail="No file-backed watched CSV metadata is available.",
        )

    if meta.materialization != "file":
        raise HTTPException(
            status_code=404,
            detail="Watched CSV is not file-backed.",
        )

    if meta.file_kind != "csv":
        raise HTTPException(
            status_code=400,
            detail=f"Watched file is not CSV: {meta.file_kind!r}",
        )

    try:
        lease = acquire_file_backed_load_slot()
    except FileBackedLoadBusyError:
        raise _file_backed_load_busy_http_exception()

    try:
        preview = read_file_backed_csv_preview(
            meta,
            row_limit=_table_response_limits(limit)[0],
        )
    except FileNotFoundError as e:
        lease.release()
        return _file_backed_table_error_response(
            view_id=view_id,
            title="file-backed CSV read failed",
            error=e,
            meta=meta,
            status_code=404,
        )
    except TypeError as e:
        lease.release()
        return _file_backed_table_error_response(
            view_id=view_id,
            title="file-backed CSV preview failed",
            error=e,
            meta=meta,
            status_code=400,
        )
    except Exception as e:
        lease.release()
        return _file_backed_table_error_response(
            view_id=view_id,
            title="file-backed CSV preview failed",
            error=e,
            meta=meta,
            status_code=500,
        )

    response_meta = {
        "file_backed": True,
        "watch": True,
        **_public_watched_file_meta(meta),
        "preview_bytes": preview.preview_bytes,
        "source": preview.source,
        "total_columns": preview.total_columns,
        "returned_columns": preview.returned_columns,
        "truncated": preview.truncated,
        **_watched_file_source_meta(view_id=view_id),
    }
    return StreamingResponse(
        _stream_file_backed_table_json(
            columns=preview.columns,
            rows=preview.rows,
            total_rows=preview.total_rows,
            total_rows_known=preview.total_rows_known,
            loaded_rows=preview.loaded_rows,
            returned_rows=preview.returned_rows,
            meta=response_meta,
            release=lease.release,
        ),
        media_type="application/json",
    )


def _stream_file_backed_table_json(
    *,
    columns: list[str],
    rows: list[list[Any]],
    total_rows: int | None,
    total_rows_known: bool,
    loaded_rows: int,
    returned_rows: int,
    meta: dict[str, Any],
    release: Any,
):
    """Encode one CSV row at a time and release admission after delivery."""
    buffer = bytearray()

    def append(value: bytes) -> bytes | None:
        buffer.extend(value)
        if len(buffer) >= 64 * 1024:
            chunk = bytes(buffer)
            buffer.clear()
            return chunk
        return None

    try:
        chunk = append(b'{"columns":' + json.dumps(columns, separators=(",", ":")).encode("utf-8") + b',"rows":[')
        if chunk is not None:
            yield chunk
        for index, row in enumerate(rows):
            item = dict(zip(columns, row, strict=True))
            encoded = json.dumps(item, separators=(",", ":"), default=str).encode("utf-8")
            chunk = append((b"," if index else b"") + encoded)
            # This preview belongs exclusively to the response.  Release each
            # materialised row once encoded so the growing response buffer
            # does not overlap the complete parsed table at peak memory.
            row.clear()
            if chunk is not None:
                yield chunk
        tail = {
            "total_rows": total_rows if total_rows_known else None,
            "total_rows_known": total_rows_known,
            "loaded_rows": loaded_rows,
            "returned_rows": returned_rows,
            "meta": meta,
        }
        chunk = append(b'],"total_rows":' + json.dumps(tail["total_rows"]).encode("utf-8"))
        if chunk is not None:
            yield chunk
        for key in ("total_rows_known", "loaded_rows", "returned_rows", "meta"):
            chunk = append(
                b',"' + key.encode("utf-8") + b'":' + json.dumps(tail[key], separators=(",", ":"), default=str).encode("utf-8")
            )
            if chunk is not None:
                yield chunk
        buffer.extend(b"}")
        if buffer:
            yield bytes(buffer)
    finally:
        release()


@app.get("/table/data")
def get_table_data(
    limit: int | None = Query(default=None, ge=1),
    view: str | None = None,
    snapshot: str | None = None,
) -> dict[str, Any]:
    vid = view or store.get_active_view_id()

    if snapshot:
        loaded = _load_snapshot_or_404(view_id=vid, snapshot_id=snapshot)
        if str(loaded.meta.kind).strip().lower() != "table":
            raise HTTPException(
                status_code=400,
                detail=f"Snapshot {snapshot!r} is not a table snapshot.",
            )
        df = loaded.obj
        if not isinstance(df, pd.DataFrame):
            raise HTTPException(
                status_code=500,
                detail="Stored table snapshot payload was not a DataFrame.",
            )

        total_rows = None
        returned_rows = None
        if isinstance(loaded.meta.extra, dict):
            raw_total = loaded.meta.extra.get("total_rows")
            raw_returned = loaded.meta.extra.get("returned_rows")
            total_rows = raw_total if isinstance(raw_total, int) else None
            returned_rows = raw_returned if isinstance(raw_returned, int) else None

        return _table_data_response_from_df(
            df,
            limit=limit,
            total_rows=total_rows,
            returned_rows=returned_rows,
            snapshot_id=snapshot,
        )

    if store.has_watched_file_meta(view_id=vid):
        meta = store.get_watched_file_meta(view_id=vid)

        if meta.materialization == "file" and meta.file_kind == "csv":
            return _file_backed_csv_table_data_response(
                view_id=vid,
                limit=limit,
            )

    if not store.has_table(view_id=vid):
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    df = store.get_table_df(view_id=vid)

    total_rows, returned_rows = store.get_table_counts(view_id=vid)
    from .remote_watch import public_meta
    remote = public_meta(vid)

    return _table_data_response_from_df(
        df,
        limit=limit,
        total_rows=total_rows,
        returned_rows=returned_rows,
        total_rows_known=remote is None or (remote.get("complete", False) and not remote.get("limitation")),
        meta=(
            _watched_file_source_meta(view_id=vid)
            if store.has_watched_file_meta(view_id=vid)
            else remote
        ),
    )


@app.get("/table/export")
def export_table(
    request: Request,
    format: str = "csv",
    view: str | None = None,
    snapshot: str | None = None,
) -> Response:
    """
    Export the current table (CSV for now), or a historical table snapshot.
    """
    vid = view or store.get_active_view_id()

    fmt = (format or "csv").lower().strip()
    if fmt != "csv":
        raise HTTPException(
            status_code=400, detail="Only format=csv is supported right now."
        )

    if snapshot:
        loaded = _load_snapshot_or_404(view_id=vid, snapshot_id=snapshot)
        if str(loaded.meta.kind).strip().lower() != "table":
            raise HTTPException(
                status_code=400,
                detail=f"Snapshot {snapshot!r} is not a table snapshot.",
            )
        df = loaded.obj
        if not isinstance(df, pd.DataFrame):
            raise HTTPException(
                status_code=500,
                detail="Stored table snapshot payload was not a DataFrame.",
            )

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        headers = {
            "Content-Disposition": f'attachment; filename="plotsrv_table_{snapshot}.csv"',
        }
        return Response(csv_bytes, media_type="text/csv", headers=headers)

    if store.has_watched_file_meta(view_id=vid):
        meta = store.get_watched_file_meta(view_id=vid)
        if meta.file_kind == "csv":
            if config.get_internal_read_local_only():
                require_local_request(request)
            return _watched_file_raw_response(view_id=vid, download=True)

    if not store.has_table(view_id=vid):
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    df = store.get_table_df(view_id=vid)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    from .remote_watch import public_meta
    remote = public_meta(vid)
    headers = {
        "Content-Disposition": 'attachment; filename="plotsrv_table_preview.csv"' if remote else 'attachment; filename="plotsrv_table.csv"',
    }
    if remote:
        headers["X-Plotsrv-Coverage"] = "preview"
    return Response(csv_bytes, media_type="text/csv", headers=headers)


@app.post("/publish")
async def publish_http(request: Request) -> dict[str, Any]:
    payload = await read_payload(request, MAX_PUBLISH_REQUEST_BYTES)
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(publish, request, payload)


def publish(request: Request, payload: dict[str, Any], *, _commit=None) -> dict[str, Any]:
    """
    Publish a plot or table into a specific view.

    Expected payload (flexible):
      {
        "view_id": "etl-1:import",   # optional
        "section": "etl-1",          # optional
        "label": "import",           # optional
        "kind": "plot"|"table",
        "plot_png_b64": "...",       # if plot
        "table": {                   # if table
          "columns": [...],
          "rows": [...],
          "total_rows": 123,
          "returned_rows": 100
        },
        "table_html_simple": "<table>...</table>",  # optional
        "update_limit_s": 600,        # optional throttling
        "force": false                # optional bypass throttling
      }
    """
    # Remote watch supplies a private commit callback: conversion/validation
    # stays outside its lock; the callback atomically fences and stores content
    # with source capabilities. Ordinary publication uses the same commit path.
    from .ingestion import state
    state().authenticate(request)

    from .descriptions import received_description

    try:
        description = received_description(payload)
        from .source_info import validate as validate_source_info

        source_info = validate_source_info(payload.get("source_info"))
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid source metadata") from None
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in ("plot", "table", "artifact"):
        raise HTTPException(
            status_code=422,
            detail="publish: kind must be 'plot', 'table', or 'artifact'",
        )

    section = payload.get("section")
    label = payload.get("label")
    if any(payload.get(key) is not None and not isinstance(payload[key], str) for key in ("view_id", "label", "section")):
        raise IngestionError("invalid_request", 422, "invalid_view_metadata")
    if any(key in payload for key in ("path", "watched_file", "local_path")):
        raise IngestionError("invalid_request", 422, "filesystem_metadata_not_allowed")
    view_id = store.normalize_view_id(
        payload.get("view_id"), section=section, label=label
    )

    require_admitted(view_id)
    from .contracts import ViewDescriptor
    try:
        ViewDescriptor(view_id, label or view_id, section)
    except ValueError:
        raise IngestionError("inadmissible_view", 422, "invalid_view_metadata") from None
    if "observation" in payload:
        if _commit is not None:
            raise IngestionError("invalid_request", 422, "observation_not_watch_data")
        from .observations.receiver import receive_observation
        return receive_observation({**payload, "view_id": view_id})
    publish_source_raw = payload.get("publish_source")
    publish_source = (
        str(publish_source_raw).strip().lower()
        if isinstance(publish_source_raw, str) and publish_source_raw.strip()
        else None
    )

    try:
        store.register_view(
            view_id=view_id,
            section=section,
            label=label,
            kind="none",
            icon_key="unknown",
            description=description,
            activate_if_first=False,
        )
    except store.ViewOwnershipError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    current_active = store.get_active_view_id()
    known_view_ids = {v.view_id for v in store.list_views()}
    if current_active not in known_view_ids:
        store.set_active_view(view_id)

    update_limit_s = payload.get("update_limit_s")
    force = bool(payload.get("force") or False)

    now_s = time.time()
    if not force:
        if not store.should_accept_publish(
            view_id=view_id, update_limit_s=update_limit_s, now_s=now_s
        ):
            return {
                "ok": True,
                "ignored": True,
                "reason": "throttled",
                "view_id": view_id,
            }

    if kind == "plot":
        b64 = payload.get("plot_png_b64")
        if not b64:
            _raise_publish_rejection(
                status_code=422,
                detail="publish: plot_png_b64 is required for kind='plot'",
                view_id=view_id,
                section=section,
                label=label,
                kind="plot",
                publish_source=publish_source,
            )

        try:
            png_bytes = base64.b64decode(b64.encode("utf-8"))
        except Exception:
            _raise_publish_rejection(
                status_code=422,
                detail="publish: plot_png_b64 was not valid base64",
                view_id=view_id,
                section=section,
                label=label,
                kind="plot",
                publish_source=publish_source,
            )

        max_plot_bytes = config.get_publish_max_plot_bytes()
        if len(png_bytes) > max_plot_bytes:
            _raise_publish_rejection(
                status_code=413,
                detail=(
                    f"Decoded plot payload has {len(png_bytes)} bytes, exceeding "
                    f"limits.published_objects.max_plot_bytes={max_plot_bytes}. "
                    f"publish_source={_publish_source_label(publish_source)}"
                ),
                view_id=view_id,
                section=section,
                label=label,
                kind="plot",
                publish_source=publish_source,
            )

        def commit():
            store.set_plot(
                png_bytes,
                view_id=view_id,
                publish_source=publish_source,
            )
            store.mark_success(
                duration_s=None,
                view_id=view_id,
                publish_source=publish_source,
            )
            store.note_publish(view_id, now_s=now_s)

            enqueue_snapshot(
                view_id=view_id,
                kind="plot",
                obj=png_bytes,
                section=section if isinstance(section, str) else None,
                label=label if isinstance(label, str) else None,
                source=publish_source,
            )

            return {"ok": True, "ignored": False, "view_id": view_id}

        return _commit(commit) if _commit is not None else commit()

    elif kind == "artifact":
        artifact_kind = str(payload.get("artifact_kind") or "python").strip().lower()
        if artifact_kind not in ("text", "json", "html", "markdown", "image", "python", "code", "traceback", "watch_error", "publish_error", "exception"):
            raise IngestionError("invalid_request", 422, "unsupported_artifact_kind")
        artifact_obj = payload.get("artifact")
        # Apply the policy to the actual renderer too: malformed hints must not
        # fall back to a Markdown/HTML renderer with publisher trust flags.
        from .renderers.registry import choose_renderer
        selected_renderer = choose_renderer(artifact_obj, kind_hint=artifact_kind)
        if selected_renderer is not None and selected_renderer.kind in ("html", "markdown", "image"):
            artifact_kind = selected_renderer.kind
        if artifact_kind in ("html", "markdown"):
            key = "html" if artifact_kind == "html" else "text"
            artifact_obj = {**artifact_obj, "_plotsrv_remote": True} if isinstance(artifact_obj, dict) else {key: str(artifact_obj or ""), "_plotsrv_remote": True}
        if artifact_kind == "image" and isinstance(artifact_obj, dict) and "svg" in str(artifact_obj.get("mime", "")).lower():
            raise IngestionError("invalid_request", 422, "remote_svg_not_supported")

        if artifact_kind == "traceback" and not config.get_tracebacks_enabled():
            store.mark_error(
                "Traceback artifact rejected because tracebacks are disabled.",
                view_id=view_id,
            )
            return {
                "ok": True,
                "ignored": True,
                "reason": "tracebacks_disabled",
                "view_id": view_id,
            }

        try:
            _validate_artifact_size(
                artifact_obj,
                publish_source=None,
            )
            if artifact_kind in ("html", "markdown"):
                text_key = "html" if artifact_kind == "html" else "text"
                _validate_artifact_size(artifact_obj.get(text_key, ""), publish_source=None)
        except HTTPException as e:
            _record_publish_rejection_artifact(
                exc=e,
                view_id=view_id,
                section=section,
                label=label,
                kind="artifact",
                publish_source=publish_source,
            )
            raise

        def commit():
            store.set_artifact(
                obj=artifact_obj,
                kind=artifact_kind,
                section=section,
                label=label,
                view_id=view_id,
                publish_source=publish_source,
                source_info=source_info,
            )
            store.mark_success(
                duration_s=None,
                view_id=view_id,
                publish_source=publish_source,
            )
            store.note_publish(view_id, now_s=now_s)

            enqueue_snapshot(
                view_id=view_id,
                kind=artifact_kind,
                obj=artifact_obj,
                section=section if isinstance(section, str) else None,
                label=label if isinstance(label, str) else None,
                source=publish_source,
                **({"extra": {"source_info": source_info}} if source_info else {}),
            )

            return {"ok": True, "ignored": False, "view_id": view_id}

        return _commit(commit) if _commit is not None else commit()

    elif kind == "table":
        table = payload.get("table")
        if not isinstance(table, dict):
            _raise_publish_rejection(
                status_code=422,
                detail="publish: table dict is required for kind='table'",
                view_id=view_id,
                section=section,
                label=label,
                kind="table",
                publish_source=publish_source,
            )

        cols = table.get("columns")
        rows = table.get("rows")
        if not isinstance(cols, list) or not isinstance(rows, list):
            _raise_publish_rejection(
                status_code=422,
                detail="publish: table must include columns(list) and rows(list)",
                view_id=view_id,
                section=section,
                label=label,
                kind="table",
                publish_source=publish_source,
            )

        max_rows = config.get_publish_max_table_rows()
        max_cols = config.get_publish_max_table_columns()

        if len(cols) > max_cols:
            _raise_publish_rejection(
                status_code=413,
                detail=(
                    f"Table payload has {len(cols)} columns, exceeding "
                    f"limits.published_objects.max_table_columns={max_cols}. "
                    f"publish_source={_publish_source_label(publish_source)}"
                ),
                view_id=view_id,
                section=section,
                label=label,
                kind="table",
                publish_source=publish_source,
            )

        if len(rows) > max_rows:
            _raise_publish_rejection(
                status_code=413,
                detail=(
                    f"Table payload has {len(rows)} rows, exceeding "
                    f"limits.published_objects.max_table_rows={max_rows}. "
                    f"publish_source={_publish_source_label(publish_source)}"
                ),
                view_id=view_id,
                section=section,
                label=label,
                kind="table",
                publish_source=publish_source,
            )

        for i, row in enumerate(rows[:50]):
            if isinstance(row, dict) and len(row) > max_cols:
                _raise_publish_rejection(
                    status_code=413,
                    detail=(
                        f"Table row {i} has {len(row)} fields, exceeding "
                        f"limits.published_objects.max_table_columns={max_cols}. "
                        f"publish_source={_publish_source_label(publish_source)}"
                    ),
                    view_id=view_id,
                    section=section,
                    label=label,
                    kind="table",
                    publish_source=publish_source,
                )

        total_rows = table.get("total_rows")
        returned_rows = table.get("returned_rows")

        if total_rows is not None and not isinstance(total_rows, int):
            total_rows = None
        if returned_rows is not None and not isinstance(returned_rows, int):
            returned_rows = None

        df = pd.DataFrame(rows, columns=cols)

        from .backends import df_to_html_simple
        # Rebuild from bounded data with escaping; never trust client inline HTML.
        html_simple = df_to_html_simple(df, config.get_max_table_rows_simple())

        def commit():
            store.set_table(
                df,
                html_simple,
                view_id=view_id,
                total_rows=total_rows,
                returned_rows=returned_rows,
                publish_source=publish_source,
            )
            store.mark_success(
                duration_s=None,
                view_id=view_id,
                publish_source=publish_source,
            )
            store.note_publish(view_id, now_s=now_s)

            enqueue_snapshot(
                view_id=view_id,
                kind="table",
                obj=df,
                section=section if isinstance(section, str) else None,
                label=label if isinstance(label, str) else None,
                extra={
                    "total_rows": total_rows,
                    "returned_rows": returned_rows,
                },
                source=publish_source,
            )

            return {"ok": True, "ignored": False, "view_id": view_id}

        return _commit(commit) if _commit is not None else commit()


@app.get("/", response_class=HTMLResponse)
def index(view: str | None = None) -> HTMLResponse:
    """
    Main HTML viewer.

    Supports: /?view=<view_id>
    This is request-local only and does not mutate global active view.
    """
    active_view = view or store.get_active_view_id()
    kind = store.get_kind(active_view)

    if store.has_artifact(view_id=active_view):
        art = store.get_artifact(view_id=active_view)
        if art.kind not in ("plot", "table"):
            kind = "artifact"

    table_html_simple = None
    table_has_no_rows = False
    if (
        kind == "table"
        and config.get_table_view_mode() == "simple"
        and store.has_table(view_id=active_view)
    ):
        try:
            table_html_simple = store.get_table_html_simple(view_id=active_view)
            table_has_no_rows = len(store.get_table_df(view_id=active_view).index) == 0
        except LookupError:
            table_html_simple = None

    ui = get_ui_settings()
    _ensure_assets_mount()

    views = store.list_views()
    view_freshness = {v.view_id: store.get_freshness(view_id=v.view_id) for v in views}

    html_str = html_mod.render_index(
        kind=kind,
        table_view_mode=config.get_table_view_mode(),
        table_html_simple=table_html_simple,
        table_has_no_rows=table_has_no_rows,
        max_table_rows_simple=config.get_max_table_rows_simple(),
        max_table_rows_rich=config.get_table_truncate_rows()
        or config.get_max_table_rows_rich(),
        ui_settings=ui,
        views=views,
        view_freshness=view_freshness,
        active_view_id=active_view,
        view_menu_revision=store.get_view_menu_revision(),
        browser_update_revision=browser_update_hub.current_revision(active_view),
        browser_update_instance_id=browser_update_hub.instance_id,
        table_plot_max_points=config.get_table_plot_max_points(),
        file_backed=store.has_watched_file_meta(view_id=active_view),
    )
    return HTMLResponse(content=html_str)


@app.get("/artifact")
def get_artifact(
    view: str | None = None,
    snapshot: str | None = None,
) -> dict[str, Any]:
    """
    Render the latest artifact for the view, or a historical snapshot if requested.
    """
    vid = view or store.get_active_view_id()

    if snapshot:
        loaded = _load_snapshot_or_404(view_id=vid, snapshot_id=snapshot)
        kind_hint = str(loaded.meta.kind).strip().lower()

        if kind_hint == "plot":
            return _render_plot_snapshot_html(view_id=vid, snapshot_id=snapshot)

        if kind_hint == "table":
            return _render_table_snapshot_html(view_id=vid, snapshot_id=snapshot)

        return _render_artifact_response(
            view_id=vid,
            snapshot_id=snapshot,
            obj=loaded.obj,
            kind_hint=kind_hint,
            meta={
                "snapshot": True,
                "snapshot_meta": _snapshot_summary_dict(loaded.meta),
                "source_info": (loaded.meta.extra or {}).get("source_info"),
            },
        )

    if store.has_watched_file_meta(view_id=vid):
        meta = store.get_watched_file_meta(view_id=vid)

        if meta.materialization == "file" and meta.file_kind != "csv":
            return _render_file_backed_artifact_response(view_id=vid)

    if not store.has_artifact(view_id=vid):
        raise HTTPException(
            status_code=404, detail="No artifact has been published yet."
        )

    with store._STORE_LOCK:
        art = store.get_artifact(view_id=vid)
        revision = store.get_render_revision(view_id=vid)

    watched_meta: dict[str, Any] | None = None
    if store.has_watched_file_meta(view_id=vid):
        watched_meta = _watched_file_source_meta(view_id=vid)

    rendered = _render_current_artifact_response(
        view_id=vid,
        obj=art.obj,
        kind_hint=art.kind,
        meta={
            **(watched_meta or {}),
            **({"source_info": art.source_info} if art.source_info else {}),
        },
        revision=revision,
    )
    from .remote_watch import public_meta
    remote = public_meta(vid)
    if remote:
        # Add current status outside the content revision cache: notices aren't arrivals.
        from html import escape
        message = f"Remote watch: {remote['status']}. {remote['message']} {remote.get('limitation') or ''}"
        link = remote.get("preview_download_url")
        notice = '<div class="note">' + escape(message)
        if link:
            notice += ' <a href="' + escape(link, quote=True) + '">Download hosted preview</a>'
        notice += '</div>'
        rendered = dict(rendered, meta={**rendered.get("meta", {}), **remote}, html=notice + rendered["html"])
    return rendered


@app.get("/views")
def get_views(request: Request) -> list[dict[str, Any]]:
    from .descriptions import source_description
    from .settings import get_section

    if config.get_views_local_only():
        require_local_request(request)

    out: list[dict[str, Any]] = []
    description_policy = get_section("description-settings")
    for v in store.list_views():
        watched_file = _watched_file_meta_dict(v.view_id)

        out.append(
            {
                "view_id": v.view_id,
                "section": v.section,
                "label": v.label,
                "kind": v.kind,
                "icon_key": v.icon_key,
                "code_language": v.code_language,
                "description": source_description(
                    v.view_id, v.description, policy=description_policy
                ),
                "freshness": store.get_freshness(view_id=v.view_id),
                "is_watched_file": watched_file is not None,
                "materialization": (
                    watched_file.get("materialization")
                    if watched_file is not None
                    else None
                ),
                "watched_file": watched_file,
            }
        )
    return out
