# src/plotsrv/app.py
from __future__ import annotations

import base64
import shutil
import ipaddress
import time
from pathlib import Path
from typing import Any

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


def _validate_artifact_size(obj: Any) -> None:
    max_text = config.get_publish_max_artifact_text_chars()
    max_items = config.get_publish_max_json_container_items()

    if isinstance(obj, str):
        if len(obj) > max_text:
            raise HTTPException(
                status_code=413,
                detail=f"publish: artifact text too large (>{max_text} chars)",
            )
        return

    if isinstance(obj, (dict, list, tuple, set)):
        item_count = _container_item_count(obj)
        if item_count > max_items:
            raise HTTPException(
                status_code=413,
                detail=f"publish: artifact JSON/container too large (>{max_items} items)",
            )
        return

    # repr-like fallback
    s = repr(obj)
    if len(s) > max_text:
        raise HTTPException(
            status_code=413,
            detail=f"publish: artifact representation too large (>{max_text} chars)",
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


def _snapshot_summary_dict(snap: Any) -> dict[str, Any]:
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
        "extra": snap.extra or {},
    }


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


@app.get("/status")
def status(request: Request, view: str | None = None) -> dict[str, object]:
    if config.get_status_local_only():
        require_local_request(request)

    vid = view or store.get_active_view_id()
    s = store.get_status(view_id=vid)
    s.update(store.get_service_info())
    s["view_id"] = vid
    s["freshness"] = store.get_freshness(view_id=vid)
    return s


@app.get("/history")
def get_history(request: Request, view: str | None = None) -> dict[str, Any]:
    if config.get_history_local_only():
        require_local_request(request)

    vid = view or store.get_active_view_id()
    snaps = list_snapshots(root_dir=_storage_root(), view_id=vid)

    return {
        "view_id": vid,
        "count": len(snaps),
        "snapshots": [_snapshot_summary_dict(s) for s in snaps],
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


@app.get("/table/data")
def get_table_data(
    limit: int = Query(default=config.get_max_table_rows_rich(), ge=1),
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

        max_rows = min(limit, config.get_max_table_rows_rich())
        rows_df = df.head(max_rows)
        columns = list(rows_df.columns)
        rows = rows_df.to_dict(orient="records")

        total_rows = None
        returned_rows = None
        if isinstance(loaded.meta.extra, dict):
            raw_total = loaded.meta.extra.get("total_rows")
            raw_returned = loaded.meta.extra.get("returned_rows")
            total_rows = raw_total if isinstance(raw_total, int) else None
            returned_rows = raw_returned if isinstance(raw_returned, int) else None

        total_rows = total_rows if total_rows is not None else len(df)
        returned_rows = returned_rows if returned_rows is not None else len(rows)

        return {
            "columns": columns,
            "rows": rows,
            "total_rows": total_rows,
            "returned_rows": returned_rows,
            "snapshot_id": snapshot,
        }

    if not store.has_table(view_id=vid):
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    df = store.get_table_df(view_id=vid)
    max_rows = min(limit, config.get_max_table_rows_rich())

    rows_df = df.head(max_rows)
    columns = list(rows_df.columns)
    rows = rows_df.to_dict(orient="records")

    total_rows, returned_rows = store.get_table_counts(view_id=vid)

    total_rows = total_rows if total_rows is not None else len(df)
    returned_rows = returned_rows if returned_rows is not None else len(rows)

    return {
        "columns": columns,
        "rows": rows,
        "total_rows": total_rows,
        "returned_rows": returned_rows,
    }


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
            raise HTTPException(
                status_code=422,
                detail="publish: plot_png_b64 is required for kind='plot'",
            )

        try:
            png_bytes = base64.b64decode(b64.encode("utf-8"))
        except Exception:
            raise HTTPException(
                status_code=422, detail="publish: plot_png_b64 was not valid base64"
            )

        max_plot_bytes = config.get_publish_max_plot_bytes()
        if len(png_bytes) > max_plot_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"publish: decoded plot too large (>{max_plot_bytes} bytes)",
            )

        store.set_plot(png_bytes, view_id=view_id)
        store.mark_success(duration_s=None, view_id=view_id)
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

        _validate_artifact_size(artifact_obj)

        store.set_artifact(
            obj=artifact_obj,
            kind=artifact_kind,  # type: ignore[arg-type]
            label=label,
            section=section,
            view_id=view_id,
        )
        store.mark_success(duration_s=None, view_id=view_id)
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
            raise HTTPException(
                status_code=422,
                detail="publish: table dict is required for kind='table'",
            )

        cols = table.get("columns")
        rows = table.get("rows")
        if not isinstance(cols, list) or not isinstance(rows, list):
            raise HTTPException(
                status_code=422,
                detail="publish: table must include columns(list) and rows(list)",
            )

        max_rows = config.get_publish_max_table_rows()
        max_cols = config.get_publish_max_table_columns()

        if len(cols) > max_cols:
            raise HTTPException(
                status_code=413,
                detail=f"publish: table has too many columns (>{max_cols})",
            )

        if len(rows) > max_rows:
            raise HTTPException(
                status_code=413,
                detail=f"publish: table has too many rows (>{max_rows})",
            )

        for i, row in enumerate(rows[:50]):
            if isinstance(row, dict) and len(row) > max_cols:
                raise HTTPException(
                    status_code=413,
                    detail=f"publish: table row {i} has too many fields (>{max_cols})",
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
            html_simple=html_simple,
            view_id=view_id,
            total_rows=total_rows,
            returned_rows=returned_rows,
        )
        store.mark_success(duration_s=None, view_id=view_id)
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
        max_table_rows_rich=config.get_max_table_rows_rich(),
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

        rr = render_any(loaded.obj, view_id=vid, kind_hint=kind_hint)
        return {
            "view_id": vid,
            "snapshot_id": snapshot,
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
            "meta": {
                **(rr.meta or {}),
                "snapshot": True,
                "snapshot_meta": _snapshot_summary_dict(loaded.meta),
            },
        }

    if not store.has_artifact(view_id=vid):
        raise HTTPException(
            status_code=404, detail="No artifact has been published yet."
        )

    art = store.get_artifact(view_id=vid)
    rr = render_any(art.obj, view_id=vid, kind_hint=art.kind)

    return {
        "view_id": vid,
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
        "meta": rr.meta or {},
    }


@app.get("/views")
def get_views(request: Request) -> list[dict[str, Any]]:
    if config.get_views_local_only():
        require_local_request(request)

    out: list[dict[str, Any]] = []
    for v in store.list_views():
        out.append(
            {
                "view_id": v.view_id,
                "section": v.section,
                "label": v.label,
                "kind": v.kind,
                "icon_key": v.icon_key,
                "freshness": store.get_freshness(view_id=v.view_id),
            }
        )
    return out
