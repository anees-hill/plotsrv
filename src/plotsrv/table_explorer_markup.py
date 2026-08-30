from __future__ import annotations

from html import escape
from typing import Literal

TableModeSwitch = Literal["visible", "hidden"]


def render_table_grouping_control(
    *,
    label: str = "Group",
    wrapper_class: str = "ps-table-toolbar__grouping",
) -> str:
    """Render the single grouping control owned by the shared table controller."""
    return f"""
      <label class="{escape(wrapper_class, quote=True)}">
        <span class="ps-table-toolbar__label">{escape(label)}</span>
        <select id="table-group-by-select" class="ps-table-select">
          <option value="">No grouping</option>
        </select>
      </label>
    """


def render_table_mode_switch(*, mode: TableModeSwitch = "visible") -> str:
    hidden = " hidden" if mode == "hidden" else ""
    return f"""
      <div class="ps-table-mode-switch" role="group" aria-label="Data view mode"{hidden}>
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
          Plot + data
        </button>
      </div>
    """


def render_table_plot_controls() -> str:
    return """
      <section
        id="table-plot-controls"
        class="ps-table-plot-controls"
        aria-labelledby="table-plot-controls-title"
        hidden>
        <div class="ps-table-plot-controls__identity">
          <h2 id="table-plot-controls-title">Plot controls</h2>
        </div>
        <button
          id="table-plot-controls-toggle"
          class="ps-pane-disclosure"
          type="button"
          aria-expanded="true"
          aria-controls="table-plot-controls-content"
          aria-label="Collapse Plot controls"
          title="Collapse Plot controls">−</button>
        <div id="table-plot-controls-content" class="ps-table-plot-controls__content">
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
              <span>Plot source</span>
              <select id="table-plot-source" class="ps-table-select">
                <option value="table">Filtered loaded rows</option>
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
        </div>
      </section>
    """


def render_table_explorer(
    *,
    grid_html: str,
    search_placeholder: str,
    mode_switch: TableModeSwitch = "visible",
    embedded_json: bool = False,
    leading_html: str = "",
    show_grouping: bool = True,
    trailing_html: str = "",
) -> str:
    """Render the one rich-table explorer shell shared by all table surfaces."""
    shell_classes = "ps-table-shell"
    shell_attributes = ""
    if embedded_json:
        shell_classes += " ps-json-table-shell"
        shell_attributes = ' data-json-table-explorer="1"'

    grouping_html = render_table_grouping_control() if show_grouping else ""

    return f"""
      <div class="{shell_classes}"{shell_attributes}>
        {leading_html}
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
                  placeholder="{escape(search_placeholder, quote=True)}"
                  autocomplete="off"
                />
              </label>

              {grouping_html}

              {render_table_mode_switch(mode=mode_switch)}

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

              <button id="table-reset-btn" type="button" class="ps-btn">
                Reset view
              </button>
            </div>
          </div>
        </div>

        <div id="table-filter-panel" class="ps-table-filter-panel" hidden>
          <div class="ps-table-filter-panel__header">
            <div class="ps-table-filter-panel__title">Filters</div>
            <button id="table-filter-add-btn" type="button" class="ps-btn">
              Add filter
            </button>
          </div>
          <div id="table-filter-rows" class="ps-table-filter-rows"></div>
        </div>

        <div id="table-columns-panel" class="ps-table-columns-panel" hidden>
          <div class="ps-table-columns-panel__header">
            <div class="ps-table-columns-panel__title">Columns</div>
            <div class="ps-table-columns-panel__actions">
              <button id="table-columns-show-all-btn" type="button" class="ps-btn">
                Show all
              </button>
            </div>
          </div>
          <div id="table-columns-list" class="ps-table-columns-list"></div>
        </div>

        <div id="table-active-filters" class="ps-table-active-filters" hidden></div>

        {render_table_plot_controls()}

        <div id="table-plot-output" class="ps-table-plot-root" aria-live="polite" hidden></div>

        <div id="table-supporting-data" class="ps-table-supporting-data">
          <header id="table-supporting-data-header" class="ps-table-supporting-data__header" hidden>
            <div>
              <h2>Supporting table</h2>
              <p id="table-supporting-data-copy">Filtered rows used by this plot.</p>
            </div>
            <button
              id="table-supporting-data-toggle"
              type="button"
              class="ps-btn"
              aria-expanded="true"
              aria-controls="table-data-surface">
              Hide table
            </button>
          </header>
          <div id="table-data-surface" class="plot-frame ps-frame ps-frame--table plot-frame--table">
            {grid_html}
          </div>
        </div>
        {trailing_html}
      </div>
    """
