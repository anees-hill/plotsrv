(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || { core: {}, renderers: {}, state: {}, config: {} };
  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;

  function completeFilter(filter) {
    if (!filter || !filter.field || !filter.op) return false;
    if (filter.op === "missing" || filter.op === "not_missing") return true;
    if (String(filter.value || "").trim() === "") return false;
    if (filter.op === "between" || filter.op === "not_between") {
      return String(filter.valueTo || "").trim() !== "";
    }
    return true;
  }

  function tableHasSorters() {
    const table = state.tabulatorInstance || state.streamTabulatorInstance;
    if (!table || typeof table.getSorters !== "function") return false;
    try {
      const sorters = table.getSorters();
      return Array.isArray(sorters) && sorters.length > 0;
    } catch (e) {
      return false;
    }
  }

  // The single policy boundary for every renderer. Explicit application
  // bypasses interaction blockers, but never changes historical selections.
  function getAutomaticUpdateBlockers() {
    const blockers = [];
    if (document.hidden) blockers.push("hidden_tab");
    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      blockers.push("snapshot");
    }
    if (state.streamHistoricalSessionId) blockers.push("historical_stream_session");

    const ui = state.tableUiState || {};
    if (String(ui.searchQuery || "").trim()) blockers.push("table_search");
    if (Array.isArray(ui.filters) && ui.filters.some(completeFilter)) {
      blockers.push("table_filters");
    }
    if (ui.groupBy) blockers.push("table_grouping");
    if (tableHasSorters()) blockers.push("table_sorting");
    if (state.tablePlotMode === "plot") blockers.push("plot_mode");
    if (ui.filtersOpen || ui.columnsOpen) blockers.push("open_table_panel");

    const main = document.querySelector("main");
    const focused = document.activeElement;
    if (focused && main && main.contains(focused) && focused.matches &&
        focused.matches("input, select, textarea, [contenteditable='true']")) {
      blockers.push("active_editor");
    }
    return blockers;
  }

  function historicalBlocker(blocker) {
    return blocker === "snapshot" || blocker === "historical_stream_session";
  }

  function canApplyPendingUpdate(options) {
    const force = !!(options && options.force);
    const blockers = getAutomaticUpdateBlockers();
    if (blockers.some(historicalBlocker)) return false;
    return force || blockers.length === 0;
  }

  function showPendingUpdate() {
    if (typeof core.setHeaderBrowserDataState === "function") {
      core.setHeaderBrowserDataState("update_available");
    }
  }

  function finishAppliedUpdate(revision) {
    state.appliedUpdateRevision = Math.max(state.appliedUpdateRevision, revision);
    if (typeof core.markBrowserViewApplied === "function") {
      core.markBrowserViewApplied();
    }
    if (state.pendingBrowserUpdate &&
        state.pendingBrowserUpdate.revision <= state.appliedUpdateRevision) {
      state.pendingBrowserUpdate = null;
    }
    if (!state.pendingBrowserUpdate) {
      if (typeof core.setHeaderBrowserDataState === "function") {
        core.setHeaderBrowserDataState("current");
      }
      return;
    }
    showPendingUpdate();
    window.setTimeout(function () { applyPendingUpdate(); }, 0);
  }

  function applyPendingUpdate(options) {
    const pending = state.pendingBrowserUpdate;
    if (!pending || state.browserUpdateApplying) return Promise.resolve(false);
    if (!state.initialViewLoadComplete || !canApplyPendingUpdate(options)) {
      showPendingUpdate();
      return Promise.resolve(false);
    }

    if (pending.kind && pending.kind !== config.kind) {
      window.location.reload();
      return Promise.resolve(true);
    }

    state.browserUpdateApplying = true;
    const revision = pending.revision;
    return Promise.resolve(core.reloadCurrentView())
      .then(function () {
        finishAppliedUpdate(revision);
        return true;
      })
      .catch(function () {
        showPendingUpdate();
        return false;
      })
      .then(function (result) {
        state.browserUpdateApplying = false;
        return result;
      });
  }

  function receiveBrowserUpdate(payload) {
    if (!payload || typeof payload !== "object") return;
    const revision = Number(payload.revision);
    if (!Number.isSafeInteger(revision) || revision <= state.observedUpdateRevision) return;
    state.observedUpdateRevision = revision;

    if (payload.change_type === "catalogue") {
      if (typeof core.refreshViewIcons === "function") core.refreshViewIcons(null);
      return;
    }
    if (payload.view_id && payload.view_id !== config.activeViewId) return;

    // A single assignment coalesces any burst while a fetch is in flight.
    state.pendingBrowserUpdate = payload;
    if (!state.initialViewLoadComplete || !canApplyPendingUpdate()) {
      showPendingUpdate();
      return;
    }
    applyPendingUpdate();
  }

  function bindUpdateNotifications() {
    if (state.browserUpdateSource || typeof window.EventSource !== "function") return;
    const url = "/updates?view=" + encodeURIComponent(config.activeViewId) +
      "&since=" + encodeURIComponent(state.observedUpdateRevision);
    const source = new window.EventSource(url);
    state.browserUpdateSource = source;
    source.addEventListener("update", function (event) {
      try {
        receiveBrowserUpdate(JSON.parse(event.data));
      } catch (e) {
        // A malformed notice is safely ignored; EventSource still reconnects.
      }
    });
  }

  function markInitialViewLoaded() {
    state.initialViewLoadComplete = true;
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  function notifyUpdateEligibilityChanged() {
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) notifyUpdateEligibilityChanged();
  });

  core.getAutomaticUpdateBlockers = getAutomaticUpdateBlockers;
  core.canApplyPendingUpdate = canApplyPendingUpdate;
  core.applyPendingUpdate = applyPendingUpdate;
  core.receiveBrowserUpdate = receiveBrowserUpdate;
  core.bindUpdateNotifications = bindUpdateNotifications;
  core.markInitialViewLoaded = markInitialViewLoaded;
  core.notifyUpdateEligibilityChanged = notifyUpdateEligibilityChanged;

  // Compatibility shims for integrations compiled against the old module.
  core.stopAutoRefresh = function () {};
  core.startAutoRefresh = function () {};
  core.restoreAutoRefreshState = function () {};
  core.syncAutoRefreshAvailability = notifyUpdateEligibilityChanged;
  core.bindAutoRefreshControls = function () {};
})();
