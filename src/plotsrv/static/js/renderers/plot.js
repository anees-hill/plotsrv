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

    const load = core.beginSnapshotLoad ? core.beginSnapshotLoad("plot") :
      {current: () => true, finish: () => {}, signal: undefined};
    try {
      const res = await (core.fetchView || fetch)(url, {signal: load.signal});
      if (!load.current()) return false;
      if (!res.ok) {
        if (
          res.status === 404 && !!snapshotQuery &&
          typeof core.handleMissingSnapshot === "function"
        ) {
          await core.handleMissingSnapshot("plot");
          return false;
        }
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage("Failed to load plot snapshot (" + res.status + ").");
        }
        return false;
      }

      const blob = await res.blob();
      if (!load.current() || (load.signal && load.signal.aborted)) return false;
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
      return true;
    } catch (e) {
      if (!load.current()) return false;
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to load plot snapshot (network error or timeout).");
      }
      return false;
    } finally {
      load.finish();
    }
  }

  function exportImage() {
    if (core.inspectionCapture && core.inspectionCapture()) {
      const a = document.createElement("a"); a.href = state.plotObjectUrl;
      a.download = "plotsrv-captured-plot.png"; a.click(); return true;
    }
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