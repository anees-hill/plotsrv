"""Bounded process-lifetime observation evidence; no timers or background work."""

from __future__ import annotations

from collections import OrderedDict, deque
import json
import threading

from .summary import encode_summary

MAX_SOURCES = 128
MAX_ENTRIES = 16
MAX_ENTRY_BYTES = 24 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
_LOCK = threading.Lock()
_SOURCES = OrderedDict()
_TOTAL_BYTES = 0


def compact(summary):
    result = {
        key: summary[key]
        for key in (
            "observation_version",
            "recipe_version",
            "source_type",
            "captured_at_unix_s",
            "provenance",
            "sampling",
            "metadata",
            "delivery",
            "reasons",
        )
    }
    result["fields"] = [
        {
            key: field[key]
            for key in (
                "path",
                "position",
                "scope",
                "value",
                "positions_captured",
                "values_inspected",
                "not_inspected",
                "missingness",
            )
            if key in field
        }
        | (
            {
                "numeric": {
                    key: field["numeric"][key]
                    for key in ("mean", "min", "max")
                    if key in field["numeric"]
                }
            }
            if "numeric" in field
            else {}
        )
        for field in summary["fields"]
    ]
    return result


def append(view_id, summary, *, revision, previous_revision, received_at):
    """Consumer receipt only. Congestion drops history, never queues more work."""
    global _TOTAL_BYTES
    document = compact(summary)
    document.update(revision=revision, received_at=received_at)
    payload = encode_summary(document)
    if len(payload) > MAX_ENTRY_BYTES:
        document["fields"] = []
        document["metadata"] = {}
        document["history_evidence_omitted"] = True
        payload = encode_summary(document)
    if len(payload) > min(
        MAX_ENTRY_BYTES, MAX_SOURCE_BYTES, MAX_TOTAL_BYTES
    ) or not _LOCK.acquire(False):
        return False
    try:
        source = _SOURCES.get(view_id)
        # Intervening ordinary content or missed history admission is a boundary.
        if source is not None and source["revision"] != previous_revision:
            _TOTAL_BYTES -= source["bytes"]
            del _SOURCES[view_id]
            source = None
        if source is None:
            if len(_SOURCES) >= MAX_SOURCES:
                _, evicted = _SOURCES.popitem(last=False)
                _TOTAL_BYTES -= evicted["bytes"]
            source = dict(entries=deque(), bytes=0, pruned=False, revision=revision)
            _SOURCES[view_id] = source
        size = len(payload)
        while source["entries"] and (
            len(source["entries"]) >= MAX_ENTRIES
            or source["bytes"] + size > MAX_SOURCE_BYTES
        ):
            removed = source["entries"].popleft()
            source["bytes"] -= len(removed)
            _TOTAL_BYTES -= len(removed)
            source["pruned"] = True
        while _TOTAL_BYTES + size > MAX_TOTAL_BYTES:
            key, victim = next(iter(_SOURCES.items()))
            removed = victim["entries"].popleft()
            victim["bytes"] -= len(removed)
            _TOTAL_BYTES -= len(removed)
            victim["pruned"] = True
            if not victim["entries"] and key != view_id:
                del _SOURCES[key]
        source["entries"].append(payload)
        source["bytes"] += size
        source["revision"] = revision
        _TOTAL_BYTES += size
        _SOURCES.move_to_end(view_id)
        return True
    finally:
        _LOCK.release()


def read(view_id, *, revision):
    # Copy references to immutable bytes under the lock; decode outside it.
    with _LOCK:
        source = _SOURCES.get(view_id)
        if source is None or source["revision"] != revision:
            return [], False
        entries, pruned = tuple(source["entries"]), source["pruned"]
    return [json.loads(value) for value in entries], pruned


def clear():
    global _TOTAL_BYTES
    with _LOCK:
        _SOURCES.clear()
        _TOTAL_BYTES = 0


def stats():
    with _LOCK:
        return dict(
            sources=len(_SOURCES),
            entries=sum(len(s["entries"]) for s in _SOURCES.values()),
            bytes=_TOTAL_BYTES,
        )
