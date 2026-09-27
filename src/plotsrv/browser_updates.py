"""Bounded, process-local notifications for open plotsrv browsers.

The hub carries only change metadata.  Browser clients continue to retrieve
rendered content through the existing HTTP endpoints.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
from typing import Any, Hashable
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class BrowserUpdate:
    revision: int
    view_id: str | None
    change_type: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "view_id": self.view_id,
            "change_type": self.change_type,
            **self.metadata,
        }


@dataclass(eq=False, slots=True)
class BrowserUpdateSubscription:
    view_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[BrowserUpdate]
    pending: dict[str, BrowserUpdate] = field(default_factory=dict)
    dispatch_scheduled: bool = False
    client_key: str = "unknown"


class BrowserUpdateCapacityError(RuntimeError):
    """The bounded live-browser subscriber allowance is exhausted."""


class BrowserUpdateHub:
    """Fan out coalesced changes without retaining per-client history."""

    def __init__(self, *, max_subscribers: int = 1024) -> None:
        if max_subscribers < 1:
            raise ValueError("max_subscribers must be positive")
        self._lock = threading.RLock()
        self._max_subscribers = max_subscribers
        self._revision = 0
        self.instance_id = uuid4().hex
        self._view_revisions: dict[str, int] = {}
        self._catalogue_revision = 0
        self._latest: dict[str, BrowserUpdate] = {}
        self._fingerprints: dict[str, Hashable] = {}
        self._subscribers: set[BrowserUpdateSubscription] = set()

    def current_revision(self, view_id: str) -> int:
        with self._lock:
            return max(
                self._view_revisions.get(view_id, 0), self._catalogue_revision
            )

    def publish(
        self,
        *,
        view_id: str,
        change_type: str,
        metadata: dict[str, Any] | None = None,
        fingerprint: Hashable | None = None,
    ) -> BrowserUpdate | None:
        with self._lock:
            if fingerprint is not None and self._fingerprints.get(view_id) == fingerprint:
                return None
            if fingerprint is not None:
                self._fingerprints[view_id] = fingerprint
            self._revision += 1
            if change_type == "checks" and view_id in self._latest:
                metadata = {**self._latest[view_id].metadata, **(metadata or {})}
            event = BrowserUpdate(
                revision=self._revision,
                view_id=view_id,
                change_type=change_type,
                metadata=dict(metadata or {}),
            )
            self._view_revisions[view_id] = event.revision
            self._latest[view_id] = event
            subscribers = tuple(
                subscriber
                for subscriber in self._subscribers
                if subscriber.view_id == view_id
            )
        self._offer_to(subscribers, event)
        return event

    def reconnect_update(self, view_id: str) -> BrowserUpdate:
        """Capture one coherent revision/kind snapshot for the SSE handshake."""
        with self._lock:
            latest = self._latest.get(view_id)
            return BrowserUpdate(
                revision=self.current_revision(view_id),
                view_id=view_id,
                change_type="reconnect",
                metadata=dict(latest.metadata) if latest is not None else {},
            )

    def publish_catalogue(self) -> BrowserUpdate:
        with self._lock:
            self._revision += 1
            self._catalogue_revision = self._revision
            event = BrowserUpdate(
                revision=self._revision,
                view_id=None,
                change_type="catalogue",
                metadata={},
            )
            subscribers = tuple(self._subscribers)
        self._offer_to(subscribers, event)
        return event

    def subscribe(
        self,
        *,
        view_id: str,
        since: int,
        loop: asyncio.AbstractEventLoop,
        client_key: str = "unknown",
        max_connections: int | None = None,
        max_connections_per_client: int | None = None,
    ) -> BrowserUpdateSubscription:
        subscription = BrowserUpdateSubscription(
            view_id=view_id,
            loop=loop,
            client_key=client_key,
            # Preserve one data, stored-run, check, and global-catalogue notice. Each
            # class remains coalesced, so a slow browser has a strict bound.
            queue=asyncio.Queue(maxsize=4),
        )
        with self._lock:
            limit = min(self._max_subscribers, max_connections or self._max_subscribers)
            if len(self._subscribers) >= limit:
                raise BrowserUpdateCapacityError(
                    "too many browser update connections"
                )
            if max_connections_per_client is not None and sum(
                s.client_key == client_key for s in self._subscribers
            ) >= max_connections_per_client:
                raise BrowserUpdateCapacityError("too many browser update connections from this client")
            self._subscribers.add(subscription)
            current = self.current_revision(view_id)
            latest = self._latest.get(view_id)
            if current > since:
                view_revision = self._view_revisions.get(view_id, 0)
                if view_revision <= since and self._catalogue_revision > since:
                    event = BrowserUpdate(
                        revision=self._catalogue_revision,
                        view_id=None,
                        change_type="catalogue",
                        metadata={},
                    )
                else:
                    event = BrowserUpdate(
                        revision=current,
                        view_id=view_id,
                        change_type="reconnect",
                        metadata=(dict(latest.metadata) if latest is not None else {}),
                    )
                self._offer(subscription, event)
        return subscription

    def unsubscribe(self, subscription: BrowserUpdateSubscription) -> None:
        with self._lock:
            self._subscribers.discard(subscription)
            subscription.pending.clear()

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def clear(self) -> None:
        with self._lock:
            self._view_revisions.clear()
            self._latest.clear()
            self._fingerprints.clear()
            # Keep the process-wide counter monotonic so an open page cannot
            # mistake reset-and-republish for a duplicate revision.

    def _offer_to(
        self,
        subscribers: tuple[BrowserUpdateSubscription, ...],
        event: BrowserUpdate,
    ) -> None:
        for subscription in subscribers:
            if subscription.loop.is_closed():
                self.unsubscribe(subscription)
                continue
            with self._lock:
                if subscription not in self._subscribers:
                    continue
                category = self._category(event)
                previous = subscription.pending.get(category)
                if previous is None or event.revision > previous.revision:
                    subscription.pending[category] = event
                if subscription.dispatch_scheduled:
                    continue
                subscription.dispatch_scheduled = True
                try:
                    subscription.loop.call_soon_threadsafe(self._dispatch, subscription)
                except RuntimeError:
                    subscription.dispatch_scheduled = False
                    self.unsubscribe(subscription)

    def _dispatch(self, subscription: BrowserUpdateSubscription) -> None:
        with self._lock:
            pending = sorted(subscription.pending.values(), key=lambda item: item.revision)
            subscription.pending.clear()
            subscription.dispatch_scheduled = False
            if subscription not in self._subscribers:
                return
        for event in pending:
            self._offer(subscription, event)

    @staticmethod
    def _category(event: BrowserUpdate) -> str:
        return event.change_type if event.change_type in ('catalogue', 'stream_history', 'checks') else 'view'

    @staticmethod
    def _offer(
        subscription: BrowserUpdateSubscription, event: BrowserUpdate
    ) -> None:
        queue = subscription.queue
        try:
            pending = [event]
            while True:
                pending.append(queue.get_nowait())
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass

        # These event classes describe independent state. Keep the newest of
        # each and deliver them in revision order. Repeated stream writes still
        # collapse to one notification.
        newest: dict[str, BrowserUpdate] = {}
        for candidate in pending:
            category = BrowserUpdateHub._category(candidate)
            previous = newest.get(category)
            if previous is None or candidate.revision > previous.revision:
                newest[category] = candidate
        for candidate in sorted(newest.values(), key=lambda item: item.revision):
            try:
                queue.put_nowait(candidate)
            except asyncio.QueueFull:
                # The queue has a hard bound equal to the number of classes.
                break


browser_update_hub = BrowserUpdateHub()
