# plot_server.py
from __future__ import annotations

import io
import threading
from typing import Any, Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles

import matplotlib

matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

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


# Core refresh logic ----------


def refresh_plot_server(
    obj: Any = None,
    *,
    port: int | None = None,
    force_plotnine: bool = False,
) -> None:
    """
    Update the plot being served at /plot.

    Parameters
    ----------
    obj:
        - None: use current matplotlib figure (plt.gcf()).
        - matplotlib.figure.Figure: use it directly.
        - plotnine.ggplot: call .draw() to get a Figure.
    port:
        Port to ensure the server is running on (defaults to last used / default).
    force_plotnine:
        If True, treat `obj` as a plotnine-like object and call .draw()
        regardless of its exact type, as long as it has a .draw() method.
    """
    global _LATEST_PLOT_PNG

    # Decide which fig to use
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
            "None, matplotlib.figure.Figure, plotnine.ggplot; "
            f"got {type(obj)!r}"
        )

    png_bytes = _fig_to_png_bytes(fig)
    _LATEST_PLOT_PNG = png_bytes

    # Ensure server is running!
    actual_port = port if port is not None else _DEFAULT_PORT
    _ensure_server_running(actual_port)


# auto-on-show patching ----------


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
    Simple HTML viewer for the current plot with header, logo,
    and controls for refresh/export/shutdown.
    """
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>plotsrv – current plot</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        :root {
          --bg: #f5f5f5;
          --border: #ddd;
          --accent: #444;
          --button-bg: #ffffff;
          --button-bg-hover: #f0f0f0;
        }

        * { box-sizing: border-box; }

        body {
          margin: 0;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: var(--bg);
          color: #222;
        }

        .header {
          background: #ffffff;
          border-bottom: 1px solid var(--border);
          padding: 0.5rem 1rem;
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }

        .header-logo {
          height: 28px;
          width: auto;
          display: block;
        }

        .header-title {
          font-weight: 600;
          font-size: 1rem;
          color: #555;
        }

        .page {
          max-width: 1100px;
          margin: 1.5rem auto;
          padding: 0 1rem 2rem;
        }

        .plot-card {
          background: #fff;
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 1rem 1rem 0.75rem;
          box-shadow: 0 2px 6px rgba(0,0,0,0.03);
        }

        .plot-frame {
          border-radius: 6px;
          overflow: hidden;
          border: 1px solid #eee;
          background: #fafafa;
        }

        #plot {
          max-width: 100%;
          height: auto;
          display: block;
        }

        .controls {
          margin-top: 0.75rem;
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }

        .controls button {
          flex: 0 0 auto;
          padding: 0.4rem 0.9rem;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--button-bg);
          cursor: pointer;
          font-size: 0.9rem;
        }

        .controls button:hover {
          background: var(--button-bg-hover);
        }

        .controls button.danger {
          border-color: #e48b8b;
          color: #792424;
          background: #ffecec;
        }

        .controls button.danger:hover {
          background: #ffdede;
        }

        .note {
          margin-top: 0.4rem;
          font-size: 0.8rem;
          color: #666;
        }

        @media (max-width: 600px) {
          .page {
            margin-top: 1rem;
          }
        }
      </style>
    </head>
    <body>
      <header class="header">
        <img src="/static/plotsrv_logo.jpg" alt="plotsrv logo" class="header-logo" />
        <div class="header-title">Live viewer</div>
      </header>

      <main class="page">
        <section class="plot-card">
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
        </section>
      </main>

      <script>
        function refreshPlot() {
          const img = document.getElementById("plot");
          const base = "/plot";
          const url = base + "?_ts=" + Date.now(); // cache buster
          img.src = url;
        }

        function exportImage() {
          // Navigate to /plot?download=1 to trigger a download
          const url = "/plot?download=1&_ts=" + Date.now();
          window.location.href = url;
        }

        function terminateServer() {
          fetch("/shutdown", { method: "POST" })
            .then(() => {
              const status = document.getElementById("status");
              status.textContent = "plotsrv server is shutting down…";
            })
            .catch(() => {
              const status = document.getElementById("status");
              status.textContent = "Failed to contact server (it may already be down).";
            });
        }
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

