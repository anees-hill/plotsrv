from __future__ import annotations

"""Bounded in-memory cache for rendered current-view artifacts.

Rendering a large Markdown or JSON artifact can be materially more expensive
than serving the response.  The store gives each view a monotonically
increasing render revision whenever its displayable state changes; this cache
uses that revision as its invalidation key.

File-backed watched views deliberately do not use this cache. Their source can
change outside plotsrv, so their preview must continue to be read on demand.
"""

import sys
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any

# These limits keep the optimisation useful on small servers without turning a
# stream of large, distinct views into an unbounded second artifact store.
MAX_RENDER_CACHE_ENTRIES = 32
MAX_RENDER_CACHE_BYTES = 32 * 1024 * 1024
# The JSON tree renderer emits some non-ASCII UI labels. Python therefore
# stores a representative 4.5 MiB wire response in roughly 18 MiB of memory.
# Permit one such useful response, while the total cap prevents a large-view
# stream from becoming a second unbounded artifact store.
MAX_RENDER_CACHE_ENTRY_BYTES = 24 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _RenderCacheKey:
    view_id: str
    revision: int


@dataclass(slots=True)
class _RenderCacheEntry:
    response: dict[str, Any]
    size_bytes: int


class _RenderedArtifactCache:
    def __init__(
        self,
        *,
        max_entries: int = MAX_RENDER_CACHE_ENTRIES,
        max_bytes: int = MAX_RENDER_CACHE_BYTES,
        max_entry_bytes: int = MAX_RENDER_CACHE_ENTRY_BYTES,
    ) -> None:
        self._entries: OrderedDict[_RenderCacheKey, _RenderCacheEntry] = OrderedDict()
        self._lock = RLock()
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_entry_bytes = max_entry_bytes
        self._total_bytes = 0

    def get(self, *, view_id: str, revision: int) -> dict[str, Any] | None:
        key = _RenderCacheKey(view_id=view_id, revision=revision)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None

            self._entries.move_to_end(key)
            # Route callers should not be able to mutate a cached response for
            # another request. Strings (the potentially large HTML body) are
            # immutable, so deepcopy does not duplicate their contents.
            return deepcopy(entry.response)

    def put(
        self,
        *,
        view_id: str,
        revision: int,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        size_bytes = _rendered_response_size(response)
        if size_bytes > self._max_entry_bytes:
            return response

        key = _RenderCacheKey(view_id=view_id, revision=revision)
        with self._lock:
            self._discard_view_entries(view_id=view_id)

            cached_response = deepcopy(response)
            self._entries[key] = _RenderCacheEntry(
                response=cached_response,
                size_bytes=size_bytes,
            )
            self._total_bytes += size_bytes
            self._trim()

        return response

    def _discard_view_entries(self, *, view_id: str) -> None:
        for key in tuple(self._entries):
            if key.view_id != view_id:
                continue
            entry = self._entries.pop(key)
            self._total_bytes -= entry.size_bytes

    def _trim(self) -> None:
        while self._entries and (
            len(self._entries) > self._max_entries
            or self._total_bytes > self._max_bytes
        ):
            _, entry = self._entries.popitem(last=False)
            self._total_bytes -= entry.size_bytes

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0


def _rendered_response_size(response: dict[str, Any]) -> int:
    """Return a cheap conservative size estimate for cache admission."""
    html = response.get("html")
    html_size = sys.getsizeof(html) if isinstance(html, str) else 0
    return sys.getsizeof(response) + html_size


_CACHE = _RenderedArtifactCache()


def get_cached_rendered_artifact(
    *,
    view_id: str,
    revision: int,
) -> dict[str, Any] | None:
    return _CACHE.get(view_id=view_id, revision=revision)


def cache_rendered_artifact(
    *,
    view_id: str,
    revision: int,
    response: dict[str, Any],
) -> dict[str, Any]:
    return _CACHE.put(view_id=view_id, revision=revision, response=response)


def clear_rendered_artifact_cache() -> None:
    """Clear the process-local cache. Primarily useful in tests."""
    _CACHE.clear()
