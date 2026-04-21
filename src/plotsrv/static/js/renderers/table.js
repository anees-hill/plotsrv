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

  function getViewId() {
    return config.activeViewId || "default";
  }

  function getDefaultTablePrefs() {
    return {
      column_order: [],
      hidden_fields: [],
      search_query: "",
      header_filters: {},
    };
  }

  function loadViewTablePrefs() {
    if (typeof core.loadTablePrefs !== "function") {
      return getDefaultTablePrefs();
    }
    return core.loadTablePrefs(getViewId());
  }

  function saveViewTablePrefs(prefs) {
    if (typeof core.saveTablePrefs !== "function") return;
    core.saveTablePrefs(getViewId(), prefs);
  }

  function clearViewTablePrefs() {
    if (typeof core.clearTablePrefs !== "function") return;
    core.clearTablePrefs(getViewId());
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
    if (!status) return;

    const total = Number(data.total_rows ?? 0);
    const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

    if (total <= 0 && returned <= 0) {
      status.textContent = "";
      return;
    }

    const isTrunc = returned < total;
    const hasFilter = typeof activeCount === "number" && activeCount !== returned;

    let html = "";

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

    status.innerHTML = html;
  }

  function refreshTableStatus() {
    if (!state.tableLastPayload) return;
    updateTableStatus(state.tableLastPayload, getActiveRowCount());
  }

  function getOrderedFields(defaultFields, preferredOrder) {
    const seen = new Set();
    const out = [];

    const pref = Array.isArray(preferredOrder) ? preferredOrder : [];
    const defs = Array.isArray(defaultFields) ? defaultFields : [];

    for (const field of pref) {
      const f = String(field || "");
      if (!f || seen.has(f)) continue;
      if (defs.includes(f)) {
        out.push(f);
        seen.add(f);
      }
    }

    for (const field of defs) {
      const f = String(field || "");
      if (!f || seen.has(f)) continue;
      out.push(f);
      seen.add(f);
    }

    return out;
  }

  function buildColumnDefs(fields, prefs) {
    const hidden = new Set(
      Array.isArray(prefs && prefs.hidden_fields) ? prefs.hidden_fields : []
    );
    const orderedFields = getOrderedFields(fields, prefs && prefs.column_order);

    return orderedFields.map(function (field) {
      return {
        title: field,
        field: field,
        visible: !hidden.has(field),
        headerFilter: "input",
        headerFilterPlaceholder: "Filter…",
        headerFilterFunc: "like",
      };
    });
  }

  function getCurrentHeaderFilters() {
    const out = {};

    if (
      !state.tabulatorInstance ||
      typeof state.tabulatorInstance.getHeaderFilters !== "function"
    ) {
      return out;
    }

    try {
      const filters = state.tabulatorInstance.getHeaderFilters();
      if (!Array.isArray(filters)) return out;

      for (const item of filters) {
        if (!item || !item.field) continue;
        out[String(item.field)] = String(item.value ?? "");
      }
    } catch (e) {
      // ignore
    }

    return out;
  }

  function getCurrentColumnState() {
    const fields = Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    const prefs = loadViewTablePrefs();

    if (!state.tabulatorInstance || typeof state.tabulatorInstance.getColumns !== "function") {
      return {
        column_order: Array.isArray(prefs.column_order) ? prefs.column_order : fields,
        hidden_fields: Array.isArray(prefs.hidden_fields) ? prefs.hidden_fields : [],
        search_query:
          typeof prefs.search_query === "string" ? prefs.search_query : "",
        header_filters:
          prefs.header_filters && typeof prefs.header_filters === "object"
            ? prefs.header_filters
            : {},
      };
    }

    const order = [];
    const hidden = [];

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        const field = col.getField();
        if (!field) continue;
        order.push(String(field));

        try {
          if (typeof col.isVisible === "function" && !col.isVisible()) {
            hidden.push(String(field));
          }
        } catch (e) {
          // ignore
        }
      }
    } catch (e) {
      // ignore
    }

    for (const field of fields) {
      if (!order.includes(field)) {
        order.push(field);
      }
    }

    return {
      column_order: order,
      hidden_fields: hidden,
      search_query:
        typeof prefs.search_query === "string" ? prefs.search_query : "",
      header_filters: getCurrentHeaderFilters(),
    };
  }

  function persistCurrentColumnState() {
    const current = getCurrentColumnState();
    saveViewTablePrefs(current);
  }

  function persistSearchQuery() {
    const input = document.getElementById("table-search-input");
    const prefs = getCurrentColumnState();
    prefs.search_query = input ? String(input.value || "") : "";
    saveViewTablePrefs(prefs);
  }

  function persistHeaderFilters() {
    const prefs = getCurrentColumnState();
    prefs.header_filters = getCurrentHeaderFilters();
    saveViewTablePrefs(prefs);
  }

  function closeColumnsPanel() {
    const panel = document.getElementById("table-columns-panel");
    const btn = document.getElementById("table-columns-btn");
    if (panel) panel.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function toggleColumnsPanel() {
    const panel = document.getElementById("table-columns-panel");
    const btn = document.getElementById("table-columns-btn");
    if (!panel || !btn) return;

    const nextHidden = !panel.hidden;
    panel.hidden = nextHidden;
    btn.setAttribute("aria-expanded", nextHidden ? "false" : "true");
  }

  function renderColumnsPanel() {
    const panelList = document.getElementById("table-columns-list");
    if (!panelList) return;

    const prefs = loadViewTablePrefs();
    const hidden = new Set(
      Array.isArray(prefs.hidden_fields) ? prefs.hidden_fields : []
    );
    const orderedFields = getOrderedFields(
      Array.isArray(state.tableFields) ? state.tableFields : [],
      prefs.column_order
    );

    panelList.innerHTML = "";

    for (const field of orderedFields) {
      const row = document.createElement("label");
      row.className = "ps-table-columns__item";

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !hidden.has(field);
      cb.setAttribute("data-field", field);

      cb.addEventListener("change", function () {
        if (!state.tabulatorInstance) return;

        try {
          if (cb.checked) {
            state.tabulatorInstance.showColumn(field);
          } else {
            state.tabulatorInstance.hideColumn(field);
          }
        } catch (e) {
          // ignore
        }

        persistCurrentColumnState();
        renderColumnsPanel();
        applyTableSearch(false);
        refreshTableStatus();
      });

      const text = document.createElement("span");
      text.textContent = field;

      row.appendChild(cb);
      row.appendChild(text);
      panelList.appendChild(row);
    }
  }

  function applyTableSearch(saveToPrefs) {
    const input = document.getElementById("table-search-input");
    if (!input || !state.tabulatorInstance) return;

    const q = String(input.value || "").trim().toLowerCase();

    if (saveToPrefs !== false) {
      persistSearchQuery();
    }

    if (!q) {
      try {
        state.tabulatorInstance.clearFilter();
      } catch (e) {
        // ignore
      }
      refreshTableStatus();
      return;
    }

    const visibleFields = [];

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        const field = col.getField();
        if (!field) continue;

        try {
          if (typeof col.isVisible === "function" && col.isVisible()) {
            visibleFields.push(String(field));
          }
        } catch (e) {
          visibleFields.push(String(field));
        }
      }
    } catch (e) {
      // ignore
    }

    const fields =
      visibleFields.length > 0
        ? visibleFields
        : Array.isArray(state.tableFields)
          ? state.tableFields
          : [];

    state.tabulatorInstance.setFilter(function (rowData) {
      for (const field of fields) {
        const raw = rowData[field];
        const text = String(raw == null ? "" : raw).toLowerCase();
        if (text.includes(q)) return true;
      }
      return false;
    });

    refreshTableStatus();
  }

  function applySavedHeaderFilters(prefs) {
    if (
      !state.tabulatorInstance ||
      typeof state.tabulatorInstance.setHeaderFilterValue !== "function"
    ) {
      return;
    }

    const filters =
      prefs && prefs.header_filters && typeof prefs.header_filters === "object"
        ? prefs.header_filters
        : {};

    for (const field of Array.isArray(state.tableFields) ? state.tableFields : []) {
      const value = Object.prototype.hasOwnProperty.call(filters, field)
        ? filters[field]
        : "";
      try {
        state.tabulatorInstance.setHeaderFilterValue(field, value);
      } catch (e) {
        // ignore
      }
    }
  }

  function clearAllHeaderFilters() {
    if (
      !state.tabulatorInstance ||
      typeof state.tabulatorInstance.clearHeaderFilter !== "function"
    ) {
      return;
    }

    try {
      state.tabulatorInstance.clearHeaderFilter();
    } catch (e) {
      // ignore
    }
  }

  function bindTableToolbar() {
    const input = document.getElementById("table-search-input");
    const resetBtn = document.getElementById("table-reset-btn");
    const columnsBtn = document.getElementById("table-columns-btn");
    const panel = document.getElementById("table-columns-panel");

    if (input && !input.dataset.plotsrvBound) {
      let timer = null;

      input.addEventListener("input", function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          applyTableSearch(true);
        }, 120);
      });

      input.dataset.plotsrvBound = "1";
    }

    if (columnsBtn && !columnsBtn.dataset.plotsrvBound) {
      columnsBtn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        toggleColumnsPanel();
      });

      columnsBtn.dataset.plotsrvBound = "1";
    }

    if (panel && !panel.dataset.plotsrvBound) {
      panel.addEventListener("click", function (ev) {
        ev.stopPropagation();
      });
      panel.dataset.plotsrvBound = "1";
    }

    if (!document.body.dataset.plotsrvTablePanelBound) {
      document.addEventListener("click", function () {
        closeColumnsPanel();
      });

      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") closeColumnsPanel();
      });

      document.body.dataset.plotsrvTablePanelBound = "1";
    }

    if (resetBtn && !resetBtn.dataset.plotsrvBound) {
      resetBtn.addEventListener("click", function () {
        const prefs = getDefaultTablePrefs();
        clearViewTablePrefs();

        if (input) {
          input.value = "";
        }

        closeColumnsPanel();

        if (!state.tabulatorInstance) return;

        try {
          state.tabulatorInstance.clearFilter();
        } catch (e) {
          // ignore
        }

        clearAllHeaderFilters();

        try {
          state.tabulatorInstance.clearSort();
        } catch (e) {
          // ignore
        }

        if (Array.isArray(state.tableFields) && state.tableFields.length > 0) {
          const defaultColumns = buildColumnDefs(state.tableFields, prefs);
          state.tableColumnDefs = defaultColumns;

          try {
            state.tabulatorInstance.setColumns(defaultColumns);
          } catch (e) {
            // ignore
          }
        }

        try {
          state.tabulatorInstance.replaceData(state.tableRows || []);
        } catch (e) {
          // ignore
        }

        renderColumnsPanel();
        applyTableSearch(false);
        refreshTableStatus();
      });

      resetBtn.dataset.plotsrvBound = "1";
    }
  }

  function wireTableEvents() {
    if (!state.tabulatorInstance || typeof state.tabulatorInstance.on !== "function") {
      return;
    }

    if (state.tableEventsBound) return;
    state.tableEventsBound = true;

    state.tabulatorInstance.on("dataFiltered", function () {
      persistHeaderFilters();
      refreshTableStatus();
    });

    state.tabulatorInstance.on("columnMoved", function () {
      persistCurrentColumnState();
      renderColumnsPanel();
      applyTableSearch(false);
    });

    state.tabulatorInstance.on("columnVisibilityChanged", function () {
      persistCurrentColumnState();
      renderColumnsPanel();
      applyTableSearch(false);
    });
  }

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    if (!grid) return;

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
    const fields = (data.columns || []).slice();
    const prefs = loadViewTablePrefs();
    const columns = buildColumnDefs(fields, prefs);
    const rows = data.rows || [];

    state.tableLastPayload = data;
    state.tableRows = rows;
    state.tableFields = fields;
    state.tableColumnDefs = columns;

    const input = document.getElementById("table-search-input");
    if (input) {
      input.value = typeof prefs.search_query === "string" ? prefs.search_query : "";
    }

    if (state.tabulatorInstance) {
      state.tableEventsBound = false;
      state.tabulatorInstance.setColumns(columns);
      state.tabulatorInstance.replaceData(rows);
      wireTableEvents();
      bindTableToolbar();
      renderColumnsPanel();
      applySavedHeaderFilters(prefs);
      applyTableSearch(false);
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

    wireTableEvents();
    bindTableToolbar();
    renderColumnsPanel();
    applySavedHeaderFilters(prefs);
    applyTableSearch(false);
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