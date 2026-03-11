# src/plotsrv/storage/models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SnapshotMeta:
    snapshot_id: str
    view_id: str
    section: str | None
    label: str | None
    kind: str
    created_at: str
    payload_filename: str
    payload_format: str
    size_bytes: int
    path_payload: str
    path_meta: str
    payload_exists: bool = True
    extra: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LoadedSnapshot:
    meta: SnapshotMeta
    obj: Any
