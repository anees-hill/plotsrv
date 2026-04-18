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

  function updateTableStatus(data) {
    const status = document.getElementById("status");
    if (!status) return;

    const total = Number(data.total_rows ?? 0);
    const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

    if (total > 0 && returned > 0) {
      const isTrunc = returned < total;
      status.innerHTML =
        "Showing " +
        returned +
        " of " +
        total +
        " rows." +
        (isTrunc
          ? ' <span class="badge" title="This view is showing a sampled subset of the full data.">TRUNCATED</span>'
          : "");
      return;
    }

    status.textContent = "";
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
    updateTableStatus(data);

    const columns = (data.columns || []).map(function (col) {
      return { title: col, field: col };
    });
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
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 20,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
    });
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