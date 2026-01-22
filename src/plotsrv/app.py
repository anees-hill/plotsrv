# src/plotsrv/app.py
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import store, config
from . import html as html_mod
from .backends import df_to_rich_sample
from .ui_config import get_ui_settings

app = FastAPI()

# Load UI settings once at startup
UI = get_ui_settings()

# Static files shipped inside plotsrv package (logo, etc.)
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Optional user assets mount for custom logos etc.
# If user sets logo=./www/company_logo.png, we mount /assets -> that directory.
if UI.assets_dir is not None and UI.assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(UI.assets_dir)), name="assets")


@app.get("/status")
def status() -> dict[str, object]:
    s = store.get_status()
    s.update(store.get_service_info())
    return s


@app.get("/plot")
def get_plot(download: bool = False) -> Response:
    """
    Return the current plot PNG; 404 if none.
    """
    try:
        png = store.get_plot()
    except LookupError:
        raise HTTPException(status_code=404, detail="No plot has been published yet.")

    headers: dict[str, str] = {}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="plotsrv_plot.png"'

    return Response(png, media_type="image/png", headers=headers)


@app.get("/table/data")
def get_table_data(
    limit: int = Query(default=config.MAX_TABLE_ROWS_RICH, ge=1),
) -> dict:
    """
    Return a JSON sample of the current table (for rich mode).
    """
    if not store.has_table():
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    df = store.get_table_df()
    max_rows = min(limit, config.MAX_TABLE_ROWS_RICH)
    return df_to_rich_sample(df, max_rows=max_rows)


@app.get("/table/export")
def export_table(format: str = "csv") -> Response:
    """
    Export the current table (CSV for now).
    """
    if not store.has_table():
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    df = store.get_table_df()

    fmt = (format or "csv").lower().strip()
    if fmt != "csv":
        raise HTTPException(status_code=400, detail="Only format=csv is supported right now.")

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    headers = {
        "Content-Disposition": 'attachment; filename="plotsrv_table.csv"',
    }
    return Response(csv_bytes, media_type="text/csv", headers=headers)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """
    Main HTML viewer.
    """
    kind = store.get_kind()
    table_html_simple = (
        store.get_table_html_simple()
        if kind == "table"
        and config.get_table_view_mode() == "simple"
        and store.has_table()
        else None
    )

    html_str = html_mod.render_index(
        kind=kind,
        table_view_mode=config.get_table_view_mode(),
        table_html_simple=table_html_simple,
        max_table_rows_simple=config.MAX_TABLE_ROWS_SIMPLE,
        max_table_rows_rich=config.MAX_TABLE_ROWS_RICH,
        ui_settings=UI,
    )
    return HTMLResponse(content=html_str)
