# src/plotsrv/renderers/plot.py
from __future__ import annotations

from typing import Any

from .base import RenderResult
from ..artifacts import Truncation


class PlotRenderer:
    kind = "plot"

    def can_render(self, obj: Any) -> bool:
        # In Stage 1, our store artifact for plots is always bytes
        return isinstance(obj, (bytes, bytearray))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        # We don't embed the bytes; we reference /plot for caching and download support.
        html = f"""
        <div class="plot-frame">
          <img id="plot" src="/plot?view={view_id}" alt="Plot" />
        </div>
        """
        return RenderResult(
            kind="plot",
            html=html.strip(),
            truncation=Truncation(truncated=False),
            meta={"src": f"/plot?view={view_id}"},
        )
