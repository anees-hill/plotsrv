# src/plotsrv/storage/latest.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from . import backend as storage_backend
from .models import LatestMeta, LoadedLatest


@runtime_checkable
class LatestStateBackend(Protocol):
    """
    Internal interface for latest live-state persistence.

    This is intentionally small and internal for now. v0.3.0 provides a
    file-backed implementation, but the rest of plotsrv should only need these
    operations.
    """

    def write_latest(
        self,
        *,
        view_id: str,
        kind: str,
        obj: Any,
        section: str | None = None,
        label: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> LatestMeta:
        """
        Persist the latest live state for one view, replacing any previous
        latest state for that view.
        """
        ...

    def load_latest(self, *, view_id: str) -> LoadedLatest:
        """
        Load the latest persisted live state for one view.
        """
        ...

    def list_latest(self) -> list[LatestMeta]:
        """
        List latest persisted live states for all known views.
        """
        ...

    def delete_latest(self, *, view_id: str) -> bool:
        """
        Delete the latest persisted live state for one view.
        """
        ...


class FileLatestStateBackend:
    """
    File-backed latest live-state persistence.

    Layout:

      <root_dir>/
        latest/
          <slugged_view_id>/
            latest__meta.json
            latest__payload.<ext>

    This is intentionally separate from snapshot storage. Latest state answers:
    "what should live mode show after restart?"
    """

    def __init__(self, *, root_dir: str | Path) -> None:
        self.root_dir = storage_backend.ensure_storage_root(Path(root_dir))

    @property
    def latest_root(self) -> Path:
        root = self.root_dir / "latest"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def write_latest(
        self,
        *,
        view_id: str,
        kind: str,
        obj: Any,
        section: str | None = None,
        label: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> LatestMeta:
        view_dir = self._view_dir(view_id)
        view_dir.mkdir(parents=True, exist_ok=True)

        payload = storage_backend._serialise_payload(kind=kind, obj=obj)

        payload_name = f"latest__payload.{payload['suffix']}"
        meta_name = "latest__meta.json"

        payload_path = view_dir / payload_name
        meta_path = view_dir / meta_name

        self._remove_old_payloads(view_dir=view_dir, keep=payload_name)

        storage_backend._write_bytes_atomic(payload_path, payload["data"])

        size_bytes = int(payload_path.stat().st_size) if payload_path.exists() else 0
        updated_at = datetime.now(timezone.utc).isoformat()

        meta_dict: dict[str, Any] = {
            "view_id": view_id,
            "section": section,
            "label": label,
            "kind": kind,
            "updated_at": updated_at,
            "payload_filename": payload_name,
            "payload_format": payload["format"],
            "size_bytes": size_bytes,
            "path_payload": str(payload_path),
            "path_meta": str(meta_path),
            "payload_exists": payload_path.exists(),
            "extra": extra or {},
        }

        storage_backend._write_json_atomic(meta_path, meta_dict)

        return latest_meta_from_dict(meta_dict)

    def load_latest(self, *, view_id: str) -> LoadedLatest:
        view_dir = self._view_dir(view_id)
        meta_path = view_dir / "latest__meta.json"

        if not meta_path.exists():
            raise LookupError(f"Latest state not found: {view_id}")

        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise LookupError(f"Latest state metadata invalid: {view_id}")

        meta = latest_meta_from_dict(raw)
        payload_path = Path(meta.path_payload)

        if not payload_path.exists():
            raise LookupError(f"Latest state payload missing: {view_id}")

        obj = deserialise_latest_payload(meta=meta, payload_path=payload_path)
        return LoadedLatest(meta=meta, obj=obj)

    def list_latest(self) -> list[LatestMeta]:
        root = self.latest_root

        out: list[LatestMeta] = []
        for meta_path in sorted(root.glob("*/latest__meta.json")):
            try:
                raw = json.loads(meta_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    continue

                payload_path = Path(str(raw.get("path_payload") or ""))
                raw["payload_exists"] = payload_path.exists()
                out.append(latest_meta_from_dict(raw))
            except Exception:
                continue

        out.sort(key=lambda x: (x.section or "", x.label or x.view_id, x.view_id))
        return out

    def delete_latest(self, *, view_id: str) -> bool:
        view_dir = self._view_dir(view_id)
        if not view_dir.exists() or not view_dir.is_dir():
            return False

        removed = False

        meta_path = view_dir / "latest__meta.json"
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
            matches = list(view_dir.glob("latest__payload.*"))
            payload_path = matches[0] if matches else None

        for path in (payload_path, meta_path):
            if path is None:
                continue
            try:
                if path.exists():
                    path.unlink()
                    removed = True
            except Exception:
                pass

        try:
            next(view_dir.iterdir())
        except StopIteration:
            try:
                view_dir.rmdir()
            except Exception:
                pass
        except Exception:
            pass

        return removed

    def _view_dir(self, view_id: str) -> Path:
        return self.latest_root / storage_backend._slug_view_id(view_id)

    @staticmethod
    def _remove_old_payloads(*, view_dir: Path, keep: str) -> None:
        for path in view_dir.glob("latest__payload.*"):
            if path.name == keep:
                continue
            try:
                path.unlink()
            except Exception:
                pass


def latest_meta_from_dict(d: dict[str, Any]) -> LatestMeta:
    return LatestMeta(
        view_id=str(d.get("view_id") or ""),
        section=(None if d.get("section") is None else str(d.get("section"))),
        label=(None if d.get("label") is None else str(d.get("label"))),
        kind=str(d.get("kind") or "artifact"),
        updated_at=str(d.get("updated_at") or ""),
        payload_filename=str(d.get("payload_filename") or ""),
        payload_format=str(d.get("payload_format") or ""),
        size_bytes=int(d.get("size_bytes") or 0),
        path_payload=str(d.get("path_payload") or ""),
        path_meta=str(d.get("path_meta") or ""),
        payload_exists=bool(d.get("payload_exists", True)),
        extra=(d.get("extra") if isinstance(d.get("extra"), dict) else None),
    )


def deserialise_latest_payload(*, meta: LatestMeta, payload_path: Path) -> Any:
    snapshot_like = storage_backend._meta_from_dict(
        {
            "snapshot_id": "latest",
            "view_id": meta.view_id,
            "section": meta.section,
            "label": meta.label,
            "kind": meta.kind,
            "created_at": meta.updated_at,
            "payload_filename": meta.payload_filename,
            "payload_format": meta.payload_format,
            "size_bytes": meta.size_bytes,
            "path_payload": meta.path_payload,
            "path_meta": meta.path_meta,
            "payload_exists": meta.payload_exists,
            "extra": meta.extra or {},
        }
    )
    return storage_backend._deserialise_payload(
        meta=snapshot_like,
        payload_path=payload_path,
    )


def list_latest_views(*, root_dir: str | Path) -> list[dict[str, Any]]:
    """
    Return latest live-state summaries for all views.
    """
    backend = FileLatestStateBackend(root_dir=root_dir)
    out: list[dict[str, Any]] = []

    for meta in backend.list_latest():
        out.append(
            {
                "view_id": meta.view_id,
                "section": meta.section,
                "label": meta.label,
                "kind": meta.kind,
                "updated_at": meta.updated_at,
                "size_bytes": meta.size_bytes,
                "payload_filename": meta.payload_filename,
                "payload_exists": meta.payload_exists,
            }
        )

    out.sort(key=lambda x: str(x.get("view_id") or "").lower())
    return out


def get_latest_stats(*, root_dir: str | Path) -> dict[str, Any]:
    """
    Return latest live-state storage statistics.
    """
    root = storage_backend.ensure_storage_root(Path(root_dir))
    latest_root = root / "latest"

    latest_count = 0
    total_bytes = 0

    if not latest_root.exists() or not latest_root.is_dir():
        return {
            "root_dir": str(root),
            "latest_count": 0,
            "total_bytes": 0,
        }

    for view_dir in latest_root.iterdir():
        if not view_dir.is_dir():
            continue

        has_meta = False
        for path in view_dir.iterdir():
            if not path.is_file():
                continue
            try:
                total_bytes += int(path.stat().st_size)
            except Exception:
                pass
            if path.name == "latest__meta.json":
                has_meta = True

        if has_meta:
            latest_count += 1

    return {
        "root_dir": str(root),
        "latest_count": latest_count,
        "total_bytes": total_bytes,
    }


def delete_latest_for_view(*, root_dir: str | Path, view_id: str) -> int:
    """
    Delete latest live-state files for one view.

    Returns the number of files removed.
    """
    backend = FileLatestStateBackend(root_dir=root_dir)
    view_dir = backend._view_dir(view_id)

    if not view_dir.exists() or not view_dir.is_dir():
        return 0

    removed = 0
    for path in list(view_dir.iterdir()):
        try:
            if path.is_file():
                path.unlink()
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
    except Exception:
        pass

    return removed


def delete_all_latest(*, root_dir: str | Path) -> int:
    """
    Delete all latest live-state files for all views.

    Returns the number of files removed.
    """
    root = storage_backend.ensure_storage_root(Path(root_dir))
    latest_root = root / "latest"

    if not latest_root.exists() or not latest_root.is_dir():
        return 0

    removed = 0

    for view_dir in list(latest_root.iterdir()):
        if not view_dir.is_dir():
            continue

        for path in list(view_dir.iterdir()):
            try:
                if path.is_file():
                    path.unlink()
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
        except Exception:
            pass

    try:
        next(latest_root.iterdir())
    except StopIteration:
        try:
            latest_root.rmdir()
        except Exception:
            pass
    except Exception:
        pass

    return removed
