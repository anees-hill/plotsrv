from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Literal

from .decorators import PlotsrvSpec, get_plotsrv_spec

RunKind = Literal["plot", "table"]


@dataclass(frozen=True, slots=True)
class RunResult:
    kind: RunKind
    label: str | None
    value: Any  # plot object or dataframe object


def _is_pandas_df(obj: Any) -> bool:
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return False
    return isinstance(obj, pd.DataFrame)


def _is_polars_df(obj: Any) -> bool:
    try:
        import polars as pl  # type: ignore
    except Exception:
        return False
    return isinstance(obj, pl.DataFrame)


def infer_kind_from_value(value: Any) -> RunKind:
    """
    Infer whether the function output is a plot or a table.
    """
    if _is_pandas_df(value) or _is_polars_df(value):
        return "table"
    return "plot"


def validate_zero_arg_callable(func: Any) -> None:
    """
    For v0.2.0 (Part 1), we only support calling functions with no required args.
    """
    sig = inspect.signature(func)

    for p in sig.parameters.values():
        # Allow no params at all OR params that are optional (have defaults),
        # but do not allow required positional/keyword-only params yet.
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is inspect._empty:
            raise TypeError(
                "plotsrv v0.2.0 runner supports only zero-arg functions "
                f"(found required param: {p.name!r})"
            )


def run_once(func: Any) -> RunResult:
    """
    Call a decorated (or undecorated) function exactly once.

    Returns RunResult(kind, label, value) where:
      - kind comes from decorator spec if present, else inferred.
      - label comes from decorator spec if present, else None.
    """
    if not callable(func):
        raise TypeError(f"run_once expected a callable, got {type(func)!r}")

    validate_zero_arg_callable(func)

    spec: PlotsrvSpec | None = get_plotsrv_spec(func)

    value = func()

    if spec is not None:
        kind: RunKind = spec.kind
        label = spec.label
    else:
        kind = infer_kind_from_value(value)
        label = None

    return RunResult(kind=kind, label=label, value=value)
