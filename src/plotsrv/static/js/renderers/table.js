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

  const MAX_FILTERS = 10;

  const FILTER_OPS = {
    text: [
      { value: "contains", label: "contains" },
      { value: "eq", label: "is equal to" },
      { value: "neq", label: "is not equal to" },
      { value: "in", label: "is one of" },
      { value: "not_in", label: "is not one of" },
      { value: "missing", label: "is missing" },
      { value: "not_missing", label: "is not missing" },
    ],
    number: [
      { value: "missing", label: "is missing" },
      { value: "not_missing", label: "is not missing" },
      { value: "lt", label: "is less than" },
      { value: "lte", label: "is less than or equal to" },
      { value: "gt", label: "is greater than" },
      { value: "gte", label: "is greater than or equal to" },
      { value: "eq", label: "is equal to" },
      { value: "neq", label: "is not equal to" },
      { value: "between", label: "is between" },
      { value: "not_between", label: "is not between" },
    ],
  };

  function tablePrefKey() {
    return "plotsrv:v4:table_state:" + String(config.activeViewId || "default");
  }

  function buildColumnDefs(columnNames) {
    const hidden = new Set(getHiddenColumns());

    return (columnNames || []).map(function (col) {
      const name = String(col);
      return {
        // Tabulator assigns plain string titles through innerHTML. Column
        // names come from the rendered data, so supply an inert title and
        // return a DOM node whose textContent contains the actual label.
        title: "",
        titleFormatter: function () {
          const element = document.createElement("span");
          element.textContent = name;
          return element;
        },
        field: col,
        visible: !hidden.has(name),
      };
    });
  }

  function preserveColumnOrder(columnDefs, table) {
    if (!table || typeof table.getColumns !== "function") return columnDefs;
    const byField = new Map(columnDefs.map(function (definition) {
      return [definition.field, definition];
    }));
    const ordered = [];
    try {
      table.getColumns().forEach(function (column) {
        const field = column && typeof column.getField === "function"
          ? column.getField()
          : null;
        if (!byField.has(field)) return;
        ordered.push(byField.get(field));
        byField.delete(field);
      });
    } catch (e) {
      return columnDefs;
    }
    byField.forEach(function (definition) { ordered.push(definition); });
    return ordered;
  }

  function currentSorters(table) {
    if (!table || typeof table.getSorters !== "function") return [];
    try {
      return table.getSorters().map(function (sorter) {
        const field = sorter.field ||
          (sorter.column && typeof sorter.column.getField === "function"
            ? sorter.column.getField()
            : null);
        return field ? { column: field, dir: sorter.dir || "asc" } : null;
      }).filter(Boolean);
    } catch (e) {
      return [];
    }
  }

  function defaultTableUiState() {
    return {
      searchQuery: "",
      filtersOpen: false,
      filters: [],
      columnsOpen: false,
      hiddenColumns: [],
      groupBy: null,
    };
  }

  function getTableUiState() {
    if (!state.tableUiState) {
      state.tableUiState = defaultTableUiState();
    }
    return state.tableUiState;
  }

  function saveTableUiState() {
    const ui = getTableUiState();

    try {
      localStorage.setItem(tablePrefKey(), JSON.stringify(ui));
    } catch (e) {
      // ignore
    }
  }

  function newFilterId() {
    return "f_" + Math.random().toString(36).slice(2, 10);
  }

  function normalizeFilter(filter) {
    if (!filter || typeof filter !== "object") return null;

    return {
      id: typeof filter.id === "string" && filter.id ? filter.id : newFilterId(),
      field: typeof filter.field === "string" ? filter.field : "",
      op: typeof filter.op === "string" ? filter.op : "contains",
      value: typeof filter.value === "string" ? filter.value : "",
      valueTo: typeof filter.valueTo === "string" ? filter.valueTo : "",
    };
  }

  function operatorNeedsValue(op) {
    return !["missing", "not_missing"].includes(op);
  }

  function operatorNeedsTwoValues(op) {
    return ["between", "not_between"].includes(op);
  }

  const membershipCache = new WeakMap();
  function membershipValues(filter) {
    const value = String(filter.value || "");
    const cached = membershipCache.get(filter);
    if (cached && cached.value === value) return cached.values;
    const values = new Set(value.split(/\r?\n/).map(function (entry) {
      return entry.trim().toLowerCase();
    }).filter(Boolean));
    membershipCache.set(filter, {value: value, values: values});
    return values;
  }

  function isFilterComplete(filter) {
    if (!filter.field || !filter.op) return false;
    if (!operatorNeedsValue(filter.op)) return true;
    if (filter.op === "in" || filter.op === "not_in") return membershipValues(filter).size > 0;
    if (operatorNeedsTwoValues(filter.op)) {
      return (
        String(filter.value || "").trim() !== "" &&
        String(filter.valueTo || "").trim() !== ""
      );
    }
    return String(filter.value || "").trim() !== "";
  }

  function loadTableUiState() {
    let parsed = null;

    try {
      const raw = localStorage.getItem(tablePrefKey());
      if (raw) parsed = JSON.parse(raw);
    } catch (e) {
      parsed = null;
    }

    const base = defaultTableUiState();
    const filters = Array.isArray(parsed && parsed.filters) ? parsed.filters : [];
    const normalizedFilters = filters.map(normalizeFilter).filter(Boolean);
    const hiddenColumns = Array.isArray(parsed && parsed.hiddenColumns)
      ? parsed.hiddenColumns.filter(function (x) {
          return typeof x === "string" && x;
        })
      : [];

    const hasSavedFilters = normalizedFilters.some(isFilterComplete);
    const hasHiddenColumns = hiddenColumns.length > 0;
    const groupBy =
      parsed && typeof parsed.groupBy === "string" && parsed.groupBy
        ? parsed.groupBy
        : null;

    state.tableUiState = {
      searchQuery:
        parsed && typeof parsed.searchQuery === "string"
          ? parsed.searchQuery
          : base.searchQuery,

      filtersOpen:
        parsed && typeof parsed.filtersOpen === "boolean"
          ? parsed.filtersOpen
          : hasSavedFilters,

      filters: normalizedFilters,

      columnsOpen:
        parsed && typeof parsed.columnsOpen === "boolean"
          ? parsed.columnsOpen
          : hasHiddenColumns,

      hiddenColumns: hiddenColumns,

      groupBy: groupBy,
    };
  }

  function escapeHtml(s) {
    if (typeof core.escapeHtml === "function") {
      return core.escapeHtml(s);
    }
    return String(s);
  }

  function getFieldType(field) {
    const map = state.tableFieldTypes || {};
    return map[field] === "number" ? "number" : "text";
  }

  function inferFieldTypes(columns, rows) {
    const out = {};
    const fields = Array.isArray(columns) ? columns.slice() : [];
    const sampleRows = Array.isArray(rows) ? rows.slice(0, 50) : [];

    for (const field of fields) {
      let numericHits = 0;
      let datetimeHits = 0;
      let textHits = 0;

      for (const row of sampleRows) {
        const value = row ? row[field] : null;
        if (value == null || value === "") continue;

        if (typeof value === "number" && Number.isFinite(value)) {
          numericHits += 1;
          continue;
        }

        const n = Number(value);
        if (typeof value === "string" && value.trim() !== "" && Number.isFinite(n)) {
          numericHits += 1;
        } else if (
          typeof value === "string" &&
          /^\d{4}-\d{2}-\d{2}(?:[T ][^\s]+)?/.test(value.trim()) &&
          Number.isFinite(Date.parse(value))
        ) {
          datetimeHits += 1;
        } else {
          textHits += 1;
        }
      }

      out[field] =
        numericHits > 0 && datetimeHits === 0 && textHits === 0
          ? "number"
          : datetimeHits > 0 && numericHits === 0 && textHits === 0
            ? "datetime"
            : "text";
    }

    return out;
  }

  function getActiveRowCount() {
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    return rows.filter(rowMatchesCurrentTableFilters).length;
  }

  function hasActiveTableFiltering() {
    return getSearchQuery().trim() !== "" || hasActiveFilters();
  }

  function updateTableStatus(data, activeCount, filtering) {
    const status = document.getElementById("status");
    const inline = document.getElementById("table-status-inline");

    const targetEls = [status, inline].filter(Boolean);
    if (!targetEls.length) return;

    const totalKnown = data.total_rows_known !== false;
    const total = totalKnown ? Number(data.total_rows ?? 0) : null;
    const loaded = Number(data.loaded_rows ?? data.returned_rows ?? 0);
    const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

    let html = "";

    if (total <= 0 && returned <= 0) {
      html = "";
    } else {
      const isTrunc =
        !!(data.meta && data.meta.truncated) ||
        (totalKnown && returned < total);
      const hasFilter = filtering && typeof activeCount === "number";

      if (hasFilter) {
        html =
          "Showing " +
          activeCount +
          " filtered rows of " +
          returned +
          " loaded";
        if (totalKnown && total > returned) {
          html += " (" + total + " total)";
        } else if (!totalKnown) {
          html += " (" + loaded + " loaded; full count unknown)";
        } else {
          html += ".";
        }
      } else if (!totalKnown) {
        html =
          "Showing " +
          returned +
          (loaded > returned ? " of " + loaded : "") +
          " loaded rows (full count unknown).";
      } else {
        html =
          "Showing " +
          returned +
          (total > returned ? " of " + total : "") +
          " rows.";
      }

      if (isTrunc) {
        html +=
          ' <span class="badge" title="This view is showing a sampled subset of the full data.">TRUNCATED</span>';
      }
    }

    for (const el of targetEls) {
      el.innerHTML = html;
    }
  }

  function refreshTableStatus() {
    if (!state.tableLastPayload) return;
    const activeCount = getActiveRowCount();
    const filtering = hasActiveTableFiltering();
    updateTableStatus(
      state.tableLastPayload,
      activeCount,
      filtering
    );
    syncFilteredEmptyState(activeCount, filtering);
  }

  function syncFilteredEmptyState(activeCount, filtering) {
    const empty = document.getElementById("table-filter-empty");
    if (!empty) return;
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    empty.hidden = !(
      rows.length > 0 &&
      filtering &&
      activeCount === 0
    );
  }

  function refreshActiveTablePlot(immediate) {
    if (immediate && typeof core.refreshTablePlotImmediately === "function") {
      core.refreshTablePlotImmediately();
    } else if (typeof core.refreshTablePlot === "function") {
      core.refreshTablePlot();
    }
  }

  function getSearchQuery() {
    return getTableUiState().searchQuery || "";
  }

  function setSearchQuery(value) {
    const ui = getTableUiState();
    ui.searchQuery = String(value || "");
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function getFilters() {
    return Array.isArray(getTableUiState().filters) ? getTableUiState().filters : [];
  }

  function setFilters(filters) {
    const ui = getTableUiState();
    ui.filters = Array.isArray(filters) ? filters.map(normalizeFilter).filter(Boolean) : [];
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function setFiltersOpen(isOpen) {
    const ui = getTableUiState();
    ui.filtersOpen = !!isOpen;
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function getHiddenColumns() {
    return Array.isArray(getTableUiState().hiddenColumns)
      ? getTableUiState().hiddenColumns
      : [];
  }

  function setHiddenColumns(fields) {
    const ui = getTableUiState();
    ui.hiddenColumns = Array.isArray(fields)
      ? fields.filter(function (x) {
          return typeof x === "string" && x;
        })
      : [];
    saveTableUiState();
  }

  function setColumnsOpen(isOpen) {
    const ui = getTableUiState();
    ui.columnsOpen = !!isOpen;
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function getGroupingField() {
    const field = getTableUiState().groupBy;
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    return typeof field === "string" && fields.includes(field) ? field : null;
  }

  function setGroupingField(field) {
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const next = typeof field === "string" && fields.includes(field) ? field : null;
    const ui = getTableUiState();
    ui.groupBy = next;
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
    return next;
  }

  function normalizeGroupingField() {
    const ui = getTableUiState();
    const groupingField = getGroupingField();
    if (ui.groupBy !== groupingField) {
      ui.groupBy = groupingField;
      saveTableUiState();
    }
    return groupingField;
  }

  function renderGroupingControl() {
    const select = document.getElementById("table-group-by-select");
    if (!select || typeof document.createElement !== "function") return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const selected = normalizeGroupingField();

    while (select.firstChild) {
      select.removeChild(select.firstChild);
    }

    const none = document.createElement("option");
    none.value = "";
    none.textContent = "No grouping";
    select.appendChild(none);

    for (const field of fields) {
      const option = document.createElement("option");
      option.value = field;
      option.textContent = field;
      select.appendChild(option);
    }

    select.value = selected || "";
    select.disabled = fields.length === 0;
  }

  function applyTableGrouping() {
    const table = state.tabulatorInstance;
    const groupingField = normalizeGroupingField();
    if (!table || table.initialized === false || typeof table.setGroupBy !== "function") return;

    if (state.tableAppliedGrouping === groupingField) return;
    if (!groupingField && state.tableAppliedGrouping == null) return;

    try {
      // Group keys are source data, not markup. Tabulator's default header
      // inserts them with innerHTML even when individual cells are escaped.
      if (typeof table.setGroupHeader === "function") {
        table.setGroupHeader(function (value, count) {
          const heading = document.createElement("span");
          heading.textContent = String(value) + " (" + count + " " +
            (count === 1 ? "item" : "items") + ")";
          return heading;
        });
      }
      table.setGroupBy(groupingField || false);
      state.tableAppliedGrouping = groupingField;
    } catch (e) {
      // The shared explorer remains usable with reduced Tabulator surfaces.
    }
  }

  function setTableGrouping(field) {
    const groupingField = setGroupingField(field);
    renderGroupingControl();
    applyTableGrouping();
    refreshTableStatus();
    return groupingField;
  }

  function hasHiddenColumns() {
    return getHiddenColumns().length > 0;
  }

  function getOperatorOptions(field) {
    const fieldType = getFieldType(field);
    return fieldType === "number" ? FILTER_OPS.number : FILTER_OPS.text;
  }

  function renderOperatorOptions(field, selectedOp) {
    const options = getOperatorOptions(field);
    return options
      .map(function (op) {
        const sel = op.value === selectedOp ? ' selected="selected"' : "";
        return (
          '<option value="' +
          escapeHtml(op.value) +
          '"' +
          sel +
          ">" +
          escapeHtml(op.label) +
          "</option>"
        );
      })
      .join("");
  }

  function getCompleteFilters() {
    return getFilters().filter(isFilterComplete);
  }

  function hasActiveFilters() {
    return getCompleteFilters().length > 0;
  }

  function renderFilterRows() {
    const wrap = document.getElementById("table-filter-rows");
    if (!wrap) return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const filters = getFilters();

    if (!filters.length) {
      wrap.innerHTML = '<div class="note ps-note">No filters yet.</div>';
      return;
    }

    const fieldOptions = fields.map(function (field) {
      return field;
    });

    wrap.innerHTML = filters
      .map(function (filter) {
        const field = filter.field || fieldOptions[0] || "";
        const op = filter.op || "contains";
        const twoValues = operatorNeedsTwoValues(op);
        const singleClass = twoValues ? "" : " ps-table-filter-row--single";

        const fieldSelect =
          '<select class="ps-table-filter-select" data-filter-part="field" data-filter-id="' +
          escapeHtml(filter.id) +
          '">' +
          fieldOptions
            .map(function (f) {
              const sel = f === field ? ' selected="selected"' : "";
              return (
                '<option value="' +
                escapeHtml(f) +
                '"' +
                sel +
                ">" +
                escapeHtml(f) +
                "</option>"
              );
            })
            .join("") +
          "</select>";

        const opSelect =
          '<select class="ps-table-filter-select" data-filter-part="op" data-filter-id="' +
          escapeHtml(filter.id) +
          '">' +
          renderOperatorOptions(field, op) +
          "</select>";

        const multipleValues = op === "in" || op === "not_in";
        const valueInput = multipleValues
          ? '<textarea class="ps-table-filter-value ps-table-filter-value--list" data-filter-part="value" data-filter-id="' +
            escapeHtml(filter.id) + '" rows="1" aria-label="Values, one per line" title="One exact value per line; case-insensitive. Blank lines and surrounding spaces are ignored.">' +
            escapeHtml(filter.value || "") + '</textarea>'
          :
          '<input class="ps-table-filter-value" data-filter-part="value" data-filter-id="' +
          escapeHtml(filter.id) +
          '" type="text" value="' +
          escapeHtml(filter.value || "") +
          '"' +
          (operatorNeedsValue(op) ? "" : ' disabled="disabled"') +
          ' placeholder="Value" />';

        const valueToInput = twoValues
          ? '<input class="ps-table-filter-value" data-filter-part="valueTo" data-filter-id="' +
            escapeHtml(filter.id) +
            '" type="text" value="' +
            escapeHtml(filter.valueTo || "") +
            '" placeholder="And value" />'
          : "";

        const removeBtn =
          '<button type="button" class="ps-btn ps-table-filter-remove" data-filter-action="remove" data-filter-id="' +
          escapeHtml(filter.id) +
          '">Remove</button>';

        return (
          '<div class="ps-table-filter-row' +
          singleClass +
          '" data-filter-row="' +
          escapeHtml(filter.id) +
          '">' +
          fieldSelect +
          opSelect +
          valueInput +
          valueToInput +
          removeBtn +
          "</div>"
        );
      })
      .join("");
  }

  function renderColumnsList() {
    const wrap = document.getElementById("table-columns-list");
    if (!wrap) return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const hidden = new Set(getHiddenColumns());

    if (!fields.length) {
      wrap.innerHTML = '<div class="note ps-note">No columns available.</div>';
      return;
    }

    wrap.innerHTML = fields
      .map(function (field) {
        const checked = hidden.has(field) ? "" : ' checked="checked"';
        return (
          '<label class="ps-table-column-item">' +
          '<input type="checkbox" data-column-field="' +
          escapeHtml(field) +
          '"' +
          checked +
          " />" +
          "<span>" +
          escapeHtml(field) +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function describeFilter(filter) {
    const field = filter.field || "";
    const op = filter.op || "";
    const value = filter.value || "";
    const valueTo = filter.valueTo || "";

    const labelMap = {};
    for (const group of [FILTER_OPS.text, FILTER_OPS.number]) {
      for (const item of group) {
        labelMap[item.value] = item.label;
      }
    }

    const opLabel = labelMap[op] || op;

    if (op === "in" || op === "not_in") {
      return field + " " + opLabel + " " + String(value).split(/\r?\n/).map(function (entry) {
        return entry.trim();
      }).filter(Boolean).map(function (entry) { return JSON.stringify(entry); }).join(", ");
    }

    if (operatorNeedsTwoValues(op)) {
      return field + " " + opLabel + " " + value + " and " + valueTo;
    }

    if (operatorNeedsValue(op)) {
      return field + " " + opLabel + " " + value;
    }

    return field + " " + opLabel;
  }

  function renderActiveFilters() {
    const wrap = document.getElementById("table-active-filters");
    if (!wrap) return;

    const active = getCompleteFilters();

    if (!active.length) {
      wrap.hidden = true;
      wrap.innerHTML = "";
      return;
    }

    wrap.hidden = false;
    wrap.innerHTML = active
      .map(function (filter) {
        return (
          '<span class="ps-table-filter-chip">' +
          "<span>" +
          escapeHtml(describeFilter(filter)) +
          "</span>" +
          '<button type="button" title="Remove filter" data-filter-chip-remove="' +
          escapeHtml(filter.id) +
          '">×</button>' +
          "</span>"
        );
      })
      .join("");
  }

  function syncFilterButtonUi() {
    const btn = document.getElementById("table-filters-toggle-btn");
    if (!btn) return;

    btn.classList.toggle("is-active", hasActiveFilters());
  }

  function syncColumnsButtonUi() {
    const btn = document.getElementById("table-columns-toggle-btn");
    if (!btn) return;

    btn.classList.toggle("is-active", hasHiddenColumns());
  }

  function syncFilterPanelUi() {
    const panel = document.getElementById("table-filter-panel");
    const btn = document.getElementById("table-filters-toggle-btn");
    const shouldShow = !!getTableUiState().filtersOpen;

    if (panel) {
      panel.hidden = !shouldShow;
    }

    if (btn) {
      btn.setAttribute("aria-expanded", shouldShow ? "true" : "false");
    }

    syncFilterButtonUi();
  }

  function syncColumnsPanelUi() {
    const panel = document.getElementById("table-columns-panel");
    const btn = document.getElementById("table-columns-toggle-btn");
    const shouldShow = !!getTableUiState().columnsOpen;

    if (panel) {
      panel.hidden = !shouldShow;
    }

    if (btn) {
      btn.setAttribute("aria-expanded", shouldShow ? "true" : "false");
    }

    syncColumnsButtonUi();
  }

  function getFieldValueForFilter(rowData, field) {
    return rowData ? rowData[field] : null;
  }

  function isMissing(value) {
    return value == null || String(value).trim() === "";
  }

  function matchesSingleFilter(rowData, filter) {
    if (!isFilterComplete(filter)) return true;

    const raw = getFieldValueForFilter(rowData, filter.field);
    const fieldType = getFieldType(filter.field);
    const op = filter.op;

    if (op === "missing") return isMissing(raw);
    if (op === "not_missing") return !isMissing(raw);

    if (fieldType === "number") {
      const a = Number(raw);
      const b = Number(filter.value);
      const c = Number(filter.valueTo);

      if (!Number.isFinite(a)) return false;

      if (op === "lt") return a < b;
      if (op === "lte") return a <= b;
      if (op === "gt") return a > b;
      if (op === "gte") return a >= b;
      if (op === "eq") return a === b;
      if (op === "neq") return a !== b;
      if (op === "between") return a >= Math.min(b, c) && a <= Math.max(b, c);
      if (op === "not_between") {
        return !(a >= Math.min(b, c) && a <= Math.max(b, c));
      }

      return true;
    }

    const text = String(raw == null ? "" : raw).toLowerCase();
    const q = String(filter.value || "").toLowerCase();

    if (op === "in") return membershipValues(filter).has(text);
    if (op === "not_in") return !membershipValues(filter).has(text);
    if (op === "contains") return text.includes(q);
    if (op === "eq") return text === q;
    if (op === "neq") return text !== q;

    return true;
  }

  function rowMatchesCurrentTableFilters(rowData) {
    const searchQuery = getSearchQuery().trim().toLowerCase();
    const filters = getCompleteFilters();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (searchQuery) {
      let matched = false;
      for (const field of fields) {
        const raw = rowData ? rowData[field] : null;
        const text = String(raw == null ? "" : raw).toLowerCase();
        if (text.includes(searchQuery)) {
          matched = true;
          break;
        }
      }
      if (!matched) return false;
    }

    // Positive membership lists on a column form a union. Other conditions,
    // including exclusions, still constrain that union with AND.
    let membershipMatches = null;
    for (const filter of filters) {
      if (filter.op === "in" && getFieldType(filter.field) !== "number") {
        if (!membershipMatches) membershipMatches = new Map();
        if (!membershipMatches.get(filter.field)) {
          membershipMatches.set(filter.field, matchesSingleFilter(rowData, filter));
        }
      } else if (!matchesSingleFilter(rowData, filter)) return false;
    }
    if (membershipMatches) {
      for (const matched of membershipMatches.values()) if (!matched) return false;
    }

    return true;
  }

  function getCurrentFilteredLoadedRows() {
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    return rows.filter(rowMatchesCurrentTableFilters);
  }

  function applyAllTableFilters(options) {
    const immediatePlot = !!(options && options.immediatePlot);
    if (!state.tabulatorInstance || state.tabulatorInstance.initialized === false) return;

    const searchQuery = getSearchQuery().trim().toLowerCase();
    const filters = getCompleteFilters();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (!searchQuery && !filters.length) {
      state.tabulatorInstance.clearFilter(true);
      refreshTableStatus();
      refreshActiveTablePlot(immediatePlot);
      return;
    }

    state.tabulatorInstance.setFilter(rowMatchesCurrentTableFilters);

    refreshTableStatus();
    refreshActiveTablePlot(immediatePlot);
  }

  function resetTableFilters() {
    const input = document.getElementById("table-search-input");
    setSearchQuery("");
    setFilters([]);
    setFiltersOpen(false);
    if (input) input.value = "";
    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters({ immediatePlot: true });
    refreshTableStatus();
  }

  function getColumnComponentByField(field) {
    if (!state.tabulatorInstance || typeof state.tabulatorInstance.getColumns !== "function") {
      return null;
    }

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        if (col.getField() === field) return col;
      }
    } catch (e) {
      // ignore
    }

    return null;
  }

  function applyColumnVisibilityState() {
    if (!state.tabulatorInstance || state.tabulatorInstance.initialized === false) return;

    const hidden = new Set(getHiddenColumns());
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    for (const field of fields) {
      const col = getColumnComponentByField(field);
      if (!col) continue;

      try {
        if (hidden.has(field)) {
          if (typeof col.hide === "function") col.hide();
        } else {
          if (typeof col.show === "function") col.show();
        }
      } catch (e) {
        // ignore
      }
    }

    renderColumnsList();
    syncColumnsPanelUi();
  }

  function getVisibleFieldsInCurrentOrder() {
    if (!state.tabulatorInstance || typeof state.tabulatorInstance.getColumns !== "function") {
      return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    }

    const out = [];

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        const field = col.getField();
        if (!field) continue;

        let visible = true;
        try {
          if (typeof col.isVisible === "function") {
            visible = !!col.isVisible();
          }
        } catch (e) {
          visible = true;
        }

        if (visible) out.push(field);
      }
    } catch (e) {
      return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    }

    return out;
  }

  function restoreToolbarInputs() {
    const input = document.getElementById("table-search-input");
    if (input) {
      input.value = getSearchQuery();
    }
  }

  function addFilter(initial) {
    const filters = getFilters().slice();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (filters.length >= MAX_FILTERS) {
      return;
    }

    filters.push(
      normalizeFilter(
        initial || {
          id: newFilterId(),
          field: fields[0] || "",
          op: getFieldType(fields[0] || "") === "number" ? "eq" : "contains",
          value: "",
          valueTo: "",
        }
      )
    );

    setFilters(filters);
    setFiltersOpen(true);
    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters({ immediatePlot: true });
  }

  function removeFilter(filterId) {
    const filters = getFilters().filter(function (f) {
      return f.id !== filterId;
    });

    setFilters(filters);

    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters({ immediatePlot: true });
  }

  function updateFilter(filterId, part, value, options) {
    const shouldRerender = !!(options && options.rerender);

    const filters = getFilters().map(function (filter) {
      if (filter.id !== filterId) return filter;

      const next = {
        id: filter.id,
        field: filter.field,
        op: filter.op,
        value: filter.value,
        valueTo: filter.valueTo,
      };

      next[part] = String(value || "");

      if (part === "field") {
        const allowedOps = getOperatorOptions(next.field).map(function (x) {
          return x.value;
        });

        if (!allowedOps.includes(next.op)) {
          next.op = getFieldType(next.field) === "number" ? "eq" : "contains";
          next.value = "";
          next.valueTo = "";
        }
      }

      if (part === "op") {
        if (!operatorNeedsValue(next.op)) {
          next.value = "";
          next.valueTo = "";
        } else if (!operatorNeedsTwoValues(next.op)) {
          next.valueTo = "";
        }
      }

      return next;
    });

    setFilters(filters);

    if (shouldRerender) {
      renderFilterRows();
    }

    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters({ immediatePlot: true });
  }

  function toggleColumnVisibility(field, shouldBeVisible) {
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const hidden = new Set(getHiddenColumns());

    if (!field || !fields.includes(field)) return;

    if (!shouldBeVisible) {
      const currentlyVisibleCount = fields.filter(function (f) {
        return !hidden.has(f);
      }).length;

      if (currentlyVisibleCount <= 1) {
        renderColumnsList();
        return;
      }

      hidden.add(field);
    } else {
      hidden.delete(field);
    }

    setHiddenColumns(Array.from(hidden));
    applyColumnVisibilityState();
  }

  function showAllColumns() {
    setHiddenColumns([]);
    applyColumnVisibilityState();
  }

  function bindTableToolbar() {
    const input = document.getElementById("table-search-input");
    const groupBySelect = document.getElementById("table-group-by-select");
    const resetBtn = document.getElementById("table-reset-btn");
    const resetFiltersBtn = document.getElementById("table-reset-filters-btn");
    const filtersToggleBtn = document.getElementById("table-filters-toggle-btn");
    const columnsToggleBtn = document.getElementById("table-columns-toggle-btn");
    const addFilterBtn = document.getElementById("table-filter-add-btn");
    const showAllColumnsBtn = document.getElementById("table-columns-show-all-btn");
    const filterRows = document.getElementById("table-filter-rows");
    const columnsList = document.getElementById("table-columns-list");
    const activeFilters = document.getElementById("table-active-filters");

    // Row arrivals do not change the toolbar. Replacing its children on every
    // poll closes native selects and discards focused filter inputs.
    const toolbarSignature = JSON.stringify([state.tableFields, state.tableFieldTypes]);
    const toolbarRoot = input || groupBySelect;
    const editingToolbar = document.activeElement &&
      [filterRows, columnsList, groupBySelect].some(function (element) {
        return element && element.contains(document.activeElement);
      });
    const newTable = toolbarRoot && toolbarRoot._plotsrvTable !== state.tabulatorInstance;
    if (!toolbarRoot || newTable || (toolbarRoot._plotsrvSchema !== toolbarSignature && !editingToolbar)) {
      restoreToolbarInputs();
      renderGroupingControl();
      renderFilterRows();
      renderColumnsList();
      renderActiveFilters();
      syncFilterPanelUi();
      syncColumnsPanelUi();
      if (toolbarRoot) {
        toolbarRoot._plotsrvSchema = toolbarSignature;
        toolbarRoot._plotsrvTable = state.tabulatorInstance;
      }
    }

    if (input && !input.dataset.plotsrvBound) {
      let timer = null;

      input.addEventListener("input", function () {
        const q = String(input.value || "");
        setSearchQuery(q);

        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          applyAllTableFilters({ immediatePlot: true });
        }, 120);
      });

      input.dataset.plotsrvBound = "1";
    }

    if (groupBySelect && !groupBySelect.dataset.plotsrvBound) {
      groupBySelect.addEventListener("change", function () {
        setTableGrouping(groupBySelect.value);
      });

      groupBySelect.dataset.plotsrvBound = "1";
    }

    if (resetBtn && !resetBtn.dataset.plotsrvBound) {
      resetBtn.addEventListener("click", function () {
        state.tableUiState = defaultTableUiState();
        saveTableUiState();

        if (input) input.value = "";

        if (state.tabulatorInstance && state.tabulatorInstance.initialized !== false) {
          // Clear grouping before rebuilding columns. Reset only the view:
          // replacing rows here can race with grouping and live arrivals.
          applyTableGrouping();
          try {
            state.tabulatorInstance.clearFilter(true);
          } catch (e) {
            // ignore
          }

          try {
            state.tabulatorInstance.clearSort();
          } catch (e) {
            // ignore
          }

          if (Array.isArray(state.tableColumnDefs) && state.tableColumnDefs.length > 0) {
            try {
              state.tabulatorInstance.setColumns(state.tableColumnDefs);
            } catch (e) {
              // ignore
            }
          }
        }

        renderGroupingControl();
        renderFilterRows();
        renderColumnsList();
        renderActiveFilters();
        syncFilterPanelUi();
        syncColumnsPanelUi();
        applyColumnVisibilityState();
        applyTableGrouping();
        applyAllTableFilters({ immediatePlot: true });
      });

      resetBtn.dataset.plotsrvBound = "1";
    }

    if (resetFiltersBtn && !resetFiltersBtn.dataset.plotsrvBound) {
      resetFiltersBtn.addEventListener("click", resetTableFilters);
      resetFiltersBtn.dataset.plotsrvBound = "1";
    }

    if (filtersToggleBtn && !filtersToggleBtn.dataset.plotsrvBound) {
      filtersToggleBtn.addEventListener("click", function () {
        const nextOpen = !getTableUiState().filtersOpen;
        setFiltersOpen(nextOpen);
        syncFilterPanelUi();
      });

      filtersToggleBtn.dataset.plotsrvBound = "1";
    }

    if (columnsToggleBtn && !columnsToggleBtn.dataset.plotsrvBound) {
      columnsToggleBtn.addEventListener("click", function () {
        const nextOpen = !getTableUiState().columnsOpen;
        setColumnsOpen(nextOpen);
        syncColumnsPanelUi();
      });

      columnsToggleBtn.dataset.plotsrvBound = "1";
    }

    if (addFilterBtn && !addFilterBtn.dataset.plotsrvBound) {
      addFilterBtn.addEventListener("click", function () {
        addFilter();
        const filters = getFilters();
        const newest = filters[filters.length - 1];
        if (!newest) return;

        window.requestAnimationFrame(function () {
          const firstInput = document.querySelector(
            '[data-filter-id="' + newest.id + '"][data-filter-part="value"]'
          );
          if (firstInput && typeof firstInput.focus === "function") {
            firstInput.focus();
          }
        });
      });

      addFilterBtn.dataset.plotsrvBound = "1";
    }

    if (showAllColumnsBtn && !showAllColumnsBtn.dataset.plotsrvBound) {
      showAllColumnsBtn.addEventListener("click", function () {
        showAllColumns();
      });

      showAllColumnsBtn.dataset.plotsrvBound = "1";
    }

    if (addFilterBtn) {
      addFilterBtn.disabled = getFilters().length >= MAX_FILTERS;
      addFilterBtn.title =
        getFilters().length >= MAX_FILTERS
          ? "Maximum number of filters reached"
          : "";
    }

    if (filterRows && !filterRows.dataset.plotsrvBound) {
      filterRows.addEventListener("change", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const filterId = target.getAttribute("data-filter-id");
        const part = target.getAttribute("data-filter-part");

        if (!filterId || !part) return;

        const rerender = part === "field" || part === "op";
        updateFilter(filterId, part, target.value, { rerender: rerender });
      });

      filterRows.addEventListener("input", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const filterId = target.getAttribute("data-filter-id");
        const part = target.getAttribute("data-filter-part");

        if (!filterId || !part || (part !== "value" && part !== "valueTo")) return;

        updateFilter(filterId, part, target.value, { rerender: false });
      });

      filterRows.addEventListener("click", function (ev) {
        const target =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-filter-action='remove']")
            : null;
        if (!target) return;

        const filterId = target.getAttribute("data-filter-id");
        if (!filterId) return;

        removeFilter(filterId);
      });

      filterRows.dataset.plotsrvBound = "1";
    }

    if (columnsList && !columnsList.dataset.plotsrvBound) {
      columnsList.addEventListener("change", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const field = target.getAttribute("data-column-field");
        if (!field) return;

        toggleColumnVisibility(field, !!target.checked);
      });

      columnsList.dataset.plotsrvBound = "1";
    }

    if (activeFilters && !activeFilters.dataset.plotsrvBound) {
      activeFilters.addEventListener("click", function (ev) {
        const btn =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-filter-chip-remove]")
            : null;
        if (!btn) return;

        const filterId = btn.getAttribute("data-filter-chip-remove");
        if (!filterId) return;

        removeFilter(filterId);
      });

      activeFilters.dataset.plotsrvBound = "1";
    }
  }

  function csvEscape(value) {
    const text = String(value == null ? "" : value);
    if (
      text.includes('"') ||
      text.includes(",") ||
      text.includes("\n") ||
      text.includes("\r")
    ) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  function downloadTextFile(filename, text, mime) {
    const blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function buildCsvFromRows(rows, fields) {
    const lines = [];
    lines.push(fields.map(csvEscape).join(","));

    for (const row of rows) {
      const vals = fields.map(function (field) {
        return csvEscape(row ? row[field] : "");
      });
      lines.push(vals.join(","));
    }

    return lines.join("\r\n");
  }

  function exportFilteredRichTable() {
    if (!state.tabulatorInstance) return false;

    let rows = [];
    let readActiveRows = false;
    try {
      rows = state.tabulatorInstance.getData("active");
      if (Array.isArray(rows)) readActiveRows = true;
      else rows = [];
    } catch (e) {
      rows = [];
    }

    if (!readActiveRows) {
      try {
        rows = state.tabulatorInstance.getData();
        if (!Array.isArray(rows)) rows = [];
      } catch (e) {
        rows = [];
      }
    }

    const visibleFields = getVisibleFieldsInCurrentOrder();
    if (!visibleFields.length) return false;

    const csv = buildCsvFromRows(rows, visibleFields);

    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "table").replace(/[^\w.-]+/g, "_");
    const filename = base + "-filtered-" + stamp + ".csv";

    downloadTextFile(filename, csv, "text/csv;charset=utf-8");
    return true;
  }

  function exportRetainedRawWindow() {
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    if (!fields.length) return false;

    const csv = buildCsvFromRows(rows, fields);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "stream").replace(/[^\w.-]+/g, "_");
    downloadTextFile(
      base + "-retained-window-" + stamp + ".csv",
      csv,
      "text/csv;charset=utf-8"
    );
    return true;
  }

  function configureTableExplorer(options) {
    const settings = options && typeof options === "object" ? options : {};
    const table = settings.table;
    if (!table) return;

    const fields = Array.isArray(settings.fields) ? settings.fields.slice() : [];
    const rows = Array.isArray(settings.rows) ? settings.rows : [];

    if (!state.tableUiState) {
      loadTableUiState();
    }

    // The stream renderer uses the same small controller as a rich static
    // table.  There is only one table surface per page, so this alias lets
    // search, filters, and column controls operate without duplicating their
    // state model or event bindings.
    if (state.tableGroupingOwner !== table) {
      state.tableAppliedGrouping = undefined;
      state.tableGroupingOwner = table;
    }
    state.tabulatorInstance = table;
    state.tableLastPayload = settings.payload || {};
    state.tableRows = rows;
    state.tableFields = fields;
    state.tableFieldTypes = inferFieldTypes(fields, rows);
    state.tableColumnDefs = Array.isArray(settings.columnDefs)
      ? settings.columnDefs
      : [];
    if (typeof core.setTablePlotCapabilities === "function") {
      core.setTablePlotCapabilities(settings.plotCapabilities || { sources: ["table"] });
    }

    if (typeof table.on === "function" && !table._plotsrvUpdatePolicyBound) {
      table.on("dataSorted", function () {
        if (typeof core.notifyUpdateEligibilityChanged === "function") {
          core.notifyUpdateEligibilityChanged();
        }
      });
      table._plotsrvUpdatePolicyBound = true;
    }

    bindTableToolbar();
    // Tabulator builds asynchronously. Calling setGroupBy before tableBuilt
    // can leave its display pipeline empty even though getData() has rows.
    if (table.initialized === false && typeof table.on === "function") {
      if (!table._plotsrvReadyBound) {
        table._plotsrvReadyBound = true;
        table.on("tableBuilt", function () {
          if (state.tabulatorInstance !== table) return;
          applyColumnVisibilityState();
          applyTableGrouping();
          applyAllTableFilters();
          refreshTableStatus();
          if (typeof core.configureTablePlotSurface === "function") core.configureTablePlotSurface();
        });
      }
      return;
    }
    applyTableGrouping();
    applyAllTableFilters();
    refreshTableStatus();
    if (typeof core.configureTablePlotSurface === "function") {
      core.configureTablePlotSurface();
    }
  }

  function destroyMountedTable() {
    const table = state.tabulatorInstance;
    state.tabulatorInstance = null;
    state.tableAppliedGrouping = undefined;
    state.tableGroupingOwner = null;

    if (table && typeof table.destroy === "function") {
      try {
        table.destroy();
      } catch (e) {
        // A removed artifact surface may already have been detached.
      }
    }
  }

  function initializeEmbeddedTableExplorer(options) {
    const settings = options && typeof options === "object" ? options : {};
    const grid = settings.grid;
    const data = settings.data && typeof settings.data === "object" ? settings.data : {};
    const fields = Array.isArray(data.columns) ? data.columns.slice() : [];
    const rows = Array.isArray(data.rows) ? data.rows.slice() : [];

    if (!grid || !fields.length || !Array.isArray(data.rows)) return false;
    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      return false;
    }

    destroyMountedTable();
    if (!state.tableUiState) loadTableUiState();
    const columns = buildColumnDefs(fields);
    const table = new Tabulator(grid, {
      data: rows,
      columns: columns,
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 100,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
      // JSON object and table column names are flat keys. In particular,
      // "http.status" is a literal field rather than a nested lookup.
      nestedFieldSeparator: false,
    });

    if (typeof table.on === "function") {
      table.on("dataFiltered", function () {
        refreshTableStatus();
        refreshActiveTablePlot();
      });
    }

    configureTableExplorer({
      table: table,
      payload: data,
      rows: rows,
      fields: fields,
      columnDefs: columns,
      plotCapabilities: settings.plotCapabilities || { sources: ["table"] },
    });
    state.embeddedTableExplorer = true;
    return true;
  }

  function disposeEmbeddedTableExplorer() {
    if (!state.embeddedTableExplorer) return;
    destroyMountedTable();
    state.embeddedTableExplorer = false;
  }

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    if (!grid) return;

    if (!state.tableUiState) {
      loadTableUiState();
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    const url =
      "/table/data?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&_ts=" +
      Date.now();

    let res = await fetch(url);
    // A file-backed server admits only a bounded number of expensive CSV
    // loads. A short retry keeps normal refreshes smooth without hiding a
    // persistent failure behind an endless client loop.
    for (let attempt = 0; res.status === 503 && attempt < 2; attempt += 1) {
      await new Promise(function (resolve) {
        window.setTimeout(resolve, 250 * (attempt + 1));
      });
      res = await fetch(url);
    }

    if (!res.ok) {
      if (
        res.status === 404 &&
        typeof core.isHistoryMode === "function" &&
        core.isHistoryMode() &&
        typeof core.handleMissingSnapshot === "function"
      ) {
        await core.handleMissingSnapshot("table");
        return;
      }

      console.error("Failed to load table data");
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to load table data (" + res.status + ").");
      }
      return;
    }

    const data = await res.json();
    let columns = buildColumnDefs(data.columns || []);
    const rows = data.rows || [];

    if (state.tabulatorInstance) {
      const sorters = currentSorters(state.tabulatorInstance);
      columns = preserveColumnOrder(columns, state.tabulatorInstance);
      state.tableAppliedGrouping = undefined;
      await Promise.resolve(state.tabulatorInstance.setColumns(columns));
      await Promise.resolve(state.tabulatorInstance.replaceData(rows));
      if (sorters.length && typeof state.tabulatorInstance.setSort === "function") {
        await Promise.resolve(state.tabulatorInstance.setSort(sorters));
      }
      configureTableExplorer({
        table: state.tabulatorInstance,
        payload: data,
        rows: rows,
        fields: data.columns || [],
        columnDefs: columns,
        plotCapabilities: { sources: ["table"] },
      });
      return;
    }

    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to start the rich table renderer.");
      }
      return;
    }

    state.tabulatorInstance = new Tabulator("#table-grid", {
      data: rows,
      columns: columns,
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 100,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
      // Preserve literal dotted names for ordinary and embedded table data.
      nestedFieldSeparator: false,
    });

    if (typeof state.tabulatorInstance.on === "function") {
      state.tabulatorInstance.on("dataFiltered", function () {
        refreshTableStatus();
        refreshActiveTablePlot();
      });
    }

    configureTableExplorer({
      table: state.tabulatorInstance,
      payload: data,
      rows: rows,
      fields: data.columns || [],
      columnDefs: columns,
      plotCapabilities: { sources: ["table"] },
    });
  }

  function exportCompletePublishedTable() {
    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
    const sourceDownload =
      state.tableLastPayload &&
      state.tableLastPayload.meta &&
      state.tableLastPayload.meta.source_download_url;

    if (!isHistory && typeof sourceDownload === "string" && sourceDownload) {
      window.location.href = sourceDownload + "&_ts=" + Date.now();
      return;
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    window.location.href =
      "/table/export?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&format=csv&_ts=" +
      Date.now();
  }

  function exportTable(scope) {
    if (scope === "filtered") {
      return exportFilteredRichTable();
    }
    if (scope === "retained") {
      return exportRetainedRawWindow();
    }
    if (scope === "complete") {
      return exportCompletePublishedTable();
    }

    // Retain the old public helper's behaviour for integrations that invoke
    // exportTable() directly. The bottom dock always supplies an exact scope.
    if (state.tabulatorInstance && exportFilteredRichTable()) return true;
    return exportCompletePublishedTable();
  }

  core.loadTable = loadTable;
  core.exportTable = exportTable;
  core.exportFilteredRichTable = exportFilteredRichTable;
  core.exportRetainedRawWindow = exportRetainedRawWindow;
  core.exportCompletePublishedTable = exportCompletePublishedTable;
  core.configureTableExplorer = configureTableExplorer;
  core.disposeEmbeddedTableExplorer = disposeEmbeddedTableExplorer;
  core.initializeEmbeddedTableExplorer = initializeEmbeddedTableExplorer;
  core.getCurrentFilteredLoadedRows = getCurrentFilteredLoadedRows;
  core.hasActiveTableFiltering = hasActiveTableFiltering;
  core.resetTableFilters = resetTableFilters;
  core.getTableGrouping = normalizeGroupingField;
  core.setTableGrouping = setTableGrouping;

  window.exportTable = exportTable;
})();
