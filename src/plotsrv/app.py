# src/plotsrv/app.py
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import store, config
from . import html as html_mod
from .backends import df_to_rich_sample

app = FastAPI()

# Static files (logo, etc.)
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
    )
    return HTMLResponse(content=html_str)
