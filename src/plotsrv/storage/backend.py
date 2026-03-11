# src/plotsrv/storage/backend.py
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .models import LoadedSnapshot, SnapshotMeta


def ensure_storage_root(root_dir: Path) -> Path:
    root = Path(root_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_snapshot(
    *,
    root_dir: Path,
    view_id: str,
    kind: str,
    obj: Any,
    section: str | None = None,
    label: str | None = None,
    extra: dict[str, Any] | None = None,
) -> SnapshotMeta:
    """
    Write one snapshot to disk and return its metadata.
    """
    root = ensure_storage_root(root_dir)
    view_dir = _view_dir(root, view_id)
    view_dir.mkdir(parents=True, exist_ok=True)

    snapshot_id = _new_snapshot_id()
    payload = _serialise_payload(kind=kind, obj=obj)

    payload_name = f"{snapshot_id}__payload.{payload['suffix']}"
    meta_name = f"{snapshot_id}__meta.json"

    payload_path = view_dir / payload_name
    meta_path = view_dir / meta_name

    _write_bytes_atomic(payload_path, payload["data"])

    size_bytes = int(payload_path.stat().st_size) if payload_path.exists() else 0

    meta_dict: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "view_id": view_id,
        "section": section,
        "label": label,
        "kind": kind,
        "created_at": _snapshot_id_to_iso(snapshot_id),
        "payload_filename": payload_name,
        "payload_format": payload["format"],
        "size_bytes": size_bytes,
        "path_payload": str(payload_path),
        "path_meta": str(meta_path),
        "payload_exists": payload_path.exists(),
        "extra": extra or {},
    }

    _write_json_atomic(meta_path, meta_dict)

    return _meta_from_dict(meta_dict)


def write_snapshot_and_prune(
    *,
    root_dir: Path,
    view_id: str,
    kind: str,
    obj: Any,
    keep_last: int | None,
    section: str | None = None,
    label: str | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[SnapshotMeta, list[SnapshotMeta]]:
    """
    Convenience helper:
    - write snapshot
    - prune older snapshots according to keep_last
    - return (written_snapshot, pruned_snapshots)
    """
    written = write_snapshot(
        root_dir=root_dir,
        view_id=view_id,
        kind=kind,
        obj=obj,
        section=section,
        label=label,
        extra=extra,
    )

    snapshots = list_snapshots(root_dir=root_dir, view_id=view_id)
    pruned = prune_snapshots(
        root_dir=root_dir,
        view_id=view_id,
        snapshots=snapshots,
        keep_last=keep_last,
    )
    return written, pruned


def list_snapshots(*, root_dir: Path, view_id: str) -> list[SnapshotMeta]:
    root = ensure_storage_root(root_dir)
    view_dir = _view_dir(root, view_id)

    if not view_dir.exists() or not view_dir.is_dir():
        return []

    out: list[SnapshotMeta] = []
    for meta_path in sorted(view_dir.glob("*__meta.json"), reverse=True):
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            payload_path = Path(str(raw.get("path_payload") or ""))
            raw["payload_exists"] = payload_path.exists()
            out.append(_meta_from_dict(raw))
        except Exception:
            continue

    out.sort(key=lambda x: x.snapshot_id, reverse=True)
    return out


def load_snapshot(*, root_dir: Path, view_id: str, snapshot_id: str) -> LoadedSnapshot:
    root = ensure_storage_root(root_dir)
    view_dir = _view_dir(root, view_id)
    meta_path = view_dir / f"{snapshot_id}__meta.json"

    if not meta_path.exists():
        raise LookupError(f"Snapshot not found: {snapshot_id}")

    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LookupError(f"Snapshot metadata invalid: {snapshot_id}")

    meta = _meta_from_dict(raw)
    payload_path = Path(meta.path_payload)

    if not payload_path.exists():
        raise LookupError(f"Snapshot payload missing: {snapshot_id}")

    obj = _deserialise_payload(meta=meta, payload_path=payload_path)
    return LoadedSnapshot(meta=meta, obj=obj)


def delete_snapshot(*, root_dir: Path, view_id: str, snapshot_id: str) -> bool:
    root = ensure_storage_root(root_dir)
    view_dir = _view_dir(root, view_id)

    meta_path = view_dir / f"{snapshot_id}__meta.json"
    removed = False

    payload_path: Path | None = None
    if meta_path.exists():
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload_raw = raw.get("path_payload")
                if isinstance(payload_raw, str) and payload_raw.strip():
                    payload_path = Path(payload_raw)
        except Exception:
            payload_path = None

    if payload_path is None:
        matches = list(view_dir.glob(f"{snapshot_id}__payload.*"))
        payload_path = matches[0] if matches else None

    for p in (payload_path, meta_path):
        if p is None:
            continue
        try:
            if p.exists():
                p.unlink()
                removed = True
        except Exception:
            pass

    return removed


def delete_all_snapshots_for_view(*, root_dir: Path, view_id: str) -> int:
    root = ensure_storage_root(root_dir)
    view_dir = _view_dir(root, view_id)

    if not view_dir.exists() or not view_dir.is_dir():
        return 0

    removed = 0
    for p in view_dir.iterdir():
        try:
            if p.is_file():
                p.unlink()
                removed += 1
        except Exception:
            pass

    try:
        next(view_dir.iterdir())
    except StopIteration:
        try:
            view_dir.rmdir()
        except Exception:
            pass

    return removed


def prune_snapshots(
    *,
    root_dir: Path,
    view_id: str,
    snapshots: list[SnapshotMeta],
    keep_last: int | None,
) -> list[SnapshotMeta]:
    """
    Delete snapshots beyond the newest keep_last.

    Returns the snapshots that were successfully targeted for pruning
    (best effort; manual user interference is tolerated).
    """
    if keep_last is None:
        return []

    ordered = sorted(snapshots, key=lambda x: x.snapshot_id, reverse=True)
    to_delete = ordered[keep_last:]

    pruned: list[SnapshotMeta] = []
    for snap in to_delete:
        try:
            delete_snapshot(
                root_dir=root_dir, view_id=view_id, snapshot_id=snap.snapshot_id
            )
            pruned.append(snap)
        except Exception:
            pass

    return pruned


def get_storage_stats(*, root_dir: Path) -> dict[str, Any]:
    root = ensure_storage_root(root_dir)

    view_count = 0
    snapshot_count = 0
    total_bytes = 0

    if not root.exists():
        return {
            "root_dir": str(root),
            "view_count": 0,
            "snapshot_count": 0,
            "total_bytes": 0,
        }

    for child in root.iterdir():
        if not child.is_dir():
            continue
        view_count += 1
        for p in child.iterdir():
            if p.is_file():
                try:
                    total_bytes += int(p.stat().st_size)
                except Exception:
                    pass
                if p.name.endswith("__meta.json"):
                    snapshot_count += 1

    return {
        "root_dir": str(root),
        "view_count": view_count,
        "snapshot_count": snapshot_count,
        "total_bytes": total_bytes,
    }


# ------------------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------------------


def _view_dir(root: Path, view_id: str) -> Path:
    return root / _slug_view_id(view_id)


def _slug_view_id(view_id: str) -> str:
    s = view_id.strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "__", s)
    s = s.strip("._-")
    return s or "default"


def _new_snapshot_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _snapshot_id_to_iso(snapshot_id: str) -> str:
    try:
        dt = datetime.strptime(snapshot_id, "%Y%m%dT%H%M%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _serialise_payload(*, kind: str, obj: Any) -> dict[str, Any]:
    k = str(kind).strip().lower()

    if k == "plot":
        if not isinstance(obj, (bytes, bytearray)):
            raise TypeError("plot snapshots expect PNG bytes")
        return {
            "data": bytes(obj),
            "suffix": "png",
            "format": "png",
        }

    if k == "table":
        if not isinstance(obj, pd.DataFrame):
            raise TypeError("table snapshots expect pandas DataFrame")
        csv_bytes = obj.to_csv(index=False).encode("utf-8")
        return {
            "data": csv_bytes,
            "suffix": "csv",
            "format": "csv",
        }

    if k == "json":
        raw = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        return {
            "data": raw,
            "suffix": "json",
            "format": "json",
        }

    if k == "markdown":
        return {
            "data": str(obj).encode("utf-8"),
            "suffix": "md",
            "format": "text",
        }

    if k == "html":
        return {
            "data": str(obj).encode("utf-8"),
            "suffix": "html",
            "format": "text",
        }

    if k == "python":
        return {
            "data": str(obj).encode("utf-8"),
            "suffix": "py",
            "format": "text",
        }

    if k == "image":
        if isinstance(obj, dict):
            data_b64 = obj.get("data_b64")
            mime = str(obj.get("mime") or "application/octet-stream")
            if isinstance(data_b64, str) and data_b64:
                suffix = _suffix_from_mime(mime)
                return {
                    "data": base64.b64decode(data_b64.encode("ascii")),
                    "suffix": suffix,
                    "format": "binary_image",
                }

    if isinstance(obj, (bytes, bytearray)):
        data = bytes(obj)
    else:
        data = str(obj).encode("utf-8")

    return {
        "data": data,
        "suffix": "txt",
        "format": "text",
    }


def _deserialise_payload(*, meta: SnapshotMeta, payload_path: Path) -> Any:
    kind = meta.kind.strip().lower()
    fmt = meta.payload_format.strip().lower()

    if kind == "plot":
        return payload_path.read_bytes()

    if kind == "table":
        return pd.read_csv(payload_path)

    if kind == "json" or fmt == "json":
        return json.loads(payload_path.read_text(encoding="utf-8"))

    if kind == "image" and fmt == "binary_image":
        mime, _ = mimetypes.guess_type(str(payload_path))
        raw = payload_path.read_bytes()
        return {
            "mime": mime or "application/octet-stream",
            "data_b64": base64.b64encode(raw).decode("ascii"),
            "filename": payload_path.name,
        }

    return payload_path.read_text(encoding="utf-8", errors="replace")


def _suffix_from_mime(mime: str) -> str:
    m = mime.strip().lower()
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/svg+xml": "svg",
    }
    return mapping.get(m, "bin")


def _meta_from_dict(d: dict[str, Any]) -> SnapshotMeta:
    return SnapshotMeta(
        snapshot_id=str(d.get("snapshot_id") or ""),
        view_id=str(d.get("view_id") or ""),
        section=(None if d.get("section") is None else str(d.get("section"))),
        label=(None if d.get("label") is None else str(d.get("label"))),
        kind=str(d.get("kind") or "artifact"),
        created_at=str(d.get("created_at") or ""),
        payload_filename=str(d.get("payload_filename") or ""),
        payload_format=str(d.get("payload_format") or ""),
        size_bytes=int(d.get("size_bytes") or 0),
        path_payload=str(d.get("path_payload") or ""),
        path_meta=str(d.get("path_meta") or ""),
        payload_exists=bool(d.get("payload_exists", True)),
        extra=(d.get("extra") if isinstance(d.get("extra"), dict) else None),
    )


def _write_json_atomic(path: Path, obj: Any) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    _write_bytes_atomic(path, data)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.tmp-",
    ) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name

    Path(tmp_name).replace(path)
