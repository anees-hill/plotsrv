# src/plotsrv/publisher.py
from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Any

import pandas as pd

from . import config
from .backends import df_to_html_simple, df_to_rich_sample, fig_to_png_bytes

# Optional: polars support
try:  # pragma: no cover
    import polars as pl  # type: ignore
except Exception:  # pragma: no cover
    pl = None  # type: ignore[assignment]

# Optional: matplotlib
try:  # pragma: no cover
    import matplotlib

    matplotlib.use("Agg")  # safe headless default
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover
    plt = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]

# Optional: plotnine
try:  # pragma: no cover
    from plotnine.ggplot import ggplot as PlotnineGGPlot  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    PlotnineGGPlot = None  # type: ignore[assignment]


def _is_dataframe(obj: Any) -> bool:
    if isinstance(obj, pd.DataFrame):
        return True
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        return True
    return False


def _to_dataframe(obj: Any) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return obj
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        return obj.to_pandas()
    raise TypeError(f"Expected pandas/polars DataFrame, got {type(obj)!r}")


def _to_figure(obj: Any | None) -> Any:
    """
    Normalize to a matplotlib Figure.

    Supports:
      - None -> plt.gcf()
      - matplotlib Figure
      - plotnine ggplot -> .draw()
    """
    if plt is None:
        raise RuntimeError("matplotlib is not available; cannot publish plot")

    # None => current figure
    if obj is None:
        return plt.gcf()

    # Matplotlib Figure
    if Figure is not None and isinstance(obj, Figure):  # type: ignore[arg-type]
        return obj

    # Plotnine ggplot
    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return obj.draw()

    # Generic plotnine-like object (duck typing)
    if hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        return obj.draw()

    raise TypeError(
        "Cannot publish plot: expected matplotlib.figure.Figure, plotnine.ggplot, or None; "
        f"got {type(obj)!r}"
    )


def _to_publish_payload(
    obj: Any,
    *,
    kind: str,
    label: str,
    section: str | None,
    update_limit_s: int | None,
    force: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "label": label,
        "section": section,
        "update_limit_s": update_limit_s,
        "force": force,
    }

    if kind == "plot":
        fig = _to_figure(obj)
        png = fig_to_png_bytes(fig)
        payload["plot_png_b64"] = base64.b64encode(png).decode("utf-8")
        return payload

    # table
    df = _to_dataframe(obj)
    sample = df_to_rich_sample(df, max_rows=config.MAX_TABLE_ROWS_RICH)
    payload["table"] = sample
    payload["table_html_simple"] = df_to_html_simple(df, max_rows=config.MAX_TABLE_ROWS_SIMPLE)
    return payload


def publish_view(
    obj: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    label: str,
    section: str | None = None,
    update_limit_s: int | None = None,
    force: bool = False,
) -> None:
    """
    Publish a plot/table to a running plotsrv server on host/port.

    Best effort by default:
      - conversion errors are silent unless PLOTSRV_DEBUG=1
      - network errors are always silent
    """
    debug = os.environ.get("PLOTSRV_DEBUG", "").strip() == "1"

    # decide kind
    kind = "table" if _is_dataframe(obj) else "plot"

    try:
        payload = _to_publish_payload(
            obj,
            kind=kind,
            label=label,
            section=section,
            update_limit_s=update_limit_s,
            force=force,
        )
    except Exception:
        if debug:
            raise
        return

    url = f"http://{host}:{port}/publish"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            _ = resp.read()
    except Exception:
        return


def plot_launch(
    obj: Any,
    *,
    label: str,
    section: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    update_limit_s: int | None = None,
    force: bool = False,
) -> None:
    publish_view(
        obj,
        host=host,
        port=port,
        label=label,
        section=section,
        update_limit_s=update_limit_s,
        force=force,
    )
