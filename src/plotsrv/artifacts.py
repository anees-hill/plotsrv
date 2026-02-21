# src/plotsrv/artifacts.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ArtifactKind = Literal[
    "plot", "table", "text", "json", "python", "markdown", "image", "html"
]


@dataclass(frozen=True, slots=True)
class Truncation:
    truncated: bool
    reason: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Artifact:
    kind: ArtifactKind
    obj: Any

    created_at: datetime
    label: str | None = None
    section: str | None = None
    view_id: str | None = None

    truncation: Truncation | None = None
