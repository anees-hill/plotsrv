# plot_server.py
from __future__ import annotations

import io
import threading
from typing import Any, Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles

import matplotlib

matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

import pandas as pd

try:
    import polars as pl
except Exception:
    pl = None

import uvicorn

# plotnine support
try:
    from plotnine.ggplot import ggplot as PlotnineGGPlot
except Exception:
    PlotnineGGPlot = None

# FastAPI app ----------

app = FastAPI()

# For static ui files
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Module-level state ----------

_LATEST_PLOT_PNG: Optional[bytes] = None
_SERVER_THREAD: Optional[threading.Thread] = None
_SERVER: Optional[uvicorn.Server] = None
_SERVER_RUNNING: bool = False
_DEFAULT_PORT: int = 8000

_LATEST_KIND: str = "none"  # "plot", "table", or "none"
_LATEST_TABLE_HTML: Optional[str] = None
_LATEST_TABLE_DF: Optional[pd.DataFrame] = None

# Table config
TABLE_VIEW_MODE: str = "simple"
_MAX_TABLE_ROWS_SIMPLE: int = 200
_MAX_TABLE_ROWS_RICH: int = 1000

# optional auto on show behaviour
_ORIGINAL_SHOW = plt.show
_SHOW_PATCHED = False


# FastAPI route ----------


@app.get("/plot")
def get_plot(download: bool = False) -> Response:
    if _LATEST_PLOT_PNG is None:
        raise HTTPException(status_code=404, detail="No plot has been published yet.")
    headers = {}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="plotsrv_plot.png"'
    return Response(_LATEST_PLOT_PNG, media_type="image/png", headers=headers)


# plotsrv server shutdown trigger
@app.post("/shutdown")
def shutdown(background_tasks: BackgroundTasks) -> dict:
    """
    Trigger plotsrv to shut down from the browser.
    """
    # Run stop_plot_server after the response is sent.
    background_tasks.add_task(stop_plot_server)
    return {"status": "shutting_down"}


@app.get("/table/data")
def get_table_data(
    limit: int = Query(default=_MAX_TABLE_ROWS_RICH, ge=1)
) -> dict[str, Any]:
    """
    Return a JSON sample of the current table for rich mode.

    For now we just return the first N rows; client-side handles sorting/filtering.
    """
    if _LATEST_KIND != "table" or _LATEST_TABLE_DF is None:
        raise HTTPException(status_code=404, detail="No table has been published yet.")

    n = min(limit, _MAX_TABLE_ROWS_RICH)
    df = _LATEST_TABLE_DF.head(n)

    return {
        "columns": list(df.columns),
        "rows": df.to_dict(orient="records"),
        "total_rows": int(len(_LATEST_TABLE_DF)),
        "returned_rows": int(len(df)),
    }


# Server internals ----------


def _run_server(port: int) -> None:
    """Run uvicorn server in this thread."""
    global _SERVER, _SERVER_RUNNING
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    _SERVER = server
    _SERVER_RUNNING = True
    try:
        server.run()
    finally:
        _SERVER_RUNNING = False
        _SERVER = None


def _ensure_server_running(port: int) -> None:
    """Start server in a background thread if not already running."""
    global _SERVER_THREAD, _SERVER_RUNNING

    if _SERVER_RUNNING:
        return

    thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    _SERVER_THREAD = thread
    thread.start()


def _fig_to_png_bytes(fig: Figure) -> bytes:
    """Render a matplotlib Figure to PNG bytes."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    return buf.read()


def _df_to_html_simple(df: "pd.DataFrame") -> str:
    """
    Render a simple HTML table for the first N rows of a DataFrame.

    This is the 'simple' table mode: no JS, just a basic scrollable table.
    """
    trimmed = df.head(_MAX_TABLE_ROWS_SIMPLE)
    # Basic, clean HTML. You can tweak classes/styles later.
    return trimmed.to_html(
        classes="tbl-simple",
        border=0,
        index=False,
        escape=True,
    )


def set_table_view_mode(mode: str) -> None:
    """
    Set how DataFrames are shown in the browser.

    mode:
      - "simple": static HTML table (df.head(N).to_html()).
      - "rich": Tabulator JS grid over a sample of the DataFrame.
    """
    global TABLE_VIEW_MODE
    if mode not in ("simple", "rich"):
        raise ValueError("table_view_mode must be 'simple' or 'rich'")
    TABLE_VIEW_MODE = mode


# Core refresh logic ----------


def refresh_plot_server(
    obj: Any = None,
    *,
    port: int | None = None,
    force_plotnine: bool = False,
) -> None:
    """
    Update what is being served at the viewer.

    - obj is None:
        Use current matplotlib figure (plt.gcf()) → 'plot' mode.
    - obj is a matplotlib Figure:
        Use it directly → 'plot' mode.
    - obj is a plotnine.ggplot (or force_plotnine=True):
        Call .draw() to get a Figure → 'plot' mode.
    - obj is a pandas or polars DataFrame:
        Render a simple HTML table for the first N rows → 'table' mode.
    """
    global _LATEST_PLOT_PNG, _LATEST_KIND, _LATEST_TABLE_HTML, _LATEST_TABLE_DF

    # ---- TABLE MODE: pandas / polars DataFrame --------------------------------
    if isinstance(obj, pd.DataFrame) or (pl is not None and isinstance(obj, pl.DataFrame)):  # type: ignore[arg-type]
        # Normalise to pandas
        if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
            df = obj.to_pandas()
        else:
            df = obj  # pandas DataFrame

        _LATEST_TABLE_DF = df
        _LATEST_KIND = "table"

        if TABLE_VIEW_MODE == "simple":
            _LATEST_TABLE_HTML = _df_to_html_simple(df)
        else:
            _LATEST_TABLE_HTML = None  # rich mode uses JSON, not pre-rendered HTML

        actual_port = port if port is not None else _DEFAULT_PORT
        _ensure_server_running(actual_port)
        return

    # ---- PLOT MODE: matplotlib / plotnine / current figure --------------------
    # Decide which Figure to use
    if obj is None:
        fig = plt.gcf()

    elif isinstance(obj, Figure):
        fig = obj

    elif force_plotnine:
        if not hasattr(obj, "draw"):
            raise TypeError(
                "force_plotnine=True but object has no .draw() method; "
                f"got {type(obj)!r}"
            )
        fig = obj.draw()

    elif PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):
        fig = obj.draw()

    elif hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        fig = obj.draw()

    else:
        raise TypeError(
            "refresh_plot_server expected one of: "
            "None, matplotlib.figure.Figure, plotnine.ggplot, "
            "pandas.DataFrame, polars.DataFrame; "
            f"got {type(obj)!r}"
        )

    # Render + store PNG for plot mode
    png_bytes = _fig_to_png_bytes(fig)
    _LATEST_PLOT_PNG = png_bytes
    _LATEST_KIND = "plot"

    actual_port = port if port is not None else _DEFAULT_PORT
    _ensure_server_running(actual_port)


def _patched_show(*args: Any, **kwargs: Any) -> None:
    """
    Replacement for plt.show that also updates the plot server
    from the current figure.
    """
    refresh_plot_server()
    _ORIGINAL_SHOW(*args, **kwargs)


def _patch_matplotlib_show() -> None:
    global _SHOW_PATCHED
    if _SHOW_PATCHED:
        return
    plt.show = _patched_show
    _SHOW_PATCHED = True


# Public API ----------


def start_plot_server(
    *,
    port: int = 8000,
    auto_on_show: bool = True,
) -> None:
    """
    Start the FastAPI/uvicorn plot server.

    - Binds to 0.0.0.0:<port>.
    - If auto_on_show=True, monkeypatches matplotlib.pyplot.show so that
      each call to plt.show() also updates the served plot.
    """
    global _DEFAULT_PORT
    _DEFAULT_PORT = port
    _ensure_server_running(port)
    if auto_on_show:
        _patch_matplotlib_show()


def stop_plot_server() -> None:
    """
    Request the background uvicorn server to shut down.
    """
    global _SERVER
    if _SERVER is not None:
        _SERVER.should_exit = True


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """
    Main viewer page.
    Renders either:
      - the current plot,
      - a simple HTML table,
      - or a rich Tabulator grid.
    """

    # -----------------------------
    # Tabulator CDN (only in rich mode)
    # -----------------------------
    tabulator_head = ""
    extra_js = ""

    if _LATEST_KIND == "table" and TABLE_VIEW_MODE == "rich":
        tabulator_head = """
        <link href="https://unpkg.com/tabulator-tables@5.5.0/dist/css/tabulator.min.css" rel="stylesheet">
        <script src="https://unpkg.com/tabulator-tables@5.5.0/dist/js/tabulator.min.js"></script>
        """

        # JS that loads the JSON and constructs a Tabulator grid
        extra_js = f"""
        async function loadTable() {{
          const res = await fetch("/table/data");
          if (!res.ok) {{
            console.error("Failed to load table data");
            return;
          }}

          const data = await res.json();
          const columns = data.columns.map(col => {{ return {{ title: col, field: col }}; }});
          const rows = data.rows;

          new Tabulator("#table-grid", {{
            data: rows,
            columns: columns,
            height: "600px",
            layout: "fitDataStretch",
            pagination: "local",
            paginationSize: 20,
            movableColumns: true,
          }});
        }}

        document.addEventListener("DOMContentLoaded", function () {{
          if (document.getElementById("table-grid")) {{
            loadTable();
          }}
        }});
        """

    # -----------------------------
    # MAIN CONTENT SWITCH
    # -----------------------------
    if _LATEST_KIND == "table" and _LATEST_TABLE_DF is not None:

        # --- SIMPLE TABLE MODE ---
        if TABLE_VIEW_MODE == "simple" and _LATEST_TABLE_HTML is not None:
            main_content = f"""
              <div class="plot-frame">
                <div class="table-scroll">
                  {_LATEST_TABLE_HTML}
                </div>
              </div>

              <div class="controls">
                <button type="button" onclick="window.location.reload()">Refresh</button>
                <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
              </div>

              <div class="note" id="status">
                Showing up to {_MAX_TABLE_ROWS_SIMPLE} rows (simple table mode).
              </div>
            """

        # --- RICH TABLE MODE ---
        else:
            main_content = f"""
              <div class="plot-frame">
                <div id="table-grid" class="table-scroll"></div>
              </div>

              <div class="controls">
                <button type="button" onclick="window.location.reload()">Refresh</button>
                <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
              </div>

              <div class="note" id="status">
                Showing up to {_MAX_TABLE_ROWS_RICH} rows (rich table mode).
              </div>
            """

    # -----------------------------
    # PLOT MODE
    # -----------------------------
    elif _LATEST_KIND == "plot" and _LATEST_PLOT_PNG is not None:
        main_content = """
          <div class="plot-frame">
            <img id="plot" src="/plot" alt="Current plot (or none yet)" />
          </div>

          <div class="controls">
            <button type="button" onclick="refreshPlot()">Refresh</button>
            <button type="button" onclick="exportImage()">Export image</button>
            <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
          </div>

          <div class="note" id="status">
            If no plot has been published yet, you may see a broken image until your code calls
            <code>refresh_plot_server</code> or <code>plt.show()</code>.
          </div>
        """

    # -----------------------------
    # NO CONTENT YET
    # -----------------------------
    else:
        main_content = """
          <div class="plot-frame empty">
            <div class="empty-state">
              No plot or table has been published yet.<br />
              Call <code>refresh_plot_server(fig)</code> or <code>refresh_plot_server(df)</code>.
            </div>
          </div>

          <div class="controls">
            <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
          </div>

          <div class="note" id="status"></div>
        """

    # -----------------------------
    # FULL HTML PAGE
    # -----------------------------
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>plotsrv – viewer</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      {tabulator_head}
      <style>
        :root {{
          --bg: #f5f5f5;
          --border: #ddd;
          --button-bg: #ffffff;
          --button-bg-hover: #f0f0f0;
        }}

        body {{
          margin: 0;
          font-family: system-ui, sans-serif;
          background: var(--bg);
          color: #222;
        }}

        .header {{
          background: #ffffff;
          border-bottom: 1px solid var(--border);
          padding: 0.5rem 1rem;
          display: flex;
          gap: 0.5rem;
          align-items: center;
        }}

        .header-logo {{
          height: 28px;
        }}

        .header-title {{
          font-weight: 600;
          font-size: 1rem;
          color: #555;
        }}

        .page {{
          max-width: 1100px;
          margin: 1.5rem auto;
          padding: 0 1rem 2rem;
        }}

        .plot-card {{
          background: #fff;
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 1rem;
          box-shadow: 0 2px 6px rgba(0,0,0,0.03);
        }}

        .plot-frame {{
          border-radius: 6px;
          overflow: hidden;
          border: 1px solid #eee;
          background: #fafafa;
          padding: 0.5rem;
        }}

        .table-scroll {{
          overflow: auto;
          max-height: 600px;
        }}

        .controls {{
          margin-top: 0.75rem;
          display: flex;
          gap: 0.5rem;
        }}

        .controls button {{
          padding: 0.4rem 0.9rem;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--button-bg);
          cursor: pointer;
        }}

        .controls button:hover {{
          background: var(--button-bg-hover);
        }}

        .controls .danger {{
          border-color: #e48b8b;
          color: #792424;
          background: #ffecec;
        }}

        .note {{
          margin-top: 0.5rem;
          font-size: 0.8rem;
          color: #666;
        }}
      </style>
    </head>

    <body>
      <header class="header">
        <img src="/static/plotsrv_logo.jpg" class="header-logo" />
        <div class="header-title">live viewer</div>
      </header>

      <main class="page">
        <section class="plot-card">
          {main_content}
        </section>
      </main>

      <script>
        function refreshPlot() {{
          const img = document.getElementById("plot");
          if (!img) return;
          img.src = "/plot?_ts=" + Date.now();
        }}

        function exportImage() {{
          window.location.href = "/plot?download=1&_ts=" + Date.now();
        }}

        function terminateServer() {{
          fetch("/shutdown", {{ method: "POST" }})
            .then(() => {{
              const status = document.getElementById("status");
              if (status) status.textContent = "plotsrv server is shutting down…";
            }});
        }}

        {extra_js}
      </script>
    </body>
    </html>
    """

    return HTMLResponse(content=html)
