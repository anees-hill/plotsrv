# src/plotsrv/tracebacks.py
from __future__ import annotations

import json
import linecache
import traceback
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import store
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
    opts = options or TracebackPublishOptions()
    payload = _build_traceback_payload(exc, options=opts)

    # ---- Remote publish (POST /publish) --------------------------------------
    if host is not None and port is not None:
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

        url = f"http://{host}:{int(port)}/publish"
        data = json.dumps(post).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
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
