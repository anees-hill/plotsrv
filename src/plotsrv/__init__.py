# src/plotsrv/__init__.py
from __future__ import annotations

from .server import (
    start_server,
    stop_server,
    refresh_view,
    plot_session,
    start_plot_server,
    stop_plot_server,
    refresh_plot_server,
)
from .config import set_table_view_mode
from .decorators import (
    view,
    plotsrv,
    plot,
    table,
    get_plotsrv_spec,
    PlotsrvSpec,
)
from .publisher import plot_launch, publish_view, publish_artifact
from .capture import capture_exceptions
from .tracebacks import publish_traceback, TracebackPublishOptions
from .runtime import WatchConfig

__all__ = [
    # Preferred server/session API
    "start_server",
    "stop_server",
    "refresh_view",
    "plot_session",
    # Preferred public API
    "view",
    "publish_view",
    # Exception helpers
    "capture_exceptions",
    "publish_traceback",
    "TracebackPublishOptions",
    # Advanced metadata
    "get_plotsrv_spec",
    "PlotsrvSpec",
    "WatchConfig",
    # Runtime config
    "set_table_view_mode",
    # Compatibility aliases;
    "plotsrv",
    "plot",
    "table",
    "publish_artifact",
    "plot_launch",
    "start_plot_server",
    "stop_plot_server",
    "refresh_plot_server",
]
