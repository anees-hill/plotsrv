# src/plotsrv/storage/__init__.py
from __future__ import annotations

from .models import SnapshotMeta, LoadedSnapshot, LatestMeta, LoadedLatest
from .latest import (
    LatestStateBackend,
    FileLatestStateBackend,
    latest_meta_from_dict,
    deserialise_latest_payload,
    list_latest_views,
    get_latest_stats,
    delete_latest_for_view,
    delete_all_latest,
)
from .backend import (
    ensure_storage_root,
    write_snapshot,
    write_snapshot_and_prune,
    list_snapshots,
    load_snapshot,
    delete_snapshot,
    delete_all_snapshots_for_view,
    prune_snapshots,
    get_storage_stats,
)
from .policy import (
    AdmissionDecision,
    should_store_snapshot,
    snapshots_to_prune,
    estimate_payload_size_bytes,
)

__all__ = [
    "SnapshotMeta",
    "LoadedSnapshot",
    "LatestMeta",
    "LoadedLatest",
    "LatestStateBackend",
    "AdmissionDecision",
    "ensure_storage_root",
    "write_snapshot",
    "write_snapshot_and_prune",
    "list_snapshots",
    "load_snapshot",
    "delete_snapshot",
    "delete_all_snapshots_for_view",
    "prune_snapshots",
    "get_storage_stats",
    "should_store_snapshot",
    "snapshots_to_prune",
    "estimate_payload_size_bytes",
    "FileLatestStateBackend",
    "latest_meta_from_dict",
    "deserialise_latest_payload",
    "list_latest_views",
    "get_latest_stats",
    "delete_latest_for_view",
    "delete_all_latest",
]
