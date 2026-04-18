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

  function clearPlotObjectUrl() {
    if (state.plotObjectUrl) {
      try {
        URL.revokeObjectURL(state.plotObjectUrl);
      } catch (e) {
        // ignore
      }
      state.plotObjectUrl = null;
    }
  }

  async function refreshPlot() {
    const img = document.getElementById("plot");
    if (!img) return;

    const url =
      "/plot?view=" +
      encodeURIComponent(core.getActiveViewId()) +
      core.snapshotQuery() +
      "&_ts=" +
      Date.now();

    if (!core.isHistoryMode()) {
      clearPlotObjectUrl();
      img.src = url;
      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
      return;
    }

    try {
      const res = await fetch(url);
      if (!res.ok) {
        if (res.status === 404 && core.isHistoryMode()) {
          if (typeof core.handleMissingSnapshot === "function") {
            await core.handleMissingSnapshot("plot");
          }
          return;
        }
        core.setStatusMessage(`Failed to load plot snapshot (${res.status}).`);
        return;
      }

      const blob = await res.blob();
      clearPlotObjectUrl();
      state.plotObjectUrl = URL.createObjectURL(blob);
      img.src = state.plotObjectUrl;

      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
    } catch (e) {
      core.setStatusMessage("Failed to load plot snapshot (network error).");
    }
  }

  function exportImage() {
    window.location.href =
      "/plot?view=" +
      encodeURIComponent(core.getActiveViewId()) +
      core.snapshotQuery() +
      "&download=1&_ts=" +
      Date.now();
  }

  renderers.clearPlotObjectUrl = clearPlotObjectUrl;
  renderers.refreshPlot = refreshPlot;
  renderers.exportImage = exportImage;

  window.refreshPlot = refreshPlot;
  window.exportImage = exportImage;
})();