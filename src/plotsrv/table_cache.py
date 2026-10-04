"""Bounded encoded responses for receiver-owned, ordinary current tables.

The store owns publication consistency; this module only coordinates byte builds.
No lock is held while building or waiting. Futures can be shared across ASGI loops
(including independent TestClients), and followers never occupy worker threads.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from starlette.concurrency import run_in_threadpool


@dataclass(frozen=True, slots=True)
class TableResponseKey:
    view_id: str
    revision: int
    rows: int | None
    columns: int | None


class TableResponseCache:
    def __init__(self, *, max_entries: int = 32, max_bytes: int = 16 * 1024**2,
                 max_entry_bytes: int = 8 * 1024**2, max_builds: int = 32,
                 max_waiters: int = 128) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.max_entry_bytes = max_entry_bytes
        self.max_builds = max_builds
        self.max_waiters = max_waiters
        self._lock = RLock()
        self._entries: OrderedDict[TableResponseKey, bytes] = OrderedDict()
        self._builds: dict[TableResponseKey, Future[bytes]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._bytes = 0
        self._waiters = 0

    def put(self, key: TableResponseKey, body: bytes) -> None:
        """Caller must fence publication/reset before admitting a finished build."""
        with self._lock:
            if len(body) > self.max_entry_bytes or len(body) > self.max_bytes:
                return
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._bytes -= len(previous)
            self._entries[key] = body
            self._bytes += len(body)
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                _, removed = self._entries.popitem(last=False)
                self._bytes -= len(removed)

    def invalidate(self, view_id: str | None = None) -> None:
        # In-flight readers may finish with their captured revision. The store's
        # completion fence prevents them retaining bytes after invalidation.
        with self._lock:
            for key in tuple(self._entries):
                if view_id is None or key.view_id == view_id:
                    self._bytes -= len(self._entries.pop(key))

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(entries=len(self._entries), bytes=self._bytes,
                        builds=len(self._builds), waiters=self._waiters)

    async def get_or_build(self, key: TableResponseKey, build: Callable[[], bytes]) -> bytes:
        with self._lock:
            body = self._entries.get(key)
            if body is not None:
                self._entries.move_to_end(key)
                return body
            future = self._builds.get(key)
            admitted = self._waiters < self.max_waiters and (
                future is not None or len(self._builds) < self.max_builds
            )
            if admitted:
                self._waiters += 1
                if future is None:
                    future = Future()
                    self._builds[key] = future
                    task = asyncio.create_task(self._produce(key, future, build))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
        if not admitted:
            # Cache pressure must not introduce new HTTP rejections.
            return await run_in_threadpool(build)
        assert future is not None
        wrapped = asyncio.wrap_future(future)
        # Consume errors even if this HTTP reader disconnects. The underlying
        # future remains alive for the other readers and the producer.
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.shield(wrapped)
        finally:
            with self._lock:
                self._waiters -= 1

    async def _produce(self, key: TableResponseKey, future: Future[bytes],
                       build: Callable[[], bytes]) -> None:
        try:
            body = await run_in_threadpool(build)
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(body)
        finally:
            with self._lock:
                if self._builds.get(key) is future:
                    del self._builds[key]


TABLE_RESPONSES = TableResponseCache()
