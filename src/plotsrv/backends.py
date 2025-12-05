# src/plotsrv/backends.py
from __future__ import annotations

import io
from typing import Any

import pandas as pd
from matplotlib.figure import Figure


def fig_to_png_bytes(fig: Figure) -> bytes:
    """Render a matplotlib Figure to PNG bytes."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    buf.seek(0)
    return buf.read()


def df_to_html_simple(df: pd.DataFrame, max_rows: int) -> str:
    """
    Render a simple HTML table for the first N rows of a DataFrame.
    """
    trimmed = df.head(max_rows)
    return trimmed.to_html(
        classes="tbl-simple",
        border=0,
        index=False,
        escape=True,
    )


def df_to_rich_sample(
    df: pd.DataFrame,
    max_rows: int,
) -> dict[str, Any]:
    """
    Build a JSON-serialisable sample for rich mode (Tabulator).

    Returns:
      {
        "columns": [...],
        "rows": [...],
        "total_rows": int,
        "returned_rows": int,
      }
    """
    trimmed = df.head(max_rows)
    return {
        "columns": list(trimmed.columns),
        "rows": trimmed.to_dict(orient="records"),
        "total_rows": int(len(df)),
        "returned_rows": int(len(trimmed)),
    }
