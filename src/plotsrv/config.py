# src/plotsrv/config.py
from __future__ import annotations

from typing import Literal

TableViewMode = Literal["simple", "rich"]

TABLE_VIEW_MODE: TableViewMode = "simple"
MAX_TABLE_ROWS_SIMPLE: int = 200
MAX_TABLE_ROWS_RICH: int = 1000


def get_table_view_mode() -> TableViewMode:
    return TABLE_VIEW_MODE


def set_table_view_mode(mode: TableViewMode) -> None:
    """
    Set how DataFrames are shown in the browser.

    - "simple": static HTML (df.head(N).to_html()).
    - "rich": Tabulator JS grid over a sample of the DataFrame.
    """
    global TABLE_VIEW_MODE
    if mode not in ("simple", "rich"):
        raise ValueError("table_view_mode must be 'simple' or 'rich'")
    TABLE_VIEW_MODE = mode
