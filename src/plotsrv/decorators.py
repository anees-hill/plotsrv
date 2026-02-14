# src/plotsrv/decorators.py
from __future__ import annotations
import os

from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Literal, TypeVar, overload

from .publisher import publish_view, publish_artifact


PlotsrvKind = Literal["plot", "table", "artifact"]


F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class PlotsrvSpec:
    kind: PlotsrvKind
    label: str | None = None
    section: str | None = None
    host: str | None = None
    port: int | None = None
    update_limit_s: int | None = None


_PLOTSRV_ATTR = "__plotsrv__"


def get_plotsrv_spec(func: Callable[..., Any]) -> PlotsrvSpec | None:
    return getattr(func, _PLOTSRV_ATTR, None)


def _attach_spec(func: F, spec: PlotsrvSpec) -> F:
    setattr(func, _PLOTSRV_ATTR, spec)
    return func


def _wrap_with_publish(func: F, spec: PlotsrvSpec) -> F:
    """
    Wrap function so calling it publishes result to plotsrv,
    but only if port is configured.
    """
    if spec.port is None:
        return func

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        out = func(*args, **kwargs)
        try:
            if spec.kind == "artifact":
                publish_artifact(
                    out,
                    label=spec.label or func.__name__,
                    section=spec.section,
                    host=spec.host or "127.0.0.1",
                    port=int(spec.port),
                    update_limit_s=spec.update_limit_s,
                    force=False,
                )
            else:
                publish_view(
                    out,
                    kind=spec.kind,
                    label=spec.label or func.__name__,
                    section=spec.section,
                    host=spec.host or "127.0.0.1",
                    port=int(spec.port),
                    update_limit_s=spec.update_limit_s,
                    force=False,
                )

        except Exception:
            if os.environ.get("PLOTSRV_DEBUG", "").strip() == "1":
                raise
            # if debug:
            #     raise
        return out

    return wrapper  # type: ignore[return-value]


@overload
def plot(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[F], F]: ...
def plot(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[F], F]:
    """
    Decorator: marks a function as a plotsrv plot producer.

    If port is provided, calling the function will publish its output.
    """

    def decorator(func: F) -> F:
        spec = PlotsrvSpec(
            kind="plot",
            label=label,
            section=section,
            host=host,
            port=port,
            update_limit_s=update_limit_s,
        )
        f2 = _attach_spec(func, spec)
        return _wrap_with_publish(f2, spec)

    return decorator


@overload
def table(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[F], F]: ...
def table(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[F], F]:
    """
    Decorator: marks a function as a plotsrv table producer.

    If port is provided, calling the function will publish its output.
    """

    def decorator(func: F) -> F:
        spec = PlotsrvSpec(
            kind="table",
            label=label,
            section=section,
            host=host,
            port=port,
            update_limit_s=update_limit_s,
        )
        f2 = _attach_spec(func, spec)
        return _wrap_with_publish(f2, spec)

    return decorator


@overload
def plotsrv(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[F], F]: ...
def plotsrv(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[F], F]:
    """
    Decorator: marks a function as a plotsrv *artifact* producer.

    Publishes arbitrary Python objects (text/json/python) via /publish kind="artifact".
    """

    def decorator(func: F) -> F:
        spec = PlotsrvSpec(
            kind="artifact",
            label=label,
            section=section,
            host=host,
            port=port,
            update_limit_s=update_limit_s,
        )
        f2 = _attach_spec(func, spec)
        return _wrap_with_publish(f2, spec)

    return decorator
