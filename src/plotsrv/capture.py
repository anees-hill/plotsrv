# src/plotsrv/capture.py
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .tracebacks import publish_traceback, TracebackPublishOptions


@contextmanager
def capture_exceptions(
    *,
    label: str | None = None,
    section: str | None = None,
    view_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    reraise: bool = True,
    update_limit_s: int | None = None,
    force: bool = False,
    options: TracebackPublishOptions | None = None,
) -> Iterator[None]:
    """
    Context manager that publishes a traceback artifact if an exception occurs.

    Use this for "watch/service" style code where you don't want to pepper try/except.
    """
    try:
        yield
    except Exception as e:
        publish_traceback(
            e,
            label=label,
            section=section,
            view_id=view_id,
            host=host,
            port=port,
            update_limit_s=update_limit_s,
            force=force,
            options=options,
        )
        if reraise:
            raise
