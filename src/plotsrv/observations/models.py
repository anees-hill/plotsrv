"""Bounded observation options and internal detached-work contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
import hashlib
import json
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class ObservationBudget:
    max_rows: int = 32
    max_fields: int = 16
    max_elements: int = 1024
    max_nodes: int = 1024
    max_depth: int = 6
    max_value_bytes: int = 256
    max_categories: int = 16
    max_capture_bytes: int = 256 * 1024
    max_output_bytes: int = 64 * 1024
    exploratory_rows: int = 4
    max_dimensions: int = 8
    max_blocks: int = 32
    capture_ms: float = 10.0
    view_interval_s: float = 1.0
    process_interval_s: float = 0.25
    max_pending: int = 8
    max_pending_bytes: int = 512 * 1024
    max_view_ids: int = 128

    def __post_init__(self) -> None:
        caps = {
            "max_rows": (1, 128),
            "max_fields": (1, 32),
            "max_elements": (1, 4096),
            "max_nodes": (1, 4096),
            "max_depth": (1, 8),
            "max_value_bytes": (16, 1024),
            "max_categories": (1, 64),
            "max_capture_bytes": (4096, 1024 * 1024),
            "max_output_bytes": (4096, 256 * 1024),
            "exploratory_rows": (0, 16),
            "max_dimensions": (1, 8),
            "max_blocks": (1, 32),
            "max_pending": (1, 32),
            "max_pending_bytes": (4096, 4 * 1024 * 1024),
            "max_view_ids": (1, 256),
        }
        for name, (minimum, maximum) in caps.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
        for name, low, high in (
            ("capture_ms", 0.1, 50),
            ("view_interval_s", 0.01, 3600),
            ("process_interval_s", 0.001, 3600),
        ):
            value = getattr(self, name)
            if (
                type(value) not in (int, float)
                or not low <= value <= high
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} is outside its finite safety bounds")
        if self.max_output_bytes > self.max_pending_bytes:
            raise ValueError(
                "max_pending_bytes must reserve at least one output envelope"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> ObservationBudget:
        if (
            type(value) is not dict
            or len(value) > len(fields(cls))
            or any(
                type(k) is not str or k not in cls.__dataclass_fields__ for k in value
            )
        ):
            raise ValueError("invalid observation budget settings")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class ObservationOptions:
    # Strings select bounded-inspected dictionary/pandas names; integers are
    # positional table columns.
    fields: tuple[str | int, ...] = ()
    path: tuple[str | int, ...] = ()
    include_examples: bool = False

    def __post_init__(self) -> None:
        if type(self.include_examples) is not bool:
            raise ValueError("include_examples must be boolean")
        for values, maximum in ((self.fields, 32), (self.path, 6)):
            if type(values) is not tuple or len(values) > maximum:
                raise ValueError("observation selections exceed their limit")
            for value in values:
                if type(value) is int and 0 <= value <= 2**63 - 1:
                    continue
                if (
                    type(value) is str
                    and 0 < len(value) <= 128
                    and not any(0xD800 <= ord(c) <= 0xDFFF for c in value)
                ):
                    continue
                raise ValueError(
                    "selections require bounded strings or non-negative positions"
                )

        if self.fields and any(
            type(value) is not type(self.fields[0]) for value in self.fields
        ):
            raise ValueError("field selection must use either names or positions")


# Keep the reviewed internal spelling as an alias.
CaptureOptions = ObservationOptions


@dataclass(frozen=True, slots=True)
class ObservationRoute:
    target: object
    label: str
    section: str | None = None
    update_limit_s: int | None = None
    force: bool = False
    target_key: str = field(init=False)

    def __post_init__(self):
        from ..contracts import bounded_text
        from ..publishing.models import PublishTarget

        if type(self.target) is not PublishTarget:
            raise ValueError("invalid observation target")
        for name in ("label", "section"):
            value = getattr(self, name)
            if value is not None:
                if type(value) is not str:
                    raise ValueError("invalid observation metadata")
                bounded_text(value, name, 512, empty=name == "section")
        if self.update_limit_s is not None and (
            type(self.update_limit_s) is not int
            or not 0 <= self.update_limit_s <= 86400
        ):
            raise ValueError("invalid observation update limit")
        if type(self.force) is not bool:
            raise ValueError("invalid observation force option")

        object.__setattr__(
            self, "target_key", hashlib.sha256(self.target.key.encode()).hexdigest()
        )


@dataclass(frozen=True, slots=True)
class CaptureEnvelope:
    """Independent immutable evidence for a local summary worker only.

    Sample values are private working evidence, not a publishable payload.
    A later summary builder must honour examples_enabled before exporting rows.
    No source objects, native buffers, exceptions or adapter functions survive.
    """

    payload: bytes

    def document(self) -> dict:
        return json.loads(self.payload)


@dataclass(frozen=True, slots=True)
class ObservationWork:
    token: int
    view_id: str
    envelope: CaptureEnvelope
    route: ObservationRoute | None = None
