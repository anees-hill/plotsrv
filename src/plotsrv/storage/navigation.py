"""Bounded, on-demand metadata navigation; never opens snapshot payloads.

The existing on-disk format has no ordered index. Scan under a fixed budget,
keeping only one page and its neighbours. Refuse incomplete ordering rather
than presenting a plausible but incorrect endpoint. No persistent cache/worker.
"""

from __future__ import annotations

import base64
import heapq
import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .backend import _view_dir

MAX_ENTRIES = 10_000
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024
MAX_SCAN_SECONDS = 0.5  # Cooperative between filesystem operations, not cancellation.
_READERS = threading.BoundedSemaphore(2)
_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


class NavigationUnavailable(Exception):
    pass


def valid_snapshot_id(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(_ID.fullmatch(value))
        and value not in (".", "..")
    )


def timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid timestamp")
    dt = datetime.fromisoformat(value)
    return (
        dt.replace(tzinfo=UTC).isoformat(timespec="microseconds")
        if dt.tzinfo is None
        else dt.astimezone(UTC).isoformat(timespec="microseconds")
    )


def encode_cursor(key: tuple[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def decode_cursor(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    if len(value) > 512:
        raise ValueError("Invalid snapshot cursor")
    try:
        parts = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if (
            not isinstance(parts, list)
            or len(parts) != 2
            or not valid_snapshot_id(parts[1])
        ):
            raise ValueError()
        return timestamp(parts[0]), parts[1]
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("Invalid snapshot cursor") from exc


def navigation_page(
    *,
    root_dir: Path,
    view_id: str,
    selected: str | None = None,
    before: str | None = None,
    limit: int = 50,
    start: str | None = None,
    end: str | None = None,
    days: bool = False,
) -> dict:
    if not 1 <= limit <= 100 or (selected and not valid_snapshot_id(selected)):
        raise ValueError("Invalid snapshot selection or page size")
    cursor = decode_cursor(before)
    start = timestamp(start) if start else None
    end = timestamp(end) if end else None
    if start and end and start >= end:
        raise ValueError("History start must precede end")
    if days and (
        not start
        or not end
        or (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days > 31
    ):
        raise ValueError("Availability requires one bounded month")
    if not _READERS.acquire(blocking=False):
        raise NavigationUnavailable("Snapshot metadata readers are busy. Try again.")
    try:
        return _scan(
            Path(root_dir).expanduser(),
            view_id,
            selected,
            cursor,
            limit,
            start,
            end,
            days,
        )
    finally:
        _READERS.release()


def _scan(root, view_id, selected, cursor, limit, start, end, days=False):
    directory = _view_dir(root, view_id)
    deadline = time.monotonic() + MAX_SCAN_SECONDS
    read_bytes = 0

    def read(path):
        nonlocal read_bytes
        # Size is bounded before JSON parsing; unneeded extra/path metadata is discarded.
        if path.is_symlink():
            raise ValueError("Invalid metadata link")
        with path.open("rb") as handle:
            content = handle.read(
                min(MAX_FILE_BYTES, MAX_METADATA_BYTES - read_bytes) + 1
            )
        read_bytes += len(content)
        if len(content) > MAX_FILE_BYTES or read_bytes > MAX_METADATA_BYTES:
            raise NavigationUnavailable(
                "Snapshot metadata exceeds the navigation byte budget."
            )
        raw = json.loads(content)
        if not isinstance(raw, dict):
            raise ValueError("Invalid metadata")
        if raw.get("view_id") != view_id:
            return None  # Legacy directory slugs can collide; identities cannot.
        sid = raw["snapshot_id"]
        if not valid_snapshot_id(sid) or path.name != sid + "__meta.json":
            raise ValueError("Invalid snapshot identity")
        key = (timestamp(raw["created_at"]), sid)
        kind = str(raw["kind"])
        if len(kind) > 64:
            raise ValueError("Invalid kind")
        row = dict(
            snapshot_id=sid,
            created_at=key[0],
            kind=kind,
            is_live_equivalent=False,
            equivalence="unknown",
        )
        return key, row

    selected_item = None
    if selected:
        try:
            selected_item = read(directory / (selected + "__meta.json"))
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            pass  # Selected metadata unreadable/missing is explicit in the response.
    heap = []
    older = newer = newest = None
    count = eligible = 0
    available_days = {}
    try:
        entries = os.scandir(directory)
    except FileNotFoundError:
        entries = None
    if entries is not None:
        with entries:
            for index, entry in enumerate(entries):
                if index >= MAX_ENTRIES or time.monotonic() > deadline:
                    raise NavigationUnavailable(
                        "Snapshot history exceeds the navigation scan budget. Reduce retained history or try again."
                    )
                if not entry.name.endswith("__meta.json"):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    item = read(Path(entry.path))
                except FileNotFoundError:
                    continue  # Retention concurrently removed this version.
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    RecursionError,
                ) as exc:
                    raise NavigationUnavailable(
                        "Snapshot metadata is unreadable; ordering is unavailable."
                    ) from exc
                if item is None:
                    continue
                key, row = item
                if newest is None or key > newest[0]:
                    newest = item
                if selected_item:
                    pivot = selected_item[0]
                    if key < pivot and (older is None or key > older[0]):
                        older = item
                    if key > pivot and (newer is None or key < newer[0]):
                        newer = item
                if (start and key[0] < start) or (end and key[0] >= end):
                    continue
                count += 1
                if days:
                    day = key[0][:10]
                    available_days[day] = available_days.get(day, 0) + 1
                if cursor and key >= cursor:
                    continue
                eligible += 1
                if len(heap) < limit:
                    heapq.heappush(heap, item)
                elif key > heap[0][0]:
                    heapq.heapreplace(heap, item)
    page = sorted(heap, reverse=True)
    for key, row in page:
        row["is_latest"] = newest is not None and key == newest[0]
    return dict(
        days=available_days,
        snapshots=[row for _, row in page],
        count=count,
        next_cursor=encode_cursor(page[-1][0]) if eligible > limit and page else None,
        selected=selected_item[1] if selected_item else None,
        selection_state=(
            "latest"
            if not selected
            else "available" if selected_item else "unavailable"
        ),
        older=(
            (older if selected else newest)[1]
            if (older if selected else newest)
            else None
        ),
        newer=newer[1] if newer else None,
        can_return_latest=bool(selected),
    )
