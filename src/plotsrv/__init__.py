# src/plotsrv/__init__.py
from __future__ import annotations

from .server import (
    start_server,
    stop_server,
    refresh_view,
    plot_session,
)
from .config import set_table_view_mode
from .decorators import (
    view,
    get_plotsrv_spec,
    PlotsrvSpec,
)
from .publisher import publish_view
from .capture import capture_exceptions
from .tracebacks import publish_traceback, TracebackPublishOptions
from .runtime import WatchConfig

__all__ = [
    # Core public API
    "view",
    "publish_view",
    # Server/session API
    "start_server",
    "stop_server",
    "plot_session",
    # Backwards-compatible in-process helper
    "refresh_view",
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
]
