# src/plotsrv/storage/latest.py
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import LatestMeta, LoadedLatest


@runtime_checkable
class LatestStateBackend(Protocol):
    """
    Internal interface for latest live-state persistence.

    This is intentionally small and internal for now. v0.3.0 will provide a
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
