(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const config = window.PLOTSRV.config;

  // These limits deliberately refuse to render rather than selecting a
  // subset. Keep them local to the browser renderer: this feature must not
  // introduce a server-side charting or callback API.
  const TABLE_PLOT_LIMITS = {
    maxSourceRows: 10000,
    maxPoints: 1000,
    maxCategories: 40,
  };

  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

  function plural(count, singular, pluralText) {
    return count === 1 ? singular : (pluralText || singular + "s");
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function htmlElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function svgElement(tag, attributes, text) {
    const element = document.createElementNS(SVG_NAMESPACE, tag);
    const attrs = attributes || {};
    for (const key of Object.keys(attrs)) {
      if (attrs[key] != null) element.setAttribute(key, String(attrs[key]));
    }
    if (text != null) element.textContent = text;
    return element;
  }

  function appendSvgText(svg, attributes, text) {
    const label = svgElement("text", attributes, text);
    svg.appendChild(label);
    return label;
  }

  function formatNumber(value) {
    if (!Number.isFinite(value)) return "";
    const absolute = Math.abs(value);
    if ((absolute >= 1000000 || (absolute > 0 && absolute < 0.001))) {
      return value.toExponential(2);
    }
    return String(Math.round(value * 1000) / 1000);
  }

  function fieldLabel(field) {
    return typeof field === "string" && field ? field : "selected field";
  }

  function isMissing(value) {
    return value == null || (typeof value === "string" && value.trim() === "");
  }

  function numericValue(value) {
    if (isMissing(value)) return { kind: "missing" };
    if (typeof value === "boolean" || typeof value === "bigint") {
      return { kind: "invalid" };
    }
    const number = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(number)) return { kind: "invalid" };
    return { kind: "value", value: number };
  }

  function categoricalValue(value) {
    if (isMissing(value)) return { kind: "missing" };
    if (typeof value === "number" && !Number.isFinite(value)) {
      return { kind: "invalid" };
    }
    if (typeof value === "object" || typeof value === "function" ||
        typeof value === "symbol") {
      return { kind: "invalid" };
    }
    return {
      kind: "value",
      key: typeof value + ":" + String(value),
      label: String(value),
    };
  }

  function currentFilteredRows(settings) {
    if (Array.isArray(settings.rows)) return settings.rows.slice();
    if (typeof core.getCurrentFilteredLoadedRows === "function") {
      const rows = core.getCurrentFilteredLoadedRows();
      if (Array.isArray(rows)) return rows;
    }
    return [];
  }

  function sourceScopeText(settings, rowCount, plottedCount) {
    const isSummary = settings.scopeKind === "summary";
    let text = isSummary
      ? "Plot scope: " + rowCount + " loaded derived summary " +
        plural(rowCount, "window") + "; " + plottedCount + " " +
        plural(plottedCount, "value") +
        " plotted. These are selected aggregate records, not source log rows."
      : "Plot scope: " + rowCount + " loaded " +
        plural(rowCount, "row") +
        " passing the current browser filters; " + plottedCount + " " +
        plural(plottedCount, "value") + " plotted.";

    let sourceDescription =
      typeof settings.scopeDescription === "string"
        ? settings.scopeDescription.trim()
        : "";
    if (!sourceDescription && config.kind === "stream" && !isSummary) {
      sourceDescription =
        "Stream source: the retained recent raw observation window currently loaded in this table.";
    }
    if (sourceDescription) text += " " + sourceDescription;
    return text;
  }

  function skippedText(missing, invalid) {
    const details = [];
    if (missing > 0) {
      details.push(missing + " " + plural(missing, "row") + " with missing values");
    }
    if (invalid > 0) {
      details.push(invalid + " " + plural(invalid, "row") + " with invalid values");
    }
    return details.length ? "Excluded " + details.join(" and ") + "." : "";
  }

  function renderNotice(container, kind, title, detail, scope) {
    clearElement(container);
    const notice = htmlElement("section", "ps-table-plot__notice ps-table-plot__notice--" + kind);
    notice.dataset.plotState = kind;
    notice.appendChild(htmlElement("h2", "ps-table-plot__notice-title", title));
    if (detail) notice.appendChild(htmlElement("p", "ps-table-plot__notice-detail", detail));
    if (scope) notice.appendChild(htmlElement("p", "ps-table-plot__scope", scope));
    container.appendChild(notice);
  }

  function refusal(container, reason, detail, settings, rowCount) {
    const scope = sourceScopeText(settings, rowCount, 0);
    renderNotice(container, "refused", "Plot not rendered", detail, scope);
    return {
      ok: false,
      reason: reason,
      rowCount: rowCount,
      plottedCount: 0,
      scope: scope,
    };
  }

  function createFrame(container, type, title) {
    clearElement(container);
    const figure = htmlElement("figure", "ps-table-plot");
    figure.dataset.plotType = type;
    figure.dataset.plotState = "rendered";
    figure.appendChild(htmlElement("h2", "ps-table-plot__title", title));
    container.appendChild(figure);
    return figure;
  }

  function appendPlotSummary(figure, detail, scope) {
    if (detail) figure.appendChild(htmlElement("p", "ps-table-plot__detail", detail));
    figure.appendChild(htmlElement("figcaption", "ps-table-plot__scope", scope));
  }

  function appendBarAxes(svg, dimensions, maxValue) {
    const ticks = 4;
    const width = dimensions.width - dimensions.left - dimensions.right;
    const bottom = dimensions.height - dimensions.bottom;

    for (let index = 0; index <= ticks; index += 1) {
      const fraction = index / ticks;
      const x = dimensions.left + width * fraction;
      const value = maxValue * fraction;
      svg.appendChild(svgElement("line", {
        x1: x,
        y1: dimensions.top,
        x2: x,
        y2: bottom,
        class: "ps-table-plot__grid-line",
      }));
      appendSvgText(svg, {
        x: x,
        y: bottom + 20,
        "text-anchor": "middle",
        class: "ps-table-plot__tick",
      }, formatNumber(value));
    }

    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: dimensions.top,
      x2: dimensions.left,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: bottom,
      x2: dimensions.width - dimensions.right,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
  }

  function renderBarChart(figure, categories, categoryField) {
    const rowHeight = 30;
    const dimensions = {
      width: 820,
      height: Math.max(230, 86 + categories.length * rowHeight),
      left: 280,
      right: 72,
      top: 28,
      bottom: 42,
    };
    const plotWidth = dimensions.width - dimensions.left - dimensions.right;
    const plotHeight = dimensions.height - dimensions.top - dimensions.bottom;
    const maxValue = Math.max.apply(null, categories.map(function (item) {
      return item.count;
    }).concat([1]));
    const svg = svgElement("svg", {
      viewBox: "0 0 " + dimensions.width + " " + dimensions.height,
      role: "img",
      "aria-label": "Categorical count bar chart for " + fieldLabel(categoryField),
      class: "ps-table-plot__svg ps-table-plot__svg--bar",
    });
    svg.appendChild(svgElement("title", null, "Count by " + fieldLabel(categoryField)));
    appendBarAxes(svg, dimensions, maxValue);

    const barHeight = Math.max(10, Math.min(20, plotHeight / categories.length - 6));
    const rowSize = plotHeight / categories.length;
    categories.forEach(function (item, index) {
      const centerY = dimensions.top + rowSize * index + rowSize / 2;
      const width = plotWidth * (item.count / maxValue);
      appendSvgText(svg, {
        x: dimensions.left - 10,
        y: centerY,
        "text-anchor": "end",
        "dominant-baseline": "middle",
        class: "ps-table-plot__category",
      }, item.label);
      svg.appendChild(svgElement("rect", {
        x: dimensions.left,
        y: centerY - barHeight / 2,
        width: width,
        height: barHeight,
        rx: 2,
        class: "ps-table-plot__bar",
      }));
      appendSvgText(svg, {
        x: dimensions.left + width + 7,
        y: centerY,
        "dominant-baseline": "middle",
        class: "ps-table-plot__value",
      }, String(item.count));
    });

    figure.appendChild(svg);
  }

  function numericDomain(points, key) {
    let minimum = Infinity;
    let maximum = -Infinity;
    for (const point of points) {
      minimum = Math.min(minimum, point[key]);
      maximum = Math.max(maximum, point[key]);
    }
    if (minimum === maximum) {
      const padding = minimum === 0 ? 1 : Math.abs(minimum) * 0.1;
      minimum -= padding;
      maximum += padding;
    }
    return { minimum: minimum, maximum: maximum };
  }

  function linearScale(domain, start, end) {
    const span = domain.maximum - domain.minimum;
    return function (value) {
      return start + ((value - domain.minimum) / span) * (end - start);
    };
  }

  function appendNumericAxes(svg, dimensions, xDomain, yDomain, xField, yField) {
    const ticks = 4;
    const right = dimensions.width - dimensions.right;
    const bottom = dimensions.height - dimensions.bottom;
    const plotWidth = right - dimensions.left;
    const plotHeight = bottom - dimensions.top;

    for (let index = 0; index <= ticks; index += 1) {
      const fraction = index / ticks;
      const x = dimensions.left + plotWidth * fraction;
      const y = bottom - plotHeight * fraction;
      const xValue = xDomain.minimum + (xDomain.maximum - xDomain.minimum) * fraction;
      const yValue = yDomain.minimum + (yDomain.maximum - yDomain.minimum) * fraction;
      svg.appendChild(svgElement("line", {
        x1: x,
        y1: dimensions.top,
        x2: x,
        y2: bottom,
        class: "ps-table-plot__grid-line",
      }));
      svg.appendChild(svgElement("line", {
        x1: dimensions.left,
        y1: y,
        x2: right,
        y2: y,
        class: "ps-table-plot__grid-line",
      }));
      appendSvgText(svg, {
        x: x,
        y: bottom + 22,
        "text-anchor": "middle",
        class: "ps-table-plot__tick",
      }, formatNumber(xValue));
      appendSvgText(svg, {
        x: dimensions.left - 10,
        y: y + 4,
        "text-anchor": "end",
        class: "ps-table-plot__tick",
      }, formatNumber(yValue));
    }

    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: dimensions.top,
      x2: dimensions.left,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: bottom,
      x2: right,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
    appendSvgText(svg, {
      x: dimensions.left + plotWidth / 2,
      y: dimensions.height - 10,
      "text-anchor": "middle",
      class: "ps-table-plot__axis-label",
    }, fieldLabel(xField));
    appendSvgText(svg, {
      x: 18,
      y: dimensions.top + plotHeight / 2,
      transform: "rotate(-90 18 " + (dimensions.top + plotHeight / 2) + ")",
      "text-anchor": "middle",
      class: "ps-table-plot__axis-label",
    }, fieldLabel(yField));
  }

  function renderPointChart(figure, type, points, xField, yField) {
    const dimensions = {
      width: 780,
      height: 430,
      left: 78,
      right: 32,
      top: 28,
      bottom: 66,
    };
    const xDomain = numericDomain(points, "x");
    const yDomain = numericDomain(points, "y");
    const svg = svgElement("svg", {
      viewBox: "0 0 " + dimensions.width + " " + dimensions.height,
      role: "img",
      "aria-label":
        (type === "line" ? "Line" : "Scatter") +
        " plot of " + fieldLabel(yField) + " by " + fieldLabel(xField),
      class: "ps-table-plot__svg ps-table-plot__svg--points",
    });
    svg.appendChild(svgElement("title", null,
      (type === "line" ? "Line" : "Scatter") +
      " plot: " + fieldLabel(yField) + " by " + fieldLabel(xField)
    ));
    appendNumericAxes(svg, dimensions, xDomain, yDomain, xField, yField);

    const scaleX = linearScale(xDomain, dimensions.left, dimensions.width - dimensions.right);
    const scaleY = linearScale(yDomain, dimensions.height - dimensions.bottom, dimensions.top);
    const renderedPoints = type === "line"
      ? points.slice().sort(function (left, right) {
          return left.x - right.x || left.index - right.index;
        })
      : points;

    if (type === "line") {
      const coordinates = renderedPoints.map(function (point) {
        return scaleX(point.x) + "," + scaleY(point.y);
      }).join(" ");
      svg.appendChild(svgElement("polyline", {
        points: coordinates,
        fill: "none",
        class: "ps-table-plot__line",
      }));
    }

    renderedPoints.forEach(function (point) {
      svg.appendChild(svgElement("circle", {
        cx: scaleX(point.x),
        cy: scaleY(point.y),
        r: type === "line" ? 2.7 : 3.3,
        class: type === "line"
          ? "ps-table-plot__point ps-table-plot__point--line"
          : "ps-table-plot__point",
      }));
    });

    figure.appendChild(svg);
  }

  function buildBarSeries(rows, field) {
    const categories = new Map();
    let missing = 0;
    let invalid = 0;
    let plottedCount = 0;

    for (const row of rows) {
      const value = categoricalValue(row ? row[field] : null);
      if (value.kind === "missing") {
        missing += 1;
        continue;
      }
      if (value.kind === "invalid") {
        invalid += 1;
        continue;
      }
      plottedCount += 1;
      const existing = categories.get(value.key);
      if (existing) existing.count += 1;
      else categories.set(value.key, { label: value.label, count: 1 });
    }

    return {
      categories: Array.from(categories.values()),
      plottedCount: plottedCount,
      missing: missing,
      invalid: invalid,
    };
  }

  function buildPointSeries(rows, xField, yField) {
    const points = [];
    let missing = 0;
    let invalid = 0;

    rows.forEach(function (row, index) {
      const x = numericValue(row ? row[xField] : null);
      const y = numericValue(row ? row[yField] : null);
      if (x.kind === "missing" || y.kind === "missing") {
        missing += 1;
        return;
      }
      if (x.kind !== "value" || y.kind !== "value") {
        invalid += 1;
        return;
      }
      points.push({ x: x.value, y: y.value, index: index });
    });

    return {
      points: points,
      missing: missing,
      invalid: invalid,
    };
  }

  function renderTablePlot(options) {
    const settings = options && typeof options === "object" ? options : {};
    const container = settings.container;
    if (!container || typeof container.appendChild !== "function") {
      return { ok: false, reason: "missing_container", rowCount: 0, plottedCount: 0 };
    }

    const type = String(settings.type || "").toLowerCase();
    const rows = currentFilteredRows(settings);
    if (!rows.length) {
      return refusal(
        container,
        "no_rows",
        "No loaded rows pass the current filters. Change or clear filters to plot data.",
        settings,
        0
      );
    }
    if (rows.length > TABLE_PLOT_LIMITS.maxSourceRows) {
      return refusal(
        container,
        "source_limit",
        "This plot has " + rows.length + " filtered loaded rows (limit " +
          TABLE_PLOT_LIMITS.maxSourceRows +
          "). Filter the table before plotting; no rows were sampled or plotted.",
        settings,
        rows.length
      );
    }

    if (type === "bar") {
      const categoryField = typeof settings.categoryField === "string"
        ? settings.categoryField
        : settings.xField;
      if (typeof categoryField !== "string" || !categoryField) {
        return refusal(
          container,
          "missing_category_field",
          "Choose a categorical field for the bar chart.",
          settings,
          rows.length
        );
      }
      const series = buildBarSeries(rows, categoryField);
      if (!series.plottedCount) {
        return refusal(
          container,
          "no_valid_values",
          "No usable categorical values were found. " + skippedText(series.missing, series.invalid),
          settings,
          rows.length
        );
      }
      if (series.categories.length > TABLE_PLOT_LIMITS.maxCategories) {
        return refusal(
          container,
          "category_limit",
          "This bar chart has " + series.categories.length + " categories (limit " +
            TABLE_PLOT_LIMITS.maxCategories +
            "). Filter the table or choose a different field; no categories were collapsed or sampled.",
          settings,
          rows.length
        );
      }

      const figure = createFrame(container, "bar", "Count by " + fieldLabel(categoryField));
      renderBarChart(figure, series.categories, categoryField);
      const scope = sourceScopeText(settings, rows.length, series.plottedCount);
      appendPlotSummary(figure, skippedText(series.missing, series.invalid), scope);
      return {
        ok: true,
        type: type,
        rowCount: rows.length,
        plottedCount: series.plottedCount,
        categoryCount: series.categories.length,
        missingCount: series.missing,
        invalidCount: series.invalid,
        scope: scope,
      };
    }

    if (type !== "line" && type !== "scatter") {
      return refusal(
        container,
        "unknown_type",
        "Choose a bar, line, or scatter plot.",
        settings,
        rows.length
      );
    }

    const xField = typeof settings.xField === "string" ? settings.xField : "";
    const yField = typeof settings.yField === "string" ? settings.yField : "";
    if (!xField || !yField) {
      return refusal(
        container,
        "missing_numeric_field",
        "Choose numeric x and y fields for the " + type + " plot.",
        settings,
        rows.length
      );
    }

    const series = buildPointSeries(rows, xField, yField);
    if (!series.points.length) {
      return refusal(
        container,
        "no_valid_points",
        "No usable numeric point pairs were found. " + skippedText(series.missing, series.invalid),
        settings,
        rows.length
      );
    }
    if (series.points.length > TABLE_PLOT_LIMITS.maxPoints) {
      return refusal(
        container,
        "point_limit",
        "This " + type + " plot has " + series.points.length + " valid points (limit " +
          TABLE_PLOT_LIMITS.maxPoints +
          "). Filter the table before plotting; no points were sampled or plotted.",
        settings,
        rows.length
      );
    }

    const figure = createFrame(container, type,
      (type === "line" ? "Line" : "Scatter") + " plot: " +
      fieldLabel(yField) + " by " + fieldLabel(xField)
    );
    renderPointChart(figure, type, series.points, xField, yField);
    const scope = sourceScopeText(settings, rows.length, series.points.length);
    appendPlotSummary(figure, skippedText(series.missing, series.invalid), scope);
    return {
      ok: true,
      type: type,
      rowCount: rows.length,
      plottedCount: series.points.length,
      missingCount: series.missing,
      invalidCount: series.invalid,
      scope: scope,
    };
  }

  core.TABLE_PLOT_LIMITS = TABLE_PLOT_LIMITS;
  core.renderTablePlot = renderTablePlot;
})();
