# src/plotsrv/renderers/image.py
from __future__ import annotations

from typing import Any

from .registry import RenderResult, Renderer


class ImageRenderer(Renderer):
    kind = "image"

    def can_render(self, obj: Any, *, kind_hint: str | None = None) -> bool:
        if (kind_hint or "").lower() != "image":
            return False
        return isinstance(obj, dict) and "data_b64" in obj and "mime" in obj

    def render(
        self, obj: Any, *, view_id: str, kind_hint: str | None = None
    ) -> RenderResult:
        mime = str(obj.get("mime") or "application/octet-stream")
        data_b64 = str(obj.get("data_b64") or "")
        filename = obj.get("filename")

        html = (
            "<div style='display:flex;flex-direction:column;gap:8px'>"
            + (f"<div style='opacity:0.7'>{filename}</div>" if filename else "")
            + f"<img src='data:{mime};base64,{data_b64}' style='max-width:100%;height:auto' />"
            + "</div>"
        )
        return RenderResult(
            kind="image",
            html=html,
            mime="text/html",
            truncation=None,
            meta={"mime": mime},
        )
