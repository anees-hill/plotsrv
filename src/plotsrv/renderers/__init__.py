# src/plotsrv/renderers/__init__.py
from __future__ import annotations

from .registry import register_renderer
from .plot import PlotRenderer
from .table import TableRenderer
from .text import TextRenderer
from .json_tree import JsonTreeRenderer


def register_default_renderers() -> None:
    # Order matters: more specific first.
    register_renderer(PlotRenderer())
    register_renderer(TableRenderer())
    register_renderer(JsonTreeRenderer())
    register_renderer(TextRenderer())
