# plot_server.py
from __future__ import annotations

import io
import threading
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, HTMLResponse


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
def get_plot() -> Response:
    if _LATEST_PLOT_PNG is None:
        raise HTTPException(status_code=404, detail="No plot has been published yet.")
    return Response(_LATEST_PLOT_PNG, media_type="image/png")


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
    Simple HTML viewer for the current plot.

    Shows the current plot image and a 'Refresh' button that
    reloads the image with a cache-busting query parameter.
    """
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>plotsrv – current plot</title>
        <style>
            body {
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                margin: 1.5rem;
                max-width: 900px;
            }
            h1 {
                font-size: 1.4rem;
                margin-bottom: 1rem;
            }
            #plot-container {
                border: 1px solid #ddd;
                padding: 1rem;
                border-radius: 8px;
                background: #fafafa;
            }
            #plot {
                max-width: 100%;
                height: auto;
                display: block;
                margin-bottom: 1rem;
            }
            button {
                padding: 0.4rem 0.8rem;
                border-radius: 4px;
                border: 1px solid #ccc;
                cursor: pointer;
                background: #f5f5f5;
            }
            button:hover {
                background: #e9e9e9;
            }
            .note {
                font-size: 0.85rem;
                color: #666;
                margin-top: 0.5rem;
            }
        </style>
    </head>
    <body>
        <h1>plotsrv – current plot</h1>
        <div id="plot-container">
            <img id="plot" src="/plot" alt="Current plot (or none yet)" />
            <button type="button" onclick="refreshPlot()">Refresh</button>
            <div class="note">
                If no plot has been published yet, you may see a broken image until your code calls <code>refresh_plot_server</code> or <code>plt.show()</code>.
            </div>
        </div>

        <script>
            function refreshPlot() {
                const img = document.getElementById("plot");
                const base = "/plot";
                const url = base + "?_ts=" + Date.now(); // cache buster
                img.src = url;
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
