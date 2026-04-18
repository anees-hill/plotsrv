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
  const renderers = window.PLOTSRV.renderers;

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    if (!grid) return;

    const res = await fetch(
      "/table/data?view=" +
        encodeURIComponent(core.getActiveViewId()) +
        core.snapshotQuery() +
        "&_ts=" +
        Date.now()
    );

    if (!res.ok) {
      if (res.status === 404 && core.isHistoryMode()) {
        if (typeof core.handleMissingSnapshot === "function") {
          await core.handleMissingSnapshot("table");
        }
        return;
      }
      console.error("Failed to load table data");
      return;
    }

    const data = await res.json();

    const status = document.getElementById("status");
    if (status) {
      const total = Number(data.total_rows ?? 0);
      const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

      if (total > 0 && returned > 0) {
        const isTrunc = returned < total;
        status.innerHTML =
          `Showing ${returned} of ${total} rows (rich table mode).` +
          (core.isHistoryMode() ? ' <span class="badge">SNAPSHOT</span>' : "") +
          (isTrunc
            ? ' <span class="badge" title="This view is showing a sampled subset of the full data.">TRUNCATED</span>'
            : "");
      } else {
        status.textContent =
          `Showing up to ${config.maxTableRowsRich} rows (rich table mode).`;
      }
    }

    const columns = (data.columns || []).map((col) => ({ title: col, field: col }));
    const rows = data.rows || [];

    if (state.tabulatorInstance) {
      state.tabulatorInstance.setColumns(columns);
      state.tabulatorInstance.replaceData(rows);
      return;
    }

    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      return;
    }

    state.tabulatorInstance = new Tabulator("#table-grid", {
      data: rows,
      columns: columns,
      height: "600px",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 20,
      paginationSizeSelector: [10, 20, 50, 100],
      movableColumns: true,
    });
  }

  function exportTable() {
    window.location.href =
      "/table/export?view=" +
      encodeURIComponent(core.getActiveViewId()) +
      core.snapshotQuery() +
      "&format=csv&_ts=" +
      Date.now();
  }

  renderers.loadTable = loadTable;
  renderers.exportTable = exportTable;

  window.exportTable = exportTable;
})();