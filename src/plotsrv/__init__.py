from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .capture import capture_exceptions
    from .config import set_table_view_mode
    from .decorators import PlotsrvSpec, get_plotsrv_spec, view
    from .publisher import flush_views, publish_view
    from .runtime import WatchConfig
    from .server import plot_session, refresh_view, start_server, stop_server
    from .streams import StreamHandle, stream_view
    from .tracebacks import TracebackPublishOptions, publish_traceback

__all__ = [  # noqa: RUF022 - grouped by public API area
    # Core public API
    "view",
    "publish_view",
    "flush_views",
    "stream_view",
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
    "StreamHandle",
    # Runtime config
    "set_table_view_mode",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "start_server": (".server", "start_server"),
    "stop_server": (".server", "stop_server"),
    "refresh_view": (".server", "refresh_view"),
    "plot_session": (".server", "plot_session"),
    "set_table_view_mode": (".config", "set_table_view_mode"),
    "view": (".decorators", "view"),
    "get_plotsrv_spec": (".decorators", "get_plotsrv_spec"),
    "PlotsrvSpec": (".decorators", "PlotsrvSpec"),
    "flush_views": (".publisher", "flush_views"),
    "publish_view": (".publisher", "publish_view"),
    "stream_view": (".streams", "stream_view"),
    "capture_exceptions": (".capture", "capture_exceptions"),
    "publish_traceback": (".tracebacks", "publish_traceback"),
    "TracebackPublishOptions": (".tracebacks", "TracebackPublishOptions"),
    "WatchConfig": (".runtime", "WatchConfig"),
    "StreamHandle": (".streams", "StreamHandle"),
}


def __getattr__(name: str) -> Any:
    """Load public API objects only when callers first use them."""
    if name == "__version__":
        from importlib.metadata import version

        value = version("plotsrv")
        globals()[name] = value
        return value

    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__, "__version__"})
