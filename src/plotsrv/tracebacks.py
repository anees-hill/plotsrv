# src/plotsrv/tracebacks.py
from __future__ import annotations

import linecache
import traceback
from dataclasses import dataclass
from typing import Any

from . import config, store
from .artifacts import Truncation


@dataclass(slots=True)
class TracebackPublishOptions:
    context_lines: int = 2
    max_frames: int = 50


def publish_traceback(
    exc: BaseException,
    *,
    view_id: str | None = None,
    label: str | None = None,
    section: str | None = None,
    host: str | None = None,
    port: int | None = None,
    update_limit_s: int | None = None,
    force: bool = False,
    options: TracebackPublishOptions | None = None,
) -> None:
    from .connection_config import resolve_publish_target
    try:
        target = resolve_publish_target(host=host, port=port)
    except Exception:
        return
    if not config.get_tracebacks_enabled():
        safe_message = f"{type(exc).__name__}: traceback publishing disabled"

        if target.kind == "local":
            store.mark_error(safe_message, view_id=view_id)

        return
    opts = options or TracebackPublishOptions()
    payload = _build_traceback_payload(exc, options=opts)

    # ---- Remote publish (POST /publish) --------------------------------------
    if target.kind == "remote":
        post: dict[str, Any] = {
            "kind": "artifact",
            "artifact_kind": "traceback",
            "artifact": payload,
            "label": label,
            "section": section,
            "view_id": view_id,
            "update_limit_s": update_limit_s,
            "force": bool(force),
        }

        from .publishing.transport import request_json
        try:
            request_json(target, "/publish", post, feature="publish")
        except Exception:
            pass
        return

    # ---- In-process fallback --------------------------------------------------
    store.set_artifact(
        obj=payload,
        kind="traceback",
        label=label,
        section=section,
        view_id=view_id,
        truncation=Truncation(truncated=False),
    )
    store.mark_error(f"{type(exc).__name__}: {exc}", view_id=view_id)


def _build_traceback_payload(
    exc: BaseException, *, options: TracebackPublishOptions
) -> dict[str, Any]:
    tbexc = traceback.TracebackException.from_exception(exc, capture_locals=False)

    frames: list[dict[str, Any]] = []
    count = 0
    for fr in tbexc.stack:
        count += 1
        if count > options.max_frames:
            break

        filename = fr.filename
        lineno = fr.lineno
        func = fr.name

        line = linecache.getline(filename, lineno).rstrip("\n") if lineno else ""
        before: list[str] = []
        after: list[str] = []

        if lineno and options.context_lines > 0:
            for i in range(lineno - options.context_lines, lineno):
                if i > 0:
                    before.append(linecache.getline(filename, i).rstrip("\n"))
            for i in range(lineno + 1, lineno + 1 + options.context_lines):
                after.append(linecache.getline(filename, i).rstrip("\n"))

        frames.append(
            {
                "filename": filename,
                "lineno": lineno,
                "function": func,
                "line": line,
                "context_before": before,
                "context_after": after,
            }
        )

    return {
        "type": "traceback",
        "exc_type": type(exc).__name__,
        "exc_msg": str(exc),
        "frames": frames,
    }
