from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import config, store
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


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC)


def _latest_snapshot_is_live_equivalent(*, view_id: str, snap: Any) -> bool:
    """
    Best-effort check that the newest snapshot represents current live state.

    A snapshot written as part of the current publish is normally created at or
    just after the store last_updated timestamp. If the live view has updated
    since the latest snapshot, last_updated will be later and this returns false.
    """
    status = store.get_status(view_id=view_id)
    last_updated = _parse_iso_datetime(status.get("last_updated"))
    snap_created = _parse_iso_datetime(getattr(snap, "created_at", None))

    if last_updated is None or snap_created is None:
        return False

    if snap_created < last_updated:
        return False

    live_kind = store.get_kind(view_id)
    snap_kind = str(getattr(snap, "kind", "") or "").strip().lower()

    if live_kind == "artifact":
        try:
            art = store.get_artifact(view_id=view_id)
            return str(art.kind).strip().lower() == snap_kind
        except LookupError:
            return False

    return live_kind == snap_kind


def _load_snapshot_or_404(*, view_id: str, snapshot_id: str):
    try:
        return load_snapshot(
            root_dir=_storage_root(),
            view_id=view_id,
            snapshot_id=snapshot_id,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
