from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


PublishTargetKind = Literal["local", "remote"]


@dataclass(frozen=True, slots=True)
class PublishTarget:
    """Where a live-view update will be delivered."""

    kind: PublishTargetKind
    host: str
    port: int

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class PublishTask:
    """One replaceable live-view update waiting for background delivery."""

    obj: Any
    target: PublishTarget
    coalesce_view_id: str
    label: str | None = None
    section: str | None = None
    view_id: str | None = None
    update_limit_s: int | None = None
    force: bool = False
    kind: str | None = None
    artifact_kind: str | None = None
    estimated_bytes: int = 0

    @property
    def coalesce_key(self) -> str:
        return f"{self.target.key}:{self.coalesce_view_id}"


@dataclass(frozen=True, slots=True)
class PublishQueueStats:
    """A point-in-time, JSON-ready summary of the live publish worker."""

    queued: int
    in_flight: int
    pending_bytes: int
    max_pending_views: int
    max_pending_bytes: int
    submitted: int
    processed: int
    coalesced: int
    dropped: int
    rejected: int
    failed: int
    last_error: str | None
    running: bool
