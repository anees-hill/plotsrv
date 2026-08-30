(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;
  const PLOT_PREFERENCE_PREFIX = "plotsrv:v1:table_plot:";
  const SUPPORTING_TABLE_PREFERENCE_PREFIX = "plotsrv:v1:plot_supporting_table:";
  const PLOT_CONTROLS_PREFERENCE_PREFIX = "plotsrv:v1:plot_controls:";
  const PLOT_TYPES = ["bar", "line", "scatter"];

  function normalizeCapabilities(raw) {
    const value = raw && typeof raw === "object" ? raw : {};
    const requestedSources = Array.isArray(value.sources) ? value.sources : ["table"];
    const sources = ["table"];
    if (requestedSources.includes("summary")) sources.push("summary");
    return {
      sources: sources,
      tableLabel: typeof value.tableLabel === "string" && value.tableLabel
        ? value.tableLabel
        : "Filtered loaded rows",
      summaryLabel: typeof value.summaryLabel === "string" && value.summaryLabel
        ? value.summaryLabel
        : "Derived summary windows",
      tableScopeDescription:
        typeof value.tableScopeDescription === "string"
          ? value.tableScopeDescription
          : "",
      summaryScopeDescription:
        typeof value.summaryScopeDescription === "string"
          ? value.summaryScopeDescription
          : "Stream source: currently loaded derived summary windows with their displayed aggregate bounds.",
    };
  }

  function capabilities() {
    if (!state.tablePlotCapabilities) {
      state.tablePlotCapabilities = normalizeCapabilities(null);
    }
    return state.tablePlotCapabilities;
  }

  function setTablePlotCapabilities(raw) {
    state.tablePlotCapabilities = normalizeCapabilities(raw);
  }

  function preferenceKey() {
    return PLOT_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function supportingTablePreferenceKey() {
    return SUPPORTING_TABLE_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function plotControlsPreferenceKey() {
    return PLOT_CONTROLS_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function plotControlsCollapsed() {
    if (typeof state.tablePlotControlsCollapsed === "boolean") {
      return state.tablePlotControlsCollapsed;
    }
    let collapsed = false;
    try {
      collapsed = localStorage.getItem(plotControlsPreferenceKey()) === "collapsed";
    } catch (e) {
      collapsed = false;
    }
    state.tablePlotControlsCollapsed = collapsed;
    return collapsed;
  }

  function syncPlotControlsDisclosure() {
    const panel = document.getElementById("table-plot-controls");
    const content = document.getElementById("table-plot-controls-content");
    const toggle = document.getElementById("table-plot-controls-toggle");
    if (!panel || !content || !toggle) return;
    const collapsed = plotControlsCollapsed();
    content.hidden = collapsed;
    if (panel.classList && typeof panel.classList.toggle === "function") {
      panel.classList.toggle("is-collapsed", collapsed);
    }
    toggle.textContent = collapsed ? "+" : "−";
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      (collapsed ? "Expand" : "Collapse") + " Plot controls"
    );
    toggle.title = (collapsed ? "Expand" : "Collapse") + " Plot controls";
  }

  function setPlotControlsCollapsed(collapsed) {
    state.tablePlotControlsCollapsed = collapsed === true;
    try {
      localStorage.setItem(
        plotControlsPreferenceKey(),
        state.tablePlotControlsCollapsed ? "collapsed" : "expanded"
      );
    } catch (e) {
      // The disclosure still works when browser-local preferences are blocked.
    }
    syncPlotControlsDisclosure();
  }

  function loadSupportingTablePreference() {
    let collapsed = null;
    try {
      const stored = localStorage.getItem(supportingTablePreferenceKey());
      if (stored === "collapsed") collapsed = true;
      if (stored === "expanded") collapsed = false;
    } catch (e) {
      collapsed = null;
    }
    if (collapsed === null) {
      collapsed = typeof window.matchMedia === "function" &&
        window.matchMedia("(max-width: 640px)").matches;
    }
    state.tablePlotSupportingCollapsed = collapsed;
    return collapsed;
  }

  function supportingTableCollapsed() {
    if (typeof state.tablePlotSupportingCollapsed !== "boolean") {
      return loadSupportingTablePreference();
    }
    return state.tablePlotSupportingCollapsed;
  }

  function saveSupportingTablePreference() {
    try {
      localStorage.setItem(
        supportingTablePreferenceKey(),
        supportingTableCollapsed() ? "collapsed" : "expanded"
      );
    } catch (e) {
      // Supporting-table disclosure is optional browser-local convenience.
    }
  }

  function defaultPreferences() {
    return {
      type: "bar",
      source: "table",
      categoryField: "",
      xField: "",
      yField: "",
    };
  }

  function loadPreferences() {
    let parsed = null;
    try {
      const stored = localStorage.getItem(preferenceKey());
      if (stored) parsed = JSON.parse(stored);
    } catch (e) {
      parsed = null;
    }

    const defaults = defaultPreferences();
    state.tablePlotPreferences = {
      type:
        parsed && typeof parsed.type === "string" && PLOT_TYPES.includes(parsed.type)
          ? parsed.type
          : defaults.type,
      source:
        parsed && typeof parsed.source === "string" &&
        ["table", "summary"].includes(parsed.source)
          ? parsed.source
          : defaults.source,
      categoryField:
        parsed && typeof parsed.categoryField === "string" ? parsed.categoryField : "",
      xField: parsed && typeof parsed.xField === "string" ? parsed.xField : "",
      yField: parsed && typeof parsed.yField === "string" ? parsed.yField : "",
    };
  }

  function preferences() {
    if (!state.tablePlotPreferences) loadPreferences();
    return state.tablePlotPreferences;
  }

  function savePreferences() {
    try {
      localStorage.setItem(preferenceKey(), JSON.stringify(preferences()));
    } catch (e) {
      // Plot preferences are optional browser-local convenience only.
    }
  }

  function tableFields() {
    return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
  }

  function tableNumericFields() {
    const types = state.tableFieldTypes || {};
    return tableFields().filter(function (field) {
      return types[field] === "number";
    });
  }

  function sourceFields(source) {
    if (source === "summary") {
      return Array.isArray(state.tablePlotSummaryFields)
        ? state.tablePlotSummaryFields.slice()
        : [];
    }
    return tableFields();
  }

  function sourceNumericFields(source) {
    if (source === "summary") {
      const types = state.tablePlotSummaryFieldTypes || {};
      return sourceFields(source).filter(function (field) {
        return types[field] === "number";
      });
    }
    return tableNumericFields();
  }

  function chooseField(saved, candidates, otherField) {
    if (typeof saved === "string" && candidates.includes(saved)) return saved;
    return candidates.find(function (field) {
      return field !== otherField;
    }) || candidates[0] || "";
  }

  function normalizePreferences() {
    const prefs = preferences();
    const availableSources = capabilities().sources;
    const source = prefs.source === "summary" && availableSources.includes("summary")
      ? "summary"
      : "table";
    const allFields = sourceFields(source);
    const numeric = sourceNumericFields(source);
    const nextType = PLOT_TYPES.includes(prefs.type) ? prefs.type : "bar";
    const nextCategory = chooseField(prefs.categoryField, allFields);
    const nextX = chooseField(prefs.xField, numeric);
    const nextY = chooseField(prefs.yField, numeric, nextX);
    const changed =
      prefs.type !== nextType ||
      prefs.source !== source ||
      prefs.categoryField !== nextCategory ||
      prefs.xField !== nextX ||
      prefs.yField !== nextY;

    prefs.type = nextType;
    prefs.source = source;
    prefs.categoryField = nextCategory;
    prefs.xField = nextX;
    prefs.yField = nextY;
    if (changed) savePreferences();
    return prefs;
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function populateSelect(select, values, selected, placeholder) {
    if (!select || typeof document.createElement !== "function") return;
    clearElement(select);

    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    select.appendChild(empty);

    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }

    select.value = selected || "";
    select.disabled = values.length === 0;
  }

  function setButtonState(button, pressed) {
    if (!button) return;
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
    if (button.classList && typeof button.classList.toggle === "function") {
      button.classList.toggle("is-active", pressed);
    }
  }

  function currentMode() {
    return state.tablePlotMode === "plot" ? "plot" : "table";
  }

  function renderControls() {
    const type = document.getElementById("table-plot-type");
    const source = document.getElementById("table-plot-source");
    const category = document.getElementById("table-plot-category");
    const x = document.getElementById("table-plot-x");
    const y = document.getElementById("table-plot-y");
    const categoryControl = document.getElementById("table-plot-category-control");
    const xControl = document.getElementById("table-plot-x-control");
    const yControl = document.getElementById("table-plot-y-control");
    const sourceControl = document.getElementById("table-plot-source-control");
    const scopeNotice = document.getElementById("table-plot-controls-scope");
    const supportingCopy = document.getElementById("table-supporting-data-copy");
    if (!type || !source || !category || !x || !y) return;

    const prefs = normalizePreferences();
    const availableCapabilities = capabilities();
    type.value = prefs.type;
    source.value = prefs.source;
    const sourceOptions = Array.from(source.options || []);
    sourceOptions.forEach(function (option) {
      if (option.value === "table") option.textContent = availableCapabilities.tableLabel;
      if (option.value === "summary") option.textContent = availableCapabilities.summaryLabel;
      option.hidden = !availableCapabilities.sources.includes(option.value);
    });
    source.disabled = availableCapabilities.sources.length < 2;
    if (sourceControl) sourceControl.hidden = availableCapabilities.sources.length < 2;
    const availableFields = sourceFields(prefs.source);
    const availableNumericFields = sourceNumericFields(prefs.source);
    populateSelect(category, availableFields, prefs.categoryField, "Choose a category");
    populateSelect(x, availableNumericFields, prefs.xField, "Choose an x field");
    populateSelect(y, availableNumericFields, prefs.yField, "Choose a y field");

    const isBar = prefs.type === "bar";
    if (categoryControl) categoryControl.hidden = !isBar;
    if (xControl) xControl.hidden = isBar;
    if (yControl) yControl.hidden = isBar;
    if (scopeNotice) {
      scopeNotice.textContent = prefs.source === "summary"
        ? "Derived summary plots use only the currently loaded aggregate windows; they are not source log rows and raw-table filters do not apply."
        : availableCapabilities.tableScopeDescription ||
          "Plots use only loaded rows that pass the current browser filters.";
    }
    if (supportingCopy) {
      supportingCopy.textContent = prefs.source === "summary"
        ? "Recent source rows for cross-reference; this plot uses derived summary windows."
        : "Filtered rows used by this plot.";
    }
  }

  function renderControllerError(output) {
    output.replaceChildren();
    const notice = document.createElement("section");
    notice.className = "ps-table-plot__notice ps-table-plot__notice--error";
    notice.dataset.plotState = "error";
    const title = document.createElement("h2");
    title.className = "ps-table-plot__notice-title";
    title.textContent = "Unable to render plot";
    const detail = document.createElement("p");
    detail.className = "ps-table-plot__notice-detail";
    detail.textContent = "Return to the table or change the plot selections and try again.";
    notice.appendChild(title);
    notice.appendChild(detail);
    output.appendChild(notice);
  }

  function refreshTablePlot() {
    if (currentMode() !== "plot") return null;
    const output = document.getElementById("table-plot-output");
    if (!output || typeof core.renderTablePlot !== "function") return null;

    renderControls();
    const prefs = normalizePreferences();
    const options = {
      container: output,
      type: prefs.type,
      categoryField: prefs.categoryField,
      xField: prefs.xField,
      yField: prefs.yField,
    };
    if (prefs.source === "summary") {
      options.rows = Array.isArray(state.tablePlotSummaryRows)
        ? state.tablePlotSummaryRows
        : [];
      options.scopeKind = "summary";
      options.scopeDescription = capabilities().summaryScopeDescription;
    } else {
      options.scopeDescription = capabilities().tableScopeDescription;
    }
    try {
      return core.renderTablePlot(options);
    } catch (error) {
      console.error("Unable to render table plot", error);
      renderControllerError(output);
      return { ok: false, reason: "renderer_error", rowCount: 0, plottedCount: 0 };
    }
  }

  function redrawTable() {
    const table = state.tabulatorInstance || state.streamTabulatorInstance;
    if (!table || typeof table.redraw !== "function") return;
    try {
      table.redraw(true);
    } catch (e) {
      // A redraw failure does not prevent switching or expanding modes.
    }
  }

  function syncSupportingTable(isPlot) {
    const section = document.getElementById("table-supporting-data");
    const header = document.getElementById("table-supporting-data-header");
    const toggle = document.getElementById("table-supporting-data-toggle");
    const surface = document.getElementById("table-data-surface");
    if (!surface) return;

    const collapsed = isPlot && supportingTableCollapsed();
    surface.hidden = collapsed;
    if (header) header.hidden = !isPlot;
    if (section && section.classList && typeof section.classList.toggle === "function") {
      section.classList.toggle("is-plot-support", isPlot);
      section.classList.toggle("is-collapsed", collapsed);
    }
    if (toggle) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.textContent = collapsed ? "Show table" : "Hide table";
    }
  }

  function applyMode(mode, options) {
    const nextMode = mode === "plot" ? "plot" : "table";
    const surface = document.getElementById("table-data-surface");
    const controls = document.getElementById("table-plot-controls");
    const output = document.getElementById("table-plot-output");
    const tableButton = document.getElementById("table-mode-table-btn");
    const plotButton = document.getElementById("table-mode-plot-btn");
    if (!surface || !controls || !output || !tableButton || !plotButton) return;

    state.tablePlotMode = nextMode;
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
    const isPlot = nextMode === "plot";
    controls.hidden = !isPlot;
    output.hidden = !isPlot;
    syncPlotControlsDisclosure();
    syncSupportingTable(isPlot);
    setButtonState(tableButton, !isPlot);
    setButtonState(plotButton, isPlot);

    if (isPlot) {
      refreshTablePlot();
      if (!surface.hidden) redrawTable();
      return;
    }

    if (!options || options.redraw !== false) {
      redrawTable();
    }
  }

  function bindControls() {
    const tableButton = document.getElementById("table-mode-table-btn");
    const plotButton = document.getElementById("table-mode-plot-btn");
    const type = document.getElementById("table-plot-type");
    const source = document.getElementById("table-plot-source");
    const category = document.getElementById("table-plot-category");
    const x = document.getElementById("table-plot-x");
    const y = document.getElementById("table-plot-y");
    const supportingToggle = document.getElementById("table-supporting-data-toggle");
    const plotControlsToggle = document.getElementById("table-plot-controls-toggle");

    if (tableButton && !tableButton.dataset.plotsrvBound) {
      tableButton.addEventListener("click", function () {
        applyMode("table");
      });
      tableButton.dataset.plotsrvBound = "1";
    }

    if (plotButton && !plotButton.dataset.plotsrvBound) {
      plotButton.addEventListener("click", function () {
        applyMode("plot");
      });
      plotButton.dataset.plotsrvBound = "1";
    }

    if (supportingToggle && !supportingToggle.dataset.plotsrvBound) {
      supportingToggle.addEventListener("click", function () {
        state.tablePlotSupportingCollapsed = !supportingTableCollapsed();
        saveSupportingTablePreference();
        syncSupportingTable(currentMode() === "plot");
        if (!state.tablePlotSupportingCollapsed) redrawTable();
      });
      supportingToggle.dataset.plotsrvBound = "1";
    }

    if (plotControlsToggle && !plotControlsToggle.dataset.plotsrvBound) {
      plotControlsToggle.addEventListener("click", function () {
        setPlotControlsCollapsed(!plotControlsCollapsed());
      });
      plotControlsToggle.dataset.plotsrvBound = "1";
    }

    if (type && !type.dataset.plotsrvBound) {
      type.addEventListener("change", function () {
        preferences().type = PLOT_TYPES.includes(type.value) ? type.value : "bar";
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      type.dataset.plotsrvBound = "1";
    }

    if (source && !source.dataset.plotsrvBound) {
      source.addEventListener("change", function () {
        preferences().source = source.value === "summary" ? "summary" : "table";
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      source.dataset.plotsrvBound = "1";
    }

    function bindField(select, preferenceName) {
      if (!select || select.dataset.plotsrvBound) return;
      select.addEventListener("change", function () {
        preferences()[preferenceName] = String(select.value || "");
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      select.dataset.plotsrvBound = "1";
    }

    bindField(category, "categoryField");
    bindField(x, "xField");
    bindField(y, "yField");
  }

  function safeSummaryNumber(value) {
    const number = Number(value);
    return Number.isSafeInteger(number) && number >= 0 ? number : null;
  }

  function setTablePlotSummaryRows(payload) {
    const windows = Array.isArray(payload && payload.windows) ? payload.windows : [];
    const rows = [];
    const summaryFields = [
      "summary_window",
      "summary_tier",
      "record_count",
      "first_browser_sequence",
      "last_browser_sequence",
      "resolution_seconds",
    ];
    const summaryTypes = {
      summary_window: "number",
      summary_tier: "text",
      record_count: "number",
      first_browser_sequence: "number",
      last_browser_sequence: "number",
      resolution_seconds: "number",
    };

    windows.forEach(function (window) {
      if (!window || typeof window !== "object" || window.derived !== true) return;
      const row = {
        summary_window: rows.length + 1,
        summary_tier: typeof window.tier === "string" ? window.tier : "unknown",
      };
      const metrics = [
        ["record_count", window.record_count],
        ["first_browser_sequence", window.first_browser_sequence],
        ["last_browser_sequence", window.last_browser_sequence],
        [
          "resolution_seconds",
          window.resolution && typeof window.resolution === "object"
            ? window.resolution.seconds
            : null,
        ],
      ];
      for (const metric of metrics) {
        const number = safeSummaryNumber(metric[1]);
        if (number !== null) row[metric[0]] = number;
      }
      rows.push(row);
    });

    state.tablePlotSummaryRows = rows;
    state.tablePlotSummaryFields = summaryFields;
    state.tablePlotSummaryFieldTypes = summaryTypes;
    if (currentMode() === "plot" && preferences().source === "summary") {
      refreshTablePlot();
    }
  }

  function configureTablePlotSurface() {
    const tableButton = document.getElementById("table-mode-table-btn");
    const plotButton = document.getElementById("table-mode-plot-btn");
    const surface = document.getElementById("table-data-surface");
    const output = document.getElementById("table-plot-output");
    if (!tableButton || !plotButton || !surface || !output) return;

    if (state.tablePlotViewId !== config.activeViewId) {
      state.tablePlotViewId = config.activeViewId;
      // Mode is deliberately not a saved preference: every page opens with
      // the primary table visible until the user explicitly switches to Plot.
      state.tablePlotMode = "table";
      state.tablePlotPreferences = null;
      state.tablePlotSupportingCollapsed = null;
      state.tablePlotControlsCollapsed = null;
    }

    bindControls();
    renderControls();
    applyMode(currentMode(), { redraw: false });
  }

  core.configureTablePlotSurface = configureTablePlotSurface;
  core.refreshTablePlot = refreshTablePlot;
  core.setTablePlotMode = applyMode;
  core.setTablePlotCapabilities = setTablePlotCapabilities;
  core.setTablePlotSummaryRows = setTablePlotSummaryRows;
  core.setPlotControlsCollapsed = setPlotControlsCollapsed;
})();
