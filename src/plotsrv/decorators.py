# src/plotsrv/decorators.py
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Literal, TypeVar, overload

from .publisher import publish_view
from .tracebacks import publish_traceback

PlotsrvKind = Literal["artifact"]
OnErrorMode = Literal["raise", "publish", "publish_and_raise"]

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class PlotsrvSpec:
    kind: PlotsrvKind
    label: str | None = None
    section: str | None = None
    host: str | None = None
    port: int | None = None
    update_limit_s: int | None = None
    on_error: OnErrorMode = "raise"
    launch_server: bool = False


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
        for i, (k, v) in enumerate(d.items()):
            if i >= 200:
                attrs["…"] = f"(+{len(d) - 200} more attrs)"
                break

            try:
                attrs[str(k)] = _escape_repr(repr(v))
            except Exception:
                attrs[str(k)] = "<unrepr-able>"
    except Exception:
        pass

    out["attrs"] = attrs
    return out


def _should_publish(spec: PlotsrvSpec) -> bool:
    """
    Decide whether @view should actively publish when the wrapped callable/class
    is used.

    Passive metadata-only usage:

        @ps.view(label="x")
        def f(): ...

    Active publishing usage:

        @ps.view(port=8000)
        def f(): ...

        @ps.view(host="127.0.0.1", port=8000)
        def f(): ...

        @ps.view(launch_server=True)
        def f(): ...
    """
    return bool(spec.launch_server or spec.host is not None or spec.port is not None)


def _publish_host(spec: PlotsrvSpec) -> str | None:
    return spec.host


def _publish_port(spec: PlotsrvSpec) -> int | None:
    return int(spec.port) if spec.port is not None else None


def _traceback_host(spec: PlotsrvSpec) -> str:
    return spec.host or "127.0.0.1"


def _traceback_port(spec: PlotsrvSpec) -> int:
    return int(spec.port) if spec.port is not None else 8000


def _wrap_class_with_publish(cls: type[Any], spec: PlotsrvSpec) -> type[Any]:
    if getattr(cls, _PLOTSRV_CLASS_WRAPPED, False):
        return cls

    orig_init = getattr(cls, "__init__", None)
    if orig_init is None:
        return cls

    @wraps(orig_init)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)

        try:
            publish_view(
                _inspect_instance(self),
                label=spec.label or cls.__name__,
                section=spec.section,
                host=_publish_host(spec),
                port=_publish_port(spec),
                launch_server=spec.launch_server,
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
    Wrap function so calling it publishes result to plotsrv, OR wrap class so
    instantiation publishes an inspection artifact.

    If the decorator is metadata-only, the object is returned unchanged.
    """
    if not _should_publish(spec):
        return func

    # Class support for @view(...)
    if isinstance(func, type):
        if spec.kind != "artifact":
            return func
        return _wrap_class_with_publish(func, spec)

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            out = func(*args, **kwargs)
        except Exception as e:
            if spec.on_error in ("publish", "publish_and_raise"):
                try:
                    publish_traceback(
                        e,
                        label=spec.label or func.__name__,
                        section=spec.section,
                        host=_traceback_host(spec),
                        port=_traceback_port(spec),
                    )
                except Exception:
                    if os.environ.get("PLOTSRV_DEBUG", "").strip() == "1":
                        raise

            if spec.on_error in ("raise", "publish_and_raise"):
                raise

            return None

        # success path: publish result
        try:
            publish_view(
                out,
                label=spec.label or func.__name__,
                section=spec.section,
                host=_publish_host(spec),
                port=_publish_port(spec),
                launch_server=spec.launch_server,
                update_limit_s=spec.update_limit_s,
                force=False,
            )
        except Exception:
            if os.environ.get("PLOTSRV_DEBUG", "").strip() == "1":
                raise

        return out

    return wrapper


@overload
def view(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
    on_error: OnErrorMode = "raise",
    launch_server: bool = False,
) -> Callable[[F], F]: ...


@overload
def view(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
    on_error: OnErrorMode = "raise",
    launch_server: bool = False,
) -> Callable[[type[Any]], type[Any]]: ...


def view(
    *,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
    on_error: OnErrorMode = "raise",
    launch_server: bool = False,
) -> Callable[[Any], Any]:
    """
    Decorator: marks a function OR class as a plotsrv view producer.

    Metadata-only usage:

        @ps.view(label="daily import", section="pipelines")
        def daily_import_status():
            ...

    This lets plotsrv discover the view for UI pre-population.

    Active publishing usage:

        @ps.view(label="daily import", section="pipelines", port=8000)
        def daily_import_status():
            ...

    This publishes to an existing plotsrv server when the function is called.

        @ps.view(label="daily import", section="pipelines", launch_server=True)
        def daily_import_status():
            ...

    This starts/uses an in-process plotsrv server and publishes locally when the
    function is called.
    """

    def decorator(obj: Any) -> Any:
        spec = PlotsrvSpec(
            kind="artifact",
            label=label,
            section=section,
            host=host,
            port=port,
            update_limit_s=update_limit_s,
            on_error=on_error,
            launch_server=launch_server,
        )

        o2 = _attach_spec(obj, spec)
        return _wrap_with_publish(o2, spec)

    return decorator
