"""Lightweight presentation metadata shared by the store and HTML renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IconKey = Literal[
    "unknown",
    "plot",
    "table",
    "stream",
    "text",
    "json",
    "python",
    "code",
    "markdown",
    "image",
    "html",
    "traceback",
    "exception",
]


@dataclass(frozen=True, slots=True)
class ViewMeta:
    """
    Metadata that describes a view shown in the UI dropdown.
    """

    view_id: str
    kind: str  # "none" | "plot" | "table" | "artifact" | "stream"
    label: str
    section: str | None = None

    icon_key: IconKey = "unknown"
    description: str | None = None
    code_language: str | None = None
