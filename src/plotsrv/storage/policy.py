# src/plotsrv/storage/policy.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config
from .models import SnapshotMeta


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    accepted: bool
    reason: str
    keep_last: int | None
    min_store_interval_s: int | None
    max_snapshot_size_bytes: int


def should_store_snapshot(
    *,
    view_id: str,
    payload_size_bytes: int,
    existing_snapshots: list[SnapshotMeta],
) -> AdmissionDecision:
    """
    Decide whether an incoming live publish should be persisted to disk.

    0.0.5 admission checks:
    - global storage enabled
    - payload size <= max snapshot size
    - min_store_interval respected
    """
    keep_last = config.get_storage_keep_last(view_id)
    min_store_interval_s = config.get_storage_min_store_interval_s(view_id)
    max_snapshot_size_bytes = config.get_storage_max_snapshot_size_bytes()

    if not config.get_storage_enabled():
        return AdmissionDecision(
            accepted=False,
            reason="storage_disabled",
            keep_last=keep_last,
            min_store_interval_s=min_store_interval_s,
            max_snapshot_size_bytes=max_snapshot_size_bytes,
        )

    if payload_size_bytes > max_snapshot_size_bytes:
        return AdmissionDecision(
            accepted=False,
            reason="payload_too_large",
            keep_last=keep_last,
            min_store_interval_s=min_store_interval_s,
            max_snapshot_size_bytes=max_snapshot_size_bytes,
        )

    if min_store_interval_s is not None and existing_snapshots:
        latest = _latest_snapshot(existing_snapshots)
        if latest is not None:
            delta_s = _seconds_between_snapshot_ids(
                latest.snapshot_id,
                _new_snapshot_id_like_now(),
            )
            if delta_s is not None and delta_s < min_store_interval_s:
                return AdmissionDecision(
                    accepted=False,
                    reason="min_store_interval",
                    keep_last=keep_last,
                    min_store_interval_s=min_store_interval_s,
                    max_snapshot_size_bytes=max_snapshot_size_bytes,
                )

    return AdmissionDecision(
        accepted=True,
        reason="accepted",
        keep_last=keep_last,
        min_store_interval_s=min_store_interval_s,
        max_snapshot_size_bytes=max_snapshot_size_bytes,
    )


def snapshots_to_prune(
    *,
    view_id: str,
    snapshots: list[SnapshotMeta],
) -> list[SnapshotMeta]:
    """
    Return snapshots that should be deleted according to keep_last policy.

    Behaviour:
    - keep_last=None => infinite retention => prune none
    - keep_last=N => keep newest N, prune the rest
    """
    keep_last = config.get_storage_keep_last(view_id)
    if keep_last is None:
        return []

    ordered = sorted(snapshots, key=lambda x: x.snapshot_id, reverse=True)
    return ordered[keep_last:]


def estimate_payload_size_bytes(*, kind: str, obj: Any) -> int:
    """
    Approximate storage size before serialisation.

    This does not need to be perfect for 0.0.5; it just needs to be conservative
    enough to make admission decisions sensible before writing.
    """
    k = str(kind).strip().lower()

    if k == "plot":
        if isinstance(obj, (bytes, bytearray)):
            return len(obj)
        return _len_str_fallback(obj)

    if k == "table":
        try:
            import pandas as pd

            if isinstance(obj, pd.DataFrame):
                csv_bytes = obj.to_csv(index=False).encode("utf-8")
                return len(csv_bytes)
        except Exception:
            pass
        return _len_str_fallback(obj)

    if k == "json":
        try:
            import json

            return len(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))
        except Exception:
            return _len_str_fallback(obj)

    if k == "image":
        if isinstance(obj, dict):
            data_b64 = obj.get("data_b64")
            if isinstance(data_b64, str):
                # base64 expands size ~4/3; reverse roughly
                return max(1, int(len(data_b64) * 0.75))
        return _len_str_fallback(obj)

    if isinstance(obj, (bytes, bytearray)):
        return len(obj)

    return _len_str_fallback(obj)


def _len_str_fallback(obj: Any) -> int:
    try:
        return len(str(obj).encode("utf-8"))
    except Exception:
        return 0


def _latest_snapshot(snapshots: list[SnapshotMeta]) -> SnapshotMeta | None:
    if not snapshots:
        return None
    return max(snapshots, key=lambda x: x.snapshot_id)


def _seconds_between_snapshot_ids(older: str, newer: str) -> int | None:
    dt_old = _parse_snapshot_id(older)
    dt_new = _parse_snapshot_id(newer)
    if dt_old is None or dt_new is None:
        return None
    return int((dt_new - dt_old).total_seconds())


def _parse_snapshot_id(snapshot_id: str):
    from datetime import datetime, timezone

    try:
        return datetime.strptime(snapshot_id, "%Y%m%dT%H%M%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        return None


def _new_snapshot_id_like_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
