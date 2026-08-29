# src/plotsrv/html.py
from __future__ import annotations

from typing import Literal
import json

from .config import TableViewMode
from .store import ViewMeta
from .ui_assets import get_ui_assets
from .ui_config import UISettings, get_ui_settings

ViewKind = Literal["none", "plot", "table", "artifact", "stream"]


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

    bottom_meta_html = ""
    if ui.show_statusline:
        bottom_meta_html = """
        <div class="ps-bottom-bar__meta">
          <span class="ps-bottom-bar__updated">
            Last updated: <span id="status-updated">—</span>
            <span id="status-updated-ago"></span>
          </span>
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
        </div>
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
            <label id="snapshots-selector" class="ps-snapshots__selector">
              <span>Snapshots</span>
              <select id="history-select" class="ps-select" aria-label="Snapshots">
                <option value="">Loading snapshots…</option>
              </select>
            </label>
            <div id="snapshots-unavailable" class="ps-snapshots__unavailable" hidden>
              <strong>Snapshots unavailable</strong>
              <span id="snapshots-unavailable-reason">Checking snapshot storage.</span>
              <button id="snapshots-return-latest" type="button" hidden>Return to latest</button>
            </div>
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

        menu_parts: list[str] = []
        for sec in sections:
            menu_parts.append('<div class="ps-viewselect__group">')
            menu_parts.append(
                f'<div class="ps-viewselect__group-label">{_escape_html(sec)}</div>'
            )
            menu_parts.append('<div class="ps-viewselect__group-items">')

            for v in groups[sec]:
                view_id_attr = _escape_attr(v.view_id)
                icon = _safe_url_attr(_icon_url(v))
                label_html = _escape_html(v.label)

                is_sel = "true" if v.view_id == active_view_id else "false"
                freshness_class = _freshness_class(v)
                freshness_title = _freshness_title(v)

                menu_parts.append(f"""
                    <button type="button"
                            class="ps-viewselect__item{freshness_class}"
                            role="option"
                            aria-selected="{is_sel}"
                            data-plotsrv-view="{view_id_attr}"{freshness_title}>
                      <span class="ps-viewselect__freshness" data-plotsrv-view-freshness="{view_id_attr}" hidden aria-hidden="true"></span>
                      <img class="ps-viewselect__itemicon" src="{icon}" alt="" />
                      <span class="ps-viewselect__itemlabel">{label_html}</span>
                    </button>
                    """)

            menu_parts.append("</div>")

        dropdown_html = f"""
          <div class="ps-viewselect" data-plotsrv-viewselect="1">
            <button type="button"
                    class="ps-viewselect__btn"
                    aria-haspopup="listbox"
                    aria-expanded="false">
              <img class="ps-viewselect__icon" src="{active_icon}" alt="" />
              <span class="ps-viewselect__label">{active_label}</span>
              <span class="ps-viewselect__chev" aria-hidden="true">▾</span>
            </button>

            <div class="ps-viewselect__menu" role="listbox" tabindex="-1" hidden>
              {''.join(menu_parts)}
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
                {_terminate_button_html()}
              </div>
              {bottom_meta_html}
            </div>
          </div>
        """

    content_html = ""
    footer_html = ""

    if kind == "table":
        table_plot_controls_html = (
            """
            <div class="ps-table-mode-switch" role="group" aria-label="Table display mode">
              <button
                id="table-mode-table-btn"
                type="button"
                class="ps-btn is-active"
                aria-pressed="true">
                Table
              </button>
              <button
                id="table-mode-plot-btn"
                type="button"
                class="ps-btn"
                aria-pressed="false">
                Plot
              </button>
            </div>
            """
            if table_view_mode != "simple" or table_html_simple is None
            else ""
        )

        table_plot_panel_html = (
            """
            <section
              id="table-plot-controls"
              class="ps-table-plot-controls"
              aria-label="Plot controls"
              hidden>
              <div class="ps-table-plot-controls__fields">
                <label class="ps-table-plot-control">
                  <span>Plot type</span>
                  <select id="table-plot-type" class="ps-table-select">
                    <option value="bar">Count bar</option>
                    <option value="line">Line</option>
                    <option value="scatter">Scatter</option>
                  </select>
                </label>
                <label id="table-plot-source-control" class="ps-table-plot-control" hidden>
                  <span>Stream source</span>
                  <select id="table-plot-source" class="ps-table-select">
                    <option value="table">Filtered recent rows</option>
                    <option value="summary">Derived summary windows</option>
                  </select>
                </label>
                <label id="table-plot-category-control" class="ps-table-plot-control">
                  <span>Category</span>
                  <select id="table-plot-category" class="ps-table-select"></select>
                </label>
                <label id="table-plot-x-control" class="ps-table-plot-control" hidden>
                  <span>X field</span>
                  <select id="table-plot-x" class="ps-table-select"></select>
                </label>
                <label id="table-plot-y-control" class="ps-table-plot-control" hidden>
                  <span>Y field</span>
                  <select id="table-plot-y" class="ps-table-select"></select>
                </label>
              </div>
              <p id="table-plot-controls-scope" class="ps-table-plot-controls__scope">
                Plots use only loaded rows that pass the current browser filters.
              </p>
            </section>
            """
            if table_plot_controls_html
            else ""
        )

        table_shell_open = f"""
          <div class="ps-table-shell">
            <div class="ps-table-topbar">
              <div class="ps-table-topbar__left">
                <p id="table-status-inline" class="ps-table-status"></p>
              </div>
              <div class="ps-table-topbar__right">
                <div class="ps-table-toolbar">
                  <label class="ps-table-toolbar__search">
                    <span class="ps-table-toolbar__label">Search</span>
                    <input
                      id="table-search-input"
                      class="ps-table-input"
                      type="text"
                      placeholder="Search loaded rows…"
                      autocomplete="off"
                    />
                  </label>

                  <label class="ps-table-toolbar__grouping">
                    <span class="ps-table-toolbar__label">Group</span>
                    <select id="table-group-by-select" class="ps-table-select">
                      <option value="">No grouping</option>
                    </select>
                  </label>

                  {table_plot_controls_html}

                  <button
                    id="table-filters-toggle-btn"
                    type="button"
                    class="ps-btn"
                    aria-expanded="false"
                    aria-controls="table-filter-panel">
                    Filters
                  </button>

                  <button
                    id="table-columns-toggle-btn"
                    type="button"
                    class="ps-btn"
                    aria-expanded="false"
                    aria-controls="table-columns-panel">
                    Columns
                  </button>

                  <button
                    id="table-reset-btn"
                    type="button"
                    class="ps-btn">
                    Reset view
                  </button>
                </div>
              </div>
            </div>

            <div id="table-filter-panel" class="ps-table-filter-panel" hidden>
              <div class="ps-table-filter-panel__header">
                <div class="ps-table-filter-panel__title">Filters</div>
                <button
                  id="table-filter-add-btn"
                  type="button"
                  class="ps-btn">
                  Add filter
                </button>
              </div>

              <div id="table-filter-rows" class="ps-table-filter-rows"></div>
            </div>

            <div id="table-columns-panel" class="ps-table-columns-panel" hidden>
              <div class="ps-table-columns-panel__header">
                <div class="ps-table-columns-panel__title">Columns</div>
                <div class="ps-table-columns-panel__actions">
                  <button
                    id="table-columns-show-all-btn"
                    type="button"
                    class="ps-btn">
                    Show all
                  </button>
                </div>
              </div>

              <div id="table-columns-list" class="ps-table-columns-list"></div>
            </div>

            <div id="table-active-filters" class="ps-table-active-filters" hidden></div>

            {table_plot_panel_html}
        """

        table_shell_close = "</div>"

        if table_view_mode == "simple" and table_html_simple is not None:
            content_html = f"""
              {table_shell_open}
              <div class="plot-frame ps-frame ps-frame--table plot-frame--table">
                <div class="table-scroll ps-table-scroll ps-table--simple">
                  {table_html_simple}
                </div>
              </div>
              {table_shell_close}
            """
        else:
            content_html = f"""
              {table_shell_open}
              <div id="table-data-surface" class="plot-frame ps-frame ps-frame--table plot-frame--table">
                <div id="table-grid" class="table-grid ps-tablegrid ps-table--rich"></div>
              </div>
              <div id="table-plot-output" class="ps-table-plot-root" aria-live="polite" hidden></div>
              {table_shell_close}
            """

        footer_html = _footer_html(kind)

    elif kind == "stream":
        content_html = """
          <div class="ps-stream-shell">
            <div class="ps-stream-topbar">
              <span id="stream-lifecycle-badge" class="ps-stream-badge ps-stream-badge--live">LIVE OBSERVATION</span>
              <p id="stream-status-inline" class="ps-stream-status" aria-live="polite">
                Waiting for appended JSON objects.
              </p>
              <p id="stream-health-inline" class="ps-stream-health" aria-live="polite"></p>
            </div>

            <section
              id="stream-history-picker"
              class="ps-stream-history-picker"
              aria-labelledby="stream-history-picker-title"
              hidden>
              <div>
                <h2 id="stream-history-picker-title" class="ps-stream-history-picker__title">Stored sessions</h2>
                <p id="stream-history-picker-status" class="ps-stream-history-picker__notice">
                  Select a stored session to inspect bounded historical observations.
                </p>
              </div>
              <label class="ps-stream-history-picker__control">
                <span>Session</span>
                <select id="stream-history-session-select"></select>
              </label>
            </section>

            <div class="ps-table-shell">
              <div class="ps-table-topbar">
                <div class="ps-table-topbar__left">
                  <p id="table-status-inline" class="ps-table-status"></p>
                </div>
                <div class="ps-table-topbar__right">
                  <div class="ps-table-toolbar">
                    <label class="ps-table-toolbar__search">
                      <span class="ps-table-toolbar__label">Search</span>
                      <input
                        id="table-search-input"
                        class="ps-table-input"
                        type="text"
                        placeholder="Search retained rows…"
                        autocomplete="off"
                      />
                    </label>

                    <label class="ps-table-toolbar__grouping">
                      <span class="ps-table-toolbar__label">Group</span>
                      <select id="table-group-by-select" class="ps-table-select">
                        <option value="">No grouping</option>
                      </select>
                    </label>

                    <div class="ps-table-mode-switch" role="group" aria-label="Table display mode">
                      <button
                        id="table-mode-table-btn"
                        type="button"
                        class="ps-btn is-active"
                        aria-pressed="true">
                        Table
                      </button>
                      <button
                        id="table-mode-plot-btn"
                        type="button"
                        class="ps-btn"
                        aria-pressed="false">
                        Plot
                      </button>
                    </div>

                    <button
                      id="table-filters-toggle-btn"
                      type="button"
                      class="ps-btn"
                      aria-expanded="false"
                      aria-controls="table-filter-panel">
                      Filters
                    </button>

                    <button
                      id="table-columns-toggle-btn"
                      type="button"
                      class="ps-btn"
                      aria-expanded="false"
                      aria-controls="table-columns-panel">
                      Columns
                    </button>

                    <button
                      id="table-reset-btn"
                      type="button"
                      class="ps-btn">
                      Reset view
                    </button>
                  </div>
                </div>
              </div>

              <div id="table-filter-panel" class="ps-table-filter-panel" hidden>
                <div class="ps-table-filter-panel__header">
                  <div class="ps-table-filter-panel__title">Filters</div>
                  <button
                    id="table-filter-add-btn"
                    type="button"
                    class="ps-btn">
                    Add filter
                  </button>
                </div>

                <div id="table-filter-rows" class="ps-table-filter-rows"></div>
              </div>

              <div id="table-columns-panel" class="ps-table-columns-panel" hidden>
                <div class="ps-table-columns-panel__header">
                  <div class="ps-table-columns-panel__title">Columns</div>
                  <div class="ps-table-columns-panel__actions">
                    <button
                      id="table-columns-show-all-btn"
                      type="button"
                      class="ps-btn">
                      Show all
                    </button>
                  </div>
                </div>

                <div id="table-columns-list" class="ps-table-columns-list"></div>
              </div>

              <div id="table-active-filters" class="ps-table-active-filters" hidden></div>

              <section
                id="table-plot-controls"
                class="ps-table-plot-controls"
                aria-label="Plot controls"
                hidden>
                <div class="ps-table-plot-controls__fields">
                  <label class="ps-table-plot-control">
                    <span>Plot type</span>
                    <select id="table-plot-type" class="ps-table-select">
                      <option value="bar">Count bar</option>
                      <option value="line">Line</option>
                      <option value="scatter">Scatter</option>
                    </select>
                  </label>
                  <label id="table-plot-source-control" class="ps-table-plot-control" hidden>
                    <span>Stream source</span>
                    <select id="table-plot-source" class="ps-table-select">
                      <option value="table">Filtered recent rows</option>
                      <option value="summary">Derived summary windows</option>
                    </select>
                  </label>
                  <label id="table-plot-category-control" class="ps-table-plot-control">
                    <span>Category</span>
                    <select id="table-plot-category" class="ps-table-select"></select>
                  </label>
                  <label id="table-plot-x-control" class="ps-table-plot-control" hidden>
                    <span>X field</span>
                    <select id="table-plot-x" class="ps-table-select"></select>
                  </label>
                  <label id="table-plot-y-control" class="ps-table-plot-control" hidden>
                    <span>Y field</span>
                    <select id="table-plot-y" class="ps-table-select"></select>
                  </label>
                </div>
                <p id="table-plot-controls-scope" class="ps-table-plot-controls__scope">
                  Plots use only loaded rows that pass the current browser filters.
                </p>
              </section>

              <div id="table-data-surface" class="plot-frame ps-frame ps-frame--table plot-frame--table">
                <div id="stream-grid" class="table-grid ps-tablegrid ps-stream-grid"></div>
              </div>
              <div id="table-plot-output" class="ps-table-plot-root" aria-live="polite" hidden></div>
            </div>

            <section
              class="ps-stream-returning"
              aria-labelledby="stream-since-visit-title"
              data-returning-kind="since-last-visit">
              <div class="ps-stream-returning__header">
                <div>
                  <h2 id="stream-since-visit-title" class="ps-stream-returning__title">Since last visit</h2>
                  <p class="ps-stream-returning__notice">
                    Exact changes are shown only when this browser has a compatible checkpoint for the current plotsrv stream state.
                  </p>
                </div>
                <p id="stream-since-visit-status" class="ps-stream-returning__status" aria-live="polite">
                  Waiting for current stream state.
                </p>
              </div>
              <div id="stream-since-visit-details" class="ps-stream-returning__details"></div>
            </section>

            <section
              class="ps-stream-noteworthy"
              aria-labelledby="stream-noteworthy-title"
              data-noteworthy-kind="stream-noteworthy">
              <div class="ps-stream-noteworthy__header">
                <div>
                  <h2 id="stream-noteworthy-title" class="ps-stream-noteworthy__title">Noteworthy observations</h2>
                  <p class="ps-stream-noteworthy__notice">
                    This is a bounded retained selection, not a complete source-log history.
                  </p>
                </div>
                <p id="stream-noteworthy-status" class="ps-stream-noteworthy__status" aria-live="polite">
                  No noteworthy state received yet.
                </p>
              </div>
              <div id="stream-noteworthy-items" class="ps-stream-noteworthy__items"></div>
            </section>

            <section
              class="ps-stream-summary"
              aria-labelledby="stream-summary-title"
              data-summary-kind="derived-stream-history">
              <div class="ps-stream-summary__header">
                <div>
                  <h2 id="stream-summary-title" class="ps-stream-summary__title">Derived compact history</h2>
                  <p class="ps-stream-summary__notice">
                    Aggregated windows are derived from older observations and are not source log rows.
                  </p>
                </div>
                <p id="stream-summary-status" class="ps-stream-summary__status" aria-live="polite">
                  No derived windows yet.
                </p>
              </div>
              <div id="stream-summary-windows" class="ps-stream-summary__windows"></div>
            </section>
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
        ui.logo_url or "/static/plotsrv_title_logo_ui-white-bk.png"
    )
    header_status_html = ""
    status_modal_html = ""
    if ui.show_freshness or ui.show_history_banner:
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
        status_modal_html = """
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
                <section class="ps-status-modal__summary" aria-label="Current status summary">
                  <div class="ps-status-fact">
                    <span class="ps-status-fact__label">Viewing</span>
                    <strong id="status-modal-viewing">Latest data</strong>
                    <span id="status-modal-viewing-detail">This view follows live updates.</span>
                  </div>
                  <div class="ps-status-fact">
                    <span class="ps-status-fact__label">Last data received</span>
                    <strong id="status-modal-received">Not yet</strong>
                    <span id="status-modal-received-detail">No process-lifetime arrival recorded.</span>
                  </div>
                  <div class="ps-status-fact">
                    <span class="ps-status-fact__label">Browser view</span>
                    <strong id="status-modal-browser">Loading</strong>
                    <span id="status-modal-browser-detail">Checking browser state.</span>
                  </div>
                  <div class="ps-status-fact">
                    <span class="ps-status-fact__label">Freshness</span>
                    <strong id="status-modal-freshness">Checking</strong>
                    <span id="status-modal-freshness-detail">Checking freshness policy.</span>
                  </div>
                </section>

                <section class="ps-status-modal__policy" aria-labelledby="status-modal-policy-title">
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
                  <div class="ps-arrival-chart" role="img" aria-labelledby="status-modal-activity-title status-modal-activity-description">
                    <div id="status-modal-activity-dots" class="ps-arrival-chart__track"></div>
                    <div class="ps-arrival-chart__axis">
                      <span id="status-modal-range-start">—</span>
                      <span id="status-modal-range-end">Now</span>
                    </div>
                  </div>
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

    cfg_json = json.dumps(
        {
            "active_view_id": active_view_id,
            "kind": kind,
            "table_view_mode": table_view_mode,
            "max_table_rows_simple": max_table_rows_simple,
            "max_table_rows_rich": max_table_rows_rich,
            "view_menu_revision": view_menu_revision,
            "browser_update_revision": browser_update_revision,
            # These existing settings now independently control the two modes
            # of the shared header status. ``show_statusline`` controls the
            # compact last-updated row in the bottom dock.
            "show_header_freshness": ui.show_freshness,
            "show_header_history": ui.show_history_banner,
        },
        ensure_ascii=False,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>{page_title}</title>
      <link rel="icon" href="{favicon_url}">
      <meta name="viewport" content="width=device-width, initial-scale=1" />
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
      <header class="header ps-header" style="background:{header_fill};">
        <div class="header-left ps-header__left">
          <img src="{logo_url}" alt="plotsrv logo" class="header-logo ps-header__logo" />
          <div class="header-title ps-header__title">{header_text}</div>
        </div>

        <div class="header-right ps-header__right">
          {header_status_html}
          {dropdown_html}
        </div>
      </header>

      <main class="page ps-page">
        <section class="plot-card ps-card">
          {content_html}
        </section>
      </main>
      {status_modal_html}
      {footer_html}

    </body>
    </html>
    """
    return html
