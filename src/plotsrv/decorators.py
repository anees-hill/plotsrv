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
_PLOTSRV_CLASS_WRAPPED = "__plotsrv_class_wrapped__"


def get_plotsrv_spec(func: Callable[..., Any]) -> PlotsrvSpec | None:
    return getattr(func, _PLOTSRV_ATTR, None)


def _attach_spec(func: Any, spec: PlotsrvSpec) -> Any:
    setattr(func, _PLOTSRV_ATTR, spec)
    return func


def _escape_repr(s: str, *, max_chars: int = 1000) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "…"


def _inspect_instance(obj: Any) -> dict[str, Any]:
    """
    Cheap, safe-ish instance inspection to feed JsonTreeRenderer.
    Values are repr() strings (so always JSON-safe after publisher _json_safe).
    """
    cls = obj.__class__
    out: dict[str, Any] = {
        "kind": "instance",
        "class": getattr(cls, "__name__", str(cls)),
        "module": getattr(cls, "__module__", None),
        "repr": _escape_repr(repr(obj)),
    }

    attrs: dict[str, Any] = {}
    try:
        d = vars(obj)
        # cap attribute count (avoid mega objects)
        for i, (k, v) in enumerate(d.items()):
            if i >= 200:
                attrs["…"] = f"(+{len(d) - 200} more attrs)"
                break
            try:
                attrs[str(k)] = _escape_repr(repr(v))
            except Exception:
                attrs[str(k)] = "<unrepr-able>"
    except Exception:
        # objects without __dict__ etc.
        pass

    out["attrs"] = attrs
    return out


def _wrap_class_with_publish(cls: type[Any], spec: PlotsrvSpec) -> type[Any]:
    """
    Monkeypatch cls.__init__ so that instantiation publishes an inspection artifact.
    Keeps the same class object (so isinstance checks behave as expected).
    """
    if getattr(cls, _PLOTSRV_CLASS_WRAPPED, False):
        return cls

    orig_init = getattr(cls, "__init__", None)
    if orig_init is None:
        return cls

    @wraps(orig_init)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        # call original init first
        orig_init(self, *args, **kwargs)

        # then publish inspection
        try:
            publish_artifact(
                _inspect_instance(self),
                label=spec.label or cls.__name__,
                section=spec.section,
                host=spec.host or "127.0.0.1",
                port=int(spec.port) if spec.port is not None else 8000,
                artifact_kind="json",
                update_limit_s=spec.update_limit_s,
                force=False,
            )
        except Exception:
            if os.environ.get("PLOTSRV_DEBUG", "").strip() == "1":
                raise
            return

    try:
        setattr(cls, "__init__", __init__)
        setattr(cls, _PLOTSRV_CLASS_WRAPPED, True)
    except Exception:
        return cls

    return cls


def _wrap_with_publish(func: Any, spec: PlotsrvSpec) -> Any:
    """
    Wrap function so calling it publishes result to plotsrv,
    OR wrap class so instantiating publishes an inspection artifact,
    but only if port is configured.
    """
    if spec.port is None:
        return func

    # Class support for @plotsrv(...)
    if isinstance(func, type):
        if spec.kind != "artifact":
            return func
        return _wrap_class_with_publish(func, spec)

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
        return out

    return wrapper


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
        return _wrap_with_publish(f2, spec)  # type: ignore[return-value]

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
        return _wrap_with_publish(f2, spec)  # type: ignore[return-value]

    return decorator


# NOTE: plotsrv can decorate either a function OR a class
@overload
def plotsrv(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[F], F]: ...
@overload
def plotsrv(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[type[Any]], type[Any]]: ...
def plotsrv(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
) -> Callable[[Any], Any]:
    """
    Decorator: marks a function OR class as a plotsrv artifact producer.

    - If applied to a function: publishes whatever it returns (existing behavior).
    - If applied to a class: wraps __init__ so creating an instance publishes an "inspect" artifact.
    """

    def decorator(obj: Any) -> Any:
        spec = PlotsrvSpec(
            kind="artifact",
            label=label,
            section=section,
            host=host,
            port=port,
            update_limit_s=update_limit_s,
        )
        o2 = _attach_spec(obj, spec)
        return _wrap_with_publish(o2, spec)

    return decorator
