# src/plotsrv/renderers/traceback.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import Renderer, RenderResult


@dataclass(slots=True)
class TracebackRenderer(Renderer):
    kind: str = "traceback"

    def can_render(self, obj: Any) -> bool:
        # Expect a structured payload from publish_traceback()
        if not isinstance(obj, dict):
            return False
        return obj.get("type") == "traceback" and isinstance(obj.get("frames"), list)

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        payload = obj if isinstance(obj, dict) else {}
        exc_type = str(payload.get("exc_type") or "Exception")
        exc_msg = str(payload.get("exc_msg") or "")
        frames = payload.get("frames") or []

        header = (
            f'<div class="ps-traceback__header">'
            f"<strong>{_escape_html(exc_type)}</strong>"
        )
        if exc_msg:
            header += f": {_escape_html(exc_msg)}"
        header += "</div>"

        items: list[str] = []
        for i, fr in enumerate(frames):
            if not isinstance(fr, dict):
                continue
            filename = str(fr.get("filename") or "<?>")
            lineno = fr.get("lineno")
            func = str(fr.get("function") or "<module>")
            line = str(fr.get("line") or "")
            ctx_before = fr.get("context_before") or []
            ctx_after = fr.get("context_after") or []

            where = f"{filename}:{lineno}" if lineno is not None else filename

            ctx_lines: list[str] = []
            for s in ctx_before:
                ctx_lines.append(_escape_html(str(s)))
            if line:
                ctx_lines.append(f"<mark>{_escape_html(line)}</mark>")
            for s in ctx_after:
                ctx_lines.append(_escape_html(str(s)))

            ctx_html = ""
            if ctx_lines:
                ctx_html = (
                    "<pre class='ps-traceback__code'>" + "\n".join(ctx_lines) + "</pre>"
                )

            items.append(
                f"""
<details class="ps-traceback__frame" {"open" if i == 0 else ""}>
  <summary class="ps-traceback__summary">
    <span class="ps-traceback__func">{_escape_html(func)}</span>
    <span class="ps-traceback__where">{_escape_html(where)}</span>
  </summary>
  {ctx_html}
</details>
""".strip()
            )

        body = '<div class="ps-traceback__frames">' + "\n".join(items) + "</div>"

        html = f"""
<div class="ps-traceback">
  {header}
  {body}
</div>
""".strip()

        return RenderResult(
            kind="traceback",
            html=html,
            mime="text/html",
            meta={"view_id": view_id, "frames": len(frames)},
        )


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
