# src/plotsrv/renderers/json_tree.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import RenderResult
from .limits import DEFAULT_JSON_LIMITS, JsonLimits, safe_scalar_text
from ..artifacts import Truncation


class JsonTreeRenderer:
    kind = "json"

    def __init__(self, *, limits: JsonLimits | None = None) -> None:
        self._limits = limits or DEFAULT_JSON_LIMITS

    def can_render(self, obj: Any) -> bool:
        return isinstance(obj, (dict, list, tuple))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        ctx = _JsonCtx(limits=self._limits)
        tree_html = _render_node(obj, ctx=ctx, depth=0, label="root")

        if ctx.truncated:
            truncation = Truncation(
                truncated=True,
                reason="json tree truncated by limits",
                details={
                    "max_depth": ctx.limits.max_depth,
                    "max_nodes": ctx.limits.max_nodes,
                    "max_string_chars": ctx.limits.max_string_chars,
                    "max_list_items": ctx.limits.max_list_items,
                    "max_dict_items": ctx.limits.max_dict_items,
                    "visited_nodes": ctx.nodes,
                    "hit": ctx.hit,
                },
            )
        else:
            truncation = Truncation(truncated=False)

        toolbar = """
        <div class="artifact-toolbar" data-plotsrv-toolbar="json">
          <div class="artifact-toolbar-group">
            <span class="artifact-toolbar-label">Find</span>
            <input class="artifact-input" type="text" placeholder="key or value…" data-plotsrv-json-find="1" />
            <button type="button" class="artifact-btn" data-plotsrv-action="find-prev" title="Previous match">Prev</button>
            <button type="button" class="artifact-btn" data-plotsrv-action="find-next" title="Next match">Next</button>
            <span class="artifact-counter" data-plotsrv-json-count="1"></span>
          </div>
        </div>
        """.strip()

        html = f"""
        {toolbar}
        <div class="json-tree" data-plotsrv-json="1">
          {tree_html}
        </div>
        """.strip()

        return RenderResult(
            kind="json",
            html=html,
            truncation=truncation,
            meta={"view_id": view_id, "visited_nodes": ctx.nodes},
        )


@dataclass(slots=True)
class _JsonCtx:
    limits: JsonLimits
    nodes: int = 0
    truncated: bool = False
    hit: str | None = None  # which limit caused truncation


def _render_node(obj: Any, *, ctx: _JsonCtx, depth: int, label: str) -> str:
    ctx.nodes += 1
    if ctx.nodes > ctx.limits.max_nodes:
        ctx.truncated = True
        ctx.hit = ctx.hit or "max_nodes"
        return _badge(f"{label}: …", reason="node limit")

    if depth > ctx.limits.max_depth:
        ctx.truncated = True
        ctx.hit = ctx.hit or "max_depth"
        return _badge(f"{label}: …", reason="depth limit")

    if isinstance(obj, dict):
        return _render_dict(obj, ctx=ctx, depth=depth, label=label)

    if isinstance(obj, (list, tuple)):
        return _render_list(list(obj), ctx=ctx, depth=depth, label=label)

    return _render_scalar(obj, ctx=ctx, label=label)


def _render_dict(d: dict[Any, Any], *, ctx: _JsonCtx, depth: int, label: str) -> str:
    items = list(d.items())
    total = len(items)

    shown = items
    if total > ctx.limits.max_dict_items:
        ctx.truncated = True
        ctx.hit = ctx.hit or "max_dict_items"
        shown = items[: ctx.limits.max_dict_items]

    inner_parts: list[str] = []
    for k, v in shown:
        k_str = str(k)
        inner_parts.append(_render_node(v, ctx=ctx, depth=depth + 1, label=k_str))

        if ctx.truncated and ctx.hit in ("max_nodes", "max_depth"):
            break

    more = ""
    if total > len(shown):
        more = _badge(f"… {total - len(shown)} more keys", reason="dict item limit")

    summary = (
        f'<span class="json-label" data-json-text="{_escape_attr(label)}">{_escape_html(label)}</span>'
        f' <span class="json-summary">{"{…}"} ({total} keys)</span>'
    )
    inner_html = "".join(f"<li>{p}</li>" for p in inner_parts) + (
        f"<li>{more}</li>" if more else ""
    )

    return f"""
    <details open class="json-node json-node--dict">
      <summary class="json-summaryline">{summary}</summary>
      <ul class="json-children">{inner_html}</ul>
    </details>
    """.strip()


def _render_list(xs: list[Any], *, ctx: _JsonCtx, depth: int, label: str) -> str:
    total = len(xs)
    shown = xs
    if total > ctx.limits.max_list_items:
        ctx.truncated = True
        ctx.hit = ctx.hit or "max_list_items"
        shown = xs[: ctx.limits.max_list_items]

    inner_parts: list[str] = []
    for i, v in enumerate(shown):
        inner_parts.append(_render_node(v, ctx=ctx, depth=depth + 1, label=f"[{i}]"))

        if ctx.truncated and ctx.hit in ("max_nodes", "max_depth"):
            break

    more = ""
    if total > len(shown):
        more = _badge(f"… {total - len(shown)} more items", reason="list item limit")

    summary = (
        f'<span class="json-label" data-json-text="{_escape_attr(label)}">{_escape_html(label)}</span>'
        f' <span class="json-summary">[…] ({total} items)</span>'
    )
    inner_html = "".join(f"<li>{p}</li>" for p in inner_parts) + (
        f"<li>{more}</li>" if more else ""
    )

    return f"""
    <details open class="json-node json-node--list">
      <summary class="json-summaryline">{summary}</summary>
      <ul class="json-children">{inner_html}</ul>
    </details>
    """.strip()


def _render_scalar(x: Any, *, ctx: _JsonCtx, label: str) -> str:
    s, was_trunc = safe_scalar_text(x, max_chars=ctx.limits.max_string_chars)
    if was_trunc:
        ctx.truncated = True
        ctx.hit = ctx.hit or "max_string_chars"

    label_html = f'<span class="json-key" data-json-text="{_escape_attr(label)}">{_escape_html(label)}</span>'
    val_html = f'<span class="json-val" data-json-text="{_escape_attr(s)}">{_escape_html(s)}</span>'
    return f'<span class="json-scalar">{label_html}: {val_html}</span>'


def _badge(text: str, *, reason: str) -> str:
    return f'<span class="badge json-badge" title="{_escape_html(reason)}">{_escape_html(text)}</span>'


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_attr(s: str) -> str:
    # safe for attribute values in double quotes
    return _escape_html(s).replace("\n", " ").replace("\r", " ")
