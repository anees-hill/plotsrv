from __future__ import annotations

from html import escape
from typing import Literal

TableModeSwitch = Literal["visible", "hidden"]


def render_table_mode_switch(*, mode: TableModeSwitch = "visible") -> str:
    hidden = " hidden" if mode == "hidden" else ""
    return f"""
      <div class="ps-table-mode-switch" role="group" aria-label="Table display mode"{hidden}>
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


def render_table_plot_controls() -> str:
    return """
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
      </section>
    """


def render_table_explorer(
    *,
    grid_html: str,
    search_placeholder: str,
    mode_switch: TableModeSwitch = "visible",
    embedded_json: bool = False,
    trailing_html: str = "",
) -> str:
    """Render the one rich-table explorer shell shared by all table surfaces."""
    shell_classes = "ps-table-shell"
    shell_attributes = ""
    if embedded_json:
        shell_classes += " ps-json-table-shell"
        shell_attributes = ' data-json-table-explorer="1"'

    return f"""
      <div class="{shell_classes}"{shell_attributes}>
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

              <label class="ps-table-toolbar__grouping">
                <span class="ps-table-toolbar__label">Group</span>
                <select id="table-group-by-select" class="ps-table-select">
                  <option value="">No grouping</option>
                </select>
              </label>

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

        <div id="table-data-surface" class="plot-frame ps-frame ps-frame--table plot-frame--table">
          {grid_html}
        </div>
        <div id="table-plot-output" class="ps-table-plot-root" aria-live="polite" hidden></div>
        {trailing_html}
      </div>
    """
