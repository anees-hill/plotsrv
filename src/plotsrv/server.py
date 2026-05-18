# src/plotsrv/server.py
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any
from pathlib import Path
from collections.abc import Sequence


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
from fastapi import BackgroundTasks, HTTPException

from .app import app, require_local_request
from .backends import fig_to_png_bytes, df_to_html_simple
from . import store, config
from .storage.worker import stop_storage_worker
from .file_kinds import coerce_file_to_publishable
from .json_model import build_json_document

# plotnine support (optional)
try:  # pragma: no cover
    from plotnine.ggplot import ggplot as PlotnineGGPlot  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    PlotnineGGPlot = None  # type: ignore[assignment]


# ---- Server state

_SERVER_THREAD: threading.Thread | None = None
_SERVER: uvicorn.Server | None = None
_SERVER_RUNNING: bool = False

_DEFAULT_HOST: str = "127.0.0.1"
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


def _wait_for_server_ready(host: str, port: int, *, timeout_s: float = 5.0) -> bool:
    import time
    import urllib.request

    url = f"http://{host}:{port}/status"
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.2) as resp:
                if resp.status in (200, 404):
                    return True
        except Exception:
            time.sleep(0.1)

    return False


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


def _looks_like_plot_object(obj: Any | None) -> bool:
    if obj is None:
        return True

    if isinstance(obj, Figure):
        return True

    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return True

    if hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        return True

    return False


def _is_pathlike_file(obj: Any) -> bool:
    if isinstance(obj, (str, bytes, bytearray)):
        return False

    try:
        p = Path(obj)  # type: ignore[arg-type]
    except Exception:
        return False

    is_pathlike = isinstance(obj, Path) or getattr(obj, "__fspath__", None) is not None
    if not is_pathlike:
        return False

    try:
        return p.expanduser().resolve().is_file()
    except Exception:
        return False


def _view_id_for_refresh(
    *,
    view_id: str | None,
    section: str | None,
    label: str | None,
) -> str | None:
    """
    Resolve the target view for refresh_view().

    Returns None when the active/default view should be used for backwards
    compatibility.
    """
    if view_id is not None:
        return store.normalize_view_id(view_id, section=section, label=label)

    if section is not None or label is not None:
        return store.normalize_view_id(None, section=section, label=label)

    return None


def _register_refresh_view_if_named(
    *,
    resolved_view_id: str | None,
    section: str | None,
    label: str | None,
    kind: str,
    icon_key: str | None = None,
) -> None:
    if resolved_view_id is None:
        return

    store.register_view(
        view_id=resolved_view_id,
        section=section,
        label=label,
        kind=kind,
        icon_key=icon_key,  # type: ignore[arg-type]
        activate_if_first=False,
    )
    store.set_active_view(resolved_view_id)


def _infer_artifact_kind_for_refresh(obj: Any) -> str:
    if isinstance(obj, str):
        return "text"
    if isinstance(obj, (bytes, bytearray)):
        return "text"
    if isinstance(obj, (dict, list, tuple, set)):
        return "json"
    return "python"


def _json_artifact_for_refresh(obj: Any) -> Any:
    if isinstance(obj, dict) and obj.get("type") == "plotsrv_json_document":
        return obj

    return build_json_document(
        obj,
        source_format="python_object",
        raw_text=None,
        source_filename=None,
    )


def _set_artifact_for_refresh(
    obj: Any,
    *,
    artifact_kind: str | None,
    label: str | None,
    section: str | None,
    view_id: str | None,
) -> None:
    kind = (artifact_kind or "").strip().lower() or _infer_artifact_kind_for_refresh(
        obj
    )

    if kind == "html" and isinstance(obj, str):
        obj = {"html": obj, "unsafe": True}

    if kind == "json":
        obj = _json_artifact_for_refresh(obj)

    elif kind == "text":
        if isinstance(obj, (bytes, bytearray)):
            obj = bytes(obj).decode("utf-8", errors="replace")
        else:
            obj = str(obj)

    elif kind == "markdown":
        obj = obj if isinstance(obj, dict) else str(obj)

    elif kind == "python":
        obj = repr(obj)

    store.set_artifact(
        obj=obj,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        section=section,
        view_id=view_id,
    )


# ---- Core refresh logic


def refresh_view(
    obj: Any | None = None,
    *,
    label: str | None = None,
    section: str | None = None,
    view_id: str | None = None,
    kind: str | None = None,
    artifact_kind: str | None = None,
    force_plotnine: bool = False,
    update_status: bool = True,
) -> None:
    """
    Update an in-process plotsrv view directly.

    This is the in-process counterpart to publish_view(...).

    - DataFrame (pandas or polars) -> table view
    - Figure / plotnine / None -> plot view
    - dict/list/tuple/set -> JSON artifact view
    - str/bytes -> text artifact view
    - Path-like file -> inferred table/artifact view
    - generic Python object -> python artifact view

    If label/section/view_id are omitted, refreshes the active/default view for
    backwards compatibility.
    """
    resolved_view_id = _view_id_for_refresh(
        view_id=view_id,
        section=section,
        label=label,
    )

    forced_kind = (kind or "").strip().lower() or None

    # Path-like file mode
    if (
        obj is not None
        and forced_kind in (None, "artifact", "table")
        and _is_pathlike_file(obj)
    ):
        path = Path(obj).expanduser().resolve()  # type: ignore[arg-type]
        coerced = coerce_file_to_publishable(
            path,
            max_rows=config.get_max_table_rows_rich(),
        )

        if coerced.publish_kind == "table":
            df = _object_to_dataframe(coerced.obj)
            html_simple = (
                df_to_html_simple(df, config.get_max_table_rows_simple())
                if config.get_table_view_mode() == "simple"
                else None
            )

            _register_refresh_view_if_named(
                resolved_view_id=resolved_view_id,
                section=section,
                label=label,
                kind="table",
                icon_key="table",
            )
            store.set_table(df, html_simple, view_id=resolved_view_id)

            if update_status:
                store.mark_success(duration_s=None, view_id=resolved_view_id)

            _ensure_server_running(_DEFAULT_HOST, _DEFAULT_PORT, quiet=True)
            return

        ak = artifact_kind or coerced.artifact_kind or "text"
        obj_to_store = coerced.obj

        _register_refresh_view_if_named(
            resolved_view_id=resolved_view_id,
            section=section,
            label=label,
            kind="artifact",
            icon_key=ak,
        )
        _set_artifact_for_refresh(
            obj_to_store,
            artifact_kind=ak,
            label=label,
            section=section,
            view_id=resolved_view_id,
        )

        if update_status:
            store.mark_success(duration_s=None, view_id=resolved_view_id)

        _ensure_server_running(_DEFAULT_HOST, _DEFAULT_PORT, quiet=True)
        return

    # Table mode
    if forced_kind == "table" or (
        forced_kind is None and obj is not None and _object_is_dataframe(obj)
    ):
        df = _object_to_dataframe(obj)
        if config.get_table_view_mode() == "simple":
            html_simple = df_to_html_simple(df, config.get_max_table_rows_simple())
        else:
            html_simple = None

        _register_refresh_view_if_named(
            resolved_view_id=resolved_view_id,
            section=section,
            label=label,
            kind="table",
            icon_key="table",
        )
        store.set_table(df, html_simple, view_id=resolved_view_id)

        if update_status:
            store.mark_success(duration_s=None, view_id=resolved_view_id)

        _ensure_server_running(_DEFAULT_HOST, _DEFAULT_PORT, quiet=True)
        return

    # Plot mode
    if forced_kind == "plot" or (forced_kind is None and _looks_like_plot_object(obj)):
        fig = _object_to_figure(obj, force_plotnine=force_plotnine)
        png_bytes = fig_to_png_bytes(fig)

        _register_refresh_view_if_named(
            resolved_view_id=resolved_view_id,
            section=section,
            label=label,
            kind="plot",
            icon_key="plot",
        )
        store.set_plot(png_bytes, view_id=resolved_view_id)

        if update_status:
            store.mark_success(duration_s=None, view_id=resolved_view_id)

        _ensure_server_running(_DEFAULT_HOST, _DEFAULT_PORT, quiet=True)
        return

    # Generic artifact mode
    if forced_kind in (None, "artifact"):
        ak = artifact_kind or _infer_artifact_kind_for_refresh(obj)

        _register_refresh_view_if_named(
            resolved_view_id=resolved_view_id,
            section=section,
            label=label,
            kind="artifact",
            icon_key=ak,
        )
        _set_artifact_for_refresh(
            obj,
            artifact_kind=ak,
            label=label,
            section=section,
            view_id=resolved_view_id,
        )

        if update_status:
            store.mark_success(duration_s=None, view_id=resolved_view_id)

        _ensure_server_running(_DEFAULT_HOST, _DEFAULT_PORT, quiet=True)
        return

    raise ValueError(
        "refresh_view kind must be one of: None, 'plot', 'table', or 'artifact'"
    )


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
    host: str = "127.0.0.1",
    port: int = 8000,
    auto_on_show: bool = True,
    quiet: bool = True,
    config: str | Path | None = None,
    name: str | None = None,
    truncate: int | str | None = None,
    no_truncate: bool = False,
    watches: Sequence[Any] | None = None,
) -> None:
    """
    Start the viewer server in a background thread.

    - host: e.g. "0.0.0.0" (all interfaces) or "127.0.0.1".
    - port: TCP port.
    - auto_on_show: patch plt.show to also refresh the view.
    - quiet: reduce uvicorn noise if True.
    - config: path to plotsrv.yml / plotsrv.yaml, equivalent to CLI --config.
    - name: runtime instance name, equivalent to CLI --name.
    - truncate: runtime truncation override, equivalent to CLI --truncate.
    - no_truncate: disable text/html/markdown truncation.
    - watches: optional WatchConfig/dict values for files to publish live.
    """
    from .runtime import apply_runtime_options, start_watch_threads

    apply_runtime_options(
        config=config,
        name=name,
        truncate=truncate,
        no_truncate=no_truncate,
    )

    global _DEFAULT_HOST, _DEFAULT_PORT
    _DEFAULT_HOST = host
    _DEFAULT_PORT = port

    _ensure_server_running(host, port, quiet=quiet)

    if auto_on_show:
        _patch_matplotlib_show()

    if watches:
        _wait_for_server_ready(host, port, timeout_s=5.0)
        start_watch_threads(watches, host=host, port=port)


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

    stop_storage_worker(join=False)
    _unpatch_matplotlib_show()


@contextmanager
def plot_session(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    auto_on_show: bool = True,
    quiet: bool = True,
    config: str | Path | None = None,
    name: str | None = None,
    truncate: int | str | None = None,
    no_truncate: bool = False,
    watches: Sequence[Any] | None = None,
):
    """
    Context manager: start server on entry, stop on exit.
    """
    start_server(
        host=host,
        port=port,
        auto_on_show=auto_on_show,
        quiet=quiet,
        config=config,
        name=name,
        truncate=truncate,
        no_truncate=no_truncate,
        watches=watches,
    )
    try:
        yield
    finally:
        stop_server(join=False)


# ---- /shutdown route


@app.post("/shutdown")
def shutdown(background_tasks: BackgroundTasks, request) -> dict[str, str]:
    """
    Shutdown endpoint triggered from the browser.

    Disabled by default.
    """
    if not config.get_shutdown_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    if config.get_control_local_only():
        require_local_request(request)

    def _do_shutdown() -> None:
        stopped_service = store.request_service_stop()
        if not stopped_service:
            stop_server()

    background_tasks.add_task(_do_shutdown)
    return {"status": "shutting_down"}
