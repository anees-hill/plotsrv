from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeVar, overload

PlotsrvKind = Literal["plot", "table"]

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class PlotsrvSpec:
    kind: PlotsrvKind
    label: str | None = None


_PLOTSRV_ATTR = "__plotsrv__"


def get_plotsrv_spec(func: Callable[..., Any]) -> PlotsrvSpec | None:
    """
    Return the plotsrv metadata attached to a function, if present.
    """
    return getattr(func, _PLOTSRV_ATTR, None)


def _attach_spec(func: F, spec: PlotsrvSpec) -> F:
    setattr(func, _PLOTSRV_ATTR, spec)
    return func


@overload
def plot(*, label: str | None = None) -> Callable[[F], F]: ...
def plot(*, label: str | None = None) -> Callable[[F], F]:
    """
    Decorator: marks a function as a plotsrv plot producer.
    """

    def decorator(func: F) -> F:
        return _attach_spec(func, PlotsrvSpec(kind="plot", label=label))

    return decorator


@overload
def table(*, label: str | None = None) -> Callable[[F], F]: ...
def table(*, label: str | None = None) -> Callable[[F], F]:
    """
    Decorator: marks a function as a plotsrv table producer.
    """

    def decorator(func: F) -> F:
        return _attach_spec(func, PlotsrvSpec(kind="table", label=label))

    return decorator
