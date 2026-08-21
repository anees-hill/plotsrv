from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

try:  # optional
    import polars as pl  # type: ignore
except Exception:  # noqa: BLE001  # pragma: no cover - optional dependency import
    pl = None  # type: ignore[assignment]

try:  # pragma: no cover
    from plotnine.ggplot import ggplot as PlotnineGGPlot  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001  # pragma: no cover - optional dependency import
    PlotnineGGPlot = None  # type: ignore[assignment]


def _is_pathlike_file(obj: Any) -> bool:
    if isinstance(obj, (str, bytes, bytearray)):
        return False

    try:
        path = Path(obj)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False

    is_pathlike = isinstance(obj, Path) or getattr(obj, "__fspath__", None) is not None
    if not is_pathlike:
        return False

    try:
        return path.expanduser().resolve().is_file()
    except (OSError, RuntimeError):
        return False


def _object_is_dataframe(obj: Any) -> bool:
    if isinstance(obj, pd.DataFrame):
        return True
    return pl is not None and isinstance(obj, pl.DataFrame)  # type: ignore[arg-type]


def _object_to_dataframe(obj: Any) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return obj
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        return obj.to_pandas()
    raise TypeError("Expected pandas or polars DataFrame")


def _object_to_figure(obj: Any | None, force_plotnine: bool) -> Figure:
    """
    Normalise an object into a matplotlib Figure.
    """
    if obj is None:
        return plt.gcf()

    if isinstance(obj, Figure):
        return obj

    if force_plotnine:
        if not hasattr(obj, "draw"):
            raise TypeError(
                "force_plotnine=True but object has no .draw() method; "
                f"got {type(obj)!r}"
            )
        return obj.draw()  # type: ignore[no-any-return]

    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return obj.draw()  # type: ignore[no-any-return]

    if hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        return obj.draw()  # type: ignore[no-any-return]

    raise TypeError(
        "refresh_view expected one of: "
        "None, matplotlib.figure.Figure, plotnine.ggplot; "
        f"got {type(obj)!r}"
    )


def _looks_like_plot_object(obj: Any | None) -> bool:
    if obj is None:
        return True

    if isinstance(obj, Figure):
        return True

    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return True

    return hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine")
