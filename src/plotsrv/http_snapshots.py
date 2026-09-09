from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import config
from .storage.backend import load_snapshot


def _storage_root() -> Path:
    return config.get_storage_root_dir()


def _snapshot_summary_dict(
    snap: Any,
    *,
    is_latest: bool = False,
    is_live_equivalent: bool = False,
) -> dict[str, Any]:
    return {
        "snapshot_id": snap.snapshot_id,
        "view_id": snap.view_id,
        "section": snap.section,
        "label": snap.label,
        "kind": snap.kind,
        "created_at": snap.created_at,
        "payload_filename": snap.payload_filename,
        "payload_format": snap.payload_format,
        "size_bytes": snap.size_bytes,
        "payload_exists": snap.payload_exists,
        "is_latest": is_latest,
        "is_live_equivalent": is_live_equivalent,
        "extra": snap.extra or {},
    }


def _latest_snapshot_is_live_equivalent(*, view_id: str, snap: Any) -> bool:
    # Stored metadata has no durable identity tying it to a live revision.
    # Timestamps (including equal timestamps) cannot prove equal content.
    return False


def _load_snapshot_or_404(*, view_id: str, snapshot_id: str):
    from .storage.navigation import valid_snapshot_id

    if not valid_snapshot_id(snapshot_id):
        raise HTTPException(status_code=404, detail="Snapshot unavailable")
    try:
        return load_snapshot(
            root_dir=_storage_root(),
            view_id=view_id,
            snapshot_id=snapshot_id,
        )
    except (LookupError, OSError, ValueError, TypeError) as e:
        raise HTTPException(
            status_code=404, detail="Snapshot unavailable or unreadable"
        ) from e


def _render_plot_snapshot_html(*, view_id: str, snapshot_id: str) -> dict[str, Any]:
    src = f"/plot?view={view_id}&snapshot={snapshot_id}"
    html = f"""
    <div class="plot-frame">
      <img id="plot" src="{src}" alt="Plot snapshot" />
    </div>
    """.strip()

    return {
        "view_id": view_id,
        "snapshot_id": snapshot_id,
        "kind": "plot",
        "html": html,
        "mime": "text/html",
        "truncation": None,
        "meta": {
            "src": src,
            "snapshot": True,
        },
    }


def _render_table_snapshot_html(*, view_id: str, snapshot_id: str) -> dict[str, Any]:
    data_src = f"/table/data?view={view_id}&snapshot={snapshot_id}"
    html = """
    <div class="plot-frame">
      <div id="table-grid" class="table-grid"></div>
    </div>
    """.strip()

    return {
        "view_id": view_id,
        "snapshot_id": snapshot_id,
        "kind": "table",
        "html": html,
        "mime": "text/html",
        "truncation": None,
        "meta": {
            "data_src": data_src,
            "snapshot": True,
        },
    }
