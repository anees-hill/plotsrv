# src/plotsrv/renderers/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..artifacts import ArtifactKind, Truncation


@dataclass(frozen=True, slots=True)
class RenderResult:
    kind: ArtifactKind
    html: str
    mime: str = "text/html"
    truncation: Truncation | None = None
    meta: dict[str, Any] | None = None


class Renderer(Protocol):
    kind: ArtifactKind

    def can_render(self, obj: Any) -> bool: ...
    def render(self, obj: Any, *, view_id: str) -> RenderResult: ...
