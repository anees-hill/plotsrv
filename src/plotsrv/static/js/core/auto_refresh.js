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

  function getSelect() {
    return document.getElementById("auto-refresh-select");
  }

  function getSelectedSeconds() {
    const sel = getSelect();
    if (!sel) return 0;
    const raw = String(sel.value || "off").trim().toLowerCase();
    if (raw === "off" || raw === "") return 0;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function stopAutoRefresh() {
    if (state.autoRefreshTimer !== null) {
      clearInterval(state.autoRefreshTimer);
      state.autoRefreshTimer = null;
    }
  }

  function tickAutoRefresh() {
    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      stopAutoRefresh();
      return;
    }

    if (typeof core.reloadCurrentView === "function") {
      core.reloadCurrentView();
    }
  }

  function startAutoRefresh() {
    const seconds = getSelectedSeconds();
    if (seconds <= 0) {
      stopAutoRefresh();
      return;
    }

    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      stopAutoRefresh();
      return;
    }

    stopAutoRefresh();
    state.autoRefreshTimer = setInterval(tickAutoRefresh, seconds * 1000);
  }

  function saveAutoRefreshState() {
    const sel = getSelect();
    if (!sel || !core.storageKeys || typeof core.savePref !== "function") return;
    core.savePref(core.storageKeys.autoRefreshInterval, sel.value || "off");
  }

  function restoreAutoRefreshState() {
    const sel = getSelect();
    if (!sel || !core.storageKeys || typeof core.loadPref !== "function") return;

    const savedValue = core.loadPref(core.storageKeys.autoRefreshInterval, "off");
    sel.value = savedValue ? String(savedValue) : "off";

    if (typeof core.syncAutoRefreshAvailability === "function") {
      core.syncAutoRefreshAvailability();
    }

    if (getSelectedSeconds() > 0) {
      tickAutoRefresh();
      startAutoRefresh();
    } else {
      stopAutoRefresh();
    }
  }

  function syncAutoRefreshAvailability() {
    const sel = getSelect();
    if (!sel) return;

    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;

    sel.disabled = isHistory;

    const wrap = sel.closest(".ps-auto-refresh");
    if (wrap) {
      wrap.classList.toggle("ps-disabled-control", isHistory);
    }

    if (isHistory) {
      stopAutoRefresh();
      return;
    }

    if (getSelectedSeconds() > 0) {
      startAutoRefresh();
    } else {
      stopAutoRefresh();
    }
  }

  function bindAutoRefreshControls() {
    const sel = getSelect();
    if (!sel) return;

    sel.addEventListener("change", function () {
      saveAutoRefreshState();
      if (typeof core.syncAutoRefreshAvailability === "function") {
        core.syncAutoRefreshAvailability();
      }
    });
  }

  core.getSelectedSeconds = getSelectedSeconds;
  core.stopAutoRefresh = stopAutoRefresh;
  core.startAutoRefresh = startAutoRefresh;
  core.tickAutoRefresh = tickAutoRefresh;
  core.saveAutoRefreshState = saveAutoRefreshState;
  core.restoreAutoRefreshState = restoreAutoRefreshState;
  core.syncAutoRefreshAvailability = syncAutoRefreshAvailability;
  core.bindAutoRefreshControls = bindAutoRefreshControls;
})();