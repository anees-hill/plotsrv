# src/plotsrv/renderers/table.py
from __future__ import annotations

from typing import Any

import pandas as pd

from .base import RenderResult
from ..artifacts import Truncation


class TableRenderer:
    kind = "table"

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, pd.DataFrame)

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        # Keep it simple for now: either server has simple HTML already or uses /table/data.
        html = """
        <div class="plot-frame">
          <div id="table-grid" class="table-grid"></div>
        </div>
        """
        return RenderResult(
            kind="table",
            html=html.strip(),
            truncation=Truncation(truncated=False),
            meta={"data_src": f"/table/data?view={view_id}"},
        )
