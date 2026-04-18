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

  async function refreshPlot() {
    const img = document.getElementById("plot");
    if (!img) return;

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    const url =
      "/plot?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&_ts=" +
      Date.now();

    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;

    if (!isHistory) {
      if (typeof core.clearPlotObjectUrl === "function") {
        core.clearPlotObjectUrl();
      }
      img.src = url;

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
      return;
    }

    try {
      const res = await fetch(url);
      if (!res.ok) {
        if (
          res.status === 404 &&
          typeof core.handleMissingSnapshot === "function"
        ) {
          await core.handleMissingSnapshot("plot");
          return;
        }
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage("Failed to load plot snapshot (" + res.status + ").");
        }
        return;
      }

      const blob = await res.blob();
      if (typeof core.clearPlotObjectUrl === "function") {
        core.clearPlotObjectUrl();
      }
      state.plotObjectUrl = URL.createObjectURL(blob);
      img.src = state.plotObjectUrl;

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
    } catch (e) {
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to load plot snapshot (network error).");
      }
    }
  }

  function exportImage() {
    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    window.location.href =
      "/plot?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&download=1&_ts=" +
      Date.now();
  }

  core.refreshPlot = refreshPlot;
  core.exportImage = exportImage;

  window.refreshPlot = refreshPlot;
  window.exportImage = exportImage;
})();