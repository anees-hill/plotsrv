# src/plotsrv/server.py
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import pandas as pd

try:  # optional
    import polars as pl  # type: ignore
except Exception:  # pragma: no cover
    pl = None  # type: ignore[assignment]

import uvicorn
from fastapi import BackgroundTasks

from .app import app
from .backends import fig_to_png_bytes, df_to_html_simple
from . import store, config

# plotnine support (optional)
try:  # pragma: no cover
    from plotnine.ggplot import ggplot as PlotnineGGPlot  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    PlotnineGGPlot = None  # type: ignore[assignment]


# ---- Server state

_SERVER_THREAD: threading.Thread | None = None
_SERVER: uvicorn.Server | None = None
_SERVER_RUNNING: bool = False

_DEFAULT_HOST: str = "0.0.0.0"
_DEFAULT_PORT: int = 8000
_CURRENT_HOST: str = _DEFAULT_HOST
_CURRENT_PORT: int = _DEFAULT_PORT

_ORIGINAL_SHOW = plt.show
_SHOW_PATCHED: bool = False


# ---- Uvicorn


def _run_server(host: str, port: int, quiet: bool) -> None:
    global _SERVER, _SERVER_RUNNING

    log_level = "error" if quiet else "info"
    access_log = not quiet

    config_uv = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=access_log,
    )
    server = uvicorn.Server(config_uv)
    _SERVER = server
    _SERVER_RUNNING = True
    try:
        server.run()
    finally:
        _SERVER_RUNNING = False
        _SERVER = None


def _ensure_server_running(host: str, port: int, quiet: bool) -> None:
    """
    Start server in a background thread if not already running.

    If already running on a different host/port, raise an error.
    """
    global _SERVER_THREAD, _SERVER_RUNNING, _CURRENT_HOST, _CURRENT_PORT

    if _SERVER_RUNNING:
        if host != _CURRENT_HOST or port != _CURRENT_PORT:
            raise RuntimeError(
                f"plotsrv server already running on {_CURRENT_HOST}:{_CURRENT_PORT}; "
                f"stop it before starting a new one."
            )
        return

    _CURRENT_HOST = host
    _CURRENT_PORT = port

    thread = threading.Thread(
        target=_run_server,
        args=(host, port, quiet),
        daemon=True,
    )
    _SERVER_THREAD = thread
    thread.start()


# ---- Helpers to normalize objects


def _object_is_dataframe(obj: Any) -> bool:
    if isinstance(obj, pd.DataFrame):
        return True
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        return True
    return False


def _object_to_dataframe(obj: Any) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return obj
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        return obj.to_pandas()
    raise TypeError("Expected pandas or polars DataFrame")


def _object_to_figure(obj: Any | None, force_plotnine: bool) -> Figure:
    """
    Normalise an object into a matplotlib Figure.
    """
    if obj is None:
        return plt.gcf()

    if isinstance(obj, Figure):
        return obj

    if force_plotnine:
        if not hasattr(obj, "draw"):
            raise TypeError(
                "force_plotnine=True but object has no .draw() method; "
                f"got {type(obj)!r}"
            )
        return obj.draw()  # type: ignore[no-any-return]

    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return obj.draw()  # type: ignore[no-any-return]

    if hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        return obj.draw()  # type: ignore[no-any-return]

    raise TypeError(
        "refresh_view expected one of: "
        "None, matplotlib.figure.Figure, plotnine.ggplot; "
        f"got {type(obj)!r}"
    )


# ---- Core refresh logic


def refresh_view(
    obj: Any | None = None,
    *,
    force_plotnine: bool = False,
) -> None:
    """
    Update the currently served view.

    - DataFrame (pandas or polars) → table mode.
    - Figure / plotnine / None → plot mode.
    """
    # Table mode
    if obj is not None and _object_is_dataframe(obj):
        df = _object_to_dataframe(obj)
        if config.get_table_view_mode() == "simple":
            html_simple = df_to_html_simple(df, config.MAX_TABLE_ROWS_SIMPLE)
        else:
            html_simple = None

        store.set_table(df, html_simple)

        # Ensure server is running (default host/port) if not already
        _ensure_server_running(_DEFAULT_HOST, _DEFAULT_PORT, quiet=True)
        return

    # Plot mode
    fig = _object_to_figure(obj, force_plotnine=force_plotnine)
    png_bytes = fig_to_png_bytes(fig)
    store.set_plot(png_bytes)
    _ensure_server_running(_DEFAULT_HOST, _DEFAULT_PORT, quiet=True)


# ---- matplotlib show (patching)


def _patched_show(*args: Any, **kwargs: Any) -> None:
    """
    Replacement for plt.show that also updates the view from the current figure.
    """
    refresh_view()
    backend = matplotlib.get_backend().lower()
    if "agg" not in backend:
        _ORIGINAL_SHOW(*args, **kwargs)


def _patch_matplotlib_show() -> None:
    global _SHOW_PATCHED
    if _SHOW_PATCHED:
        return
    plt.show = _patched_show  # type: ignore[assignment]
    _SHOW_PATCHED = True


def _unpatch_matplotlib_show() -> None:
    global _SHOW_PATCHED
    if not _SHOW_PATCHED:
        return
    plt.show = _ORIGINAL_SHOW  # type: ignore[assignment]
    _SHOW_PATCHED = False


# ---- Public API


def start_server(
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    auto_on_show: bool = True,
    quiet: bool = True,
) -> None:
    """
    Start the viewer server in a background thread.

    - host: e.g. "0.0.0.0" (all interfaces) or "127.0.0.1".
    - port: TCP port.
    - auto_on_show: patch plt.show to also refresh the view.
    - quiet: reduce uvicorn noise if True.
    """
    global _DEFAULT_HOST, _DEFAULT_PORT
    _DEFAULT_HOST = host
    _DEFAULT_PORT = port

    _ensure_server_running(host, port, quiet=quiet)

    if auto_on_show:
        _patch_matplotlib_show()


def stop_server(*, join: bool = False, timeout: float = 10.0) -> None:
    """
    Request the background server to shut down.

    If join=True, wait (up to `timeout` seconds) for the thread to exit.
    """
    global _SERVER, _SERVER_THREAD
    if _SERVER is not None:
        _SERVER.should_exit = True

    if join and _SERVER_THREAD is not None:
        _SERVER_THREAD.join(timeout=timeout)

    _unpatch_matplotlib_show()


@contextmanager
def plot_session(
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    auto_on_show: bool = True,
    quiet: bool = True,
):
    """
    Context manager: start server on entry, stop on exit.
    """
    start_server(host=host, port=port, auto_on_show=auto_on_show, quiet=quiet)
    try:
        yield
    finally:
        stop_server(join=False)


# Backwards-compatible aliases
start_plot_server = start_server
stop_plot_server = stop_server
refresh_plot_server = refresh_view


# ---- /shutdown route


@app.post("/shutdown")
def shutdown(background_tasks: BackgroundTasks) -> dict[str, str]:
    """
    Trigger plotsrv to shut down from the browser.
    """
    background_tasks.add_task(stop_server)
    return {"status": "shutting_down"}
