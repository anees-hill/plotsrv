# src/plotsrv/renderers/json_tree.py
from __future__ import annotations

import json
from typing import Any

from .base import RenderResult
from .limits import DEFAULT_JSON_LIMITS, JsonLimits
from ..artifacts import Truncation
from ..json_model import JsonModelLimits, build_json_document

_ICON_SRC = {
    "json": "/static/logo_json.png",
    "table": "/static/logo_table.png",
    "plot": "/static/logo_plot.png",
    "python": "/static/logo_python.png",
    "image": "/static/logo_image.png",
    "text": "/static/logo_txt.png",
    "markdown": "/static/logo_markdown.png",
    "html": "/static/logo_html.png",
    "traceback": "/static/logo_exception.png",
    "exception": "/static/logo_exception.png",  # legacy alias
}


def _to_json_model_limits(limits: JsonLimits) -> JsonModelLimits:
    return JsonModelLimits(
        max_depth=limits.max_depth,
        max_nodes=limits.max_nodes,
        max_dict_items=limits.max_dict_items,
        max_list_items=limits.max_list_items,
        max_string_chars=limits.max_string_chars,
        max_preview_chars=min(260, limits.max_string_chars),
    )


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
        return self._render_runtime_payload(obj, view_id=view_id)

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
          <div class="ps-json-rich-head__cell ps-json-rich-head__cell--actions"></div>
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
                "hit": meta.get("hit"),
            },
        )

        toolbar = """
        <div class="ps-json-topbar artifact-toolbar" data-plotsrv-toolbar="json">
          <div class="artifact-toolbar-group ps-json-toolbar-group" data-json-toolbar-group="levels">
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

          <div class="artifact-toolbar-group ps-json-toolbar-group" data-json-toolbar-group="find">
            <span class="artifact-toolbar-label">Find</span>
            <input class="artifact-input" type="text" placeholder="key or value…" data-plotsrv-json-find="1" />
            <button type="button" class="artifact-btn" data-plotsrv-action="find-prev" title="Previous match">Prev</button>
            <button type="button" class="artifact-btn" data-plotsrv-action="find-next" title="Next match">Next</button>
            <span class="artifact-counter" data-plotsrv-json-count="1"></span>
          </div>

          <div class="artifact-toolbar-group ps-json-toolbar-group" data-json-toolbar-group="pins">
            <button type="button" class="artifact-btn" data-plotsrv-action="open-pinned">Pinned</button>
          </div>

          <div class="artifact-toolbar-group ps-json-toolbar-group" data-json-toolbar-group="view">
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

          <div class="ps-json-pinnedmodal" data-json-pinned-modal="1" hidden>
            <div class="ps-json-pinnedmodal__backdrop" data-json-pinned-close="1"></div>
            <div class="ps-json-pinnedmodal__dialog" role="dialog" aria-modal="true" aria-label="Pinned values">
              <div class="ps-json-pinnedmodal__header">
                <div class="ps-json-pinnedmodal__title">Pinned values</div>
                <button type="button" class="ps-json-pinnedmodal__close" data-json-pinned-close="1" aria-label="Close">×</button>
              </div>
              <div class="ps-json-pinnedmodal__body" data-json-pinned-list="1"></div>
            </div>
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

    def _render_runtime_payload(self, obj: Any, *, view_id: str) -> RenderResult:
        doc = build_json_document(
            obj,
            source_format="python_object",
            raw_text=None,
            source_filename=None,
            limits=_to_json_model_limits(self._limits),
        )
        return self._render_document_payload(doc, view_id=view_id)


def _render_document_node(node: dict[str, Any]) -> str:
    path = _node_path(node)
    display_key = str(node.get("display_key") or "")
    type_label = str(node.get("type_label") or "")
    summary = node.get("summary")
    preview = node.get("preview")
    full_value = node.get("full_value")

    if full_value is None and preview is not None:
        full_value = preview

    icon_key = node.get("icon_key")
    node_kind = str(node.get("node_kind") or "scalar")
    value_kind = str(node.get("value_kind") or "value")
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

    show_summary = bool(summary) and expandable

    summary_html = (
        f'<span class="ps-json-cell ps-json-cell--summary" data-json-text="{_escape_attr(str(summary))}">({_escape_html(str(summary))})</span>'
        if show_summary
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
        hint_html = (
            '<span class="ps-json-cell ps-json-cell--hint">'
            + _escape_html(more_text + ", " + entry_text + " total")
            + "</span>"
        )

    value_html = '<span class="ps-json-cell ps-json-cell--value"></span>'
    if preview and node_kind != "container":
        value_html = (
            f'<span class="ps-json-cell ps-json-cell--value" '
            f'data-json-text="{_escape_attr(str(preview))}" '
            f'title="{_escape_attr(str(full_value or preview))}">'
            f"{_escape_html(str(preview))}</span>"
        )

    actions_html = '<span class="ps-json-cell ps-json-cell--actions"></span>'
    if not expandable:
        pin_btn = (
            f'<button type="button" class="ps-json-actionbtn ps-json-actionbtn--pin" '
            f'data-json-pin-toggle="{_escape_attr(path)}" '
            f'aria-pressed="false" title="Pin value">📌</button>'
        )
        actions_html = (
            '<span class="ps-json-cell ps-json-cell--actions">' f"{pin_btn}</span>"
        )

    trunc_html = ""
    if truncated:
        reason_raw = str(truncation_reason or "truncated")
        reason = _escape_html(reason_raw)

        if reason_raw == "dict item limit":
            badge_text = "… more keys"
        elif reason_raw == "list item limit":
            badge_text = "… more items"
        elif reason_raw == "node limit":
            badge_text = "… node limit"
        elif reason_raw == "depth limit":
            badge_text = "… depth limit"
        elif reason_raw == "string preview limit":
            badge_text = "… truncated"
        else:
            badge_text = "…"

        trunc_html = (
            f'<span class="badge json-badge" title="{reason}">'
            f"{_escape_html(badge_text)}"
            f"</span>"
        )

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
    {actions_html}
    """.strip()

    if not expandable:
        full_value_text = str(full_value if full_value is not None else "")

        return f"""
        <div class="ps-json-entry ps-json-entry--scalar"
             data-json-path="{_escape_attr(path)}"
             data-json-depth="{depth}"
             data-json-key="{_escape_attr(display_key)}"
             data-json-full-value="{_escape_attr(full_value_text)}">
          <div class="ps-json-row ps-json-row--leaf ps-json-row--{_escape_attr(value_kind)}"
               data-json-depth="{depth}"
               data-json-path="{_escape_attr(path)}"
               data-json-text="{_escape_attr(row_text)}">
            {row_inner}
          </div>
          <pre hidden data-json-full-value-text="1">{_escape_html(full_value_text)}</pre>
        </div>
        """.strip()

    children_html = "".join(f"<li>{_render_document_node(ch)}</li>" for ch in children)

    return f"""
    <details open
             class="ps-json-node ps-json-node--{_escape_attr(value_kind)}"
             data-json-depth="{depth}"
             data-json-expandable="1"
             data-json-path="{_escape_attr(path)}">
      <summary class="ps-json-row ps-json-row--container ps-json-row--{_escape_attr(value_kind)}"
               data-json-depth="{depth}"
               data-json-path="{_escape_attr(path)}"
               data-json-text="{_escape_attr(row_text)}">
        {row_inner}
      </summary>
      <ul class="ps-json-children">
        {children_html}
      </ul>
    </details>
    """.strip()


def _render_simple_document_node(node: dict[str, Any]) -> str:
    path = _node_path(node)
    display_key = str(node.get("display_key") or "")
    type_label = str(node.get("type_label") or "")
    summary = node.get("summary")
    preview = node.get("preview")
    expandable = bool(node.get("expandable") or False)
    children = node.get("children") if isinstance(node.get("children"), list) else []
    depth = int(node.get("depth") or 0)

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
        return (
            f'<div class="json-scalar" data-json-depth="{depth}" '
            f'data-json-path="{_escape_attr(path)}">{summaryline}</div>'
        )

    inner_html = "".join(
        f"<li>{_render_simple_document_node(ch)}</li>" for ch in children
    )

    return f"""
    <details open class="json-node json-node--simple"
             data-json-depth="{depth}"
             data-json-path="{_escape_attr(path)}">
      <summary class="json-summaryline">{summaryline}</summary>
      <ul class="json-children">{inner_html}</ul>
    </details>
    """.strip()


def _node_path(node: dict[str, Any]) -> str:
    raw_path = node.get("path")

    if isinstance(raw_path, str) and raw_path:
        return raw_path

    node_id = node.get("id")
    if isinstance(node_id, str) and node_id:
        return node_id

    if isinstance(raw_path, list):
        parts: list[str] = []
        for part in raw_path:
            if isinstance(part, int):
                parts.append(f"[{part}]")
            else:
                parts.append(str(part))
        return "/".join(parts)

    return ""


def _pretty_json_fallback(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, default=repr)
    except Exception:
        try:
            return repr(obj)
        except Exception:
            return "<unrepresentable>"


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
