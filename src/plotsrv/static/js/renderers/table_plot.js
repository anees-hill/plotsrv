(function () {
  "use strict";
  window.PLOTSRV = window.PLOTSRV || {core: {}, renderers: {}, state: {}, config: {}};
  const core = window.PLOTSRV.core;
  const config = window.PLOTSRV.config;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const configuredPointLimit = Number(config.tablePlotMaxPoints);
  const TABLE_PLOT_LIMITS = {
    maxSourceRows: 100000,
    maxPoints: Number.isSafeInteger(configuredPointLimit)
      ? Math.max(1, Math.min(25000, configuredPointLimit))
      : 5000,
    maxCategories: 40,
    maxSeries: 8,
  };
  const TABLE_PLOT_PALETTES = {
    plotsrv: {name: "plotsrv", kind: "discrete", colours: ["#d55970", "#7a3950", "#e58a5f", "#4e8291", "#8e6aae", "#d4a72c"], darkColours: ["#f07b91", "#d9a0b2", "#f2a47c", "#72b7c7", "#b49ad4", "#e1c15c"]},
    accessible: {name: "Accessible", kind: "discrete", colours: ["#0072b2", "#e69f00", "#009e73", "#cc79a7", "#d55e00", "#56b4e9", "#f0e442", "#000000"], darkColours: ["#56b4e9", "#f0b84f", "#4bc99c", "#e69ac8", "#ef8354", "#8bd3f2", "#f5e96b", "#e7edf2"]},
    ocean: {name: "Ocean", kind: "discrete", colours: ["#2166ac", "#0891b2", "#0f766e", "#60a5fa", "#5ab4ac", "#164e63"], darkColours: ["#60a5fa", "#22d3ee", "#2dd4bf", "#93c5fd", "#7dd3fc", "#5eead4"]},
    forest: {name: "Forest", kind: "discrete", colours: ["#1b7837", "#5aae61", "#8c6d31", "#4d9221", "#7f9f35", "#356859"], darkColours: ["#6ccf7f", "#a3d977", "#d1aa62", "#73c991", "#b4d568", "#83b9a4"]},
    sunset: {name: "Sunset", kind: "discrete", colours: ["#b2182b", "#ef8a62", "#f1a340", "#d6604d", "#9970ab", "#c45d38"], darkColours: ["#f87171", "#fb9a78", "#f7bd65", "#ef7770", "#c4a2df", "#ee9465"]},
    violet: {name: "Violet", kind: "discrete", colours: ["#6a51a3", "#807dba", "#54278f", "#9e6ab0", "#8c6bb1", "#b05c91"], darkColours: ["#a78bfa", "#c4b5fd", "#b89af5", "#d6a3e3", "#c6a9df", "#e19bc5"]},
    neutral: {name: "Neutral", kind: "discrete", colours: ["#374151", "#6b7280", "#78716c", "#4b5563", "#9ca3af", "#57534e"], darkColours: ["#d1d5db", "#9ca3af", "#c4b8ad", "#b8c0cc", "#e5e7eb", "#aaa39d"]},
    viridis: {name: "Viridis", kind: "continuous", colours: ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"], darkColours: ["#7b2f8e", "#6677b5", "#42a1b4", "#40c39d", "#98dc70", "#f5e85c"]},
    plasma: {name: "Plasma", kind: "continuous", colours: ["#0d0887", "#6a00a8", "#b12a90", "#e16462", "#fca636", "#f0f921"], darkColours: ["#5b55c7", "#9b4dcc", "#db68b2", "#f18879", "#fcb95b", "#f3ef64"]},
    blues: {name: "Blues", kind: "continuous", colours: ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c"], darkColours: ["#d7e8f7", "#b9d8ef", "#89bee1", "#58a0cc", "#347eb2", "#8fc7ed"]},
    ember: {name: "Ember", kind: "continuous", colours: ["#fff5eb", "#fdd0a2", "#fdae6b", "#fd8d3c", "#e6550d", "#a63603"], darkColours: ["#ffe0c2", "#ffc489", "#f9a45d", "#ef8240", "#df6230", "#f29a68"]},
  };

  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }
  function html(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function svg(tag, attrs, text) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { if (attrs[key] != null) node.setAttribute(key, String(attrs[key])); });
    if (text != null) node.textContent = text;
    return node;
  }
  function svgText(root, attrs, text) { const node = svg("text", attrs, text); root.appendChild(node); return node; }
  function plural(n, word) { return n === 1 ? word : word + "s"; }
  function formatNumber(value) {
    if (!Number.isFinite(value)) return "";
    if (Math.abs(value) >= 1000000 || (value !== 0 && Math.abs(value) < 0.001)) return value.toExponential(2);
    return new Intl.NumberFormat(undefined, {maximumFractionDigits: 3}).format(value);
  }
  function formatTime(value, span) {
    const opts = span < 86400000 ? {hour: "2-digit", minute: "2-digit", second: "2-digit"} :
      span < 31536000000 ? {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"} :
        {year: "numeric", month: "short", day: "numeric"};
    return new Intl.DateTimeFormat(undefined, opts).format(new Date(value));
  }
  function label(field) { return typeof field === "string" && field ? field : "selected field"; }
  function missing(value) { return value == null || (typeof value === "string" && value.trim() === ""); }
  function numberValue(value) {
    if (missing(value)) return {kind: "missing"};
    if (typeof value === "boolean" || typeof value === "bigint") return {kind: "invalid"};
    const n = typeof value === "number" ? value : Number(value);
    return Number.isFinite(n) ? {kind: "value", value: n} : {kind: "invalid"};
  }
  function dateValue(value) {
    if (missing(value)) return {kind: "missing"};
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}(?:[T ][^\s]+)?/.test(value.trim())) return {kind: "invalid"};
    const n = Date.parse(value);
    return Number.isFinite(n) ? {kind: "value", value: n} : {kind: "invalid"};
  }
  function categoryValue(value) {
    if (missing(value)) return {kind: "missing"};
    if ((typeof value === "number" && !Number.isFinite(value)) || typeof value === "object" || typeof value === "function" || typeof value === "symbol") return {kind: "invalid"};
    return {kind: "value", key: typeof value + ":" + String(value), label: String(value)};
  }
  function rowsFor(settings) {
    if (Array.isArray(settings.rows)) return settings.rows.slice();
    if (typeof core.getCurrentFilteredLoadedRows === "function") {
      const rows = core.getCurrentFilteredLoadedRows();
      if (Array.isArray(rows)) return rows;
    }
    return [];
  }
  function scopeText(settings, rows, plotted) {
    let text = settings.scopeKind === "summary"
      ? "Plot scope: " + rows + " loaded derived summary " + plural(rows, "window") + "; " + plotted + " " + plural(plotted, "value") + " plotted. These are selected aggregate records, not source log rows."
      : "Plot scope: " + rows + " loaded " + plural(rows, "row") + " passing the current browser filters; " + plotted + " " + plural(plotted, "value") + " plotted.";
    if (typeof settings.scopeDescription === "string" && settings.scopeDescription.trim()) text += " " + settings.scopeDescription.trim();
    return text;
  }
  function skipped(missingCount, invalidCount) {
    const parts = [];
    if (missingCount) parts.push(missingCount + " " + plural(missingCount, "row") + " with missing values");
    if (invalidCount) parts.push(invalidCount + " " + plural(invalidCount, "row") + " with invalid values");
    return parts.length ? "Excluded " + parts.join(" and ") + "." : "";
  }
  function notice(container, reason, detail, settings, rowCount, actions) {
    clear(container);
    const root = html("section", "ps-table-plot__notice ps-table-plot__notice--refused");
    root.dataset.plotState = "refused";
    root.appendChild(html("h2", "ps-table-plot__notice-title", "Plot not rendered"));
    root.appendChild(html("p", "ps-table-plot__notice-detail", detail));
    if (Array.isArray(actions) && actions.length) {
      const actionRoot = html("div", "ps-table-plot__notice-actions");
      actions.forEach(function (action) {
        if (!action || typeof action.onClick !== "function") return;
        const button = html("button", "ps-btn ps-table-plot__notice-action", action.label);
        button.type = "button";
        button.addEventListener("click", action.onClick);
        actionRoot.appendChild(button);
      });
      root.appendChild(actionRoot);
    }
    root.appendChild(html("p", "ps-table-plot__scope", scopeText(settings, rowCount, 0)));
    container.appendChild(root);
    return {ok: false, reason: reason, rowCount: rowCount, plottedCount: 0};
  }
  function frame(container, type, automaticTitle, settings) {
    clear(container);
    const figure = html("figure", "ps-table-plot");
    figure.dataset.plotType = type;
    figure.dataset.plotState = "rendered";
    figure.dataset.plotPalette = settings.palette || "plotsrv";
    figure.dataset.plotTitleAlign = settings.titleAlign === "center" ? "center" : "left";
    figure.appendChild(html("h2", "ps-table-plot__title", settings.title || automaticTitle));
    const tip = html("div", "ps-table-plot__tooltip");
    tip.hidden = true;
    tip.setAttribute("role", "tooltip");
    figure.appendChild(tip);
    container.appendChild(figure);
    return figure;
  }
  function summary(figure, detail, scope) {
    if (detail) figure.appendChild(html("p", "ps-table-plot__detail", detail));
    figure.appendChild(html("figcaption", "ps-table-plot__scope", scope));
  }
  function tooltip(mark, figure, text, tabbable) {
    mark.appendChild(svg("title", {}, text));
    if (tabbable) mark.setAttribute("tabindex", "0");
    const tip = figure.querySelector(".ps-table-plot__tooltip");
    if (!tip || typeof mark.addEventListener !== "function") return;
    function show(event) {
      tip.textContent = text;
      tip.hidden = false;
      const box = figure.getBoundingClientRect ? figure.getBoundingClientRect() : {left: 0, top: 0};
      tip.style.left = Math.max(8, (event && Number.isFinite(event.clientX) ? event.clientX - box.left : 18) + 10) + "px";
      tip.style.top = Math.max(42, (event && Number.isFinite(event.clientY) ? event.clientY - box.top : 42) + 10) + "px";
      mark.classList.add("is-highlighted");
    }
    function hide() { tip.hidden = true; mark.classList.remove("is-highlighted"); }
    ["mouseenter", "mousemove", "focus"].forEach(function (name) { mark.addEventListener(name, show); });
    ["mouseleave", "blur"].forEach(function (name) { mark.addEventListener(name, hide); });
  }
  function domain(values, includeZero, logarithmic) {
    let low = Math.min.apply(null, values);
    let high = Math.max.apply(null, values);
    if (includeZero && !logarithmic) { low = Math.min(0, low); high = Math.max(0, high); }
    if (low === high) { if (logarithmic) { low /= 10; high *= 10; } else { const pad = low === 0 ? 1 : Math.abs(low) * 0.1; low -= pad; high += pad; } }
    return {minimum: low, maximum: high};
  }
  function scale(domainValue, start, end, logarithmic) {
    const transform = logarithmic ? Math.log10 : function (v) { return v; };
    const low = transform(domainValue.minimum);
    const span = transform(domainValue.maximum) - low;
    return function (value) { return start + ((transform(value) - low) / span) * (end - start); };
  }
  function darkThemeActive() {
    const theme = document.documentElement && document.documentElement.getAttribute("data-theme");
    return theme === "dark" || (theme === "system" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function paletteFor(settings) {
    const selected = TABLE_PLOT_PALETTES[settings.palette] || TABLE_PLOT_PALETTES.plotsrv;
    return {name: selected.name, kind: selected.kind || "discrete", colours: darkThemeActive() ? selected.darkColours : selected.colours};
  }
  function paletteColour(palette, index, count) {
    if (palette.kind === "continuous" && count > 1) {
      const position = index * (palette.colours.length - 1) / (count - 1);
      const lower = Math.max(0, Math.min(palette.colours.length - 1, Math.floor(position)));
      const upper = Math.min(palette.colours.length - 1, lower + 1);
      const fraction = position - lower;
      const from = palette.colours[lower].slice(1).match(/.{2}/g).map(function (part) { return parseInt(part, 16); });
      const to = palette.colours[upper].slice(1).match(/.{2}/g).map(function (part) { return parseInt(part, 16); });
      const channels = from.map(function (channel, channelIndex) {
        return Math.round(channel + (to[channelIndex] - channel) * fraction).toString(16).padStart(2, "0");
      });
      return "#" + channels.join("");
    }
    return palette.colours[index % palette.colours.length];
  }
  function seriesFor(rows, field) {
    if (!field) return [{key: "__all__", label: "All rows"}];
    const found = new Map();
    rows.forEach(function (row) { const value = categoryValue(row ? row[field] : null); if (value.kind === "value" && !found.has(value.key)) found.set(value.key, value); });
    return Array.from(found.values());
  }
  function legend(series, palette, position) {
    if (series.length <= 1) return null;
    const root = html("div", "ps-table-plot__legend ps-table-plot__legend--" + (position || "top"));
    root.setAttribute("aria-label", "Plot series");
    series.forEach(function (item, index) {
      const entry = html("span", "ps-table-plot__legend-item", item.label);
      entry.tabIndex = 0;
      entry.title = item.label;
      const swatch = html("span", "ps-table-plot__legend-swatch");
      swatch.style.backgroundColor = paletteColour(palette, index, series.length);
      entry.insertBefore(swatch, entry.firstChild);
      root.appendChild(entry);
    });
    return root;
  }
  function chartBody(figure, drawing, chartLegend) {
    const body = html("div", "ps-table-plot__body" + (chartLegend ? " ps-table-plot__body--legend-" + chartLegend.className.split("--").pop() : ""));
    if (chartLegend && chartLegend.classList.contains("ps-table-plot__legend--top")) body.appendChild(chartLegend);
    body.appendChild(drawing);
    if (chartLegend && !chartLegend.parentNode) body.appendChild(chartLegend);
    figure.appendChild(body);
  }

  function accumulator() { return {count: 0, sum: 0, min: Infinity, max: -Infinity}; }
  function add(acc, value, aggregation) { acc.count += 1; if (aggregation !== "count") { acc.sum += value; acc.min = Math.min(acc.min, value); acc.max = Math.max(acc.max, value); } }
  function aggregate(acc, aggregation) {
    if (!acc || !acc.count) return 0;
    return aggregation === "sum" ? acc.sum : aggregation === "mean" ? acc.sum / acc.count : aggregation === "min" ? acc.min : aggregation === "max" ? acc.max : acc.count;
  }
  function merge(into, from) { into.count += from.count; into.sum += from.sum; into.min = Math.min(into.min, from.min); into.max = Math.max(into.max, from.max); }
  function barData(rows, settings, series) {
    const map = new Map();
    let missingCount = 0;
    let invalidCount = 0;
    rows.forEach(function (row) {
      const category = categoryValue(row ? row[settings.categoryField] : null);
      const group = settings.seriesField ? categoryValue(row ? row[settings.seriesField] : null) : {kind: "value", key: "__all__"};
      const value = settings.aggregation === "count" ? {kind: "value", value: 1} : numberValue(row ? row[settings.valueField] : null);
      if (category.kind === "missing" || group.kind === "missing" || value.kind === "missing") { missingCount += 1; return; }
      if (category.kind !== "value" || group.kind !== "value" || value.kind !== "value") { invalidCount += 1; return; }
      if (!map.has(category.key)) map.set(category.key, {label: category.label, values: new Map()});
      const item = map.get(category.key);
      if (!item.values.has(group.key)) item.values.set(group.key, accumulator());
      add(item.values.get(group.key), value.value, settings.aggregation);
    });
    let categories = Array.from(map.values());
    function score(item) { return series.reduce(function (total, group) { return total + aggregate(item.values.get(group.key), settings.aggregation); }, 0); }
    categories.forEach(function (item) { item.score = score(item); });
    const order = settings.sort || "value-desc";
    function compare(a, b) {
      if (order === "value-asc") return a.score - b.score;
      if (order === "category-asc") return a.label.localeCompare(b.label);
      if (order === "category-desc") return b.label.localeCompare(a.label);
      return b.score - a.score;
    }
    const limit = Math.max(1, Math.min(TABLE_PLOT_LIMITS.maxCategories, Number(settings.categoryLimit) || 10));
    if (categories.length > limit) {
      const ranked = categories.slice().sort(function (a, b) { return b.score - a.score; });
      const selected = ranked.slice(0, limit);
      const remainder = ranked.slice(limit);
      const other = {label: "Other", values: new Map(), score: 0, isOther: true};
      series.forEach(function (group) {
        const combined = accumulator();
        remainder.forEach(function (item) { if (item.values.has(group.key)) merge(combined, item.values.get(group.key)); });
        if (combined.count) other.values.set(group.key, combined);
      });
      other.score = score(other);
      categories = selected.sort(compare).concat([other]);
    } else {
      categories.sort(compare);
    }
    return {categories: categories, missing: missingCount, invalid: invalidCount, plotted: rows.length - missingCount - invalidCount};
  }
  function drawBars(figure, data, series, settings, palette) {
    const rowHeight = Math.max(34, series.length * 18 + 16);
    const d = {width: 860, height: Math.max(240, 92 + data.categories.length * rowHeight), left: 220, right: 72, top: 28, bottom: 46};
    const right = d.width - d.right;
    const bottom = d.height - d.bottom;
    let min = 0, max = 0;
    data.categories.forEach(function (category) {
      const values = series.map(function (group) { return aggregate(category.values.get(group.key), settings.aggregation); });
      if (settings.display === "stacked" && series.length > 1) {
        min = Math.min(min, values.filter(function (v) { return v < 0; }).reduce(function (a, b) { return a + b; }, 0));
        max = Math.max(max, values.filter(function (v) { return v > 0; }).reduce(function (a, b) { return a + b; }, 0));
      } else { min = Math.min.apply(null, [min].concat(values)); max = Math.max.apply(null, [max].concat(values)); }
    });
    if (min === max) max = min + 1;
    const x = scale({minimum: min, maximum: max}, d.left, right, false);
    const zero = x(0);
    const drawing = svg("svg", {viewBox: "0 0 " + d.width + " " + d.height, role: "img", "aria-label": "Bar chart for " + label(settings.categoryField), class: "ps-table-plot__svg ps-table-plot__svg--bar"});
    for (let index = 0; index <= 4; index += 1) {
      const value = min + (max - min) * index / 4;
      const xx = x(value);
      drawing.appendChild(svg("line", {x1: xx, y1: d.top, x2: xx, y2: bottom, class: "ps-table-plot__grid-line"}));
      svgText(drawing, {x: xx, y: bottom + 22, "text-anchor": "middle", class: "ps-table-plot__tick"}, formatNumber(value));
    }
    drawing.appendChild(svg("line", {x1: zero, y1: d.top, x2: zero, y2: bottom, class: "ps-table-plot__axis"}));
    const band = (bottom - d.top) / data.categories.length;
    data.categories.forEach(function (category, categoryIndex) {
      const center = d.top + band * categoryIndex + band / 2;
      svgText(drawing, {x: d.left - 10, y: center, "text-anchor": "end", "dominant-baseline": "middle", class: "ps-table-plot__category"}, category.label);
      let positive = 0, negative = 0;
      series.forEach(function (group, seriesIndex) {
        const values = category.values.get(group.key);
        const value = aggregate(values, settings.aggregation);
        const grouped = settings.display !== "stacked" || series.length === 1;
        const height = grouped ? Math.max(7, Math.min(16, (band - 8) / series.length)) : Math.max(12, Math.min(22, band - 10));
        const y = grouped ? center - series.length * height / 2 + seriesIndex * height : center - height / 2;
        const start = grouped ? 0 : value >= 0 ? positive : negative;
        const end = start + value;
        if (!grouped) { if (value >= 0) positive = end; else negative = end; }
        const x1 = x(start), x2 = x(end);
        const colourIndex = series.length > 1 ? seriesIndex : categoryIndex;
        const colourCount = series.length > 1 ? series.length : data.categories.length;
        const mark = svg("rect", {x: Math.min(x1, x2), y: y, width: Math.max(1, Math.abs(x2 - x1)), height: height - 2, rx: 2, fill: paletteColour(palette, colourIndex, colourCount), class: "ps-table-plot__bar"});
        tooltip(mark, figure, category.label + (series.length > 1 ? " · " + group.label : "") + ": " + formatNumber(value) + (settings.aggregation === "count" || !values ? "" : " · " + values.count + " " + plural(values.count, "row")), true);
        drawing.appendChild(mark);
      });
    });
    svgText(drawing, {x: d.left + (right - d.left) / 2, y: d.height - 8, "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.xLabel || (settings.aggregation === "count" ? "Count" : label(settings.valueField)));
    if (settings.yLabel) svgText(drawing, {x: 18, y: d.top + (bottom - d.top) / 2, transform: "rotate(-90 18 " + (d.top + (bottom - d.top) / 2) + ")", "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.yLabel);
    chartBody(figure, drawing, legend(series, palette, settings.legend));
  }

  function pointData(rows, settings, series) {
    const groups = new Map();
    series.forEach(function (group) { groups.set(group.key, {key: group.key, label: group.label, points: []}); });
    let missingCount = 0, invalidCount = 0;
    rows.forEach(function (row, index) {
      const x = settings.xKind === "datetime" ? dateValue(row ? row[settings.xField] : null) : numberValue(row ? row[settings.xField] : null);
      const y = numberValue(row ? row[settings.yField] : null);
      const group = settings.seriesField ? categoryValue(row ? row[settings.seriesField] : null) : {kind: "value", key: "__all__"};
      if (x.kind === "missing" || y.kind === "missing" || group.kind === "missing") { missingCount += 1; return; }
      if (x.kind !== "value" || y.kind !== "value" || group.kind !== "value" || (settings.xScale === "log" && x.value <= 0) || (settings.yScale === "log" && y.value <= 0)) { invalidCount += 1; return; }
      if (groups.has(group.key)) groups.get(group.key).points.push({x: x.value, y: y.value, index: index});
    });
    const list = Array.from(groups.values()).filter(function (group) { return group.points.length > 0; });
    return {groups: list, points: list.flatMap(function (group) { return group.points; }), missing: missingCount, invalid: invalidCount};
  }
  function limitedPointData(data, limit, mode) {
    if (!data || data.points.length <= limit) return data;
    const ordered = data.points.slice().sort(function (a, b) { return a.index - b.index; });
    let selected;
    if (mode === "first") {
      selected = ordered.slice(0, limit);
    } else if (mode === "latest") {
      selected = ordered.slice(-limit);
    } else {
      selected = Array.from({length: limit}, function (_, index) {
        if (limit === 1) return ordered[0];
        return ordered[Math.round(index * (ordered.length - 1) / (limit - 1))];
      });
    }
    const retained = new Set(selected);
    return {
      groups: data.groups.map(function (group) {
        return {
          key: group.key,
          label: group.label,
          points: group.points.filter(function (point) { return retained.has(point); }),
        };
      }).filter(function (group) { return group.points.length > 0; }),
      points: selected,
      missing: data.missing,
      invalid: data.invalid,
      sampledFrom: data.points.length,
      selectionMode: mode,
    };
  }
  function axes(drawing, d, xDomain, yDomain, settings) {
    const right = d.width - d.right, bottom = d.height - d.bottom;
    const x = scale(xDomain, d.left, right, settings.xScale === "log");
    const y = scale(yDomain, bottom, d.top, settings.yScale === "log");
    const span = xDomain.maximum - xDomain.minimum;
    for (let index = 0; index <= 4; index += 1) {
      const fraction = index / 4;
      const xv = settings.xScale === "log" ? Math.pow(10, Math.log10(xDomain.minimum) + (Math.log10(xDomain.maximum) - Math.log10(xDomain.minimum)) * fraction) : xDomain.minimum + span * fraction;
      const yv = settings.yScale === "log" ? Math.pow(10, Math.log10(yDomain.minimum) + (Math.log10(yDomain.maximum) - Math.log10(yDomain.minimum)) * fraction) : yDomain.minimum + (yDomain.maximum - yDomain.minimum) * fraction;
      const xx = x(xv), yy = y(yv);
      drawing.appendChild(svg("line", {x1: xx, y1: d.top, x2: xx, y2: bottom, class: "ps-table-plot__grid-line"}));
      drawing.appendChild(svg("line", {x1: d.left, y1: yy, x2: right, y2: yy, class: "ps-table-plot__grid-line"}));
      svgText(drawing, {x: xx, y: bottom + 22, "text-anchor": "middle", class: "ps-table-plot__tick"}, settings.xKind === "datetime" ? formatTime(xv, span) : formatNumber(xv));
      svgText(drawing, {x: d.left - 10, y: yy + 4, "text-anchor": "end", class: "ps-table-plot__tick"}, formatNumber(yv));
    }
    drawing.appendChild(svg("line", {x1: d.left, y1: d.top, x2: d.left, y2: bottom, class: "ps-table-plot__axis"}));
    drawing.appendChild(svg("line", {x1: d.left, y1: bottom, x2: right, y2: bottom, class: "ps-table-plot__axis"}));
    svgText(drawing, {x: d.left + (right - d.left) / 2, y: d.height - 10, "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.xLabel || label(settings.xField));
    svgText(drawing, {x: 18, y: d.top + (bottom - d.top) / 2, transform: "rotate(-90 18 " + (d.top + (bottom - d.top) / 2) + ")", "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.yLabel || label(settings.yField));
    return {x: x, y: y};
  }
  function drawPoints(figure, type, data, settings, palette) {
    const d = {width: 820, height: 450, left: 82, right: 34, top: 28, bottom: 68};
    const xDomain = domain(data.points.map(function (point) { return point.x; }), settings.zeroBaseline && settings.xKind !== "datetime", settings.xScale === "log");
    const yDomain = domain(data.points.map(function (point) { return point.y; }), settings.zeroBaseline, settings.yScale === "log");
    const drawing = svg("svg", {viewBox: "0 0 " + d.width + " " + d.height, role: "img", "aria-label": (type === "line" ? "Line" : "Scatter") + " plot of " + label(settings.yField) + " by " + label(settings.xField), class: "ps-table-plot__svg ps-table-plot__svg--points"});
    const scales = axes(drawing, d, xDomain, yDomain, settings);
    data.groups.forEach(function (group, index) {
      const points = type === "line" ? group.points.slice().sort(function (a, b) { return a.x - b.x || a.index - b.index; }) : group.points;
      const colour = paletteColour(palette, index, data.groups.length);
      if (type === "line" && points.length > 1) drawing.appendChild(svg("polyline", {points: points.map(function (point) { return scales.x(point.x) + "," + scales.y(point.y); }).join(" "), fill: "none", stroke: colour, class: "ps-table-plot__line"}));
      if (type === "scatter" || settings.showPoints !== false) points.forEach(function (point) {
        const mark = svg("circle", {cx: scales.x(point.x), cy: scales.y(point.y), r: type === "line" ? 2.8 : 3.5, fill: type === "line" ? "var(--ps-surface, #fff)" : colour, stroke: colour, class: "ps-table-plot__point"});
        const xText = settings.xKind === "datetime" ? formatTime(point.x, xDomain.maximum - xDomain.minimum) : formatNumber(point.x);
        tooltip(mark, figure, (group.label !== "All rows" ? group.label + " · " : "") + (settings.xLabel || settings.xField) + ": " + xText + " · " + (settings.yLabel || settings.yField) + ": " + formatNumber(point.y), false);
        drawing.appendChild(mark);
      });
    });
    chartBody(figure, drawing, legend(data.groups, palette, settings.legend));
  }

  function histogramData(rows, settings) {
    const values = [];
    let missingCount = 0, invalidCount = 0;
    rows.forEach(function (row) { const value = numberValue(row ? row[settings.histogramField] : null); if (value.kind === "missing") missingCount += 1; else if (value.kind !== "value") invalidCount += 1; else values.push(value.value); });
    if (!values.length) return {values: values, bins: [], missing: missingCount, invalid: invalidCount};
    const min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    const requested = settings.bins === "auto" ? Math.ceil(Math.sqrt(values.length)) : Number(settings.bins);
    const count = min === max ? 1 : Math.max(1, Math.min(40, requested || 10));
    const width = min === max ? 1 : (max - min) / count;
    const start = min === max ? min - 0.5 : min;
    const bins = Array.from({length: count}, function (_, index) { return {start: start + width * index, end: start + width * (index + 1), count: 0}; });
    values.forEach(function (value) { bins[Math.min(count - 1, Math.floor((value - start) / width))].count += 1; });
    return {values: values, bins: bins, missing: missingCount, invalid: invalidCount};
  }
  function drawHistogram(figure, data, settings, palette) {
    const d = {width: 820, height: 420, left: 76, right: 30, top: 26, bottom: 66};
    const bottom = d.height - d.bottom, right = d.width - d.right;
    const max = Math.max.apply(null, data.bins.map(function (bin) { return bin.count; }).concat([1]));
    const x = scale({minimum: 0, maximum: data.bins.length}, d.left, right, false);
    const y = scale({minimum: 0, maximum: max}, bottom, d.top, false);
    const drawing = svg("svg", {viewBox: "0 0 " + d.width + " " + d.height, role: "img", "aria-label": "Histogram of " + label(settings.histogramField), class: "ps-table-plot__svg ps-table-plot__svg--histogram"});
    for (let index = 0; index <= 4; index += 1) { const value = max * index / 4, yy = y(value); drawing.appendChild(svg("line", {x1: d.left, y1: yy, x2: right, y2: yy, class: "ps-table-plot__grid-line"})); svgText(drawing, {x: d.left - 10, y: yy + 4, "text-anchor": "end", class: "ps-table-plot__tick"}, formatNumber(value)); }
    data.bins.forEach(function (bin, index) {
      const left = x(index), next = x(index + 1);
      const mark = svg("rect", {x: left + 1, y: y(bin.count), width: Math.max(1, next - left - 2), height: bottom - y(bin.count), fill: paletteColour(palette, index, data.bins.length), class: "ps-table-plot__bar"});
      tooltip(mark, figure, formatNumber(bin.start) + " to " + formatNumber(bin.end) + ": " + bin.count + " " + plural(bin.count, "row"), true);
      drawing.appendChild(mark);
      if (index === 0 || index === data.bins.length - 1 || index % Math.max(1, Math.floor(data.bins.length / 5)) === 0) svgText(drawing, {x: left, y: bottom + 21, "text-anchor": "middle", class: "ps-table-plot__tick"}, formatNumber(bin.start));
    });
    drawing.appendChild(svg("line", {x1: d.left, y1: bottom, x2: right, y2: bottom, class: "ps-table-plot__axis"}));
    svgText(drawing, {x: d.left + (right - d.left) / 2, y: d.height - 9, "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.xLabel || label(settings.histogramField));
    svgText(drawing, {x: 18, y: d.top + (bottom - d.top) / 2, transform: "rotate(-90 18 " + (d.top + (bottom - d.top) / 2) + ")", "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.yLabel || "Count");
    chartBody(figure, drawing, null);
  }

  function renderTablePlot(options) {
    const settings = options && typeof options === "object" ? options : {};
    if (!["count", "sum", "mean", "min", "max"].includes(settings.aggregation)) settings.aggregation = "count";
    if (!["grouped", "stacked"].includes(settings.display)) settings.display = "grouped";
    if (!["linear", "log"].includes(settings.xScale)) settings.xScale = "linear";
    if (!["linear", "log"].includes(settings.yScale)) settings.yScale = "linear";
    const container = settings.container;
    if (!container || typeof container.appendChild !== "function") return {ok: false, reason: "missing_container", rowCount: 0, plottedCount: 0};
    const rows = rowsFor(settings);
    if (!rows.length) {
      const resetActions = settings.scopeKind === "summary" || typeof settings.onResetFilters !== "function"
        ? []
        : [{label: "Reset filters", onClick: settings.onResetFilters}];
      return notice(container, "no_rows", settings.scopeKind === "summary" ? "No derived summary windows are currently loaded. Raw-table filters do not apply to this source." : "No loaded rows pass the current filters.", settings, 0, resetActions);
    }
    if (rows.length > TABLE_PLOT_LIMITS.maxSourceRows) return notice(container, "source_limit", "This plot has " + rows.length + " loaded values (limit " + TABLE_PLOT_LIMITS.maxSourceRows + "). Filter or narrow the source; no rows were sampled or plotted.", settings, rows.length);
    const type = String(settings.type || "bar").toLowerCase();
    const palette = paletteFor(settings);
    if (type === "bar") {
      if (!settings.categoryField) return notice(container, "missing_category_field", "Choose a categorical field for the bar chart.", settings, rows.length);
      if (settings.aggregation !== "count" && !settings.valueField) return notice(container, "missing_value_field", "Choose a numeric value field for this aggregation.", settings, rows.length);
      const series = seriesFor(rows, settings.seriesField);
      if (series.length > TABLE_PLOT_LIMITS.maxSeries) return notice(container, "series_limit", "This field has " + series.length + " series (limit " + TABLE_PLOT_LIMITS.maxSeries + "). Filter the table or choose a lower-cardinality field; no series were merged.", settings, rows.length);
      const data = barData(rows, settings, series);
      if (!data.plotted) return notice(container, "no_valid_values", "No usable values were found. " + skipped(data.missing, data.invalid), settings, rows.length);
      const activeSeries = series.filter(function (group) {
        return data.categories.some(function (category) { return category.values.has(group.key); });
      });
      const autoTitle = (settings.aggregation === "count" ? "Count" : settings.aggregation.charAt(0).toUpperCase() + settings.aggregation.slice(1) + " of " + label(settings.valueField)) + " by " + label(settings.categoryField);
      const figure = frame(container, type, autoTitle, settings);
      drawBars(figure, data, activeSeries, settings, palette);
      const scope = scopeText(settings, rows.length, data.plotted);
      summary(figure, skipped(data.missing, data.invalid), scope);
      return {ok: true, type: type, rowCount: rows.length, plottedCount: data.plotted, categoryCount: data.categories.length, seriesCount: activeSeries.length, scope: scope};
    }
    if (type === "histogram") {
      if (!settings.histogramField) return notice(container, "missing_numeric_field", "Choose a numeric field for the histogram.", settings, rows.length);
      const data = histogramData(rows, settings);
      if (!data.values.length) return notice(container, "no_valid_values", "No usable numeric values were found. " + skipped(data.missing, data.invalid), settings, rows.length);
      const figure = frame(container, type, "Distribution of " + label(settings.histogramField), settings);
      drawHistogram(figure, data, settings, palette);
      const scope = scopeText(settings, rows.length, data.values.length);
      summary(figure, skipped(data.missing, data.invalid), scope);
      return {ok: true, type: type, rowCount: rows.length, plottedCount: data.values.length, binCount: data.bins.length, scope: scope};
    }
    if (type !== "line" && type !== "scatter") return notice(container, "unknown_type", "Choose a bar, line, scatter, or histogram plot.", settings, rows.length);
    if (!settings.xField || !settings.yField) return notice(container, "missing_numeric_field", "Choose numeric or timestamp X and numeric Y fields for the " + type + " plot.", settings, rows.length);
    const series = seriesFor(rows, settings.seriesField);
    if (series.length > TABLE_PLOT_LIMITS.maxSeries) return notice(container, "series_limit", "This field has " + series.length + " series (limit " + TABLE_PLOT_LIMITS.maxSeries + "). Filter the table or choose a lower-cardinality field; no series were merged.", settings, rows.length);
    let data = pointData(rows, settings, series);
    if (!data.points.length) return notice(container, "no_valid_points", "No usable point pairs were found. Check log-scale values and selected fields. " + skipped(data.missing, data.invalid), settings, rows.length);
    const originalPointCount = data.points.length;
    const pointSelection = ["sample", "first", "latest"].includes(settings.pointSelection)
      ? settings.pointSelection
      : "refuse";
    if (originalPointCount > TABLE_PLOT_LIMITS.maxPoints && pointSelection === "refuse") {
      const actions = typeof settings.onPointLimitChoice === "function"
        ? [
            {label: "Plot even sample", onClick: function () { settings.onPointLimitChoice("sample"); }},
            {label: "Plot first " + TABLE_PLOT_LIMITS.maxPoints, onClick: function () { settings.onPointLimitChoice("first"); }},
            {label: "Plot latest " + TABLE_PLOT_LIMITS.maxPoints, onClick: function () { settings.onPointLimitChoice("latest"); }},
          ]
        : [];
      return notice(container, "point_limit", "This " + type + " plot has " + originalPointCount + " valid points (limit " + TABLE_PLOT_LIMITS.maxPoints + "). Filter the table or choose a bounded browser-side selection.", settings, rows.length, actions);
    }
    if (originalPointCount > TABLE_PLOT_LIMITS.maxPoints) {
      data = limitedPointData(data, TABLE_PLOT_LIMITS.maxPoints, pointSelection);
    }
    const figure = frame(container, type, (type === "line" ? "Line" : "Scatter") + " plot: " + label(settings.yField) + " by " + label(settings.xField), settings);
    drawPoints(figure, type, data, settings, palette);
    const scope = scopeText(settings, rows.length, data.points.length);
    const selectionDetail = data.sampledFrom
      ? "Showing " + data.points.length + " of " + data.sampledFrom + " valid points using " + (data.selectionMode === "sample" ? "an even sample" : data.selectionMode === "first" ? "the first values" : "the latest values") + "."
      : "";
    summary(figure, [selectionDetail, skipped(data.missing, data.invalid)].filter(Boolean).join(" "), scope);
    return {ok: true, type: type, rowCount: rows.length, plottedCount: data.points.length, sampledFrom: data.sampledFrom || null, pointSelection: data.selectionMode || null, seriesCount: data.groups.length, scope: scope};
  }

  core.TABLE_PLOT_LIMITS = TABLE_PLOT_LIMITS;
  core.TABLE_PLOT_PALETTES = TABLE_PLOT_PALETTES;
  core.renderTablePlot = renderTablePlot;
})();
