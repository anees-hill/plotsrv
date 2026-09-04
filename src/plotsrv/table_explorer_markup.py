from __future__ import annotations

from html import escape
from typing import Literal

TableModeSwitch = Literal["visible", "hidden"]


def render_table_grouping_control(
    *,
    label: str = "Grouping",
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
        <p id="table-plot-controls-summary" class="ps-table-plot-controls__summary" hidden></p>
        <div class="ps-table-plot-controls__actions">
          <label id="table-plot-layout-control" class="ps-table-plot-layout" hidden>
            <span class="ps-table-plot-layout__label">Layout</span>
            <select id="table-plot-layout" aria-label="Detached controls layout">
              <option value="toolbar">Toolbar</option>
              <option value="sidebar">Left sidebar</option>
            </select>
          </label>
          <button id="table-plot-edit" class="ps-btn" type="button" aria-expanded="false" aria-controls="table-plot-controls-content" hidden>Edit plot</button>
          <button
            id="table-plot-controls-pin"
            class="ps-table-plot-controls__pin"
            type="button"
            aria-pressed="false"
            aria-label="Pin Plot controls while scrolling"
            title="Pin Plot controls while scrolling">
            <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
              <path d="M8.2 3.5h7.6l-1.25 5.1 2.85 2.85v1.45h-4.55V20l-.85 1-.85-1v-7.1H6.6v-1.45L9.45 8.6 8.2 3.5Z"></path>
            </svg>
          </button>
          <button
            id="table-plot-controls-toggle"
            class="ps-pane-disclosure"
            type="button"
            aria-expanded="true"
            aria-controls="table-plot-controls-content"
            aria-label="Collapse Plot controls"
            title="Collapse Plot controls">−</button>
        </div>
        <div id="table-plot-controls-content" class="ps-table-plot-controls__content">
          <div class="ps-table-plot-controls__fields ps-table-plot-controls__fields--definition">
            <label class="ps-table-plot-control ps-table-plot-control--type">
              <span>Plot type</span>
              <select id="table-plot-type" class="ps-table-select">
                <option value="bar">Bar</option>
                <option value="line">Line</option>
                <option value="scatter">Scatter</option>
                <option value="histogram">Histogram</option>
              </select>
            </label>
            <label id="table-plot-category-control" class="ps-table-plot-control">
              <span>Category <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Category: Groups rows by this field, creating one bar for each category." data-tooltip="Groups rows by this field, creating one bar for each category.">i</span></span>
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
            <label id="table-plot-aggregation-control" class="ps-table-plot-control">
              <span>Aggregate <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Aggregate: Chooses how values within each category and series are combined." data-tooltip="Chooses how values within each category and series are combined.">i</span></span>
              <select id="table-plot-aggregation" class="ps-table-select">
                <option value="count">Count</option>
                <option value="sum">Sum</option>
                <option value="mean">Mean</option>
                <option value="min">Min</option>
                <option value="max">Max</option>
              </select>
            </label>
            <label id="table-plot-value-control" class="ps-table-plot-control" hidden>
              <span>Value field <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Value field: Selects the numeric field used by the chosen aggregate." data-tooltip="Selects the numeric field used by the chosen aggregate.">i</span></span>
              <select id="table-plot-value" class="ps-table-select"></select>
            </label>
            <label id="table-plot-histogram-control" class="ps-table-plot-control" hidden>
              <span>Numeric field <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Numeric field: Selects the values whose distribution the histogram shows." data-tooltip="Selects the values whose distribution the histogram shows.">i</span></span>
              <select id="table-plot-histogram" class="ps-table-select"></select>
            </label>
            <label id="table-plot-bins-control" class="ps-table-plot-control ps-table-plot-control--compact" hidden>
              <span>Bins <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Bins: Sets how many value intervals the histogram uses; Auto adapts to the data." data-tooltip="Sets how many value intervals the histogram uses; Auto adapts to the data.">i</span></span>
              <select id="table-plot-bins" class="ps-table-select">
                <option value="auto">Auto</option>
                <option value="5">5</option>
                <option value="10">10</option>
                <option value="20">20</option>
                <option value="40">40</option>
              </select>
            </label>
            <label id="table-plot-series-control" class="ps-table-plot-control" hidden>
              <span>Series <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Series: Splits the plot by another field and identifies each group by colour." data-tooltip="Splits the plot by another field and identifies each group by colour.">i</span></span>
              <select id="table-plot-series" class="ps-table-select"></select>
            </label>
          </div>
          <div class="ps-table-plot-controls__fields ps-table-plot-controls__fields--secondary">
            <div class="ps-table-plot-control ps-table-plot-palette-control">
              <span id="table-plot-palette-label">Palette</span>
              <div id="table-plot-palette" class="ps-table-plot-palette">
                <button id="table-plot-palette-button" class="ps-table-select ps-table-plot-palette__button" type="button" aria-haspopup="listbox" aria-expanded="false" aria-controls="table-plot-palette-menu" aria-labelledby="table-plot-palette-label table-plot-palette-name">
                  <span id="table-plot-palette-preview" class="ps-table-plot-palette__preview" aria-hidden="true"></span>
                  <span id="table-plot-palette-name">plotsrv</span>
                  <span class="ps-table-plot-palette__chevron" aria-hidden="true">⌄</span>
                </button>
                <div id="table-plot-palette-menu" class="ps-table-plot-palette__menu" role="listbox" aria-labelledby="table-plot-palette-label" hidden></div>
              </div>
            </div>
            <label id="table-plot-sort-control" class="ps-table-plot-control">
              <span>Order <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Order: Controls how bar-chart categories are arranged." data-tooltip="Controls how bar-chart categories are arranged.">i</span></span>
              <select id="table-plot-sort" class="ps-table-select">
                <option value="value-desc">Value, high to low</option>
                <option value="value-asc">Value, low to high</option>
                <option value="category-asc">Category, A to Z</option>
                <option value="category-desc">Category, Z to A</option>
              </select>
            </label>
            <label id="table-plot-limit-control" class="ps-table-plot-control ps-table-plot-control--compact">
              <span>Categories <span class="ps-table-plot-help" tabindex="0" role="img" aria-label="Categories: Limits named bars; remaining categories are combined as Other." data-tooltip="Limits named bars; remaining categories are combined as Other.">i</span></span>
              <select id="table-plot-limit" class="ps-table-select">
                <option value="5">Top 5</option>
                <option value="10">Top 10</option>
                <option value="20">Top 20</option>
                <option value="40">Top 40</option>
              </select>
            </label>
            <label id="table-plot-display-control" class="ps-table-plot-control ps-table-plot-control--compact" hidden>
              <span>Display</span>
              <select id="table-plot-display" class="ps-table-select">
                <option value="grouped">Grouped</option>
                <option value="stacked">Stacked</option>
              </select>
            </label>
          <details id="table-plot-advanced" class="ps-table-plot-advanced">
            <summary>Advanced</summary>
            <div class="ps-table-plot-advanced__fields">
              <label id="table-plot-source-control" class="ps-table-plot-control" hidden>
                <span>Plot source</span>
                <select id="table-plot-source" class="ps-table-select">
                  <option value="table">Filtered loaded rows</option>
                  <option value="summary">Derived summary windows</option>
                </select>
              </label>
              <label class="ps-table-plot-control"><span>Custom title</span><input id="table-plot-title" class="ps-table-input" type="text" placeholder="Automatic title"></label>
              <label class="ps-table-plot-control ps-table-plot-control--compact"><span>Title alignment</span><select id="table-plot-title-align" class="ps-table-select"><option value="left">Left</option><option value="center">Centred</option></select></label>
              <label class="ps-table-plot-control"><span>X-axis label</span><input id="table-plot-x-label" class="ps-table-input" type="text" placeholder="Automatic label"></label>
              <label class="ps-table-plot-control"><span>Y-axis label</span><input id="table-plot-y-label" class="ps-table-input" type="text" placeholder="Automatic label"></label>
              <label id="table-plot-x-scale-control" class="ps-table-plot-control ps-table-plot-control--compact"><span>X scale</span><select id="table-plot-x-scale" class="ps-table-select"><option value="linear">Linear</option><option value="log">Log</option></select></label>
              <label id="table-plot-y-scale-control" class="ps-table-plot-control ps-table-plot-control--compact"><span>Y scale</span><select id="table-plot-y-scale" class="ps-table-select"><option value="linear">Linear</option><option value="log">Log</option></select></label>
              <label id="table-plot-zero-control" class="ps-table-plot-check"><input id="table-plot-zero" type="checkbox"><span>Include zero baseline</span></label>
              <label id="table-plot-points-control" class="ps-table-plot-check" hidden><input id="table-plot-points" type="checkbox" checked><span>Show line points</span></label>
              <label id="table-plot-legend-control" class="ps-table-plot-control ps-table-plot-control--compact" hidden><span>Legend</span><select id="table-plot-legend" class="ps-table-select"><option value="top">Top</option><option value="right">Right</option><option value="bottom">Bottom</option></select></label>
              <label id="table-plot-point-selection-control" class="ps-table-plot-control"><span>When over point limit</span><select id="table-plot-point-selection" class="ps-table-select"><option value="refuse">Ask before plotting</option><option value="sample">Even sample</option><option value="first">First values</option><option value="latest">Latest values</option></select></label>
              <button id="table-plot-reset" class="ps-btn ps-table-plot-reset" type="button">Reset plot options</button>
              <p id="table-plot-controls-scope" class="ps-table-plot-controls__scope">
                Plots use only loaded rows that pass the current browser filters.
              </p>
            </div>
          </details>
          </div>
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
    trailing_html: str = "",
) -> str:
    """Render the one rich-table explorer shell shared by all table surfaces."""
    shell_classes = "ps-table-shell"
    shell_attributes = ""
    if embedded_json:
        shell_classes += " ps-json-table-shell"
        shell_attributes = ' data-json-table-explorer="1"'

    grouping_html = render_table_grouping_control()

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
            <div class="ps-table-filter-panel__title" title="Is one of filters on the same column combine with OR. Different columns and all other conditions combine with AND.">Filters</div>
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

        <div id="table-plot-workspace" class="ps-table-plot-workspace">
          {render_table_plot_controls()}
          <div id="table-plot-output" class="ps-table-plot-root" aria-live="polite" hidden></div>
        </div>

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
            <div id="table-filter-empty" class="ps-table-filter-empty" role="status" hidden>
              <span>All data is filtered.</span>
              <button id="table-reset-filters-btn" class="ps-btn" type="button">Reset filters</button>
            </div>
            {grid_html}
          </div>
        </div>
        {trailing_html}
      </div>
    """
