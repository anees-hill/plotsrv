# src/plotsrv/renderers/image.py
from __future__ import annotations

import re
from typing import Any

from .base import RenderResult, Renderer

_SAFE_IMAGE_MIME_RE = re.compile(
    r"^image/(png|jpeg|jpg|gif|webp|bmp|svg\+xml)$",
    re.IGNORECASE,
)

_SAFE_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s_-]*$")


def _escape_html(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_attr(s: str) -> str:
    return _escape_html(s).replace("\n", " ").replace("\r", " ")


def _safe_image_mime(raw: Any) -> str:
    mime = str(raw or "application/octet-stream").strip().lower()
    if _SAFE_IMAGE_MIME_RE.match(mime):
        return mime
    return "application/octet-stream"


def _safe_data_b64(raw: Any) -> str:
    data = str(raw or "").strip()
    if not _SAFE_B64_RE.match(data):
        return ""
    return data


class ImageRenderer(Renderer):
    kind = "image"

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, dict) and "data_b64" in obj and "mime" in obj

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        d = obj if isinstance(obj, dict) else {}
        mime = _safe_image_mime(d.get("mime"))
        data_b64 = _safe_data_b64(d.get("data_b64"))
        filename = d.get("filename")

        filename_html = ""
        if filename:
            filename_html = (
                f"<div style='opacity:0.7'>{_escape_html(str(filename))}</div>"
            )

        html = (
            "<div style='display:flex;flex-direction:column;gap:8px'>"
            + filename_html
            + f"<img src='data:{_escape_attr(mime)};base64,{_escape_attr(data_b64)}' style='max-width:100%;height:auto' />"
            + "</div>"
        )

        return RenderResult(
            kind="image",
            html=html,
            mime="text/html",
            truncation=None,
            meta={"mime": mime, "view_id": view_id},
        )
