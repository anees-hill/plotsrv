(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const renderers = window.PLOTSRV.renderers;

  function terminateServer() {
    fetch("/shutdown", { method: "POST" })
      .then(() => {
        const status = document.getElementById("status");
        if (status) status.textContent = "plotsrv is shutting down…";
      })
      .catch(() => {
        const status = document.getElementById("status");
        if (status) {
          status.textContent = "Failed to contact server (it may already be down).";
        }
      });
  }

  function bootstrap() {
    if (typeof core.bindAutoRefreshControls === "function") {
      core.bindAutoRefreshControls();
    }

    if (typeof core.bindViewDropdown === "function") {
      core.bindViewDropdown();
    }

    if (typeof core.bindHistoryControls === "function") {
      core.bindHistoryControls();
    }

    const loadHistory = typeof core.loadHistory === "function"
      ? core.loadHistory()
      : Promise.resolve();

    loadHistory.then(() => {
      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }

      if (
        document.getElementById("artifact-root") &&
        typeof renderers.loadArtifact === "function"
      ) {
        renderers.loadArtifact().then(() => {
          if (typeof core.refreshStatus === "function") core.refreshStatus();
        });
      } else if (
        document.getElementById("table-grid") &&
        typeof renderers.loadTable === "function"
      ) {
        renderers.loadTable().then(() => {
          if (typeof core.refreshStatus === "function") core.refreshStatus();
        });
      } else if (
        document.getElementById("plot") &&
        typeof renderers.refreshPlot === "function"
      ) {
        Promise.resolve(renderers.refreshPlot()).then(() => {
          if (typeof core.refreshStatus === "function") core.refreshStatus();
        });
      } else if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }

      if (typeof core.refreshViewIcons === "function") {
        core.refreshViewIcons();
      }

      if (typeof core.restoreAutoRefreshState === "function") {
        core.restoreAutoRefreshState();
      }

      if (typeof core.syncHistoryControls === "function") {
        core.syncHistoryControls();
      }
    });
  }

  core.terminateServer = terminateServer;
  core.bootstrap = bootstrap;

  window.terminateServer = terminateServer;

  document.addEventListener("DOMContentLoaded", function () {
    bootstrap();
  });
})();