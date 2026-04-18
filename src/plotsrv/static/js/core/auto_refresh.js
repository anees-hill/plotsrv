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
  const renderers = window.PLOTSRV.renderers;

  function saveAutoRefreshState() {
    const toggle = document.getElementById("auto-refresh-toggle");
    const interval = document.getElementById("auto-refresh-interval");
    if (toggle) core.savePref(core.storageKeys.autoRefreshEnabled, toggle.checked ? "1" : "0");
    if (interval) core.savePref(core.storageKeys.autoRefreshInterval, String(interval.value || "5"));
  }

  function getAutoRefreshMs() {
    const sel = document.getElementById("auto-refresh-interval");
    if (!sel) return 5000;
    const seconds = Number(sel.value || 5);
    return Math.max(1, seconds) * 1000;
  }

  function stopAutoRefresh() {
    if (state.autoRefreshTimer !== null) {
      clearInterval(state.autoRefreshTimer);
      state.autoRefreshTimer = null;
    }
  }

  function tickAutoRefresh() {
    if (core.isHistoryMode()) {
      stopAutoRefresh();
      return;
    }

    const img = document.getElementById("plot");
    if (img && typeof renderers.refreshPlot === "function") {
      renderers.refreshPlot();
      return;
    }

    if (document.getElementById("artifact-root") && typeof renderers.loadArtifact === "function") {
      renderers.loadArtifact().then(() => {
        if (typeof core.refreshStatus === "function") core.refreshStatus();
      });
      return;
    }

    if (document.getElementById("table-grid") && typeof renderers.loadTable === "function") {
      renderers.loadTable().then(() => {
        if (typeof core.refreshStatus === "function") core.refreshStatus();
      });
      return;
    }

    if (typeof core.refreshStatus === "function") {
      core.refreshStatus();
    }
  }

  function startAutoRefresh() {
    if (core.isHistoryMode()) return;
    stopAutoRefresh();
    const ms = getAutoRefreshMs();
    state.autoRefreshTimer = setInterval(tickAutoRefresh, ms);
  }

  function syncAutoRefreshAvailability() {
    const toggle = document.getElementById("auto-refresh-toggle");
    const interval = document.getElementById("auto-refresh-interval");

    if (!toggle) return;

    const isHistory = core.isHistoryMode();

    toggle.disabled = isHistory;
    if (interval) interval.disabled = isHistory;

    const toggleWrap = toggle.closest(".toggle");
    const intervalWrap = interval ? interval.closest(".interval") : null;

    if (toggleWrap) toggleWrap.classList.toggle("ps-disabled-control", isHistory);
    if (intervalWrap) intervalWrap.classList.toggle("ps-disabled-control", isHistory);

    if (isHistory) {
      stopAutoRefresh();
    } else if (toggle.checked) {
      startAutoRefresh();
    }
  }

  function restoreAutoRefreshState() {
    const toggle = document.getElementById("auto-refresh-toggle");
    const interval = document.getElementById("auto-refresh-interval");

    if (interval) {
      const savedInterval = core.loadPref(core.storageKeys.autoRefreshInterval, null);
      if (savedInterval) interval.value = savedInterval;
    }

    if (toggle) {
      const savedEnabled = core.loadPref(core.storageKeys.autoRefreshEnabled, null);
      if (savedEnabled === "1") {
        toggle.checked = true;
        if (!core.isHistoryMode()) {
          tickAutoRefresh();
          startAutoRefresh();
        }
      }
    }

    syncAutoRefreshAvailability();
  }

  function bindAutoRefreshControls() {
    const toggle = document.getElementById("auto-refresh-toggle");
    const interval = document.getElementById("auto-refresh-interval");
    if (!toggle) return;

    toggle.addEventListener("change", function () {
      saveAutoRefreshState();
      if (core.isHistoryMode()) {
        stopAutoRefresh();
        return;
      }
      if (toggle.checked) {
        tickAutoRefresh();
        startAutoRefresh();
      } else {
        stopAutoRefresh();
      }
    });

    if (interval) {
      interval.addEventListener("change", function () {
        saveAutoRefreshState();
        if (!core.isHistoryMode() && toggle.checked) startAutoRefresh();
      });
    }
  }

  core.saveAutoRefreshState = saveAutoRefreshState;
  core.getAutoRefreshMs = getAutoRefreshMs;
  core.stopAutoRefresh = stopAutoRefresh;
  core.tickAutoRefresh = tickAutoRefresh;
  core.startAutoRefresh = startAutoRefresh;
  core.syncAutoRefreshAvailability = syncAutoRefreshAvailability;
  core.restoreAutoRefreshState = restoreAutoRefreshState;
  core.bindAutoRefreshControls = bindAutoRefreshControls;
})();