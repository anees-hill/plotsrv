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
      clearTimeout(state.autoRefreshTimer);
      state.autoRefreshTimer = null;
    }
    state.autoRefreshGeneration += 1;
  }

  function canAutoRefresh() {
    if (document.hidden) return false;
    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      return false;
    }
    return getSelectedSeconds() > 0;
  }

  function scheduleAutoRefresh(generation) {
    if (generation !== state.autoRefreshGeneration || !canAutoRefresh()) {
      return;
    }

    const seconds = getSelectedSeconds();
    state.autoRefreshTimer = window.setTimeout(function () {
      state.autoRefreshTimer = null;
      tickAutoRefresh(generation);
    }, seconds * 1000);
  }

  function tickAutoRefresh(generation) {
    const refreshGeneration =
      typeof generation === "number" ? generation : state.autoRefreshGeneration;

    if (refreshGeneration !== state.autoRefreshGeneration || !canAutoRefresh()) {
      return Promise.resolve();
    }

    if (typeof core.reloadCurrentView === "function") {
      return Promise.resolve(core.reloadCurrentView())
        .catch(function () {
          // The current renderer shows its own visible failure state.
        })
        .then(function () {
          scheduleAutoRefresh(refreshGeneration);
        });
    }

    scheduleAutoRefresh(refreshGeneration);
    return Promise.resolve();
  }

  function startAutoRefresh(options) {
    const immediate = !!(options && options.immediate);
    if (getSelectedSeconds() <= 0) {
      stopAutoRefresh();
      return;
    }

    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      stopAutoRefresh();
      return;
    }

    stopAutoRefresh();
    const generation = state.autoRefreshGeneration;
    if (immediate && !document.hidden) {
      tickAutoRefresh(generation);
      return;
    }
    scheduleAutoRefresh(generation);
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
      startAutoRefresh({ immediate: true });
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

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        stopAutoRefresh();
        return;
      }

      if (getSelectedSeconds() > 0) {
        startAutoRefresh({ immediate: true });
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
