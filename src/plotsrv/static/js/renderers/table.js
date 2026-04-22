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
    return "plotsrv:v3:table_state:" + String(config.activeViewId || "default");
  }

  function defaultTableUiState() {
    return {
      searchQuery: "",
      filtersOpen: false,
      filters: [],
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

    state.tableUiState = {
      searchQuery:
        parsed && typeof parsed.searchQuery === "string"
          ? parsed.searchQuery
          : base.searchQuery,
      filtersOpen:
        parsed && typeof parsed.filtersOpen === "boolean"
          ? parsed.filtersOpen
          : base.filtersOpen,
      filters: filters.map(normalizeFilter).filter(Boolean),
    };
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
        } else {
          textHits += 1;
        }
      }

      out[field] = numericHits > 0 && textHits === 0 ? "number" : "text";
    }

    return out;
  }

  function getActiveRowCount() {
    if (!state.tabulatorInstance) return null;

    try {
      const active = state.tabulatorInstance.getData("active");
      if (Array.isArray(active)) return active.length;
    } catch (e) {
      // ignore
    }

    try {
      const allRows = state.tabulatorInstance.getData();
      if (Array.isArray(allRows)) return allRows.length;
    } catch (e) {
      // ignore
    }

    return null;
  }

  function updateTableStatus(data, activeCount) {
    const status = document.getElementById("status");
    const inline = document.getElementById("table-status-inline");

    const targetEls = [status, inline].filter(Boolean);
    if (!targetEls.length) return;

    const total = Number(data.total_rows ?? 0);
    const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

    let html = "";

    if (total <= 0 && returned <= 0) {
      html = "";
    } else {
      const isTrunc = returned < total;
      const hasFilter = typeof activeCount === "number" && activeCount !== returned;

      if (hasFilter) {
        html =
          "Showing " +
          activeCount +
          " filtered rows of " +
          returned +
          " loaded";
        if (total > returned) {
          html += " (" + total + " total)";
        } else {
          html += ".";
        }
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
    updateTableStatus(state.tableLastPayload, getActiveRowCount());
  }

  function getSearchQuery() {
    return getTableUiState().searchQuery || "";
  }

  function setSearchQuery(value) {
    const ui = getTableUiState();
    ui.searchQuery = String(value || "");
    saveTableUiState();
  }

  function getFilters() {
    return Array.isArray(getTableUiState().filters) ? getTableUiState().filters : [];
  }

  function setFilters(filters) {
    const ui = getTableUiState();
    ui.filters = Array.isArray(filters) ? filters.map(normalizeFilter).filter(Boolean) : [];
    saveTableUiState();
  }

  function setFiltersOpen(isOpen) {
    const ui = getTableUiState();
    ui.filtersOpen = !!isOpen;
    saveTableUiState();
  }

  function getOperatorOptions(field) {
    const fieldType = getFieldType(field);
    return fieldType === "number" ? FILTER_OPS.number : FILTER_OPS.text;
  }

  function operatorNeedsValue(op) {
    return !["missing", "not_missing"].includes(op);
  }

  function operatorNeedsTwoValues(op) {
    return ["between", "not_between"].includes(op);
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

  function escapeHtml(s) {
    if (typeof core.escapeHtml === "function") {
      return core.escapeHtml(s);
    }
    return String(s);
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
              return '<option value="' + escapeHtml(f) + '"' + sel + ">" + escapeHtml(f) + "</option>";
            })
            .join("") +
          "</select>";

        const opSelect =
          '<select class="ps-table-filter-select" data-filter-part="op" data-filter-id="' +
          escapeHtml(filter.id) +
          '">' +
          renderOperatorOptions(field, op) +
          "</select>";

        const valueInput =
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

    if (operatorNeedsTwoValues(op)) {
      return field + " " + opLabel + " " + value + " and " + valueTo;
    }

    if (operatorNeedsValue(op)) {
      return field + " " + opLabel + " " + value;
    }

    return field + " " + opLabel;
  }

  function isFilterComplete(filter) {
    if (!filter.field || !filter.op) return false;
    if (!operatorNeedsValue(filter.op)) return true;
    if (operatorNeedsTwoValues(filter.op)) {
      return String(filter.value || "").trim() !== "" && String(filter.valueTo || "").trim() !== "";
    }
    return String(filter.value || "").trim() !== "";
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

  function syncFilterPanelUi() {
    const panel = document.getElementById("table-filter-panel");
    const btn = document.getElementById("table-filters-toggle-btn");
    const ui = getTableUiState();

    const shouldShow = !!ui.filtersOpen || hasActiveFilters();

    if (panel) {
      panel.hidden = !shouldShow;
    }

    if (btn) {
      btn.setAttribute("aria-expanded", shouldShow ? "true" : "false");
    }

    syncFilterButtonUi();
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
      if (op === "not_between") return !(a >= Math.min(b, c) && a <= Math.max(b, c));

      return true;
    }

    const text = String(raw == null ? "" : raw).toLowerCase();
    const q = String(filter.value || "").toLowerCase();

    if (op === "contains") return text.includes(q);
    if (op === "eq") return text === q;
    if (op === "neq") return text !== q;

    return true;
  }

  function applyAllTableFilters() {
    if (!state.tabulatorInstance) return;

    const searchQuery = getSearchQuery().trim().toLowerCase();
    const filters = getCompleteFilters();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (!searchQuery && !filters.length) {
      state.tabulatorInstance.clearFilter(true);
      refreshTableStatus();
      return;
    }

    state.tabulatorInstance.setFilter(function (rowData) {
      if (searchQuery) {
        let matched = false;
        for (const field of fields) {
          const raw = rowData[field];
          const text = String(raw == null ? "" : raw).toLowerCase();
          if (text.includes(searchQuery)) {
            matched = true;
            break;
          }
        }
        if (!matched) return false;
      }

      for (const filter of filters) {
        if (!matchesSingleFilter(rowData, filter)) return false;
      }

      return true;
    });

    refreshTableStatus();
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
    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
  }

  function removeFilter(filterId) {
    const filters = getFilters().filter(function (f) {
      return f.id !== filterId;
    });

    setFilters(filters);
    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
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
    applyAllTableFilters();
  }

  function bindTableToolbar() {
    const input = document.getElementById("table-search-input");
    const resetBtn = document.getElementById("table-reset-btn");
    const filtersToggleBtn = document.getElementById("table-filters-toggle-btn");
    const addFilterBtn = document.getElementById("table-filter-add-btn");
    const filterRows = document.getElementById("table-filter-rows");
    const activeFilters = document.getElementById("table-active-filters");

    restoreToolbarInputs();
    syncFilterPanelUi();
    renderFilterRows();
    renderActiveFilters();

    if (input && !input.dataset.plotsrvBound) {
      let timer = null;

      input.addEventListener("input", function () {
        const q = String(input.value || "");
        setSearchQuery(q);

        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          applyAllTableFilters();
        }, 120);
      });

      input.dataset.plotsrvBound = "1";
    }

    if (resetBtn && !resetBtn.dataset.plotsrvBound) {
      resetBtn.addEventListener("click", function () {
        state.tableUiState = defaultTableUiState();
        saveTableUiState();

        if (input) input.value = "";

        if (state.tabulatorInstance) {
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

          try {
            state.tabulatorInstance.replaceData(state.tableRows || []);
          } catch (e) {
            // ignore
          }
        }

        renderFilterRows();
        renderActiveFilters();
        syncFilterPanelUi();
        applyAllTableFilters();
      });

      resetBtn.dataset.plotsrvBound = "1";
    }

    if (filtersToggleBtn && !filtersToggleBtn.dataset.plotsrvBound) {
      filtersToggleBtn.addEventListener("click", function () {
        const willOpen = !(!!getTableUiState().filtersOpen || hasActiveFilters());
        setFiltersOpen(willOpen);
        syncFilterPanelUi();
      });

      filtersToggleBtn.dataset.plotsrvBound = "1";
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

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    if (!grid) return;

    if (!state.tableUiState) {
      loadTableUiState();
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    const res = await fetch(
      "/table/data?view=" +
        encodeURIComponent(config.activeViewId) +
        snapshotQuery +
        "&_ts=" +
        Date.now()
    );

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
      return;
    }

    const data = await res.json();
    const columns = (data.columns || []).map(function (col) {
      return { title: col, field: col };
    });
    const rows = data.rows || [];

    state.tableLastPayload = data;
    state.tableRows = rows;
    state.tableFields = (data.columns || []).slice();
    state.tableFieldTypes = inferFieldTypes(data.columns || [], rows);
    state.tableColumnDefs = columns;

    if (state.tabulatorInstance) {
      state.tabulatorInstance.setColumns(columns);
      state.tabulatorInstance.replaceData(rows);
      bindTableToolbar();
      applyAllTableFilters();
      refreshTableStatus();
      return;
    }

    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      return;
    }

    state.tabulatorInstance = new Tabulator("#table-grid", {
      data: rows,
      columns: columns,
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 20,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
    });

    if (typeof state.tabulatorInstance.on === "function") {
      state.tabulatorInstance.on("dataFiltered", function () {
        refreshTableStatus();
      });
    }

    bindTableToolbar();
    applyAllTableFilters();
    refreshTableStatus();
  }

  function exportTable() {
    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    window.location.href =
      "/table/export?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&format=csv&_ts=" +
      Date.now();
  }

  core.loadTable = loadTable;
  core.exportTable = exportTable;

  window.exportTable = exportTable;
})();