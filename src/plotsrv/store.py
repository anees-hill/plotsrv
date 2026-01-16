# src/plotsrv/store.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

# ---- View state (plot/table/none) ---------------------------------------------

_KIND: str = "none"  # "none" | "plot" | "table"

_LATEST_PLOT: bytes | None = None

_LATEST_TABLE_DF: pd.DataFrame | None = None
_LATEST_TABLE_HTML_SIMPLE: str | None = None

# ---- Status info for UI -------------------------------------------------------

_STATUS: dict[str, Any] = {
    "last_updated": None,  # ISO string
    "last_duration_s": None,  # float | None
    "last_error": None,  # str | None
}

# ---- Service mode / CLI RunnerService info -----------------------------------

_SERVICE_INFO: dict[str, Any] = {
    "service_mode": False,
    "service_target": None,
    "service_refresh_rate_s": None,
}

_SERVICE_STOP_HOOK: Callable[[], None] | None = None


# ------------------------------------------------------------------------------
# Plot + table setters/getters
# ------------------------------------------------------------------------------


def set_plot(png_bytes: bytes) -> None:
    global _KIND, _LATEST_PLOT
    _KIND = "plot"
    _LATEST_PLOT = png_bytes


def get_plot() -> bytes:
    if _LATEST_PLOT is None:
        raise LookupError("No plot available")
    return _LATEST_PLOT


def has_plot() -> bool:
    return _LATEST_PLOT is not None


def set_table(df: pd.DataFrame, html_simple: str | None) -> None:
    global _KIND, _LATEST_TABLE_DF, _LATEST_TABLE_HTML_SIMPLE
    _KIND = "table"
    _LATEST_TABLE_DF = df
    _LATEST_TABLE_HTML_SIMPLE = html_simple


def has_table() -> bool:
    return _LATEST_TABLE_DF is not None


def get_table_df() -> pd.DataFrame:
    if _LATEST_TABLE_DF is None:
        raise LookupError("No table available")
    return _LATEST_TABLE_DF


def get_table_html_simple() -> str:
    if _LATEST_TABLE_HTML_SIMPLE is None:
        raise LookupError("No simple HTML table available")
    return _LATEST_TABLE_HTML_SIMPLE


def get_kind() -> str:
    return _KIND


# ------------------------------------------------------------------------------
# Status bookkeeping (last updated/duration/error)
# ------------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_success(duration_s: float | None) -> None:
    _STATUS["last_updated"] = _now_iso()
    _STATUS["last_duration_s"] = duration_s
    _STATUS["last_error"] = None


def mark_error(message: str) -> None:
    _STATUS["last_updated"] = _now_iso()
    _STATUS["last_error"] = message


def get_status() -> dict[str, Any]:
    return dict(_STATUS)


# ------------------------------------------------------------------------------
# Service info + shutdown control
# ------------------------------------------------------------------------------


def set_service_info(
    *,
    service_mode: bool,
    target: str | None,
    refresh_rate_s: int | None,
) -> None:
    _SERVICE_INFO["service_mode"] = bool(service_mode)
    _SERVICE_INFO["service_target"] = target
    _SERVICE_INFO["service_refresh_rate_s"] = refresh_rate_s


def get_service_info() -> dict[str, Any]:
    return dict(_SERVICE_INFO)


def set_service_stop_hook(hook: Callable[[], None]) -> None:
    """
    Register a callback to stop the CLI service loop.

    RunnerService should call this with `self.stop`.
    """
    global _SERVICE_STOP_HOOK
    _SERVICE_STOP_HOOK = hook


def clear_service_stop_request() -> None:
    """
    Optional helper: just clears any old hook.
    """
    global _SERVICE_STOP_HOOK
    _SERVICE_STOP_HOOK = _SERVICE_STOP_HOOK  # no-op (kept for compatibility)


def request_service_stop() -> bool:
    """
    Called by /shutdown.

    Returns True if a service stop was requested (hook existed).
    """
    global _SERVICE_STOP_HOOK

    if _SERVICE_STOP_HOOK is None:
        return False

    # Call hook once, then clear it
    hook = _SERVICE_STOP_HOOK
    _SERVICE_STOP_HOOK = None
    try:
        hook()
    except Exception:
        # Don't crash shutdown endpoint; status will show error elsewhere
        pass
    return True
