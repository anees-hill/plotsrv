# src/plotsrv/backends.py
from __future__ import annotations

import io
from typing import Any

import pandas as pd
from matplotlib.figure import Figure

from . import config


def fig_to_png_bytes(fig: Figure) -> bytes:
    """Render a matplotlib Figure to PNG bytes."""
    buf = io.BytesIO()

    dpi = config.get_plot_dpi()
    default_size = config.get_plot_default_figsize_in()
    bbox_tight = config.get_plot_bbox_tight()
    pad_inches = config.get_plot_pad_inches()

    # Matplotlib default figure size is typically (6.4, 4.8).
    # If the user hasn't chosen a size (still default), we can "upgrade"
    # to a wider default for better on-screen readability.
    orig_size = tuple(float(x) for x in fig.get_size_inches())
    mutated = False
    if default_size is not None:
        # "Close enough" check to avoid changing intentional sizes.
        if abs(orig_size[0] - 6.4) < 0.05 and abs(orig_size[1] - 4.8) < 0.05:
            fig.set_size_inches(default_size[0], default_size[1], forward=True)
            mutated = True

    try:
        save_kwargs: dict[str, Any] = {"format": "png", "dpi": dpi}
        if bbox_tight:
            save_kwargs["bbox_inches"] = "tight"
            save_kwargs["pad_inches"] = pad_inches

        fig.savefig(buf, **save_kwargs)
        buf.seek(0)
        return buf.read()
    finally:
        if mutated:
            fig.set_size_inches(orig_size[0], orig_size[1], forward=True)


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
