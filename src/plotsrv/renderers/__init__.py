# src/plotsrv/renderers/__init__.py
from __future__ import annotations

from .registry import register_renderer, render_any
from .plot import PlotRenderer
from .table import TableRenderer


def register_default_renderers() -> None:
    register_renderer(PlotRenderer())
    register_renderer(TableRenderer())
