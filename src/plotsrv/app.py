# src/plotsrv/app.py
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import store, config
from . import html as html_mod
from .backends import df_to_rich_sample
from .ui_config import get_ui_settings
from .renderers import register_default_renderers
from .renderers.registry import render_any


app = FastAPI()

# Load UI settings once at startup
UI = get_ui_settings()
register_default_renderers()


# Static files shipped inside plotsrv package (logo, etc.)
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Optional user assets mount for custom logos etc.
if UI.assets_dir is not None and UI.assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(UI.assets_dir)), name="assets")


@app.get("/status")
def status(view: str | None = None) -> dict[str, object]:
    """
    Status for a single view (default: active view).
    """
    vid = view or store.get_active_view_id()
    s = store.get_status(view_id=vid)
    s.update(store.get_service_info())
    s["view_id"] = vid
    return s


@app.get("/plot")
def get_plot(download: bool = False, view: str | None = None) -> Response:
    """
    Return the current plot PNG for a view; 404 if none.
    """
    vid = view or store.get_active_view_id()
    try:
        png = store.get_plot(view_id=vid)
    except LookupError:
        raise HTTPException(status_code=404, detail="No plot has been published yet.")

    headers: dict[str, str] = {}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="plotsrv_plot.png"'

    return Response(png, media_type="image/png", headers=headers)


@app.get("/table/data")
def get_table_data(
    limit: int = Query(default=config.get_max_table_rows_rich(), ge=1),
    view: str | None = None,
) -> dict[str, Any]:
    vid = view or store.get_active_view_id()

    if not store.has_table(view_id=vid):
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    df = store.get_table_df(view_id=vid)
    max_rows = min(limit, config.get_max_table_rows_rich())

    rows_df = df.head(max_rows)
    columns = list(rows_df.columns)
    rows = rows_df.to_dict(orient="records")

    total_rows, returned_rows = store.get_table_counts(view_id=vid)

    # fall back safely if older publishers didn’t send counts
    total_rows = total_rows if total_rows is not None else len(df)
    returned_rows = returned_rows if returned_rows is not None else len(rows)

    return {
        "columns": columns,
        "rows": rows,
        "total_rows": total_rows,
        "returned_rows": returned_rows,
    }


@app.get("/table/export")
def export_table(format: str = "csv", view: str | None = None) -> Response:
    """
    Export the current table (CSV for now).
    """
    vid = view or store.get_active_view_id()

    if not store.has_table(view_id=vid):
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    df = store.get_table_df(view_id=vid)

    fmt = (format or "csv").lower().strip()
    if fmt != "csv":
        raise HTTPException(
            status_code=400, detail="Only format=csv is supported right now."
        )

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    headers = {
        "Content-Disposition": 'attachment; filename="plotsrv_table.csv"',
    }
    return Response(csv_bytes, media_type="text/csv", headers=headers)


@app.post("/publish")
def publish(payload: dict[str, Any]) -> dict[str, Any]:
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

    # auto-register view so it appears in dropdown even before content arrives
    store.register_view(
        view_id=view_id,
        section=section,
        label=label,
        kind="none",
        activate_if_first=False,
    )

    # throttling (server-side)
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

    # apply publish
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

        store.set_plot(png_bytes, view_id=view_id)
        store.register_view(
            view_id=view_id,
            section=section,
            label=label,
            kind="plot",
            activate_if_first=False,
        )
        store.mark_success(duration_s=None, view_id=view_id)
        store.note_publish(view_id, now_s=now_s)

    elif kind == "artifact":
        artifact_kind = payload.get("artifact_kind")
        if not isinstance(artifact_kind, str) or not artifact_kind.strip():
            raise HTTPException(
                status_code=422,
                detail="publish: artifact_kind is required for kind='artifact'",
            )

        # We store the artifact payload “as-is” (string or JSON-like)
        artifact_obj = payload.get("artifact")

        # store.set_artifact should exist from your earlier store changes
        store.set_artifact(
            obj=artifact_obj,
            kind=artifact_kind.strip().lower(),
            label=label,
            section=section,
            view_id=view_id,
        )

        store.register_view(
            view_id=view_id,
            section=section,
            label=label,
            kind="artifact",
            activate_if_first=False,
        )
        store.mark_success(duration_s=None, view_id=view_id)
        store.note_publish(view_id, now_s=now_s)

        return {"ok": True, "ignored": False, "view_id": view_id}

    else:
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

        total_rows = table.get("total_rows")
        returned_rows = table.get("returned_rows")

        if total_rows is not None and not isinstance(total_rows, int):
            total_rows = None
        if returned_rows is not None and not isinstance(returned_rows, int):
            returned_rows = None

        # reconstruct DataFrame from rows/columns (server only stores sample)
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

        store.register_view(
            view_id=view_id,
            section=section,
            label=label,
            kind="table",
            activate_if_first=False,
        )
        store.mark_success(duration_s=None, view_id=view_id)
        store.note_publish(view_id, now_s=now_s)

    return {"ok": True, "ignored": False, "view_id": view_id}


@app.get("/", response_class=HTMLResponse)
def index(view: str | None = None) -> HTMLResponse:
    """
    Main HTML viewer.

    Supports: /?view=<view_id>
    """
    if view:
        store.set_active_view(view)

    active_view = store.get_active_view_id()
    kind = store.get_kind(active_view)

    if hasattr(store, "has_artifact") and store.has_artifact(view_id=active_view):
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

    html_str = html_mod.render_index(
        kind=kind,
        table_view_mode=config.get_table_view_mode(),
        table_html_simple=table_html_simple,
        max_table_rows_simple=config.get_max_table_rows_simple(),
        max_table_rows_rich=config.get_max_table_rows_rich(),
        ui_settings=UI,
        views=store.list_views(),
        active_view_id=active_view,
    )
    return HTMLResponse(content=html_str)


@app.get("/artifact")
def get_artifact(view: str | None = None) -> dict[str, Any]:
    """
    Render the latest artifact for the view and return HTML + meta.
    """
    vid = view or store.get_active_view_id()
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
