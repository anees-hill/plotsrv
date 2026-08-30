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
  const PLOT_TYPES = ["bar", "line", "scatter", "histogram"];
  const AGGREGATIONS = ["count", "sum", "mean", "min", "max"];
  const BAR_SORTS = ["value-desc", "value-asc", "category-asc", "category-desc"];
  const PALETTES = ["plotsrv", "ocean", "forest", "sunset", "violet", "neutral"];
  const STREAM_PLOT_REDRAW_MS = 2000;

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
      liveUpdates: value.liveUpdates === true,
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
      aggregation: "count",
      valueField: "",
      histogramField: "",
      bins: "auto",
      seriesField: "",
      palette: "plotsrv",
      sort: "value-desc",
      categoryLimit: 10,
      display: "grouped",
      title: "",
      xLabel: "",
      yLabel: "",
      xScale: "linear",
      yScale: "linear",
      zeroBaseline: false,
      showPoints: true,
      legend: "top",
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
      aggregation:
        parsed && AGGREGATIONS.includes(parsed.aggregation)
          ? parsed.aggregation : defaults.aggregation,
      valueField: parsed && typeof parsed.valueField === "string" ? parsed.valueField : "",
      histogramField: parsed && typeof parsed.histogramField === "string" ? parsed.histogramField : "",
      bins: parsed && ["auto", "5", "10", "20", "40"].includes(String(parsed.bins)) ? String(parsed.bins) : defaults.bins,
      seriesField: parsed && typeof parsed.seriesField === "string" ? parsed.seriesField : "",
      palette: parsed && PALETTES.includes(parsed.palette) ? parsed.palette : defaults.palette,
      sort: parsed && BAR_SORTS.includes(parsed.sort) ? parsed.sort : defaults.sort,
      categoryLimit: parsed && [5, 10, 20, 40].includes(Number(parsed.categoryLimit)) ? Number(parsed.categoryLimit) : defaults.categoryLimit,
      display: parsed && parsed.display === "stacked" ? "stacked" : defaults.display,
      title: parsed && typeof parsed.title === "string" ? parsed.title : "",
      xLabel: parsed && typeof parsed.xLabel === "string" ? parsed.xLabel : "",
      yLabel: parsed && typeof parsed.yLabel === "string" ? parsed.yLabel : "",
      xScale: parsed && parsed.xScale === "log" ? "log" : defaults.xScale,
      yScale: parsed && parsed.yScale === "log" ? "log" : defaults.yScale,
      zeroBaseline: parsed && parsed.zeroBaseline === true,
      showPoints: !parsed || parsed.showPoints !== false,
      legend: parsed && ["top", "right", "bottom"].includes(parsed.legend) ? parsed.legend : defaults.legend,
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

  function sourceXAxisFields(source) {
    const types = source === "summary"
      ? (state.tablePlotSummaryFieldTypes || {})
      : (state.tableFieldTypes || {});
    return sourceFields(source).filter(function (field) {
      return types[field] === "number" || types[field] === "datetime";
    });
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
    const xCandidates = sourceXAxisFields(source);
    const nextType = PLOT_TYPES.includes(prefs.type) ? prefs.type : "bar";
    const nextCategory = chooseField(prefs.categoryField, allFields);
    const nextX = chooseField(prefs.xField, xCandidates);
    const nextY = chooseField(prefs.yField, numeric, nextX);
    const nextValue = chooseField(prefs.valueField, numeric);
    const nextHistogram = chooseField(prefs.histogramField, numeric);
    const nextSeries = prefs.seriesField && allFields.includes(prefs.seriesField)
      ? prefs.seriesField : "";
    const changed =
      prefs.type !== nextType ||
      prefs.source !== source ||
      prefs.categoryField !== nextCategory ||
      prefs.xField !== nextX ||
      prefs.yField !== nextY ||
      prefs.valueField !== nextValue ||
      prefs.histogramField !== nextHistogram ||
      prefs.seriesField !== nextSeries;

    prefs.type = nextType;
    prefs.source = source;
    prefs.categoryField = nextCategory;
    prefs.xField = nextX;
    prefs.yField = nextY;
    prefs.valueField = nextValue;
    prefs.histogramField = nextHistogram;
    prefs.seriesField = nextSeries;
    const typeMap = source === "summary" ? (state.tablePlotSummaryFieldTypes || {}) : (state.tableFieldTypes || {});
    let advancedChanged = false;
    if (typeMap[prefs.xField] === "datetime" && prefs.xScale !== "linear") {
      prefs.xScale = "linear";
      advancedChanged = true;
    }
    if ((prefs.xScale === "log" || prefs.yScale === "log") && prefs.zeroBaseline) {
      prefs.zeroBaseline = false;
      advancedChanged = true;
    }
    if (changed || advancedChanged) savePreferences();
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

  function fieldTypes(source) {
    return source === "summary"
      ? (state.tablePlotSummaryFieldTypes || {})
      : (state.tableFieldTypes || {});
  }

  function paletteDefinition(key) {
    const palettes = core.TABLE_PLOT_PALETTES || {};
    return palettes[key] || palettes.plotsrv || {
      name: "Plotsrv", colours: ["#d55970", "#7a3950", "#e58a5f"],
    };
  }

  function appendPalettePreview(target, palette) {
    clearElement(target);
    const theme = document.documentElement && document.documentElement.getAttribute("data-theme");
    const dark = theme === "dark" || (theme === "system" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const colours = dark && Array.isArray(palette.darkColours) ? palette.darkColours : palette.colours;
    colours.slice(0, 3).forEach(function (colour) {
      const swatch = document.createElement("span");
      swatch.className = "ps-table-plot-palette__swatch";
      swatch.style.backgroundColor = colour;
      target.appendChild(swatch);
    });
  }

  function renderPaletteControl(selected) {
    const preview = document.getElementById("table-plot-palette-preview");
    const name = document.getElementById("table-plot-palette-name");
    const menu = document.getElementById("table-plot-palette-menu");
    const palette = paletteDefinition(selected);
    if (preview) appendPalettePreview(preview, palette);
    if (name) name.textContent = palette.name;
    if (!menu) return;
    if (!menu.childNodes.length) {
      PALETTES.forEach(function (key) {
        const definition = paletteDefinition(key);
        const option = document.createElement("button");
        option.type = "button";
        option.className = "ps-table-plot-palette__option";
        option.dataset.plotPalette = key;
        option.setAttribute("role", "option");
        const optionPreview = document.createElement("span");
        optionPreview.className = "ps-table-plot-palette__preview";
        appendPalettePreview(optionPreview, definition);
        option.appendChild(optionPreview);
        option.appendChild(document.createTextNode(definition.name));
        menu.appendChild(option);
      });
    }
    Array.from(menu.querySelectorAll("[data-plot-palette]")).forEach(function (item) {
      item.setAttribute("aria-selected", item.dataset.plotPalette === selected ? "true" : "false");
    });
  }

  function renderControls() {
    const type = document.getElementById("table-plot-type");
    const source = document.getElementById("table-plot-source");
    const category = document.getElementById("table-plot-category");
    const x = document.getElementById("table-plot-x");
    const y = document.getElementById("table-plot-y");
    const aggregation = document.getElementById("table-plot-aggregation");
    const value = document.getElementById("table-plot-value");
    const histogram = document.getElementById("table-plot-histogram");
    const bins = document.getElementById("table-plot-bins");
    const series = document.getElementById("table-plot-series");
    const sort = document.getElementById("table-plot-sort");
    const limit = document.getElementById("table-plot-limit");
    const display = document.getElementById("table-plot-display");
    const categoryControl = document.getElementById("table-plot-category-control");
    const xControl = document.getElementById("table-plot-x-control");
    const yControl = document.getElementById("table-plot-y-control");
    const aggregationControl = document.getElementById("table-plot-aggregation-control");
    const valueControl = document.getElementById("table-plot-value-control");
    const histogramControl = document.getElementById("table-plot-histogram-control");
    const binsControl = document.getElementById("table-plot-bins-control");
    const seriesControl = document.getElementById("table-plot-series-control");
    const sortControl = document.getElementById("table-plot-sort-control");
    const limitControl = document.getElementById("table-plot-limit-control");
    const displayControl = document.getElementById("table-plot-display-control");
    const sourceControl = document.getElementById("table-plot-source-control");
    const xScale = document.getElementById("table-plot-x-scale");
    const yScale = document.getElementById("table-plot-y-scale");
    const zero = document.getElementById("table-plot-zero");
    const points = document.getElementById("table-plot-points");
    const legend = document.getElementById("table-plot-legend");
    const pointsControl = document.getElementById("table-plot-points-control");
    const legendControl = document.getElementById("table-plot-legend-control");
    const xScaleControl = document.getElementById("table-plot-x-scale-control");
    const yScaleControl = document.getElementById("table-plot-y-scale-control");
    const zeroControl = document.getElementById("table-plot-zero-control");
    const title = document.getElementById("table-plot-title");
    const xLabel = document.getElementById("table-plot-x-label");
    const yLabel = document.getElementById("table-plot-y-label");
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
    const availableXAxisFields = sourceXAxisFields(prefs.source);
    populateSelect(category, availableFields, prefs.categoryField, "Choose a category");
    populateSelect(x, availableXAxisFields, prefs.xField, "Choose an x field");
    populateSelect(y, availableNumericFields, prefs.yField, "Choose a y field");
    populateSelect(value, availableNumericFields, prefs.valueField, "Choose a value");
    populateSelect(histogram, availableNumericFields, prefs.histogramField, "Choose a field");
    populateSelect(series, availableFields, prefs.seriesField, "No series");

    const isBar = prefs.type === "bar";
    const isHistogram = prefs.type === "histogram";
    const isPoints = prefs.type === "line" || prefs.type === "scatter";
    if (categoryControl) categoryControl.hidden = !isBar;
    if (xControl) xControl.hidden = !isPoints;
    if (yControl) yControl.hidden = !isPoints;
    if (aggregationControl) aggregationControl.hidden = !isBar;
    if (valueControl) valueControl.hidden = !isBar || prefs.aggregation === "count";
    if (histogramControl) histogramControl.hidden = !isHistogram;
    if (binsControl) binsControl.hidden = !isHistogram;
    if (seriesControl) seriesControl.hidden = isHistogram;
    if (sortControl) sortControl.hidden = !isBar;
    if (limitControl) limitControl.hidden = !isBar;
    if (displayControl) displayControl.hidden = !isBar || !prefs.seriesField;
    if (pointsControl) pointsControl.hidden = prefs.type !== "line";
    if (legendControl) legendControl.hidden = isHistogram || !prefs.seriesField;
    if (xScaleControl) xScaleControl.hidden = !isPoints;
    if (yScaleControl) yScaleControl.hidden = !isPoints;
    if (zeroControl) zeroControl.hidden = !isPoints;
    if (aggregation) aggregation.value = prefs.aggregation;
    if (bins) bins.value = prefs.bins;
    if (sort) sort.value = prefs.sort;
    if (limit) limit.value = String(prefs.categoryLimit);
    if (display) display.value = prefs.display;
    if (xScale) {
      xScale.value = prefs.xScale;
      xScale.disabled = fieldTypes(prefs.source)[prefs.xField] === "datetime" || !isPoints;
    }
    if (yScale) { yScale.value = prefs.yScale; yScale.disabled = !isPoints; }
    if (zero) {
      zero.checked = prefs.zeroBaseline;
      zero.disabled = prefs.xScale === "log" || prefs.yScale === "log" || !isPoints;
    }
    if (points) points.checked = prefs.showPoints;
    if (legend) legend.value = prefs.legend;
    if (title) title.value = prefs.title;
    if (xLabel) xLabel.value = prefs.xLabel;
    if (yLabel) yLabel.value = prefs.yLabel;
    renderPaletteControl(prefs.palette);
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
    cancelScheduledTablePlotRefresh();
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
      xKind: fieldTypes(prefs.source)[prefs.xField] || "number",
      aggregation: prefs.aggregation,
      valueField: prefs.valueField,
      histogramField: prefs.histogramField,
      bins: prefs.bins,
      seriesField: prefs.seriesField,
      palette: prefs.palette,
      sort: prefs.sort,
      categoryLimit: prefs.categoryLimit,
      display: prefs.display,
      title: prefs.title.trim(),
      xLabel: prefs.xLabel.trim(),
      yLabel: prefs.yLabel.trim(),
      xScale: prefs.xScale,
      yScale: prefs.yScale,
      zeroBaseline: prefs.zeroBaseline,
      showPoints: prefs.showPoints,
      legend: prefs.legend,
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
      const result = core.renderTablePlot(options);
      state.tablePlotLastResult = result;
      if (typeof core.configureBottomBar === "function") core.configureBottomBar();
      return result;
    } catch (error) {
      console.error("Unable to render table plot", error);
      renderControllerError(output);
      state.tablePlotLastResult = { ok: false, reason: "renderer_error", rowCount: 0, plottedCount: 0 };
      if (typeof core.configureBottomBar === "function") core.configureBottomBar();
      return state.tablePlotLastResult;
    }
  }

  function cancelScheduledTablePlotRefresh() {
    if (state.tablePlotRefreshTimer) {
      window.clearTimeout(state.tablePlotRefreshTimer);
      state.tablePlotRefreshTimer = null;
    }
  }

  function scheduleTablePlotRefresh() {
    if (currentMode() !== "plot") return null;
    if (!capabilities().liveUpdates) return refreshTablePlot();
    if (state.tablePlotRefreshTimer) return null;
    state.tablePlotRefreshTimer = window.setTimeout(function () {
      state.tablePlotRefreshTimer = null;
      if (currentMode() === "plot") refreshTablePlot();
    }, STREAM_PLOT_REDRAW_MS);
    return null;
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
    if (!isPlot) cancelScheduledTablePlotRefresh();
    controls.hidden = !isPlot;
    output.hidden = !isPlot;
    syncPlotControlsDisclosure();
    syncSupportingTable(isPlot);
    setButtonState(tableButton, !isPlot);
    setButtonState(plotButton, isPlot);
    if (typeof core.configureBottomBar === "function") core.configureBottomBar();

    if (isPlot) {
      if (options && options.deferPlotRefresh) scheduleTablePlotRefresh();
      else refreshTablePlot();
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
    const value = document.getElementById("table-plot-value");
    const histogram = document.getElementById("table-plot-histogram");
    const series = document.getElementById("table-plot-series");
    const paletteButton = document.getElementById("table-plot-palette-button");
    const paletteMenu = document.getElementById("table-plot-palette-menu");
    const reset = document.getElementById("table-plot-reset");
    const supportingToggle = document.getElementById("table-supporting-data-toggle");
    const plotControlsToggle = document.getElementById("table-plot-controls-toggle");

    if (!state.tablePlotThemeChangeBound) {
      window.addEventListener("plotsrv:themechange", function () {
        renderPaletteControl(preferences().palette);
        if (currentMode() === "plot") refreshTablePlot();
      });
      state.tablePlotThemeChangeBound = true;
    }

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
    bindField(value, "valueField");
    bindField(histogram, "histogramField");
    bindField(series, "seriesField");

    function bindChoice(id, preferenceName, normalize) {
      const control = document.getElementById(id);
      if (!control || control.dataset.plotsrvBound) return;
      control.addEventListener("change", function () {
        preferences()[preferenceName] = normalize ? normalize(control) : control.value;
        if ((preferenceName === "xScale" || preferenceName === "yScale") && control.value === "log") {
          preferences().zeroBaseline = false;
        }
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      control.dataset.plotsrvBound = "1";
    }

    bindChoice("table-plot-aggregation", "aggregation");
    bindChoice("table-plot-bins", "bins");
    bindChoice("table-plot-sort", "sort");
    bindChoice("table-plot-limit", "categoryLimit", function (control) { return Number(control.value); });
    bindChoice("table-plot-display", "display");
    bindChoice("table-plot-x-scale", "xScale");
    bindChoice("table-plot-y-scale", "yScale");
    bindChoice("table-plot-legend", "legend");
    bindChoice("table-plot-zero", "zeroBaseline", function (control) { return control.checked; });
    bindChoice("table-plot-points", "showPoints", function (control) { return control.checked; });
    bindChoice("table-plot-title", "title");
    bindChoice("table-plot-x-label", "xLabel");
    bindChoice("table-plot-y-label", "yLabel");

    function closePaletteMenu(restoreFocus) {
      if (!paletteMenu || !paletteButton) return;
      paletteMenu.hidden = true;
      paletteButton.setAttribute("aria-expanded", "false");
      if (restoreFocus) paletteButton.focus();
    }

    if (paletteButton && paletteMenu && !paletteButton.dataset.plotsrvBound) {
      paletteButton.addEventListener("click", function () {
        paletteMenu.hidden = !paletteMenu.hidden;
        paletteButton.setAttribute("aria-expanded", paletteMenu.hidden ? "false" : "true");
        if (!paletteMenu.hidden) {
          const selected = paletteMenu.querySelector('[aria-selected="true"]');
          if (selected) selected.focus();
        }
      });
      paletteMenu.addEventListener("click", function (event) {
        const option = event.target.closest("[data-plot-palette]");
        if (!option) return;
        preferences().palette = PALETTES.includes(option.dataset.plotPalette)
          ? option.dataset.plotPalette : "plotsrv";
        savePreferences();
        closePaletteMenu(true);
        renderControls();
        refreshTablePlot();
      });
      paletteMenu.addEventListener("keydown", function (event) {
        const options = Array.from(paletteMenu.querySelectorAll("[data-plot-palette]"));
        const index = options.indexOf(document.activeElement);
        if (event.key === "Escape") { event.preventDefault(); closePaletteMenu(true); return; }
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        const next = event.key === "ArrowDown" ? (index + 1) % options.length : (index - 1 + options.length) % options.length;
        options[next].focus();
      });
      document.addEventListener("click", function (event) {
        const root = document.getElementById("table-plot-palette");
        if (root && !root.contains(event.target)) closePaletteMenu(false);
      });
      paletteButton.dataset.plotsrvBound = "1";
    }

    if (reset && !reset.dataset.plotsrvBound) {
      reset.addEventListener("click", function () {
        state.tablePlotPreferences = defaultPreferences();
        normalizePreferences();
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      reset.dataset.plotsrvBound = "1";
    }
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
      scheduleTablePlotRefresh();
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
      state.tablePlotConfigured = false;
    }

    bindControls();
    renderControls();
    applyMode(currentMode(), {
      redraw: false,
      deferPlotRefresh: capabilities().liveUpdates && state.tablePlotConfigured === true,
    });
    state.tablePlotConfigured = true;
  }

  function plotExportFilename(extension) {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "plot").replace(/[^\w.-]+/g, "_");
    return base + "-plot-" + stamp + "." + extension;
  }

  function downloadablePlotSvg() {
    const figure = document.querySelector("#table-plot-output .ps-table-plot[data-plot-state='rendered']");
    const source = figure && figure.querySelector("svg");
    if (!figure || !source || typeof XMLSerializer === "undefined") return null;
    const clone = source.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const viewBox = (clone.getAttribute("viewBox") || "0 0 820 450").split(/\s+/).map(Number);
    clone.setAttribute("width", String(viewBox[2] || 820));
    clone.setAttribute("height", String(viewBox[3] || 450));
    const sourceNodes = [source].concat(Array.from(source.querySelectorAll("*")));
    const cloneNodes = [clone].concat(Array.from(clone.querySelectorAll("*")));
    sourceNodes.forEach(function (node, index) {
      const target = cloneNodes[index];
      if (!target || typeof window.getComputedStyle !== "function") return;
      const style = window.getComputedStyle(node);
      ["fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "font-family", "font-size", "font-weight", "opacity"].forEach(function (property) {
        const value = style.getPropertyValue(property);
        if (value) target.style.setProperty(property, value);
      });
      target.removeAttribute("tabindex");
    });
    const titleNode = figure.querySelector(".ps-table-plot__title");
    const legendItems = Array.from(figure.querySelectorAll(".ps-table-plot__legend-item"));
    let legendX = 16;
    let legendY = 48;
    const legendLayout = [];
    legendItems.forEach(function (item) {
      const width = Math.max(72, item.textContent.length * 7 + 30);
      if (legendX + width > (viewBox[2] || 820) - 16) {
        legendX = 16;
        legendY += 22;
      }
      legendLayout.push({item: item, x: legendX, y: legendY});
      legendX += width;
    });
    const headerHeight = legendItems.length ? legendY + 18 : 42;
    const drawing = document.createElementNS("http://www.w3.org/2000/svg", "g");
    drawing.setAttribute("transform", "translate(0 " + headerHeight + ")");
    while (clone.firstChild) drawing.appendChild(clone.firstChild);
    clone.appendChild(drawing);
    clone.setAttribute("viewBox", "0 0 " + (viewBox[2] || 820) + " " + ((viewBox[3] || 450) + headerHeight));
    clone.setAttribute("height", String((viewBox[3] || 450) + headerHeight));
    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("x", "16");
    title.setAttribute("y", "25");
    title.setAttribute("font-size", "16");
    title.setAttribute("font-weight", "600");
    title.setAttribute("fill", titleNode && typeof window.getComputedStyle === "function" ? window.getComputedStyle(titleNode).color : "#25282a");
    title.textContent = titleNode ? titleNode.textContent : "plotsrv plot";
    clone.insertBefore(title, drawing);
    legendLayout.forEach(function (entry) {
      const swatch = entry.item.querySelector(".ps-table-plot__legend-swatch");
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", String(entry.x + 6));
      circle.setAttribute("cy", String(entry.y - 4));
      circle.setAttribute("r", "5");
      circle.setAttribute("fill", swatch && typeof window.getComputedStyle === "function" ? window.getComputedStyle(swatch).backgroundColor : "#d55970");
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", String(entry.x + 16));
      text.setAttribute("y", String(entry.y));
      text.setAttribute("font-size", "12");
      text.setAttribute("fill", title.getAttribute("fill"));
      text.textContent = entry.item.textContent;
      clone.insertBefore(circle, drawing);
      clone.insertBefore(text, drawing);
    });
    const background = typeof window.getComputedStyle === "function"
      ? window.getComputedStyle(figure).backgroundColor : "#ffffff";
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", String(viewBox[0] || 0));
    rect.setAttribute("y", String(viewBox[1] || 0));
    rect.setAttribute("width", String(viewBox[2] || 820));
    rect.setAttribute("height", String((viewBox[3] || 450) + headerHeight));
    rect.setAttribute("fill", background || "#ffffff");
    clone.insertBefore(rect, clone.firstChild);
    return {
      text: new XMLSerializer().serializeToString(clone),
      width: viewBox[2] || 820,
      height: (viewBox[3] || 450) + headerHeight,
    };
  }

  function downloadBlob(filename, blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function exportTablePlot(format) {
    const exported = downloadablePlotSvg();
    if (!exported) return false;
    const svgBlob = new Blob([exported.text], {type: "image/svg+xml;charset=utf-8"});
    if (format === "svg") {
      downloadBlob(plotExportFilename("svg"), svgBlob);
      return true;
    }
    if (format !== "png") return false;
    const imageUrl = URL.createObjectURL(svgBlob);
    const image = new Image();
    image.onload = function () {
      const canvas = document.createElement("canvas");
      canvas.width = exported.width * 2;
      canvas.height = exported.height * 2;
      const context = canvas.getContext("2d");
      if (!context) { URL.revokeObjectURL(imageUrl); return; }
      context.scale(2, 2);
      context.drawImage(image, 0, 0, exported.width, exported.height);
      URL.revokeObjectURL(imageUrl);
      canvas.toBlob(function (blob) {
        if (blob) downloadBlob(plotExportFilename("png"), blob);
      }, "image/png");
    };
    image.onerror = function () {
      URL.revokeObjectURL(imageUrl);
      if (typeof core.setStatusMessage === "function") core.setStatusMessage("Unable to export this plot as PNG.");
    };
    image.src = imageUrl;
    return true;
  }

  core.configureTablePlotSurface = configureTablePlotSurface;
  core.refreshTablePlot = scheduleTablePlotRefresh;
  core.refreshTablePlotImmediately = refreshTablePlot;
  core.cancelScheduledTablePlotRefresh = cancelScheduledTablePlotRefresh;
  core.setTablePlotMode = applyMode;
  core.setTablePlotCapabilities = setTablePlotCapabilities;
  core.setTablePlotSummaryRows = setTablePlotSummaryRows;
  core.setPlotControlsCollapsed = setPlotControlsCollapsed;
  core.exportTablePlot = exportTablePlot;
})();
