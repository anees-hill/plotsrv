# src/plotsrv/renderers/json_tree.py
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .base import RenderResult
from .limits import DEFAULT_JSON_LIMITS, JsonLimits, safe_scalar_text
from ..artifacts import Truncation


_ICON_SRC = {
    "json": "/static/logo_json.png",
    "table": "/static/logo_table.png",
    "plot": "/static/logo_plot.png",
    "python": "/static/logo_python.png",
    "image": "/static/logo_image.png",
    "text": "/static/logo_txt.png",
    "markdown": "/static/logo_markdown.png",
    "html": "/static/logo_html.png",
    "exception": "/static/logo_exception.png",
}


class JsonTreeRenderer:
    kind = "json"

    def __init__(self, *, limits: JsonLimits | None = None) -> None:
        self._limits = limits or DEFAULT_JSON_LIMITS

    def can_render(self, obj: Any) -> bool:
        if isinstance(obj, dict) and obj.get("type") == "plotsrv_json_document":
            return True
        return isinstance(obj, (dict, list, tuple))

    def render(self, obj: Any, *, view_id: str) -> RenderResult:
        if isinstance(obj, dict) and obj.get("type") == "plotsrv_json_document":
            return self._render_document_payload(obj, view_id=view_id)

        return self._render_legacy_payload(obj, view_id=view_id)

    def _render_document_payload(
        self, obj: dict[str, Any], *, view_id: str
    ) -> RenderResult:
        root = obj.get("root")
        meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
        raw_text = obj.get("raw_text")
        pretty_text = obj.get("pretty_text")
        source_format = obj.get("source_format")

        if not isinstance(root, dict):
            html = (
                "<div class='note'>Invalid JSON document payload.</div>"
                f"<pre class='plotsrv-pre plotsrv-pre--wrap'>{_escape_html(repr(obj))}</pre>"
            )
            return RenderResult(
                kind="json",
                html=html,
                truncation=Truncation(truncated=False),
                meta={"view_id": view_id, "invalid_document": True},
            )

        rich_tree_html = _render_document_node(root)
        rich_head_html = """
        <div class="ps-json-rich-head" aria-hidden="true">
          <div class="ps-json-rich-head__cell">Key</div>
          <div class="ps-json-rich-head__cell">Summary</div>
          <div class="ps-json-rich-head__cell">Type</div>
          <div class="ps-json-rich-head__cell">Value</div>
          <div class="ps-json-rich-head__cell">Structure</div>
        </div>
        """.strip()

        simple_html = _render_simple_document_node(root)

        text_value = raw_text if isinstance(raw_text, str) else pretty_text
        if not isinstance(text_value, str):
            text_value = _pretty_json_fallback(obj)

        truncation = Truncation(
            truncated=bool(meta.get("truncated") or False),
            reason=(
                "json tree truncated by limits"
                if bool(meta.get("truncated") or False)
                else None
            ),
            details={
                "node_count": meta.get("node_count"),
                "max_depth_seen": meta.get("max_depth_seen"),
                "source_format": source_format,
            },
        )

        toolbar = """
        <div class="ps-json-topbar artifact-toolbar" data-plotsrv-toolbar="json">
          <div class="artifact-toolbar-group ps-json-toolbar-group">
            <span class="artifact-toolbar-label">Show levels</span>
            <select class="artifact-input ps-json-select" data-json-level-limit="1">
              <option value="1">1</option>
              <option value="2" selected="selected">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
              <option value="6">6</option>
              <option value="7">7</option>
              <option value="8">8</option>
              <option value="all">All</option>
            </select>
            <button type="button" class="artifact-btn" data-plotsrv-action="expand-all">Expand all</button>
            <button type="button" class="artifact-btn" data-plotsrv-action="collapse-all">Collapse all</button>
          </div>

          <div class="artifact-toolbar-group ps-json-toolbar-group">
            <span class="artifact-toolbar-label">Find</span>
            <input class="artifact-input" type="text" placeholder="key or value…" data-plotsrv-json-find="1" />
            <button type="button" class="artifact-btn" data-plotsrv-action="find-prev" title="Previous match">Prev</button>
            <button type="button" class="artifact-btn" data-plotsrv-action="find-next" title="Next match">Next</button>
            <span class="artifact-counter" data-plotsrv-json-count="1"></span>
          </div>

          <div class="artifact-toolbar-group ps-json-toolbar-group">
            <span class="artifact-toolbar-label">View</span>
            <div class="ps-json-mode-switch" role="tablist" aria-label="JSON view mode">
              <button type="button" class="artifact-btn ps-json-mode-btn is-active" data-json-mode="json">JSON</button>
              <button type="button" class="artifact-btn ps-json-mode-btn" data-json-mode="simple">JSON simple</button>
              <button type="button" class="artifact-btn ps-json-mode-btn" data-json-mode="text">Text</button>
            </div>
          </div>
        </div>
        """.strip()

        raw_text_json = _escape_attr(
            json.dumps(raw_text) if raw_text is not None else "null"
        )
        pretty_text_json = _escape_attr(
            json.dumps(pretty_text) if pretty_text is not None else "null"
        )
        source_format_attr = _escape_attr(str(source_format or "python_object"))

        html = f"""
        {toolbar}

        <div class="ps-json-shell"
             data-plotsrv-json="1"
             data-plotsrv-json-source-format="{source_format_attr}"
             data-plotsrv-json-raw-text="{raw_text_json}"
             data-plotsrv-json-pretty-text="{pretty_text_json}">

          <div class="ps-json-panel ps-json-panel--rich" data-json-panel="json">
            {rich_head_html}
            <div class="ps-json-tree ps-json-tree--rich">
              {rich_tree_html}
            </div>
          </div>

          <div class="ps-json-panel ps-json-panel--simple" data-json-panel="simple" hidden>
            <div class="json-tree json-tree--simple">
              {simple_html}
            </div>
          </div>

          <div class="ps-json-panel ps-json-panel--text" data-json-panel="text" hidden>
            <pre class="plotsrv-pre plotsrv-pre--wrap ps-json-textview" data-json-text-view="1">{_escape_html(text_value)}</pre>
          </div>
        </div>
        """.strip()

        return RenderResult(
            kind="json",
            html=html,
            truncation=truncation,
            meta={
                "view_id": view_id,
                "node_count": meta.get("node_count"),
                "max_depth_seen": meta.get("max_depth_seen"),
                "source_format": source_format,
                "has_raw_text": raw_text is not None,
            },
        )

    def _render_legacy_payload(self, obj: Any, *, view_id: str) -> RenderResult:
        ctx = _JsonCtx(limits=self._limits)
        tree_html = _render_legacy_node(obj, ctx=ctx, depth=0, label="root")

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
        <div class="ps-json-topbar artifact-toolbar" data-plotsrv-toolbar="json">
          <div class="artifact-toolbar-group ps-json-toolbar-group">
            <span class="artifact-toolbar-label">Show levels</span>
            <select class="artifact-input ps-json-select" data-json-level-limit="1">
              <option value="1">1</option>
              <option value="2" selected="selected">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
              <option value="6">6</option>
              <option value="7">7</option>
              <option value="8">8</option>
              <option value="all">All</option>
            </select>
            <button type="button" class="artifact-btn" data-plotsrv-action="expand-all">Expand all</button>
            <button type="button" class="artifact-btn" data-plotsrv-action="collapse-all">Collapse all</button>
          </div>

          <div class="artifact-toolbar-group ps-json-toolbar-group">
            <span class="artifact-toolbar-label">Find</span>
            <input class="artifact-input" type="text" placeholder="key or value…" data-plotsrv-json-find="1" />
            <button type="button" class="artifact-btn" data-plotsrv-action="find-prev" title="Previous match">Prev</button>
            <button type="button" class="artifact-btn" data-plotsrv-action="find-next" title="Next match">Next</button>
            <span class="artifact-counter" data-plotsrv-json-count="1"></span>
          </div>

          <div class="artifact-toolbar-group ps-json-toolbar-group">
            <span class="artifact-toolbar-label">View</span>
            <div class="ps-json-mode-switch" role="tablist" aria-label="JSON view mode">
              <button type="button" class="artifact-btn ps-json-mode-btn is-active" data-json-mode="json">JSON</button>
              <button type="button" class="artifact-btn ps-json-mode-btn" data-json-mode="simple">JSON simple</button>
              <button type="button" class="artifact-btn ps-json-mode-btn" data-json-mode="text">Text</button>
            </div>
          </div>
        </div>
        """.strip()

        text_value = _pretty_json_fallback(obj)

        html = f"""
        {toolbar}

        <div class="ps-json-shell"
             data-plotsrv-json="1"
             data-plotsrv-json-source-format="python_object"
             data-plotsrv-json-raw-text="null"
             data-plotsrv-json-pretty-text="{_escape_attr(json.dumps(text_value))}">

          <div class="ps-json-panel ps-json-panel--rich" data-json-panel="json">
            <div class="json-tree json-tree--simple">
              {tree_html}
            </div>
          </div>

          <div class="ps-json-panel ps-json-panel--simple" data-json-panel="simple" hidden>
            <div class="json-tree json-tree--simple">
              {tree_html}
            </div>
          </div>

          <div class="ps-json-panel ps-json-panel--text" data-json-panel="text" hidden>
            <pre class="plotsrv-pre plotsrv-pre--wrap ps-json-textview" data-json-text-view="1">{_escape_html(text_value)}</pre>
          </div>
        </div>
        """.strip()

        return RenderResult(
            kind="json",
            html=html,
            truncation=truncation,
            meta={"view_id": view_id, "visited_nodes": ctx.nodes, "legacy": True},
        )


@dataclass(slots=True)
class _JsonCtx:
    limits: JsonLimits
    nodes: int = 0
    truncated: bool = False
    hit: str | None = None


def _render_document_node(node: dict[str, Any]) -> str:
    display_key = str(node.get("display_key") or "")
    type_label = str(node.get("type_label") or "")
    summary = node.get("summary")
    preview = node.get("preview")
    icon_key = node.get("icon_key")
    node_kind = str(node.get("node_kind") or "scalar")
    value_kind = str(node.get("value_kind") or "value")
    child_count = int(node.get("child_count") or 0)
    desc_count = int(node.get("descendant_count") or 0)
    desc_layers = int(node.get("descendant_layer_count") or 0)
    expandable = bool(node.get("expandable") or False)
    children = node.get("children") if isinstance(node.get("children"), list) else []
    truncated = bool(node.get("truncated") or False)
    truncation_reason = node.get("truncation_reason")
    depth = int(node.get("depth") or 0)

    row_text_parts: list[str] = [display_key]
    if summary:
        row_text_parts.append(str(summary))
    if type_label:
        row_text_parts.append(type_label)
    if preview and node_kind != "container":
        row_text_parts.append(str(preview))
    row_text = " ".join(row_text_parts)

    icon_html = ""
    if icon_key and icon_key in _ICON_SRC:
        icon_html = (
            f'<img class="ps-json-typeicon" src="{_ICON_SRC[icon_key]}" alt="" />'
        )

    toggle_class = (
        "ps-json-toggle ps-json-toggle--expandable"
        if expandable
        else "ps-json-toggle ps-json-toggle--leaf"
    )

    summary_html = (
        f'<span class="ps-json-cell ps-json-cell--summary" data-json-text="{_escape_attr(str(summary))}">({_escape_html(str(summary))})</span>'
        if summary
        else '<span class="ps-json-cell ps-json-cell--summary"></span>'
    )

    type_html = (
        f'<span class="ps-json-cell ps-json-cell--type" data-json-text="{_escape_attr(type_label)}">{icon_html}<span class="ps-json-typelabel">{_escape_html(type_label)}</span></span>'
        if type_label
        else '<span class="ps-json-cell ps-json-cell--type"></span>'
    )

    hint_html = '<span class="ps-json-cell ps-json-cell--hint"></span>'
    if expandable and desc_layers > 0 and desc_count > 0:
        more_text = (
            f"{desc_layers} more layer"
            if desc_layers == 1
            else f"{desc_layers} more layers"
        )
        entry_text = (
            f"{desc_count} nested entry"
            if desc_count == 1
            else f"{desc_count} nested entries"
        )
        hint_html = f'<span class="ps-json-cell ps-json-cell--hint">{_escape_html(more_text + ", " + entry_text + " total")}</span>'

    value_html = '<span class="ps-json-cell ps-json-cell--value"></span>'
    if preview and node_kind != "container":
        value_html = f'<span class="ps-json-cell ps-json-cell--value" data-json-text="{_escape_attr(str(preview))}">{_escape_html(str(preview))}</span>'

    trunc_html = ""
    if truncated:
        reason = _escape_html(str(truncation_reason or "truncated"))
        trunc_html = f'<span class="badge json-badge" title="{reason}">…</span>'

    lead_html = f"""
    <span class="ps-json-cell ps-json-cell--lead">
      <span class="{toggle_class}" aria-hidden="true"></span>
      <span class="ps-json-key" data-json-text="{_escape_attr(display_key)}">{_escape_html(display_key)}</span>
      {trunc_html}
    </span>
    """.strip()

    row_inner = f"""
    {lead_html}
    {summary_html}
    {type_html}
    {value_html}
    {hint_html}
    """.strip()

    if not expandable:
        return f"""
        <div class="ps-json-row ps-json-row--leaf ps-json-row--{_escape_attr(value_kind)}"
             data-json-depth="{depth}"
             data-json-text="{_escape_attr(row_text)}">
          {row_inner}
        </div>
        """.strip()

    children_html = "".join(f"<li>{_render_document_node(ch)}</li>" for ch in children)

    return f"""
    <details open
             class="ps-json-node ps-json-node--{_escape_attr(value_kind)}"
             data-json-depth="{depth}"
             data-json-expandable="1">
      <summary class="ps-json-row ps-json-row--container ps-json-row--{_escape_attr(value_kind)}"
               data-json-depth="{depth}"
               data-json-text="{_escape_attr(row_text)}">
        {row_inner}
      </summary>
      <ul class="ps-json-children">
        {children_html}
      </ul>
    </details>
    """.strip()


def _render_simple_document_node(node: dict[str, Any]) -> str:
    display_key = str(node.get("display_key") or "")
    type_label = str(node.get("type_label") or "")
    summary = node.get("summary")
    preview = node.get("preview")
    expandable = bool(node.get("expandable") or False)
    children = node.get("children") if isinstance(node.get("children"), list) else []

    bits: list[str] = [
        f'<span class="json-key" data-json-text="{_escape_attr(display_key)}">{_escape_html(display_key)}</span>'
    ]

    if preview and not expandable:
        bits.append(
            f'<span class="json-val" data-json-text="{_escape_attr(str(preview))}">{_escape_html(str(preview))}</span>'
        )
    else:
        if summary:
            bits.append(
                f'<span class="json-summary" data-json-text="{_escape_attr(str(summary))}">({_escape_html(str(summary))})</span>'
            )
        if type_label:
            bits.append(
                f'<span class="json-type-label">{_escape_html(type_label)}</span>'
            )

    summaryline = " ".join(bits)

    if not expandable:
        return f'<div class="json-scalar">{summaryline}</div>'

    inner_html = "".join(
        f"<li>{_render_simple_document_node(ch)}</li>" for ch in children
    )

    return f"""
    <details open class="json-node json-node--simple">
      <summary class="json-summaryline">{summaryline}</summary>
      <ul class="json-children">{inner_html}</ul>
    </details>
    """.strip()


def _render_legacy_node(obj: Any, *, ctx: _JsonCtx, depth: int, label: str) -> str:
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
        return _render_legacy_dict(obj, ctx=ctx, depth=depth, label=label)

    if isinstance(obj, (list, tuple)):
        return _render_legacy_list(list(obj), ctx=ctx, depth=depth, label=label)

    return _render_legacy_scalar(obj, ctx=ctx, label=label)


def _render_legacy_dict(
    d: dict[Any, Any], *, ctx: _JsonCtx, depth: int, label: str
) -> str:
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
        inner_parts.append(
            _render_legacy_node(v, ctx=ctx, depth=depth + 1, label=k_str)
        )

        if ctx.truncated and ctx.hit in ("max_nodes", "max_depth"):
            break

    more = ""
    if total > len(shown):
        more = _badge(f"… {total - len(shown)} more keys", reason="dict item limit")

    summary = (
        f'<span class="json-label" data-json-text="{_escape_attr(label)}">{_escape_html(label)}</span>'
        f' <span class="json-summary">{{…}} ({total} keys)</span>'
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


def _render_legacy_list(xs: list[Any], *, ctx: _JsonCtx, depth: int, label: str) -> str:
    total = len(xs)
    shown = xs
    if total > ctx.limits.max_list_items:
        ctx.truncated = True
        ctx.hit = ctx.hit or "max_list_items"
        shown = xs[: ctx.limits.max_list_items]

    inner_parts: list[str] = []
    for i, v in enumerate(shown):
        inner_parts.append(
            _render_legacy_node(v, ctx=ctx, depth=depth + 1, label=f"[{i}]")
        )

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


def _render_legacy_scalar(x: Any, *, ctx: _JsonCtx, label: str) -> str:
    s, was_trunc = safe_scalar_text(x, max_chars=ctx.limits.max_string_chars)
    if was_trunc:
        ctx.truncated = True
        ctx.hit = ctx.hit or "max_string_chars"

    label_html = f'<span class="json-key" data-json-text="{_escape_attr(label)}">{_escape_html(label)}</span>'
    val_html = f'<span class="json-val" data-json-text="{_escape_attr(s)}">{_escape_html(s)}</span>'
    return f'<span class="json-scalar">{label_html}: {val_html}</span>'


def _pretty_json_fallback(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        try:
            return repr(obj)
        except Exception:
            return "<unrepresentable>"


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
    return _escape_html(s).replace("\n", " ").replace("\r", " ")
