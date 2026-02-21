# src/plotsrv/renderers/__init__.py
from __future__ import annotations

from .registry import register_renderer
from .plot import PlotRenderer
from .table import TableRenderer
from .text import TextRenderer
from .json_tree import JsonTreeRenderer
from .image import ImageRenderer
from .html import HtmlRenderer
from .markdown import MarkdownRenderer


def register_default_renderers() -> None:
    register_renderer(PlotRenderer())
    register_renderer(TableRenderer())
    register_renderer(ImageRenderer())
    register_renderer(HtmlRenderer())
    register_renderer(MarkdownRenderer())
    register_renderer(JsonTreeRenderer())
    register_renderer(TextRenderer())
