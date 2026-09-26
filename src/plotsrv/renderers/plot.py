# src/plotsrv/renderers/plot.py
from __future__ import annotations

from typing import Any
from html import escape
from urllib.parse import urlencode

from .base import RenderResult
from ..artifacts import Truncation


class PlotRenderer:
    kind = "plot"

    def can_render(self, obj: Any) -> bool:
        # In Stage 1, our store artifact for plots is always bytes
        return isinstance(obj, (bytes, bytearray))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        # We don't embed the bytes; we reference /plot for caching and download support.
        src = "/plot?" + urlencode({"view": view_id})
        html = f"""
        <div class="plot-frame">
          <img id="plot" src="{escape(src, quote=True)}" alt="Plot" />
        </div>
        """
        return RenderResult(
            kind="plot",
            html=html.strip(),
            truncation=Truncation(truncated=False),
            meta={"src": src},
        )
