# src/plotsrv/renderers/limits.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextLimits:
    max_chars: int = 50_000
    max_lines: int | None = None  # optional, not enforced by default


@dataclass(frozen=True, slots=True)
class JsonLimits:
    max_depth: int = 10
    max_nodes: int = 5_000
    max_string_chars: int = 1_000
    max_list_items: int = 200
    max_dict_items: int = 200


DEFAULT_TEXT_LIMITS = TextLimits()
DEFAULT_JSON_LIMITS = JsonLimits()
