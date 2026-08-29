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

  function refreshChromeAfterLoad() {
    if (typeof core.configureBottomBar === "function") {
      core.configureBottomBar();
    }
    if (typeof core.refreshStatus === "function") {
      return core.refreshStatus();
    }
    return Promise.resolve();
  }

  function reloadCurrentViewNow() {
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("");
    }

    if (document.getElementById("artifact-root")) {
      if (typeof core.loadArtifact === "function") {
        return core.loadArtifact().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("stream-grid")) {
      if (typeof core.loadStream === "function") {
        return core.loadStream().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("table-grid")) {
      if (typeof core.loadTable === "function") {
        return core.loadTable().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("plot")) {
      if (typeof core.refreshPlot === "function") {
        return core.refreshPlot().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (typeof core.refreshStatus === "function") {
      return core.refreshStatus();
    }

    return Promise.resolve();
  }

  core.reloadCurrentView = function () {
    if (state.reloadCurrentViewPromise) {
      return state.reloadCurrentViewPromise;
    }

    if (document.hidden) {
      return Promise.resolve();
    }

    const refreshPromise = Promise.resolve().then(reloadCurrentViewNow);
    state.reloadCurrentViewPromise = refreshPromise;

    function clearInFlight() {
      if (state.reloadCurrentViewPromise === refreshPromise) {
        state.reloadCurrentViewPromise = null;
      }
    }

    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
  };

  core.bootstrap = function () {
    if (typeof core.bindStatusModal === "function") {
      core.bindStatusModal();
    }

    if (typeof core.bindHeaderStatus === "function") {
      core.bindHeaderStatus();
    }

    if (typeof core.bindViewDropdown === "function") {
      core.bindViewDropdown();
    }

    if (typeof core.bindHistoryControls === "function") {
      core.bindHistoryControls();
    }

    if (typeof core.bindBottomBar === "function") {
      core.bindBottomBar();
    }

    if (typeof core.bindAutoRefreshControls === "function") {
      core.bindAutoRefreshControls();
    }
    if (typeof core.bindUpdateNotifications === "function") {
      core.bindUpdateNotifications();
    }

    const loadHistoryPromise =
      typeof core.loadHistory === "function"
        ? core.loadHistory()
        : Promise.resolve();

    loadHistoryPromise
      .then(function () {
        if (typeof core.syncHistoryUi === "function") {
          core.syncHistoryUi();
        }
        return core.reloadCurrentView();
      })
      .then(function () {
        if (typeof core.markInitialViewLoaded === "function") core.markInitialViewLoaded();
        if (typeof core.markBrowserViewApplied === "function") {
          core.markBrowserViewApplied();
        }
        if (typeof core.showPendingSnapshotNotice === "function") {
          core.showPendingSnapshotNotice();
        }
      })
      .catch(function () {
        if (typeof core.markInitialViewLoaded === "function") core.markInitialViewLoaded();
        if (typeof core.refreshStatus === "function") {
          core.refreshStatus();
        }
      });
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof core.bootstrap === "function") {
      core.bootstrap();
    }
  });
})();
