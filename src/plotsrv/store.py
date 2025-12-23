# src/plotsrv/store.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import datetime as dt
import threading


import pandas as pd

ViewKind = Literal["none", "plot", "table"]
_STATUS_LOCK = threading.Lock()
_LAST_UPDATED_AT: dt.datetime | None = None
_LAST_DURATION_S: float | None = None
_LAST_ERROR: str | None = None


@dataclass
class ViewState:
    kind: ViewKind = "none"
    plot_png: bytes | None = None
    table_df: pd.DataFrame | None = None
    table_html_simple: str | None = None


_state = ViewState()


# ---- Plot helpers ----------------------------------------------------------------


def set_plot(png: bytes) -> None:
    """Store PNG bytes as the current plot and clear any table."""
    _state.kind = "plot"
    _state.plot_png = png
    _state.table_df = None
    _state.table_html_simple = None


def get_plot() -> bytes:
    """Return the current plot PNG bytes or raise if none set."""
    if _state.plot_png is None:
        raise LookupError("No plot has been published yet.")
    return _state.plot_png


def has_plot() -> bool:
    return _state.plot_png is not None


# ---- Table helpers ---------------------------------------------------------------


def set_table(df: pd.DataFrame, html_simple: str | None) -> None:
    """
    Store a DataFrame as the current table.

    html_simple:
        Pre-rendered HTML for simple mode (or None for rich mode).
    """
    _state.kind = "table"
    _state.table_df = df
    _state.table_html_simple = html_simple
    _state.plot_png = None


def has_table() -> bool:
    return _state.table_df is not None


def get_table_df() -> pd.DataFrame:
    if _state.table_df is None:
        raise LookupError("No table has been published yet.")
    return _state.table_df


def get_table_html_simple() -> str:
    if _state.table_html_simple is None:
        raise LookupError("No simple table HTML available.")
    return _state.table_html_simple


# ---- CLI-error trackers ----------------------------------------------------------


def mark_success(duration_s: float | None = None) -> None:
    global _LAST_UPDATED_AT, _LAST_DURATION_S, _LAST_ERROR
    with _STATUS_LOCK:
        _LAST_UPDATED_AT = dt.datetime.now(dt.UTC)
        _LAST_DURATION_S = duration_s
        _LAST_ERROR = None


def mark_error(error: str) -> None:
    global _LAST_ERROR
    with _STATUS_LOCK:
        _LAST_ERROR = error


def get_status() -> dict[str, object]:
    with _STATUS_LOCK:
        return {
            "last_updated": _LAST_UPDATED_AT.isoformat() if _LAST_UPDATED_AT else None,
            "last_duration_s": _LAST_DURATION_S,
            "last_error": _LAST_ERROR,
        }


# ---- General ---------------------------------------------------------------------


def get_kind() -> ViewKind:
    return _state.kind


def reset() -> None:
    _state.kind = "none"
    _state.plot_png = None
    _state.table_df = None
    _state.table_html_simple = None
