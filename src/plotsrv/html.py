# src/plotsrv/html.py
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as distribution_version
from typing import Literal
import json

from .config import TableViewMode
from .store import ViewMeta
from .table_explorer_markup import render_table_explorer
from .ui_assets import get_ui_assets
from .ui_config import (
    DEFAULT_LOGO_URL,
    DEFAULT_PAGE_TITLE,
    UISettings,
    get_ui_settings,
)

ViewKind = Literal["none", "plot", "table", "artifact", "stream"]


def _plotsrv_version() -> str:
    try:
        return distribution_version("plotsrv")
    except PackageNotFoundError:
        return "development"


def _escape_html(s: object) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_attr(s: object) -> str:
    return _escape_html(s).replace("\n", " ").replace("\r", " ")


def _safe_url_attr(s: object, *, default: str = "") -> str:
    raw = str(s or "").strip()
    if not raw:
        return default

    # Allow ordinary static/app paths, relative paths, and http(s) assets.
    # Block javascript: and other active schemes.
    low = raw.lower()
    if low.startswith(("javascript:", "data:text/html")):
        return default

    return _escape_attr(raw)


def render_index(
    *,
    kind: ViewKind,
    table_view_mode: TableViewMode,
    table_html_simple: str | None,
    max_table_rows_simple: int,
    max_table_rows_rich: int,
    ui_settings: UISettings | None = None,
    views: list[ViewMeta] | None = None,
    view_freshness: dict[str, dict[str, object]] | None = None,
    active_view_id: str | None = None,
    view_menu_revision: int = 0,
    browser_update_revision: int = 0,
) -> str:
    """
    Return the HTML for the main viewer page.
    """
    ui = ui_settings or get_ui_settings()
    assets = get_ui_assets()
    views = views or []
    active_view_id = active_view_id or "default"
    active_view_id_attr = _escape_attr(active_view_id)
    view_freshness = view_freshness or {}

    page_title = _escape_html(getattr(ui, "page_title", None) or "plotsrv - live view")
    favicon_url = _safe_url_attr(
        getattr(ui, "favicon_url", None) or "/static/plotsrv_favicon.png",
        default="/static/plotsrv_favicon.png",
    )

    tabulator_head = ""
    include_tabulator = kind in ("table", "artifact", "stream") and (
        table_view_mode != "simple" or kind in ("artifact", "stream")
    )

    if include_tabulator:
        tabulator_head = f'<script src="{assets.tabulator_js}" defer></script>'

    bottom_file_indicator_html = ""
    if ui.show_statusline:
        bottom_file_indicator_html = """
        <span
          id="status-file-backed"
          class="ps-bottom-bar__disk"
          title="File-backed watched view. Data preview is retrieved from the source file on disk."
          hidden>
          <img
            class="ps-bottom-bar__disk-icon"
            src="/static/logo_on_disk.png"
            alt="File-backed watched view" />
        </span>
        """

    def _terminate_button_html() -> str:
        if not ui.terminate_process_option:
            return ""
        return """
          <button
            type="button"
            class="ps-bottom-bar__terminate"
            onclick="terminateServer()"
            title="Terminate plotsrv server"
            aria-label="Terminate plotsrv server">Stop server</button>
        """

    def _history_controls_html() -> str:
        if not ui.show_history_controls:
            return ""
        return """
          <div id="snapshots-control" class="ps-snapshots" data-state="loading">
            <label id="snapshots-selector" class="ps-snapshots__selector" title="Checking snapshot availability.">
              <span>Snapshots</span>
              <select id="history-select" class="ps-select" aria-label="Snapshots" disabled>
                <option value="">Loading snapshots…</option>
              </select>
            </label>
            <span id="snapshots-info" class="ps-snapshots__info" role="img"
                  tabindex="0" aria-label="Checking snapshot availability."
                  title="Checking snapshot availability.">i</span>
            <button id="snapshots-return-latest" class="ps-snapshots__return" type="button" hidden>Return to latest</button>
          </div>
        """

    def _export_control_html(view_kind: ViewKind) -> str:
        enabled = (
            ui.export_table
            if view_kind == "table"
            else ui.export_image
            if view_kind == "plot"
            else True
        )
        if not enabled:
            return ""

        if view_kind in ("table", "stream") and (
            view_kind == "stream" or table_view_mode != "simple"
        ):
            if view_kind == "stream":
                scopes = (
                    ("filtered", "Current filtered view"),
                    ("retained", "Retained raw window"),
                )
            else:
                scopes = (
                    ("filtered", "Current filtered view"),
                    ("complete", "Complete published table"),
                )
            items = "".join(
                f'<button type="button" role="menuitem" data-export-scope="{scope}">'
                f"{label}</button>"
                for scope, label in scopes
            )
            return f"""
              <div id="export-control" class="ps-export" data-export-kind="{view_kind}">
                <button
                  id="export-button"
                  type="button"
                  class="ps-export__button"
                  aria-haspopup="menu"
                  aria-expanded="false"
                  aria-controls="export-menu">
                  Export <span aria-hidden="true">⌄</span>
                </button>
                <div id="export-menu" class="ps-export__menu" role="menu" hidden>
                  {items}
                  <div id="plot-export-items" class="ps-export__plot-items" role="group" aria-label="Plot export" hidden>
                    <button type="button" role="menuitem" data-export-scope="plot-svg" disabled>Plot as SVG</button>
                    <button type="button" role="menuitem" data-export-scope="plot-png" disabled>Plot as PNG</button>
                  </div>
                </div>
              </div>
            """

        action = {
            "table": "table-complete",
            "plot": "plot",
            "artifact": "artifact",
        }.get(view_kind, "none")
        disabled = " disabled" if action == "none" else ""
        title = (
            ' title="Nothing is available to export yet."'
            if action == "none"
            else ""
        )
        return f"""
          <div id="export-control" class="ps-export" data-export-kind="{view_kind}">
            <button
              id="export-button"
              type="button"
              class="ps-export__button"
              data-export-action="{action}"{disabled}{title}>Export</button>
          </div>
        """

    LOGO_BY_KEY = {
        "unknown": "/static/logo_unknown.png",
        "plot": "/static/logo_plot.png",
        "table": "/static/logo_table.png",
        "stream": "/static/logo_stream.png",
        "image": "/static/logo_image.png",
        "markdown": "/static/logo_markdown.png",
        "json": "/static/logo_json.png",
        "python": "/static/logo_python.png",
        "traceback": "/static/logo_exception.png",
        "exception": "/static/logo_exception.png",  # legacy alias
        "text": "/static/logo_txt.png",
        "html": "/static/logo_html.png",
    }

    def _icon_url(v: ViewMeta | None) -> str:
        if v is None:
            return LOGO_BY_KEY["unknown"]
        return LOGO_BY_KEY.get(
            getattr(v, "icon_key", "unknown"), LOGO_BY_KEY["unknown"]
        )

    def _freshness_class(v: ViewMeta) -> str:
        freshness = view_freshness.get(v.view_id)
        if not isinstance(freshness, dict):
            return ""

        if freshness.get("enabled") is False:
            return ""

        state = str(freshness.get("state") or "").strip().lower()

        if state in ("warn", "warning", "stale"):
            return " ps-viewselect__item--warn"

        if state in ("error", "overdue", "old"):
            return " ps-viewselect__item--error"

        return ""

    def _freshness_title(v: ViewMeta) -> str:
        freshness = view_freshness.get(v.view_id)
        if not isinstance(freshness, dict):
            return ""

        state_class = _freshness_class(v)
        if not state_class:
            return ""

        label = str(freshness.get("label") or "Not fresh")
        age_s = freshness.get("age_s")
        age = f" ({age_s}s old)" if isinstance(age_s, int | float) else ""

        return f' title="{_escape_attr(label + age)}"'

    def _view_type_label(v: ViewMeta) -> str:
        icon_key = str(getattr(v, "icon_key", "unknown") or "unknown")
        kind = str(getattr(v, "kind", "none") or "none")
        labels = {
            "plot": "Plot",
            "table": "Table",
            "stream": "Live stream",
            "image": "Image",
            "markdown": "Markdown",
            "json": "JSON",
            "python": "Python object",
            "traceback": "Traceback",
            "exception": "Exception",
            "text": "Text",
            "html": "HTML",
        }
        return labels.get(icon_key) or labels.get(kind) or "View"

    def _view_item_html(
        v: ViewMeta,
        *,
        include_section: bool = False,
        compact_title: str | None = None,
        compact: bool = False,
    ) -> str:
        view_id_attr = _escape_attr(v.view_id)
        icon = _safe_url_attr(_icon_url(v))
        label_html = _escape_html(compact_title or v.label)
        section = v.section or "default"
        type_label = _view_type_label(v)
        secondary = (
            f"{section} · {type_label}" if include_section else type_label
        )
        is_selected = v.view_id == active_view_id
        selected = "true" if is_selected else "false"
        current = ' aria-current="page"' if is_selected else ""
        freshness_class = _freshness_class(v)
        freshness_title = _freshness_title(v)
        entry_class = " ps-viewselect__entry--compact" if compact else ""
        item_class = " ps-viewselect__item--compact" if compact else ""
        icon_html = (
            ""
            if compact
            else f'<img class="ps-viewselect__itemicon" src="{icon}" alt="" />'
        )

        return f"""
          <div class="ps-viewselect__entry{entry_class}" role="listitem">
            <button type="button"
                    class="ps-viewselect__item{item_class}{freshness_class}"
                    data-selected="{selected}"{current}
                    data-plotsrv-view="{view_id_attr}"
                    data-view-section="{_escape_attr(section)}"
                    data-view-kind="{_escape_attr(v.kind)}"
                    data-view-icon="{_escape_attr(v.icon_key)}"{freshness_title}>
              <span class="ps-viewselect__freshness" data-plotsrv-view-freshness="{view_id_attr}" hidden aria-hidden="true"></span>
              {icon_html}
              <span class="ps-viewselect__itemcopy">
                <span class="ps-viewselect__itemlabel">{label_html}</span>
                <span class="ps-viewselect__itemmeta">{_escape_html(secondary)}</span>
              </span>
              <span class="ps-viewselect__check" aria-hidden="true">✓</span>
            </button>
            <button type="button" class="ps-viewselect__pin" data-pin-view="{view_id_attr}"
                    aria-pressed="false" aria-label="Pin {_escape_attr(v.label)}"
                    title="Pin {_escape_attr(v.label)}">☆</button>
          </div>
        """

    configured_featured = tuple(getattr(ui, "featured_views", ()))
    configured_compact = tuple(getattr(ui, "compact_views", ()))
    views_by_id = {v.view_id: v for v in views}
    valid_featured = [
        (feature, views_by_id[feature.view_id])
        for feature in configured_featured
        if feature.view_id in views_by_id
    ]
    compact_by_id = {
        item.view_id: item
        for item in configured_compact
        if item.view_id in views_by_id
    }

    def _featured_item_html(feature: object, view: ViewMeta) -> str:
        title = getattr(feature, "title", None) or view.label
        caption = getattr(feature, "caption", None)
        thumbnail = getattr(feature, "thumbnail_url", None)
        selected = "true" if view.view_id == active_view_id else "false"
        current = ' aria-current="page"' if view.view_id == active_view_id else ""
        freshness_class = _freshness_class(view)
        freshness_title = _freshness_title(view)
        if thumbnail:
            visual = (
                '<img class="ps-viewselect__feature-thumbnail" '
                f'src="{_safe_url_attr(thumbnail)}" alt="" loading="lazy" />'
            )
        else:
            visual = (
                '<span class="ps-viewselect__feature-fallback">'
                f'<img src="{_safe_url_attr(_icon_url(view))}" alt="" />'
                "</span>"
            )
        caption_html = (
            f'<span class="ps-viewselect__feature-caption">{_escape_html(caption)}</span>'
            if caption
            else ""
        )
        view_id_attr = _escape_attr(view.view_id)
        return f"""
          <div class="ps-viewselect__entry ps-viewselect__entry--feature" role="listitem">
            <button type="button"
                    class="ps-viewselect__feature{freshness_class}"
                    data-selected="{selected}"{current}
                    data-plotsrv-view="{view_id_attr}"{freshness_title}>
              {visual}
              <span class="ps-viewselect__feature-copy">
                <span class="ps-viewselect__feature-title">{_escape_html(title)}</span>
                {caption_html}
                <span class="ps-viewselect__feature-kind">{_escape_html(_view_type_label(view))}</span>
              </span>
              <span class="ps-viewselect__check" aria-hidden="true">✓</span>
            </button>
            <button type="button" class="ps-viewselect__pin" data-pin-view="{view_id_attr}"
                    aria-pressed="false" aria-label="Pin {_escape_attr(view.label)}"
                    title="Pin {_escape_attr(view.label)}">☆</button>
          </div>
        """

    dropdown_html = ""
    if getattr(ui, "show_view_selector", True) and len(views) > 0:
        groups: dict[str, list[ViewMeta]] = {}
        sections: list[str] = []
        for v in views:
            sec = v.section or "default"
            if sec not in groups:
                groups[sec] = []
                sections.append(sec)
            groups[sec].append(v)

        active_meta = None
        for v in views:
            if v.view_id == active_view_id:
                active_meta = v
                break
        active_label = _escape_html(
            active_meta.label if active_meta else active_view_id
        )
        active_icon = _safe_url_attr(_icon_url(active_meta))

        initial_mode = "grouped"
        menu_parts: list[str] = []
        featured_ids = {view.view_id for _, view in valid_featured}
        if valid_featured:
            menu_parts.extend(
                [
                    '<section class="ps-viewselect__group ps-viewselect__group--featured" aria-labelledby="view-selector-featured">',
                    '<h3 id="view-selector-featured" class="ps-viewselect__group-label">Featured</h3>',
                    '<div class="ps-viewselect__features" role="list">',
                    *(
                        _featured_item_html(feature, view)
                        for feature, view in valid_featured
                    ),
                    "</div></section>",
                ]
            )

        for index, sec in enumerate(sections):
            section_views = [v for v in groups[sec] if v.view_id not in featured_ids]
            if not section_views:
                continue
            heading_id = f"view-selector-group-{index}"
            menu_parts.append(
                f'<section class="ps-viewselect__group" aria-labelledby="{heading_id}">'
            )
            menu_parts.append(
                f'<h3 id="{heading_id}" class="ps-viewselect__group-label">{_escape_html(sec)}</h3>'
            )
            menu_parts.append('<div class="ps-viewselect__group-items" role="list">')
            menu_parts.extend(
                _view_item_html(
                    v,
                    compact=v.view_id in compact_by_id,
                    compact_title=(
                        compact_by_id[v.view_id].title
                        if v.view_id in compact_by_id
                        else None
                    ),
                )
                for v in section_views
            )
            menu_parts.append("</div></section>")

        tab_parts: list[str] = []
        modes = ["grouped", "az"]
        mode_labels = {"grouped": "Grouped", "az": "A–Z"}
        for mode in modes:
            selected = "true" if mode == initial_mode else "false"
            tab_parts.append(
                f'<button type="button" class="ps-viewselect__tab" role="tab" '
                f'aria-selected="{selected}" tabindex="{0 if mode == initial_mode else -1}" '
                f'aria-controls="view-selector-results" '
                f'data-view-mode="{mode}">{mode_labels[mode]}</button>'
            )

        dropdown_html = f"""
          <div class="ps-viewselect" data-plotsrv-viewselect="1">
            <button type="button"
                    class="ps-viewselect__btn"
                    aria-haspopup="dialog"
                    aria-controls="view-selector-menu"
                    aria-expanded="false"
                    aria-label="Choose view; current view is {active_label}">
              <img class="ps-viewselect__icon" src="{active_icon}" alt="" />
              <span class="ps-viewselect__label">{active_label}</span>
              <span class="ps-viewselect__chev" aria-hidden="true">⌄</span>
            </button>

            <div id="view-selector-menu" class="ps-viewselect__menu" role="dialog" aria-label="Browse views" hidden>
              <div class="ps-viewselect__tools">
                <label class="ps-viewselect__search-wrap">
                  <span class="ps-viewselect__search-icon" aria-hidden="true">⌕</span>
                  <input class="ps-viewselect__search" type="search" autocomplete="off"
                         aria-label="Search views" placeholder="Search views…" />
                </label>
                <div class="ps-viewselect__tabs" role="tablist" aria-label="View browse mode">
                  {''.join(tab_parts)}
                </div>
              </div>
              <div id="view-selector-results" class="ps-viewselect__results" role="region" aria-label="Views" aria-live="polite">
                {''.join(menu_parts)}
              </div>
            </div>
          </div>
        """

    def _footer_html(view_kind: ViewKind) -> str:
        return f"""
          <div class="ps-bottom-dock" role="region" aria-label="View actions and status">
            <div class="ps-bottom-alerts" aria-live="polite">
              <div class="note ps-note" id="status"></div>
              <div id="status-error-wrap" class="ps-bottom-alert ps-bottom-alert--error" hidden>
                <strong>Error:</strong> <span id="status-error"></span>
              </div>
            </div>
            <div class="ps-bottom-bar">
              <div class="ps-bottom-bar__controls">
                {_export_control_html(view_kind)}
                {_history_controls_html()}
                {bottom_file_indicator_html}
                {_terminate_button_html()}
              </div>
            </div>
          </div>
        """

    content_html = ""
    footer_html = ""

    if kind == "table":
        if table_view_mode == "simple" and table_html_simple is not None:
            content_html = f"""
              <div class="ps-table-simple-view">
                <p class="ps-table-simple-view__notice">
                  Simple table mode is read-only. Interactive search, filters,
                  grouping, column controls, and plotting are available in rich table mode.
                </p>
                <div class="plot-frame ps-frame ps-frame--table plot-frame--table">
                  <div class="table-scroll ps-table-scroll ps-table--simple">
                    {table_html_simple}
                  </div>
                </div>
              </div>
            """
        else:
            content_html = render_table_explorer(
                grid_html=(
                    '<div id="table-grid" '
                    'class="table-grid ps-tablegrid ps-table--rich"></div>'
                ),
                search_placeholder="Search loaded rows…",
            )

        footer_html = _footer_html(kind)

    elif kind == "stream":
        stream_controls_html = f"""
          <section class="ps-stream-controls" aria-labelledby="stream-controls-title">
            <div class="ps-stream-controls__identity">
              <h2 id="stream-controls-title">Stream controls</h2>
            </div>

            <div id="stream-controls-content" class="ps-stream-controls__content">
              <div id="stream-history-picker" class="ps-stream-session">
                <span id="stream-session-label" class="ps-table-toolbar__label">Run</span>
                <div class="ps-stream-session__control">
                  <select
                    id="stream-history-session-select"
                    class="ps-table-select"
                    aria-labelledby="stream-session-label"
                    aria-label="Run. Checking stored-run availability."
                    disabled>
                    <option value="">Current run</option>
                  </select>
                </div>
                <span id="stream-history-picker-status" class="ps-visually-hidden" aria-live="polite">
                  Checking stored-run availability.
                </span>
              </div>

              <div class="ps-stream-controls__actions">
                <button
                  id="stream-pause-button"
                  class="ps-btn ps-stream-pause-button"
                  type="button"
                  aria-pressed="false"
                  aria-label="Pause stream"
                  title="Pause stream"
                  disabled>
                  <span class="ps-stream-pause-button__icon" aria-hidden="true">Ⅱ</span>
                  <span id="stream-pause-label">Pause stream</span>
                </button>

                <button
                  id="stream-insights-button"
                  class="ps-btn ps-stream-insights-button"
                  type="button"
                  aria-haspopup="dialog"
                  aria-controls="stream-insights-drawer"
                  aria-expanded="false">
                  <span aria-hidden="true">▥</span>
                  <span>Insights</span>
                  <span aria-hidden="true">›</span>
                </button>
              </div>
            </div>

            <button
              id="stream-controls-toggle"
              class="ps-pane-disclosure"
              type="button"
              aria-expanded="true"
              aria-controls="stream-controls-content"
              aria-label="Collapse Stream controls"
              title="Collapse Stream controls">−</button>
          </section>
        """
        content_html = f"""
          <div class="ps-stream-shell">
            {render_table_explorer(
                grid_html=(
                    '<p id="stream-raw-history-notice" '
                    'class="ps-stream-raw-history-notice" role="status" hidden></p>'
                    '<div id="stream-grid" '
                    'class="table-grid ps-tablegrid ps-table--rich ps-stream-grid"></div>'
                ),
                search_placeholder="Search retained rows…",
                leading_html=stream_controls_html,
            )}

            <aside
              id="stream-insights-drawer"
              class="ps-stream-insights"
              role="dialog"
              aria-modal="false"
              aria-labelledby="stream-insights-title"
              hidden>
              <header class="ps-stream-insights__header">
                <div>
                  <h2 id="stream-insights-title">Stream insights</h2>
                  <p>Context for the current stream observation.</p>
                </div>
                <button
                  id="stream-insights-close"
                  class="ps-stream-insights__close"
                  type="button"
                  aria-label="Close stream insights">×</button>
              </header>

              <div class="ps-stream-insights__status">
                <p id="stream-status-inline" class="ps-stream-status" aria-live="polite">
                  Waiting for appended JSON objects.
                </p>
                <p id="stream-health-inline" class="ps-stream-health" aria-live="polite"></p>
              </div>

              <div class="ps-stream-insights__tabs" role="tablist" aria-label="Stream insight sections">
                <button
                  id="stream-insights-tab-since"
                  type="button"
                  role="tab"
                  aria-selected="true"
                  aria-controls="stream-insights-panel-since"
                  tabindex="0"
                  data-stream-insights-tab="since">Since last visit</button>
                <button
                  id="stream-insights-tab-noteworthy"
                  type="button"
                  role="tab"
                  aria-selected="false"
                  aria-controls="stream-insights-panel-noteworthy"
                  tabindex="-1"
                  data-stream-insights-tab="noteworthy">Noteworthy</button>
                <button
                  id="stream-insights-tab-history"
                  type="button"
                  role="tab"
                  aria-selected="false"
                  aria-controls="stream-insights-panel-history"
                  tabindex="-1"
                  data-stream-insights-tab="history">History</button>
              </div>

              <div class="ps-stream-insights__body">
                <section
                  id="stream-insights-panel-since"
                  class="ps-stream-insights__panel ps-stream-returning"
                  role="tabpanel"
                  aria-labelledby="stream-insights-tab-since"
                  data-returning-kind="since-last-visit"
                  data-stream-insights-panel="since">
                  <div class="ps-stream-returning__header">
                    <div>
                      <h3 id="stream-since-visit-title" class="ps-stream-returning__title">Since last visit</h3>
                      <p class="ps-stream-returning__notice">
                        A simple comparison with this browser’s previous compatible visit.
                      </p>
                    </div>
                    <p id="stream-since-visit-status" class="ps-stream-returning__status" aria-live="polite">
                      Waiting for current stream state.
                    </p>
                  </div>
                  <div id="stream-since-visit-details" class="ps-stream-returning__details"></div>
                </section>

                <section
                  id="stream-insights-panel-noteworthy"
                  class="ps-stream-insights__panel ps-stream-noteworthy"
                  role="tabpanel"
                  aria-labelledby="stream-insights-tab-noteworthy"
                  data-noteworthy-kind="stream-noteworthy"
                  data-stream-insights-panel="noteworthy"
                  hidden>
                  <div class="ps-stream-noteworthy__header">
                    <div>
                      <h3 id="stream-noteworthy-title" class="ps-stream-noteworthy__title">Noteworthy</h3>
                      <p class="ps-stream-noteworthy__notice">
                        A bounded recent selection of deterministic observations, not a complete event history.
                      </p>
                    </div>
                    <p id="stream-noteworthy-status" class="ps-stream-noteworthy__status" aria-live="polite">
                      Loading noteworthy activity…
                    </p>
                  </div>
                  <div id="stream-noteworthy-items" class="ps-stream-noteworthy__items"></div>
                </section>

                <section
                  id="stream-insights-panel-history"
                  class="ps-stream-insights__panel ps-stream-summary"
                  role="tabpanel"
                  aria-labelledby="stream-insights-tab-history"
                  data-summary-kind="derived-stream-history"
                  data-stream-insights-panel="history"
                  hidden>
                  <div class="ps-stream-summary__header">
                    <div>
                      <h3 id="stream-summary-title" class="ps-stream-summary__title">History</h3>
                      <p class="ps-stream-summary__notice">
                        Older observations may be summarised as they leave the recent-data window. These summaries are not original rows and do not use the table’s filters.
                      </p>
                    </div>
                    <p id="stream-summary-status" class="ps-stream-summary__status" aria-live="polite">
                      Loading history…
                    </p>
                  </div>
                  <div id="stream-summary-windows" class="ps-stream-summary__windows"></div>
                </section>
              </div>
            </aside>
          </div>
        """
        footer_html = _footer_html(kind)

    elif kind == "plot":
        content_html = f"""
          <div class="plot-frame ps-frame ps-frame--plot plot-frame--plot">
            <img id="plot" class="ps-plot" src="/plot?view={active_view_id_attr}" alt="Current plot (or none yet)" />
          </div>
        """
        footer_html = _footer_html(kind)

    elif kind == "artifact":
        content_html = """
          <div class="plot-frame ps-frame ps-frame--artifact plot-frame--artifact">
            <div class="ps-artifact">
              <div id="artifact-topline" class="ps-artifact__meta">
                <span id="artifact-kind" class="note ps-note"></span>
                <span id="artifact-truncation" class="note ps-note"></span>
              </div>
              <div id="artifact-root" class="ps-artifact__content"></div>
            </div>
          </div>
        """
        footer_html = _footer_html(kind)

    else:
        content_html = """
          <div class="plot-frame empty ps-frame ps-frame--empty plot-frame--empty">
            <div class="empty-state ps-empty">
              Waiting for content.<br />
              plotsrv is running and ready to receive Python outputs or watched file updates.
            </div>
          </div>
        """
        footer_html = _footer_html(kind)

    header_fill = _escape_attr(ui.header_fill_colour or "#ffffff")
    header_text = _escape_html(ui.header_text or "")
    logo_url = _safe_url_attr(
        ui.logo_url or "/static/plotsrv_icon_title_colour_swash_logo.png"
    )
    header_status_html = ""
    status_modal_html = ""
    if ui.show_freshness or ui.show_history_banner:
        status_summary_modifier = (
            " ps-status-modal__summary--stream"
            if kind == "stream"
            else " ps-status-modal__summary--regular"
        )
        status_browser_fact_html = (
            """
                  <div class="ps-status-fact">
                    <span id="status-modal-browser-label" class="ps-status-fact__label">Browser stream</span>
                    <strong id="status-modal-browser">Loading</strong>
                    <span id="status-modal-browser-detail">Checking browser state.</span>
                  </div>
            """
            if kind == "stream"
            else ""
        )
        header_status_html = """
          <div id="header-status" class="ps-header-status">
            <button
              id="header-status-button"
              type="button"
              class="ps-header-status__button"
              aria-haspopup="dialog"
              aria-expanded="false"
              aria-controls="status-modal">
              <span id="header-status-dot" class="ps-header-status__dot" aria-hidden="true"></span>
              <span id="header-status-label" class="ps-header-status__label">Latest</span>
              <span id="header-status-context" class="ps-header-status__context">Checking status…</span>
              <span class="ps-header-status__chevron" aria-hidden="true">⌄</span>
            </button>
          </div>
        """
        status_modal_html = f"""
          <div id="status-modal-backdrop" class="ps-status-modal-backdrop" hidden>
            <section
              id="status-modal"
              class="ps-status-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="status-modal-title"
              aria-describedby="status-modal-intro"
              tabindex="-1">
              <header class="ps-status-modal__header">
                <div>
                  <h2 id="status-modal-title">Live data status</h2>
                  <p id="status-modal-intro">What plotsrv and this browser currently know about this view.</p>
                </div>
                <button
                  id="status-modal-close-icon"
                  class="ps-status-modal__close-icon"
                  type="button"
                  aria-label="Close live data status">×</button>
              </header>

              <div class="ps-status-modal__body">
                <section class="ps-status-modal__summary{status_summary_modifier}" aria-label="Current status summary">
                  <div class="ps-status-fact">
                    <span id="status-modal-viewing-label" class="ps-status-fact__label">Viewing</span>
                    <strong id="status-modal-viewing">Latest data</strong>
                    <span id="status-modal-viewing-detail">This view follows live updates.</span>
                  </div>
                  <div class="ps-status-fact">
                    <span id="status-modal-received-label" class="ps-status-fact__label">Last data received</span>
                    <strong id="status-modal-received">Not yet</strong>
                    <span id="status-modal-received-detail">No process-lifetime arrival recorded.</span>
                  </div>
                  {status_browser_fact_html}
                  <div class="ps-status-fact ps-status-fact--freshness">
                    <span id="status-modal-freshness-label" class="ps-status-fact__label">Freshness</span>
                    <strong id="status-modal-freshness">Checking</strong>
                    <span id="status-modal-freshness-detail">Checking freshness policy.</span>
                  </div>
                </section>

                <section id="status-modal-policy" class="ps-status-modal__policy" aria-labelledby="status-modal-policy-title">
                  <div>
                    <h3 id="status-modal-policy-title">Freshness policy</h3>
                    <p id="status-modal-policy-copy">Freshness thresholds are loading.</p>
                  </div>
                  <dl id="status-modal-policy-values" class="ps-status-policy-values"></dl>
                </section>

                <section id="status-modal-stream" class="ps-status-modal__stream" aria-labelledby="status-modal-stream-title" hidden>
                  <h3 id="status-modal-stream-title">Stream observation</h3>
                  <div class="ps-status-modal__stream-grid">
                    <p><span>Producer lifecycle</span><strong id="status-modal-stream-lifecycle">Unknown</strong></p>
                    <p><span>Last heartbeat</span><strong id="status-modal-stream-heartbeat">Unknown</strong></p>
                    <p><span>Source continuity</span><strong id="status-modal-stream-continuity">Unknown</strong></p>
                  </div>
                  <p id="status-modal-stream-caveat" class="ps-status-modal__caveat">This describes the producer connection observed by plotsrv, not the application’s full state.</p>
                </section>

                <section class="ps-status-modal__activity" aria-labelledby="status-modal-activity-title">
                  <div class="ps-status-modal__activity-header">
                    <div>
                      <h3 id="status-modal-activity-title">Data received over time</h3>
                      <p id="status-modal-activity-copy">Each dot represents a published update.</p>
                    </div>
                    <label class="ps-status-range">
                      <span>Time range</span>
                      <select id="status-modal-range">
                        <option value="auto">Auto</option>
                        <option value="900">Last 15 minutes</option>
                        <option value="3600">Last hour</option>
                        <option value="21600">Last 6 hours</option>
                        <option value="86400">Last 24 hours</option>
                        <option value="604800">Last 7 days</option>
                        <option value="all">All retained activity</option>
                      </select>
                    </label>
                  </div>
                  <div class="ps-arrival-chart" role="group" aria-labelledby="status-modal-activity-title status-modal-activity-description">
                    <div id="status-modal-activity-dots" class="ps-arrival-chart__track"></div>
                    <div class="ps-arrival-chart__axis">
                      <span id="status-modal-range-start">—</span>
                      <span id="status-modal-range-end">Now</span>
                    </div>
                  </div>
                  <p id="status-modal-activity-hover" class="ps-arrival-chart__detail" aria-live="polite" hidden></p>
                  <p id="status-modal-activity-empty" class="ps-arrival-chart__empty" hidden>No arrivals in this range.</p>
                  <p id="status-modal-activity-description" class="ps-status-modal__caveat">Activity is bounded to this plotsrv process lifetime and does not survive restart.</p>
                </section>

                <details class="ps-status-modal__technical">
                  <summary>Technical details</summary>
                  <dl>
                    <div><dt>View ID</dt><dd id="status-modal-view-id">—</dd></div>
                    <div><dt>Data source</dt><dd id="status-modal-source">—</dd></div>
                    <div><dt>Browser applied</dt><dd id="status-modal-applied">Not known</dd></div>
                    <div><dt>Activity retained</dt><dd id="status-modal-retained">0 events</dd></div>
                  </dl>
                </details>
              </div>

              <footer class="ps-status-modal__footer">
                <button id="status-modal-return-latest" type="button" class="ps-btn" hidden>Return to latest</button>
                <button id="status-modal-update-now" type="button" class="ps-btn ps-btn--primary" hidden>Update now</button>
                <button id="status-modal-close" type="button" class="ps-btn">Close</button>
              </footer>
            </section>
          </div>
        """

    plotsrv_version = _escape_html(_plotsrv_version())
    dashboard_header_text = str(getattr(ui, "header_text", "") or "").strip()
    dashboard_page_title = str(getattr(ui, "page_title", "") or "").strip()
    dashboard_name = dashboard_header_text or (
        dashboard_page_title
        if dashboard_page_title and dashboard_page_title != DEFAULT_PAGE_TITLE
        else "This dashboard"
    )
    dashboard_title_detail = ""
    if (
        dashboard_page_title
        and dashboard_page_title != DEFAULT_PAGE_TITLE
        and dashboard_page_title != dashboard_name
    ):
        dashboard_title_detail = (
            '<p class="ps-settings-about__detail">'
            '<span>Browser title</span>'
            f"{_escape_html(dashboard_page_title)}"
            "</p>"
        )

    dashboard_logo_html = ""
    configured_dashboard_logo = str(getattr(ui, "logo_url", "") or "").strip()
    if configured_dashboard_logo and configured_dashboard_logo != DEFAULT_LOGO_URL:
        safe_dashboard_logo = _safe_url_attr(configured_dashboard_logo)
        if safe_dashboard_logo:
            dashboard_logo_html = (
                '<img class="ps-settings-about__dashboard-logo" '
                f'src="{safe_dashboard_logo}" alt="" loading="lazy" />'
            )

    settings_html = f"""
      <section
        id="settings-page"
        class="ps-settings-page"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        aria-describedby="settings-intro"
        tabindex="-1"
        hidden>
        <header class="ps-settings-page__header">
          <div>
            <p class="ps-settings-page__eyebrow">plotsrv</p>
            <h1 id="settings-title">Settings</h1>
            <p id="settings-intro">Personalise how this dashboard appears in your browser.</p>
          </div>
          <button
            id="settings-close"
            class="ps-settings-page__close"
            type="button"
            aria-label="Close settings">×</button>
        </header>

        <main class="ps-settings-page__body">
          <section class="ps-settings-section" aria-labelledby="settings-appearance-title">
            <div class="ps-settings-section__intro">
              <h2 id="settings-appearance-title">Appearance</h2>
              <p>Choose a colour theme for the plotsrv interface in this browser.</p>
            </div>
            <div class="ps-theme-options" role="group" aria-label="Colour theme">
              <button type="button" class="ps-theme-option" data-theme-option="light" aria-pressed="true">
                <span class="ps-theme-preview ps-theme-preview--light" aria-hidden="true">
                  <span class="ps-theme-preview__bar"></span>
                  <span class="ps-theme-preview__panel"></span>
                  <span class="ps-theme-preview__lines"></span>
                </span>
                <span class="ps-theme-option__copy">
                  <strong>Light</strong>
                  <span>Bright, neutral surfaces</span>
                </span>
                <span class="ps-theme-option__check" aria-hidden="true">✓</span>
              </button>
              <button type="button" class="ps-theme-option" data-theme-option="dark" aria-pressed="false">
                <span class="ps-theme-preview ps-theme-preview--dark" aria-hidden="true">
                  <span class="ps-theme-preview__bar"></span>
                  <span class="ps-theme-preview__panel"></span>
                  <span class="ps-theme-preview__lines"></span>
                </span>
                <span class="ps-theme-option__copy">
                  <strong>Dark</strong>
                  <span>Low-light, high-contrast surfaces</span>
                </span>
                <span class="ps-theme-option__check" aria-hidden="true">✓</span>
              </button>
              <button type="button" class="ps-theme-option" data-theme-option="system" aria-pressed="false">
                <span class="ps-theme-preview ps-theme-preview--system" aria-hidden="true">
                  <span class="ps-theme-preview__bar"></span>
                  <span class="ps-theme-preview__panel"></span>
                  <span class="ps-theme-preview__lines"></span>
                </span>
                <span class="ps-theme-option__copy">
                  <strong>System</strong>
                  <span>Follow this device’s appearance</span>
                </span>
                <span class="ps-theme-option__check" aria-hidden="true">✓</span>
              </button>
            </div>
            <p class="ps-settings-section__note">
              Themes change plotsrv controls and readable text surfaces. Plot pixels,
              images, and embedded HTML reports keep their original colours.
            </p>
          </section>

          <section class="ps-settings-section" aria-labelledby="settings-about-title">
            <div class="ps-settings-section__intro">
              <h2 id="settings-about-title">About this dashboard</h2>
              <p>Dashboard identity and the software serving it.</p>
            </div>
            <div class="ps-settings-about">
              <div class="ps-settings-about__card ps-settings-about__identity">
                {dashboard_logo_html}
                <div class="ps-settings-about__copy">
                  <span class="ps-settings-about__label">Dashboard</span>
                  <h3>{_escape_html(dashboard_name)}</h3>
                  {dashboard_title_detail}
                </div>
              </div>

              <div class="ps-settings-about__card ps-settings-about__product">
                <img
                  class="ps-settings-about__plotsrv-logo"
                  src="/static/plotsrv_icon_logo.png"
                  width="64"
                  height="64"
                  alt=""
                  loading="lazy" />
                <div class="ps-settings-about__copy">
                  <p class="ps-settings-about__powered">Powered by <strong>PlotSrv</strong></p>
                  <div class="ps-settings-about__product-meta">
                    <span>Version <code>{plotsrv_version}</code></span>
                    <a href="https://docs.plotsrv.com/" target="_blank" rel="noopener noreferrer">
                      Documentation
                      <span aria-hidden="true">↗</span>
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </main>
      </section>
    """

    view_catalogue = [
        {
            "view_id": v.view_id,
            "section": v.section or "default",
            "label": v.label,
            "kind": v.kind,
            "icon_key": v.icon_key,
            "freshness": view_freshness.get(v.view_id),
        }
        for v in views
    ]
    featured_config = [
        {
            "view_id": feature.view_id,
            "title": feature.title,
            "caption": feature.caption,
            "thumbnail_url": feature.thumbnail_url,
        }
        for feature in configured_featured
    ]
    compact_config = [
        {
            "view_id": item.view_id,
            "title": item.title,
        }
        for item in configured_compact
    ]
    cfg_json = json.dumps(
        {
            "active_view_id": active_view_id,
            "kind": kind,
            "table_view_mode": table_view_mode,
            "max_table_rows_simple": max_table_rows_simple,
            "max_table_rows_rich": max_table_rows_rich,
            "view_menu_revision": view_menu_revision,
            "browser_update_revision": browser_update_revision,
            # These settings independently control the two modes of the shared
            # header status. The legacy statusline setting now only gates the
            # small file-backed source indicator in the bottom controls.
            "show_header_freshness": ui.show_freshness,
            "show_header_history": ui.show_history_banner,
            "view_catalogue": view_catalogue,
            "featured_views": featured_config,
            "compact_views": compact_config,
        },
        ensure_ascii=False,
    )
    # JSON sits in an inline script. Encode HTML-significant characters so a
    # view label or configured caption cannot terminate that element.
    cfg_json = (
        cfg_json.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>{page_title}</title>
      <link rel="icon" href="{favicon_url}">
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <script>
        (function () {{
          var theme = "light";
          try {{
            var stored = localStorage.getItem("plotsrv:v1:theme");
            if (stored === "light" || stored === "dark" || stored === "system") {{
              theme = stored;
            }}
          }} catch (error) {{
            theme = "light";
          }}
          document.documentElement.setAttribute("data-theme", theme);
          document.documentElement.style.colorScheme =
            theme === "system" ? "light dark" : theme;
        }})();
      </script>
      <link rel="stylesheet" href="{assets.css}">
      <script>
        window.PLOTSRV_CONFIG = {cfg_json};
      </script>
      {tabulator_head}
      <script src="{assets.js}" defer></script>
    </head>
    <body class="ps-body"
          data-kind="{kind}"
          data-view="{active_view_id_attr}"
          data-table-mode="{table_view_mode}">
      <header id="site-header" class="header ps-header" style="--ps-configured-header-fill:{header_fill};">
        <div class="header-left ps-header__left">
          <img src="{logo_url}" alt="plotsrv logo" class="header-logo ps-header__logo" />
          <div class="header-title ps-header__title">{header_text}</div>
        </div>

        <div class="header-right ps-header__right">
          <button
            id="settings-button"
            class="ps-settings-trigger"
            type="button"
            aria-label="Open settings"
            aria-haspopup="dialog"
            aria-controls="settings-page"
            aria-expanded="false">
            <img src="/static/settings-cog.png" alt="" aria-hidden="true" />
          </button>
          {header_status_html}
          {dropdown_html}
        </div>
      </header>

      <main class="page ps-page">
        <section class="plot-card ps-card">
          {content_html}
        </section>
      </main>
      {settings_html}
      {status_modal_html}
      {footer_html}

    </body>
    </html>
    """
    return html
