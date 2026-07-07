# src/plotsrv/app.py
from __future__ import annotations

import base64
import shutil
import ipaddress
import time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import store, config
from . import html as html_mod
from .ui_config import get_ui_settings
from .renderers import register_default_renderers
from .renderers.registry import render_any
from .storage.worker import enqueue_snapshot
from .storage.backend import list_snapshots, load_snapshot
from .runtime import read_file_backed_artifact_preview, read_file_backed_csv_preview


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


def _container_item_count(obj: Any) -> int:
    if isinstance(obj, dict):
        n = len(obj)
        for v in obj.values():
            n += _container_item_count(v)
        return n
    if isinstance(obj, (list, tuple, set)):
        n = len(obj)
        for v in obj:
            n += _container_item_count(v)
        return n
    return 0


def _is_watch_publish_source(publish_source: str | None) -> bool:
    return (publish_source or "").strip().lower() == "watch"


def _publish_source_label(publish_source: str | None) -> str:
    return (publish_source or "normal").strip().lower()


def _http_detail_to_text(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    try:
        return str(detail)
    except Exception:
        return "Unknown publish error"


def _publish_rejection_artifact_text(
    *,
    status_code: int,
    detail: Any,
    view_id: str,
    kind: str,
    publish_source: str | None,
) -> str:
    detail_text = _http_detail_to_text(detail)

    return (
        "plotsrv publish rejected\n"
        "\n"
        f"Status: {status_code}\n"
        f"View: {view_id}\n"
        f"Kind: {kind}\n"
        f"Publish source: {_publish_source_label(publish_source)}\n"
        "\n"
        "What failed:\n"
        f"{detail_text}\n"
        "\n"
        "Adjust the config key mentioned above, or publish a smaller/truncated object.\n"
    )


def _record_publish_rejection_artifact(
    *,
    exc: HTTPException,
    view_id: str,
    section: Any,
    label: Any,
    kind: str,
    publish_source: str | None,
) -> None:
    """
    Make rejected normal Python publishes visible in the UI.

    Watch publishes have their own fallback path in runtime.py, so avoid
    duplicating that behaviour here.
    """
    if _is_watch_publish_source(publish_source):
        return

    msg = _publish_rejection_artifact_text(
        status_code=int(exc.status_code),
        detail=exc.detail,
        view_id=view_id,
        kind=kind,
        publish_source=publish_source,
    )

    try:
        store.set_artifact(
            obj=msg,
            kind="publish_error",
            label=label if isinstance(label, str) else None,
            section=section if isinstance(section, str) else None,
            view_id=view_id,
            publish_source=publish_source,
        )
        store.mark_error(msg, view_id=view_id)
    except Exception:
        # Never hide the original publish rejection.
        return


def _raise_publish_rejection(
    *,
    status_code: int,
    detail: str,
    view_id: str,
    section: Any,
    label: Any,
    kind: str,
    publish_source: str | None,
) -> None:
    exc = HTTPException(status_code=status_code, detail=detail)
    _record_publish_rejection_artifact(
        exc=exc,
        view_id=view_id,
        section=section,
        label=label,
        kind=kind,
        publish_source=publish_source,
    )
    raise exc


def _validate_artifact_size(
    obj: Any,
    *,
    publish_source: str | None = None,
) -> None:
    """
        Validate normal /publish artifact payloads.


    Watched files are source-aware: by the time they reach /publish, they should
    already have been controlled by limits.watched_files and limits.truncate_after.*.
    They should not also be rejected by limits.published_objects.*.
    """
    if _is_watch_publish_source(publish_source):
        return

    source = _publish_source_label(publish_source)
    max_text = config.get_publish_max_artifact_text_chars()
    max_items = config.get_publish_max_json_container_items()

    if isinstance(obj, str):
        actual = len(obj)
        if actual > max_text:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Artifact text payload has {actual} characters, exceeding "
                    f"limits.published_objects.max_artifact_text_chars={max_text}. "
                    f"publish_source={source}"
                ),
            )
        return

    if isinstance(obj, (dict, list, tuple, set)):
        actual = _container_item_count(obj)
        if actual > max_items:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Artifact JSON/container payload has {actual} items, exceeding "
                    f"limits.published_objects.max_json_container_items={max_items}. "
                    f"publish_source={source}"
                ),
            )
        return

    s = repr(obj)
    actual = len(s)
    if actual > max_text:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Artifact representation has {actual} characters, exceeding "
                f"limits.published_objects.max_artifact_text_chars={max_text}. "
                f"publish_source={source}"
            ),
        )


def _client_ip(request: Request) -> str | None:
    client = request.client
    if client is None:
        return None
    return client.host


def _is_loopback_ip(value: str | None) -> bool:
    if not value:
        return False
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def require_local_request(request: Request) -> None:
    host = _client_ip(request)
    if not _is_loopback_ip(host):
        raise HTTPException(status_code=403, detail="Local access only")


def _storage_root() -> Path:
    return config.get_storage_root_dir()


def _snapshot_summary_dict(
    snap: Any,
    *,
    is_latest: bool = False,
    is_live_equivalent: bool = False,
) -> dict[str, Any]:
    return {
        "snapshot_id": snap.snapshot_id,
        "view_id": snap.view_id,
        "section": snap.section,
        "label": snap.label,
        "kind": snap.kind,
        "created_at": snap.created_at,
        "payload_filename": snap.payload_filename,
        "payload_format": snap.payload_format,
        "size_bytes": snap.size_bytes,
        "payload_exists": snap.payload_exists,
        "is_latest": is_latest,
        "is_live_equivalent": is_live_equivalent,
        "extra": snap.extra or {},
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _latest_snapshot_is_live_equivalent(*, view_id: str, snap: Any) -> bool:
    """
    Best-effort check that the newest snapshot represents current live state.

    A snapshot written as part of the current publish is normally created at or
    just after the store last_updated timestamp. If the live view has updated
    since the latest snapshot, last_updated will be later and this returns false.
    """
    status = store.get_status(view_id=view_id)
    last_updated = _parse_iso_datetime(status.get("last_updated"))
    snap_created = _parse_iso_datetime(getattr(snap, "created_at", None))

    if last_updated is None or snap_created is None:
        return False

    if snap_created < last_updated:
        return False

    live_kind = store.get_kind(view_id)
    snap_kind = str(getattr(snap, "kind", "") or "").strip().lower()

    if live_kind == "artifact":
        try:
            art = store.get_artifact(view_id=view_id)
            return str(art.kind).strip().lower() == snap_kind
        except LookupError:
            return False

    return live_kind == snap_kind


def _load_snapshot_or_404(*, view_id: str, snapshot_id: str):
    try:
        return load_snapshot(
            root_dir=_storage_root(),
            view_id=view_id,
            snapshot_id=snapshot_id,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _render_plot_snapshot_html(*, view_id: str, snapshot_id: str) -> dict[str, Any]:
    src = f"/plot?view={view_id}&snapshot={snapshot_id}"
    html = f"""
    <div class="plot-frame">
      <img id="plot" src="{src}" alt="Plot snapshot" />
    </div>
    """.strip()

    return {
        "view_id": view_id,
        "snapshot_id": snapshot_id,
        "kind": "plot",
        "html": html,
        "mime": "text/html",
        "truncation": None,
        "meta": {
            "src": src,
            "snapshot": True,
        },
    }


def _render_table_snapshot_html(*, view_id: str, snapshot_id: str) -> dict[str, Any]:
    data_src = f"/table/data?view={view_id}&snapshot={snapshot_id}"
    html = """
    <div class="plot-frame">
      <div id="table-grid" class="table-grid"></div>
    </div>
    """.strip()

    return {
        "view_id": view_id,
        "snapshot_id": snapshot_id,
        "kind": "table",
        "html": html,
        "mime": "text/html",
        "truncation": None,
        "meta": {
            "data_src": data_src,
            "snapshot": True,
        },
    }


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

    try:
        preview = read_file_backed_artifact_preview(meta)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Watched file not found: {e}",
        )
    except TypeError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read file-backed watched artifact: {type(e).__name__}: {e}",
        )

    return _render_artifact_response(
        view_id=view_id,
        obj=preview.artifact,
        kind_hint=preview.artifact_kind,
        meta={
            "file_backed": True,
            "watch": True,
            "materialization": meta.materialization,
            "path": meta.path,
            "file_kind": meta.file_kind,
            "read_mode": meta.read_mode,
            "encoding": meta.encoding,
            "size_bytes": meta.size_bytes,
            "mtime_ns": meta.mtime_ns,
            "max_bytes": meta.max_bytes,
            "preview_bytes": len(preview.raw),
        },
    )


def _reject_file_backed_table_export(*, view_id: str) -> None:
    try:
        meta = store.get_watched_file_meta(view_id=view_id)
    except LookupError:
        return

    if meta.materialization != "file":
        return

    if meta.file_kind != "csv":
        return

    raise HTTPException(
        status_code=409,
        detail=(
            "File-backed CSV export is not supported yet. "
            "This view is served as a bounded preview from disk via /table/data, "
            "not as an in-memory table. Exporting the full watched file safely "
            "will be added separately. Use the original CSV file directly for now."
        ),
    )


def _watched_file_meta_dict(view_id: str) -> dict[str, Any] | None:
    if not store.has_watched_file_meta(view_id=view_id):
        return None

    try:
        meta = store.get_watched_file_meta(view_id=view_id)
    except LookupError:
        return None

    return {
        "path": meta.path,
        "file_kind": meta.file_kind,
        "read_mode": meta.read_mode,
        "encoding": meta.encoding,
        "materialization": meta.materialization,
        "size_bytes": meta.size_bytes,
        "mtime_ns": meta.mtime_ns,
        "max_bytes": meta.max_bytes,
        "last_checked_at": meta.last_checked_at,
        "last_read_at": meta.last_read_at,
        "last_error": meta.last_error,
    }


@app.get("/status")
def status(request: Request, view: str | None = None) -> dict[str, object]:
    if config.get_status_local_only():
        require_local_request(request)

    vid = view or store.get_active_view_id()
    s = store.get_status(view_id=vid)
    s.update(store.get_service_info())
    s["view_id"] = vid
    s["freshness"] = store.get_freshness(view_id=vid)

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

    return {
        "view_id": vid,
        "count": len(snaps),
        "snapshots": snapshots_out,
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
    returned_rows: int | None = None,
    meta: dict[str, Any] | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    rows_df = _table_response_df(df, limit=limit)
    columns = list(rows_df.columns)
    rows = rows_df.to_dict(orient="records")

    resolved_total_rows = total_rows if total_rows is not None else len(df)
    resolved_returned_rows = returned_rows if returned_rows is not None else len(rows)

    out: dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "total_rows": resolved_total_rows,
        "returned_rows": resolved_returned_rows,
    }

    if meta:
        out["meta"] = meta

    if snapshot_id is not None:
        out["snapshot_id"] = snapshot_id

    return out


def _file_backed_csv_table_data_response(
    *,
    view_id: str,
    limit: int | None,
) -> dict[str, Any]:
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
        preview = read_file_backed_csv_preview(meta)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Watched CSV file not found: {e}",
        )
    except TypeError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read file-backed watched CSV: {type(e).__name__}: {e}",
        )

    return _table_data_response_from_df(
        preview.table_df,
        limit=limit,
        total_rows=preview.total_rows,
        returned_rows=min(
            preview.returned_rows,
            len(_table_response_df(preview.table_df, limit=limit)),
        ),
        meta={
            "file_backed": True,
            "watch": True,
            "materialization": meta.materialization,
            "path": meta.path,
            "file_kind": meta.file_kind,
            "read_mode": meta.read_mode,
            "encoding": meta.encoding,
            "size_bytes": meta.size_bytes,
            "mtime_ns": meta.mtime_ns,
            "max_bytes": meta.max_bytes,
            "preview_bytes": len(preview.raw),
            "source": preview.source,
            "total_columns": preview.total_columns,
            "returned_columns": preview.returned_columns,
            "truncated": preview.truncated,
        },
    )


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
    )


@app.get("/table/export")
def export_table(
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

    _reject_file_backed_table_export(view_id=vid)

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

    store.register_view(
        view_id=view_id,
        section=section,
        label=label,
        kind="none",
        icon_key="unknown",
        activate_if_first=False,
    )
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

    return _render_artifact_response(
        view_id=vid,
        obj=art.obj,
        kind_hint=art.kind,
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
