from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Literal

from .decorators import PlotsrvSpec, get_plotsrv_spec

RunKind = Literal["table", "artifact"]


@dataclass(frozen=True, slots=True)
class RunResult:
    kind: RunKind
    label: str | None
    value: Any


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
    Infer the generic plotsrv view kind for a callable return value.

    DataFrames are table views. Everything else is a generic artifact view.
    Plot objects are intentionally handled by publish_view()/refresh_view()
    inference later in the pipeline, not by the runner.
    """
    if _is_pandas_df(value) or _is_polars_df(value):
        return "table"
    return "artifact"


def validate_zero_arg_callable(func: Any) -> None:
    """
    For v0.2.0, callable runner supports functions with no required args.

    Optional args with defaults, *args, and **kwargs are allowed.
    """
    sig = inspect.signature(func)

    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is inspect._empty:
            raise TypeError(
                "plotsrv v0.2.0 runner supports only zero-arg functions "
                f"(found required param: {p.name!r})"
            )


def run_once(func: Any) -> RunResult:
    """
    Call a decorated or undecorated function exactly once.

    Returns RunResult(kind, label, value), where:
      - kind comes from @view metadata if present, else inferred.
      - label comes from @view metadata if present, else None.
    """
    if not callable(func):
        raise TypeError(f"run_once expected a callable, got {type(func)!r}")

    validate_zero_arg_callable(func)

    spec: PlotsrvSpec | None = get_plotsrv_spec(func)

    value = func()

    if spec is not None:
        kind: RunKind = "artifact"
        label = spec.label
    else:
        kind = infer_kind_from_value(value)
        label = None

    return RunResult(kind=kind, label=label, value=value)
