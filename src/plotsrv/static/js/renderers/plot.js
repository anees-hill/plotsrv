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
  const plot = document.getElementById("plot");
  const frame = plot && plot.closest(".plot-frame--plot");
  const controls = document.getElementById("plot-size-controls");
  let naturalWidth = 0;
  let naturalHeight = 0;
  let zoom = 1;
  let fitFrame = null;

  function sizePlot() {
    if (!plot || !frame || !naturalWidth || !naturalHeight) return;
    const style = getComputedStyle(frame);
    const horizontalSpace = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    const verticalSpace = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) +
      parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
    const width = Math.max(1, frame.clientWidth - horizontalSpace);
    const dock = document.querySelector(".ps-bottom-dock");
    const dockHeight = dock && !dock.hidden ?
      Math.max(0, window.innerHeight - dock.getBoundingClientRect().top) : 0;
    // Use the frame's document position so scrolling does not change the fit.
    const top = frame.getBoundingClientRect().top + window.scrollY;
    const height = Math.max(80, window.innerHeight - top - dockHeight - verticalSpace - 16);
    const scale = Math.min(1, width / naturalWidth, height / naturalHeight);
    plot.style.width = Math.max(1, Math.round(naturalWidth * scale * zoom)) + "px";
    frame.style.maxHeight = Math.ceil(height + verticalSpace) + "px";
  }

  function schedulePlotSize() {
    if (fitFrame !== null) return;
    fitFrame = requestAnimationFrame(function () {
      fitFrame = null;
      sizePlot();
    });
  }

  function setPlotSize(width, height) {
    naturalWidth = width;
    naturalHeight = height;
    plot.classList.add("ps-plot--sized");
    if (controls) controls.hidden = false;
    sizePlot();
  }

  if (plot && frame && controls) {
    controls.querySelector("#plot-size-fit").addEventListener("click", function () {
      zoom = 1;
      sizePlot();
      frame.scrollTo(0, 0);
    });
    controls.querySelector("#plot-size-increase").addEventListener("click", function () {
      zoom = Math.min(4, zoom * 1.25);
      sizePlot();
    });
    controls.querySelector("#plot-size-decrease").addEventListener("click", function () {
      zoom = Math.max(0.25, zoom / 1.25);
      sizePlot();
    });
    plot.addEventListener("load", function () {
      if (plot.naturalWidth && plot.naturalHeight) {
        setPlotSize(plot.naturalWidth, plot.naturalHeight);
      }
    });
    if (plot.complete && plot.naturalWidth && plot.naturalHeight) {
      setPlotSize(plot.naturalWidth, plot.naturalHeight);
    }
    window.addEventListener("resize", schedulePlotSize);
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(schedulePlotSize);
      observer.observe(frame);
      const dock = document.querySelector(".ps-bottom-dock");
      if (dock) observer.observe(dock);
    }
    if (typeof MutationObserver === "function") {
      const observer = new MutationObserver(schedulePlotSize);
      observer.observe(document.body, {attributes: true, attributeFilter: ["class"]});
      const dock = document.querySelector(".ps-bottom-dock");
      if (dock) observer.observe(dock, {attributes: true, attributeFilter: ["hidden"]});
    }
  }

  function decodePlot(url, signal) {
    const image = new Image();
    return new Promise(function (resolve, reject) {
      function cleanup() {
        image.onload = image.onerror = null;
        if (signal) signal.removeEventListener("abort", abort);
      }
      function done() { cleanup(); resolve(image); }
      function failed(error) { cleanup(); image.src = ""; reject(error); }
      function abort() { failed(new DOMException("Plot load cancelled", "AbortError")); }
      if (signal && signal.aborted) { abort(); return; }
      if (signal) signal.addEventListener("abort", abort, {once: true});
      image.src = url;
      if (typeof image.decode === "function") image.decode().then(done, failed);
      else {
        image.onload = done;
        image.onerror = () => failed(new Error("Plot image could not be decoded"));
        if (image.complete) {
          if (image.naturalWidth) done();
          else failed(new Error("Plot image could not be decoded"));
        }
      }
    });
  }

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
    let candidateUrl = null;
    try {
      const res = await fetch(url, {signal: load.signal});
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
      candidateUrl = URL.createObjectURL(blob);
      const decoded = await decodePlot(candidateUrl, load.signal);
      if (!load.current() || (load.signal && load.signal.aborted)) return false;
      const previousUrl = state.plotObjectUrl;
      setPlotSize(decoded.naturalWidth, decoded.naturalHeight);
      img.src = candidateUrl;
      img.hidden = false;
      state.plotObjectUrl = candidateUrl;
      candidateUrl = null;
      if (previousUrl) URL.revokeObjectURL(previousUrl);

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
      if (candidateUrl) URL.revokeObjectURL(candidateUrl);
      load.finish();
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
