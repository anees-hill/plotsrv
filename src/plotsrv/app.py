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
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if openapi_enabled else None,
    )


app = _build_app()
register_default_renderers()
app.include_router(stream_router)


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
) -> dict[str, Any]:
    rr = render_any(obj, view_id=view_id, kind_hint=kind_hint)

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


def _render_current_artifact_response(
    *,
    view_id: str,
    obj: Any,
    kind_hint: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render an in-memory current artifact, reusing its current revision."""
    revision = store.get_render_revision(view_id=view_id)
    cached = get_cached_rendered_artifact(view_id=view_id, revision=revision)
    if cached is not None:
        return cached

    rendered = _render_artifact_response(
        view_id=view_id,
        obj=obj,
        kind_hint=kind_hint,
        meta=meta,
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
            **_watched_file_source_meta(view_id=view_id),
        },
    )


def _watched_file_meta_dict(view_id: str) -> dict[str, Any] | None:
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

    kind = store.get_kind(vid)
    activity = store.get_data_activity(view_id=vid)
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

    if kind == "stream":
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

    return _table_data_response_from_df(
        df,
        limit=limit,
        total_rows=total_rows,
        returned_rows=returned_rows,
        meta=(
            _watched_file_source_meta(view_id=vid)
            if store.has_watched_file_meta(view_id=vid)
            else None
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
    headers = {
        "Content-Disposition": 'attachment; filename="plotsrv_table.csv"',
    }
    return Response(csv_bytes, media_type="text/csv", headers=headers)


@app.post("/publish")
def publish(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
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
    if config.get_control_local_only():
        require_local_request(request)

    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in ("plot", "table", "artifact"):
        raise HTTPException(
            status_code=422,
            detail="publish: kind must be 'plot', 'table', or 'artifact'",
        )

    section = payload.get("section")
    label = payload.get("label")
    view_id = store.normalize_view_id(
        payload.get("view_id"), section=section, label=label
    )

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

    elif kind == "artifact":
        artifact_kind = str(payload.get("artifact_kind") or "python").strip().lower()
        artifact_obj = payload.get("artifact")

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
                publish_source=publish_source,
            )
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

        store.set_artifact(
            obj=artifact_obj,
            kind=artifact_kind,
            section=section,
            label=label,
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
            kind=artifact_kind,
            obj=artifact_obj,
            section=section if isinstance(section, str) else None,
            label=label if isinstance(label, str) else None,
            source=publish_source,
        )

        return {"ok": True, "ignored": False, "view_id": view_id}

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

        html_simple = payload.get("table_html_simple")
        if html_simple is not None and not isinstance(html_simple, str):
            html_simple = None

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
    if (
        kind == "table"
        and config.get_table_view_mode() == "simple"
        and store.has_table(view_id=active_view)
    ):
        try:
            table_html_simple = store.get_table_html_simple(view_id=active_view)
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

    art = store.get_artifact(view_id=vid)

    watched_meta: dict[str, Any] | None = None
    if store.has_watched_file_meta(view_id=vid):
        watched_meta = _watched_file_source_meta(view_id=vid)

    return _render_current_artifact_response(
        view_id=vid,
        obj=art.obj,
        kind_hint=art.kind,
        meta=watched_meta,
    )


@app.get("/views")
def get_views(request: Request) -> list[dict[str, Any]]:
    if config.get_views_local_only():
        require_local_request(request)

    out: list[dict[str, Any]] = []
    for v in store.list_views():
        watched_file = _watched_file_meta_dict(v.view_id)

        out.append(
            {
                "view_id": v.view_id,
                "section": v.section,
                "label": v.label,
                "kind": v.kind,
                "icon_key": v.icon_key,
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
