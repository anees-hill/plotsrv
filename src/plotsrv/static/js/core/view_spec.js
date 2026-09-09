/* A bounded presentation contract shared by personal and future suggested views. */
(function () {
  "use strict";
  const core = window.PLOTSRV.core;
  const MAX_BYTES = 256 * 1024,
    MAX_ITEMS = 64,
    MAX_SPEC = 16 * 1024;
  const fail = (message) => {
    throw new Error(message);
  };
  const object = (value) =>
    value && typeof value === "object" && !Array.isArray(value);
  function keys(value, allowed) {
    if (
      !object(value) ||
      Object.keys(value).some((key) => !allowed.includes(key))
    )
      fail("Unsupported presentation settings.");
  }
  function text(value, limit, empty) {
    if (
      typeof value !== "string" ||
      value.length > limit ||
      (!empty && !value.length)
    )
      fail("Invalid presentation text.");
    return value;
  }
  function list(value, limit) {
    if (!Array.isArray(value) || value.length > limit)
      fail("Too many presentation settings.");
    return value;
  }
  const enums = {
    type: ["bar", "line", "scatter", "histogram", "time-count"],
    source: ["table", "summary"],
    aggregation: ["count", "sum", "mean", "min", "max"],
    bins: ["auto", "5", "10", "20", "40"],
    palette: [
      "plotsrv",
      "accessible",
      "http",
      "ocean",
      "forest",
      "sunset",
      "violet",
      "neutral",
      "viridis",
      "plasma",
      "blues",
      "ember",
    ],
    sort: ["value-desc", "value-asc", "category-asc", "category-desc"],
    display: ["grouped", "stacked"],
    xScale: ["linear", "log"],
    yScale: ["linear", "log"],
    legend: ["top", "right", "bottom"],
    titleAlign: ["left", "center"],
    pointSelection: ["refuse", "sample", "first", "latest"],
  };
  const plotFields = [
    "categoryField",
    "xField",
    "yField",
    "valueField",
    "histogramField",
    "seriesField",
  ];
  function validate(spec) {
    keys(spec, [
      "version",
      "sourceId",
      "name",
      "caption",
      "presentation",
      "requirements",
    ]);
    if (spec.version !== 1)
      fail(
        "This saved view version is not supported. It has not been changed.",
      );
    text(spec.sourceId, 512);
    text(spec.name, 80);
    text(spec.caption, 256, true);
    const p = spec.presentation;
    keys(p, [
      "search",
      "filters",
      "sort",
      "group",
      "columns",
      "hidden",
      "mode",
      "plot",
    ]);
    text(p.search, 1024, true);
    text(p.group, 256, true);
    [p.columns, p.hidden].forEach((value) =>
      list(value, 128).forEach((field) => text(field, 256)),
    );
    list(p.sort, 8).forEach((sort) => {
      keys(sort, ["field", "dir"]);
      text(sort.field, 256);
      if (!["asc", "desc"].includes(sort.dir)) fail("Invalid sort.");
    });
    list(p.filters, 10).forEach((filter) => {
      keys(filter, ["field", "op", "value", "valueTo"]);
      text(filter.field, 256);
      if (
        ![
          "contains",
          "eq",
          "neq",
          "in",
          "not_in",
          "missing",
          "not_missing",
          "lt",
          "lte",
          "gt",
          "gte",
          "between",
          "not_between",
        ].includes(filter.op)
      )
        fail("Unsupported filter.");
      text(filter.value, 2048, true);
      text(filter.valueTo, 2048, true);
      if (
        !["missing", "not_missing"].includes(filter.op) &&
        !filter.value.trim()
      )
        fail("Complete the filter before saving.");
      if (
        ["between", "not_between"].includes(filter.op) &&
        !filter.valueTo.trim()
      )
        fail("Complete the filter range before saving.");
    });
    if (!["table", "plot", "plot+data"].includes(p.mode))
      fail("Unsupported presentation mode.");
    keys(p.plot, [
      ...Object.keys(enums),
      ...plotFields,
      "title",
      "xLabel",
      "yLabel",
      "categoryLimit",
      "zeroBaseline",
      "showPoints",
    ]);
    for (const [key, value] of Object.entries(p.plot)) {
      if (enums[key]) {
        if (!enums[key].includes(value)) fail("Unsupported plot setting.");
      } else if (key === "categoryLimit") {
        if (![5, 10, 20, 40].includes(value)) fail("Invalid plot limit.");
      } else if (["zeroBaseline", "showPoints"].includes(key)) {
        if (typeof value !== "boolean") fail("Invalid plot setting.");
      } else text(value, 256, true);
    }
    if (!p.plot.type || !p.plot.source) fail("Missing plot specification.");
    keys(spec.requirements, ["fields", "plotFields", "plotSource"]);
    for (const requirements of [
      spec.requirements.fields,
      spec.requirements.plotFields,
    ]) {
      list(requirements, 128).forEach((field) => {
        keys(field, ["name", "type"]);
        text(field.name, 256);
        if (!["text", "number", "datetime", "unknown"].includes(field.type))
          fail("Invalid field requirement.");
      });
    }
    if (!["table", "summary"].includes(spec.requirements.plotSource))
      fail("Invalid plot source.");
    if (spec.requirements.plotSource !== p.plot.source)
      fail("Plot source requirement does not match the presentation.");
    const required = new Set(spec.requirements.fields.map((f) => f.name));
    if (
      p.filters.some((f) => !required.has(f.field)) ||
      p.sort.some((s) => !required.has(s.field)) ||
      (p.group && !required.has(p.group))
    )
      fail("Missing field requirements.");
    if (JSON.stringify(spec).length > MAX_SPEC)
      fail("This presentation is too large to save.");
    return JSON.parse(JSON.stringify(spec));
  }
  function compatible(spec, schema) {
    spec = validate(spec);
    const p = spec.presentation,
      notes = [],
      unsafe = [];
    const expected = new Map(
      spec.requirements.fields.map((f) => [f.name, f.type]),
    );
    const expectedPlot = new Map(
      spec.requirements.plotFields.map((f) => [f.name, f.type]),
    );
    function valid(field, types, requirements) {
      return (
        Object.prototype.hasOwnProperty.call(types, field) &&
        (!requirements.has(field) ||
          requirements.get(field) === "unknown" ||
          types[field] === requirements.get(field))
      );
    }
    const okay = (field) => valid(field, schema.fields, expected);
    p.filters = p.filters.filter((filter) => {
      const numeric = schema.fields[filter.field] === "number";
      const numericOp = [
        "lt",
        "lte",
        "gt",
        "gte",
        "between",
        "not_between",
      ].includes(filter.op);
      const textOp = ["contains", "in", "not_in"].includes(filter.op);
      const badNumber =
        numeric &&
        !["missing", "not_missing"].includes(filter.op) &&
        (!Number.isFinite(Number(filter.value)) ||
          (["between", "not_between"].includes(filter.op) &&
            !Number.isFinite(Number(filter.valueTo))));
      if (
        okay(filter.field) &&
        (!numericOp || numeric) &&
        (!textOp || !numeric) &&
        !badNumber
      )
        return true;
      unsafe.push(
        "Filter on “" +
          filter.field +
          "” needs repair (missing field, changed type or invalid value).",
      );
      return false;
    });
    p.sort = p.sort.filter((sort) => {
      if (okay(sort.field)) return true;
      notes.push(
        "Sort field “" + sort.field + "” is unavailable or changed type.",
      );
      return false;
    });
    if (p.group && !okay(p.group)) {
      notes.push(
        "Grouping field “" + p.group + "” is unavailable or changed type.",
      );
      p.group = "";
    }
    ["columns", "hidden"].forEach((key) => {
      p[key] = p[key].filter((field) => {
        if (Object.prototype.hasOwnProperty.call(schema.fields, field))
          return true;
        notes.push("Column “" + field + "” is unavailable.");
        return false;
      });
    });
    const needed =
      p.plot.type === "bar"
        ? [
            "categoryField",
            ...(p.plot.aggregation === "count" ? [] : ["valueField"]),
          ]
        : p.plot.type === "histogram"
          ? ["histogramField"]
          : p.plot.type === "time-count"
            ? ["xField"]
            : ["xField", "yField"];
    if (p.plot.seriesField) needed.push("seriesField");
    const plotTypes =
      p.plot.source === "summary" ? schema.summary : schema.fields;
    const invalidPlot = needed.some((key) => {
      const field = p.plot[key],
        type = plotTypes[field];
      if (!valid(field, plotTypes, expectedPlot)) return true;
      if (["yField", "valueField", "histogramField"].includes(key))
        return type !== "number";
      if (key === "xField")
        return (
          (p.plot.type === "time-count"
            ? type !== "datetime"
            : !["number", "datetime"].includes(type)) ||
          (type === "datetime" && p.plot.xScale === "log")
        );
      return false;
    });
    if (
      p.mode !== "table" &&
      (!schema.sources.includes(p.plot.source) || invalidPlot)
    ) {
      unsafe.push(
        "The saved plot source or fields are unavailable or changed type; choose a compatible plot.",
      );
      p.mode = "table";
    }
    return { spec, notes: [...new Set(notes)], unsafe };
  }
  function namespace() {
    // Browser origin supplies host isolation; base path/name survive server restarts.
    const path = window.location.pathname.replace(/\/+$/, "") || "/";
    return (
      "plotsrv:v1:my_views:" +
      encodeURIComponent(path) +
      ":" +
      encodeURIComponent(window.PLOTSRV.config.dashboardName || "default")
    );
  }
  function read() {
    let raw;
    try {
      raw = localStorage.getItem(namespace());
    } catch (_) {
      return { items: [], error: "Browser storage is unavailable." };
    }
    if (!raw) return { items: [], error: null };
    if (raw.length > MAX_BYTES)
      return {
        items: [],
        error:
          "Saved views storage exceeds its safety limit. It has not been changed.",
      };
    try {
      const doc = JSON.parse(raw);
      keys(doc, ["version", "items"]);
      if (doc.version !== 1)
        fail(
          "Unsupported saved views version. Existing storage has not been changed.",
        );
      const ids = new Set();
      const items = list(doc.items, MAX_ITEMS).map((item) => {
        keys(item, ["id", "spec"]);
        text(item.id, 80);
        if (ids.has(item.id)) fail("Duplicate saved view.");
        ids.add(item.id);
        return { id: item.id, spec: validate(item.spec) };
      });
      return { items, error: null };
    } catch (error) {
      return { items: [], error: "Cannot load saved views: " + error.message };
    }
  }
  function write(item, remove, expected) {
    const loaded = read();
    if (loaded.error) fail(loaded.error);
    const old = loaded.items.find((value) => value.id === item.id);
    if (
      expected !== undefined &&
      JSON.stringify(old || null) !== JSON.stringify(expected)
    )
      fail("This view changed in another tab. Reopen it before updating.");
    const items = loaded.items.filter((value) => value.id !== item.id);
    if (!remove)
      items.push({ id: text(item.id, 80), spec: validate(item.spec) });
    const raw = JSON.stringify({ version: 1, items });
    if (items.length > MAX_ITEMS || raw.length > MAX_BYTES)
      fail(
        "My views is full. Delete a saved configuration before adding another.",
      );
    if (!core.savePref(namespace(), raw))
      fail("Unable to save: browser storage is disabled or full.");
    window.dispatchEvent(new Event("plotsrv-my-views-changed"));
    return item;
  }
  async function change(item, remove, expected) {
    const locks = window.navigator && window.navigator.locks;
    if (!locks) return write(item, remove, expected);
    // Do not queue clicks behind a busy tab. Stale updates still compare their
    // original saved value; new saves merge with the latest bounded catalogue.
    return locks.request(namespace(), { ifAvailable: true }, (lock) => {
      if (!lock)
        fail("My views is being saved in another tab. Please try again.");
      return write(item, remove, expected);
    });
  }
  core.viewSpec = {
    validate,
    compatible,
    namespace,
    read,
    write,
    change,
    plotFields,
  };
})();
