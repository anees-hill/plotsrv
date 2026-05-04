(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  core.reloadCurrentView = function () {
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("");
    }

    if (document.getElementById("artifact-root")) {
      if (typeof core.loadArtifact === "function") {
        return core.loadArtifact().then(function () {
          if (typeof core.refreshStatus === "function") {
            return core.refreshStatus();
          }
        });
      }
      return Promise.resolve();
    }

    if (document.getElementById("table-grid")) {
      if (typeof core.loadTable === "function") {
        return core.loadTable().then(function () {
          if (typeof core.refreshStatus === "function") {
            return core.refreshStatus();
          }
        });
      }
      return Promise.resolve();
    }

    if (document.getElementById("plot")) {
      if (typeof core.refreshPlot === "function") {
        return core.refreshPlot().then(function () {
          if (typeof core.refreshStatus === "function") {
            return core.refreshStatus();
          }
        });
      }
      return Promise.resolve();
    }

    if (typeof core.refreshStatus === "function") {
      return core.refreshStatus();
    }

    return Promise.resolve();
  };

  core.bootstrap = function () {
    if (typeof core.bindViewDropdown === "function") {
      core.bindViewDropdown();
    }

    if (typeof core.bindHistoryControls === "function") {
      core.bindHistoryControls();
    }

    if (typeof core.bindAutoRefreshControls === "function") {
      core.bindAutoRefreshControls();
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
        if (typeof core.restoreAutoRefreshState === "function") {
          core.restoreAutoRefreshState();
        }
      })
      .catch(function () {
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