# src/plotsrv/renderers/image.py
from __future__ import annotations

from typing import Any

from .base import RenderResult, Renderer


class ImageRenderer(Renderer):
    kind = "image"

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, dict) and "data_b64" in obj and "mime" in obj

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        d = obj if isinstance(obj, dict) else {}
        mime = str(d.get("mime") or "application/octet-stream")
        data_b64 = str(d.get("data_b64") or "")
        filename = d.get("filename")

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
            meta={"mime": mime, "view_id": view_id},
        )
