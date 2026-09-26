# src/plotsrv/storage/backend.py
from __future__ import annotations

import base64
import hashlib
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
from ..file_access import open_regular_file


# These directories have their own storage backends.  Snapshot traversal must
# never treat their implementation layout as a logical snapshot view.
_RESERVED_STORAGE_DIRECTORIES = frozenset(("latest", "streams"))


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
    out: list[SnapshotMeta] = []
    paths = (p for directory in _read_view_dirs(root, view_id) for p in directory.glob("*__meta.json"))
    seen = set()
    for meta_path in paths:
        try:
            raw = _read_bound_metadata(meta_path, view_id=view_id)
            if raw["snapshot_id"] in seen:
                continue
            seen.add(raw["snapshot_id"])
            out.append(_meta_from_dict(raw))
        except Exception:
            continue

    def order(meta: SnapshotMeta) -> tuple[datetime, str]:
        try:
            created = datetime.fromisoformat(meta.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return created.astimezone(timezone.utc), meta.snapshot_id
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=timezone.utc), meta.snapshot_id

    out.sort(key=order, reverse=True)
    return out


def load_snapshot(*, root_dir: Path, view_id: str, snapshot_id: str) -> LoadedSnapshot:
    _validate_snapshot_id(snapshot_id)
    root = ensure_storage_root(root_dir)
    meta_path = _find_snapshot_metadata(root, view_id, snapshot_id)

    if not meta_path.exists():
        raise LookupError(f"Snapshot not found: {snapshot_id}")

    raw = _read_bound_metadata(meta_path, view_id=view_id)
    meta = _meta_from_dict(raw)
    payload_path = Path(meta.path_payload)

    if not payload_path.exists():
        raise LookupError(f"Snapshot payload missing: {snapshot_id}")

    obj = _deserialise_payload(meta=meta, payload_path=payload_path)
    return LoadedSnapshot(meta=meta, obj=obj)


def delete_snapshot(*, root_dir: Path, view_id: str, snapshot_id: str) -> bool:
    _validate_snapshot_id(snapshot_id)
    root = ensure_storage_root(root_dir)
    removed = False
    for directory in _read_view_dirs(root, view_id):
        meta_path = directory / f"{snapshot_id}__meta.json"
        try:
            raw = _read_bound_metadata(meta_path, view_id=view_id)
        except (OSError, ValueError, LookupError):
            continue
        for p in (Path(raw["path_payload"]), meta_path):
            try:
                p.unlink()
                removed = True
            except OSError:
                pass

    return removed


def delete_all_snapshots_for_view(*, root_dir: Path, view_id: str) -> int:
    root = ensure_storage_root(root_dir)
    removed = 0
    for snapshot in list_snapshots(root_dir=root, view_id=view_id):
        if delete_snapshot(root_dir=root, view_id=view_id, snapshot_id=snapshot.snapshot_id):
            removed += 1 + int(snapshot.payload_exists)
    for view_dir in _read_view_dirs(root, view_id):
        try:
            view_dir.rmdir()
        except OSError:
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

    ordered = sorted((s for s in snapshots if s.view_id == view_id), key=lambda x: x.snapshot_id, reverse=True)
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
        if child.name in _RESERVED_STORAGE_DIRECTORIES:
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


def list_stored_views(*, root_dir: Path) -> list[dict[str, Any]]:
    """
    Return per-view storage summaries.

    Best effort:
    - derives the true view_id from snapshot metadata where possible
    - tolerates missing / malformed metadata
    """
    root = ensure_storage_root(root_dir)

    if not root.exists():
        return []

    out: list[dict[str, Any]] = []

    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name in _RESERVED_STORAGE_DIRECTORIES:
            continue

        metas: list[SnapshotMeta] = []
        for meta_path in sorted(child.glob("*__meta.json")):
            try:
                with open_regular_file(meta_path) as source:
                    content = source.read(1024 * 1024 + 1)
                if len(content) > 1024 * 1024:
                    continue
                raw = json.loads(content)
                if not isinstance(raw, dict):
                    continue
                view = raw.get("view_id")
                if not isinstance(view, str) or child not in _read_view_dirs(root, view):
                    continue
                metas.append(_meta_from_dict(_read_bound_metadata(meta_path, view_id=view)))
            except Exception:
                continue

        if metas:
            metas.sort(key=lambda x: x.snapshot_id, reverse=True)
            for m in metas:
                existing = next((item for item in out if item["view_id"] == m.view_id), None)
                if existing is None:
                    existing = {"view_id": m.view_id, "snapshot_count": 0, "total_bytes": 0, "last_created_at": m.created_at}
                    out.append(existing)
                existing["snapshot_count"] += 1
                existing["total_bytes"] += m.size_bytes
                existing["last_created_at"] = max(existing["last_created_at"] or "", m.created_at)
            continue

        # empty / orphaned directory
        out.append(
            {
                "view_id": child.name,
                "snapshot_count": 0,
                "total_bytes": 0,
                "last_created_at": None,
            }
        )

    out.sort(key=lambda x: str(x.get("view_id") or "").lower())
    return out


def delete_all_snapshots(*, root_dir: Path) -> int:
    """
    Delete all stored snapshots for all views.

    Returns number of files removed (best effort).
    """
    root = ensure_storage_root(root_dir)

    if not root.exists() or not root.is_dir():
        return 0

    removed = 0

    for child in list(root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        if child.name in _RESERVED_STORAGE_DIRECTORIES:
            continue

        for p in list(child.iterdir()):
            try:
                if p.is_file():
                    p.unlink()
                    removed += 1
            except Exception:
                pass

        try:
            next(child.iterdir())
        except StopIteration:
            try:
                child.rmdir()
            except Exception:
                pass

    return removed


# ------------------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------------------


def _view_dir(root: Path, view_id: str) -> Path:
    return root / ("v2-" + hashlib.sha256(view_id.encode("utf-8")).hexdigest())


def _read_view_dirs(root: Path, view_id: str) -> list[Path]:
    """New writes are isolated; legacy directories are read by exact identity."""
    paths = [_view_dir(root, view_id)]
    legacy = _slug_view_id(view_id)
    if legacy not in _RESERVED_STORAGE_DIRECTORIES and len(legacy.encode()) <= 255:
        paths.append(root / legacy)
    return paths


def _validate_snapshot_id(snapshot_id: str) -> None:
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", snapshot_id) or snapshot_id in (".", ".."):
        raise LookupError("Invalid snapshot identity")


def _find_snapshot_metadata(root: Path, view_id: str, snapshot_id: str) -> Path:
    for directory in _read_view_dirs(root, view_id):
        path = directory / f"{snapshot_id}__meta.json"
        if path.exists():
            return path
    return _view_dir(root, view_id) / f"{snapshot_id}__meta.json"


def _read_bound_metadata(path: Path, *, view_id: str, latest: bool = False) -> dict:
    with open_regular_file(path) as source:
        content = source.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("Stored metadata exceeds the byte limit")
    raw = json.loads(content)
    if not isinstance(raw, dict):
        raise LookupError("Snapshot metadata invalid")
    if raw.get("view_id") != view_id:
        raise LookupError("Stored identity does not match the requested view")
    identity = "latest" if latest else raw.get("snapshot_id", "")
    if not latest:
        _validate_snapshot_id(identity)
    if path.name != identity + "__meta.json":
        raise LookupError("Stored metadata identity mismatch")
    name = raw.get("payload_filename", "")
    if not isinstance(name, str) or not re.fullmatch(re.escape(identity) + r"__payload\.[a-zA-Z0-9]+", name):
        raise LookupError("Invalid stored payload filename")
    # Serialized absolute paths are historical diagnostics, never authority.
    payload = path.parent / name
    raw["path_meta"] = str(path)
    raw["path_payload"] = str(payload)
    raw["payload_exists"] = payload.is_file() and not payload.is_symlink()
    return raw


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

    if k == "traceback":
        raw = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        return {
            "data": raw,
            "suffix": "json",
            "format": "json",
        }

    if k == "exception":  # legacy alias
        raw = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        return {
            "data": raw,
            "suffix": "json",
            "format": "json",
        }

    if k == "markdown":
        if isinstance(obj, dict) and "text" in obj:
            # Preserve rendering options and server-owned remote provenance in
            # both historical snapshots and the latest-state backend.
            return {
                "data": json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
                "suffix": "json",
                "format": "json",
            }
        return {
            "data": str(obj).encode("utf-8"),
            "suffix": "md",
            "format": "text",
        }

    if k == "html":
        if isinstance(obj, dict) and "html" in obj:
            raw = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            return {
                "data": raw,
                "suffix": "json",
                "format": "json",
            }

        return {
            "data": str(obj).encode("utf-8"),
            "suffix": "html",
            "format": "text",
        }

    if k in ("python", "code"):
        return {
            "data": str(obj).encode("utf-8"),
            "suffix": "py" if k == "python" else "txt",
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
    with open_regular_file(payload_path) as source:
        return _deserialise_open_payload(meta=meta, payload_path=payload_path, source=source)


def _deserialise_open_payload(*, meta: SnapshotMeta, payload_path: Path, source) -> Any:
    kind = meta.kind.strip().lower()
    fmt = meta.payload_format.strip().lower()

    if kind == "plot":
        return source.read()

    if kind == "table":
        return pd.read_csv(source)

    if kind in ("json", "traceback", "exception") or fmt == "json":
        return json.loads(source.read())

    if kind == "image" and fmt == "binary_image":
        mime, _ = mimetypes.guess_type(str(payload_path))
        raw = source.read()
        return {
            "mime": mime or "application/octet-stream",
            "data_b64": base64.b64encode(raw).decode("ascii"),
            "filename": payload_path.name,
        }

    return source.read().decode("utf-8", errors="replace")


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
