# plot_server.py
from __future__ import annotations

import io
import threading
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

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
