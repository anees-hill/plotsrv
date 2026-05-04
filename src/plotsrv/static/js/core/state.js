(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const raw = window.PLOTSRV_CONFIG || {};
  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;

  function readSnapshotFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      const val = params.get("snapshot");
      return val ? String(val) : null;
    } catch (e) {
      return null;
    }
  }

  function writeSnapshotToUrl(snapshotId) {
    try {
      const url = new URL(window.location.href);
      if (snapshotId) url.searchParams.set("snapshot", snapshotId);
      else url.searchParams.delete("snapshot");
      window.history.replaceState({}, "", url.toString());
    } catch (e) {
      // ignore
    }
  }

  config.activeViewId = raw.active_view_id || "default";
  config.kind = raw.kind || "none";
  config.tableViewMode = raw.table_view_mode || "rich";
  config.maxTableRowsSimple = raw.max_table_rows_simple || 200;
  config.maxTableRowsRich = raw.max_table_rows_rich || 1000;

  state.historyItems = [];
  state.currentSnapshot = readSnapshotFromUrl();
  state.plotObjectUrl = null;
  state.autoRefreshTimer = null;
  state.tabulatorInstance = null;

  core.getActiveViewId = function () {
    return config.activeViewId;
  };

  core.readSnapshotFromUrl = readSnapshotFromUrl;

  core.writeSnapshotToUrl = writeSnapshotToUrl;

  core.getCurrentSnapshot = function () {
    return state.currentSnapshot;
  };

  core.setCurrentSnapshot = function (snapshotId) {
    state.currentSnapshot = snapshotId ? String(snapshotId) : null;
    return state.currentSnapshot;
  };

  core.snapshotQuery = function () {
    return state.currentSnapshot
      ? "&snapshot=" + encodeURIComponent(state.currentSnapshot)
      : "";
  };

  core.isHistoryMode = function () {
    return !!state.currentSnapshot;
  };

  core.getHistoryItems = function () {
    return state.historyItems;
  };

  core.setHistoryItems = function (items) {
    state.historyItems = Array.isArray(items) ? items : [];
  };

  core.currentHistoryMeta = function () {
    if (!state.currentSnapshot) return null;
    for (const item of state.historyItems) {
      if (item.snapshot_id === state.currentSnapshot) return item;
    }
    return null;
  };
})();