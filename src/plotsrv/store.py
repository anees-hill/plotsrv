# src/plotsrv/store.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

ViewKind = Literal["none", "plot", "table"]


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


# ---- General ---------------------------------------------------------------------


def get_kind() -> ViewKind:
    return _state.kind


def reset() -> None:
    _state.kind = "none"
    _state.plot_png = None
    _state.table_df = None
    _state.table_html_simple = None
