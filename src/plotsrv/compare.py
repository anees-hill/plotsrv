"""On-demand, bounded Latest representation. No pin cache or publication hooks."""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
import json
import math
import threading
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from fastapi import HTTPException
from starlette.responses import Response

from . import store

MAX_BYTES = 4 * 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024
MAX_STRING = 128 * 1024
MAX_NODES = 20_000
MAX_JSON_RENDER_NODES = 256  # Rich JSON expands each input node into substantial HTML.
MAX_ROWS = 1000
MAX_COLUMNS = 64
MAX_SECONDS = 0.25  # Cooperative; does not cancel a running renderer.
_READERS = threading.BoundedSemaphore(2)
_NUMPY_SCALARS = (
    np.int8,
    np.int16,
    np.int32,
    np.int64,
    np.uint8,
    np.uint16,
    np.uint32,
    np.uint64,
    np.float16,
    np.float32,
    np.float64,
    np.bool_,
)


def unavailable(detail="Latest changed during capture. Choose Latest again.", code=409):
    raise HTTPException(code, detail)


class Budget:
    def __init__(self):
        self.nodes = 0
        self.bytes = 0
        self.deadline = time.monotonic() + MAX_SECONDS

    def copy(self, value, depth=0):
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > 16 or time.monotonic() > self.deadline:
            unavailable("Latest exceeds the bounded inspection budget.", 413)
        cls = type(value)
        if cls is str:
            if len(value) > MAX_STRING:
                unavailable(
                    "Latest contains text too large for bounded inspection.", 413
                )
            self.bytes += 4 * len(value)
        elif cls is dict or cls is list or cls is tuple:
            if len(value) > MAX_NODES - self.nodes:
                unavailable("Latest exceeds the bounded inspection budget.", 413)
            if cls is dict:
                if any(type(key) is not str for key in value):
                    unavailable("Latest has unsupported structured keys.", 413)
                return {
                    self.copy(k, depth + 1): self.copy(v, depth + 1)
                    for k, v in value.items()
                }
            return [self.copy(v, depth + 1) for v in value]
        elif value is None or cls is bool:
            pass
        elif cls is int:
            if value.bit_length() > 128:
                unavailable("Latest contains an unsupported integer.", 413)
        elif cls is float:
            if not math.isfinite(value):
                unavailable(
                    "Latest contains non-finite numbers unsupported by inspection.", 413
                )
        elif value is pd.NA or value is pd.NaT:
            return None
        elif cls is pd.Timestamp or cls is datetime or cls is date:
            # Even an exact datetime can carry arbitrary Python tzinfo callbacks.
            if (
                cls is not date
                and value.tzinfo is not None
                and type(value.tzinfo) is not timezone
                and type(value.tzinfo) is not ZoneInfo
            ):
                unavailable(
                    "Latest contains a timezone unsupported by bounded inspection.", 413
                )
            return self.copy(value.isoformat(), depth)
        elif any(cls is allowed for allowed in _NUMPY_SCALARS):
            return self.copy(value.item(), depth)
        else:
            # Never call arbitrary repr/str, lazy materialisation or extension hooks.
            unavailable(
                "Latest contains values unsupported by bounded inspection.", 413
            )
        if self.bytes > MAX_INPUT_BYTES:
            unavailable("Latest exceeds the inspection byte budget.", 413)
        return value


def capture_latest(view_id: str) -> Response:
    if not _READERS.acquire(blocking=False):
        unavailable("Latest inspection readers are busy. Choose Latest again.", 503)
    try:
        return _capture(view_id)
    finally:
        _READERS.release()


def _capture(view_id):
    # Constant-time reference/metadata capture only while holding the publisher lock.
    if not store._STORE_LOCK.acquire(blocking=False):
        unavailable("Latest is busy. Choose Latest again.", 503)
    try:
        st = store.get_view_state(view_id)
        revision, kind, artifact = st.render_revision, st.kind, st.artifact
        watched = st.watched_file
        total_rows = st.table_total_rows
        if kind == "stream":
            unavailable("Streams use their own session history.", 400)
        if watched and watched.materialization == "file":
            unavailable(
                "This source is read directly from a file and has no coherent published Latest revision. Choose a stored snapshot."
            )
        if artifact is None:
            unavailable("No Latest revision is available.", 404)
        created = artifact.created_at
    finally:
        store._STORE_LOCK.release()

    del st, watched
    budget = Budget()
    created_token = created
    created = budget.copy(created)
    if type(created) is not str or len(created) > 64:
        unavailable("Latest receipt metadata is unavailable.")
    result = {
        "version": 1,
        "server_instance_id": store.browser_update_hub.instance_id,
        "view_id": view_id,
        "revision": revision,
        "kind": kind,
        "created_at": created,
        "status": {"last_updated": created},
        "scope": "Published representation",
    }
    if kind == "plot":
        obj = artifact.obj
        if type(obj) is not bytes or len(obj) > MAX_INPUT_BYTES:
            unavailable("Plot exceeds the Latest inspection byte budget.", 413)
        result["plot"] = base64.b64encode(obj).decode("ascii")
        del artifact, obj
    elif kind == "table" or artifact.kind == "table":
        df = artifact.obj
        if type(df) is not pd.DataFrame or len(df.columns) > MAX_COLUMNS:
            unavailable("Table exceeds the inspection column budget.", 413)
        # Check column count before pandas indexing/dtype work; no whole-table conversion.
        if any(not isinstance(dtype, np.dtype) for dtype in df.dtypes):
            unavailable(
                "Table extension dtypes are unsupported for bounded Latest inspection.",
                413,
            )
        columns = budget.copy(list(df.columns))
        count = min(len(df), MAX_ROWS, MAX_NODES // max(1, len(columns) * 2 + 1))
        rows = []
        for values in df.iloc[:count].itertuples(index=False, name=None):
            rows.append({col: budget.copy(val) for col, val in zip(columns, values)})
        result["table"] = dict(
            columns=columns,
            rows=rows,
            total_rows=total_rows if total_rows is not None else len(df),
            returned_rows=count,
            loaded_rows=count,
            meta={"inspection": True},
        )
        result["scope"] = f"Published table preview: {count} of {len(df)} hosted rows"
        del artifact, df
        result["artifact"] = {
            "kind": "table",
            "html": '<div class="plot-frame"><div id="table-grid"></div></div>',
        }
    else:
        from .app import _render_artifact_response, _current_observation_context

        detached = budget.copy(artifact.obj)
        artifact_kind = artifact.kind
        del artifact
        observation = (
            artifact_kind == "json"
            and type(detached) is dict
            and detached.get("type") == "plotsrv_observation"
        )
        if (
            type(detached) in (dict, list, tuple)
            and not observation
            and budget.nodes > MAX_JSON_RENDER_NODES
        ):
            unavailable("JSON exceeds the bounded inspection rendering budget.", 413)
        context = _current_observation_context(
            view_id=view_id,
            obj=detached,
            kind_hint=artifact_kind,
            revision=revision,
            blocking=False,
        )
        if context is not None:
            context = budget.copy(context)
        result["artifact"] = _render_artifact_response(
            view_id=view_id,
            obj=detached,
            kind_hint=artifact_kind,
            observation_context=context,
        )
        # Source download links describe mutable live data, not this captured representation.
        result["artifact"].get("meta", {}).pop("source_download_url", None)

    # Serialize under a separate wire cap, without first allocating an unlimited JSON string.
    html = result.get("artifact", {}).get("html", "")
    if len(html) > MAX_BYTES // 6:
        unavailable("Rendered Latest exceeds the inspection response budget.", 413)
    parts, size = [], 0
    for part in json.JSONEncoder(
        ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).iterencode(result):
        size += len(part)
        if size > MAX_BYTES:
            unavailable("Rendered Latest exceeds the inspection response budget.", 413)
        parts.append(part)
    if not store._STORE_LOCK.acquire(blocking=False):
        unavailable()
    try:
        current = store.get_view_state(view_id)
        if (
            current.render_revision != revision
            or current.artifact is None
            or current.artifact.created_at is not created_token
        ):
            unavailable()
    finally:
        store._STORE_LOCK.release()
    return Response(
        "".join(parts),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
