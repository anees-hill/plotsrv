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

  function syncDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || !document.body) return;
    const height = Math.ceil(dock.getBoundingClientRect().height);
    document.body.style.setProperty("--ps-bottom-dock-height", height + "px");
  }

  function bindDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || dock.dataset.plotsrvClearanceBound === "1") return;
    syncDockClearance();
    window.addEventListener("resize", syncDockClearance);
    if (typeof window.ResizeObserver === "function") {
      state.bottomDockResizeObserver = new window.ResizeObserver(syncDockClearance);
      state.bottomDockResizeObserver.observe(dock);
    }
    dock.dataset.plotsrvClearanceBound = "1";
  }

  function closeExportMenu(options) {
    const settings = options && typeof options === "object" ? options : {};
    const button = document.getElementById("export-button");
    const menu = document.getElementById("export-menu");
    if (!button || !menu) return;
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (settings.restoreFocus) button.focus();
  }

  function showExportFailure() {
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("Nothing is currently available for that export scope.");
    }
  }

  function runExport(action) {
    let result;
    if (action === "filtered" || action === "retained" || action === "complete") {
      if (typeof core.exportTable === "function") {
        result = core.exportTable(action);
      }
    } else if (action === "table-complete") {
      if (typeof core.exportTable === "function") {
        result = core.exportTable("complete");
      }
    } else if (action === "plot") {
      if (typeof core.exportImage === "function") result = core.exportImage();
    } else if (action === "artifact") {
      if (typeof core.exportArtifact === "function") result = core.exportArtifact();
    } else if (action === "plot-svg" || action === "plot-png") {
      if (typeof core.exportTablePlot === "function") {
        result = core.exportTablePlot(action === "plot-svg" ? "svg" : "png");
      }
    }

    if (result === false) showExportFailure();
  }

  function configureBottomBar() {
    const complete = document.querySelector('[data-export-scope="complete"]');
    if (complete) {
      const sourceDownload =
        state.tableLastPayload &&
        state.tableLastPayload.meta &&
        state.tableLastPayload.meta.source_download_url;
      const isHistory =
        typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
      complete.textContent =
        !isHistory && typeof sourceDownload === "string" && sourceDownload
          ? "Complete source CSV file"
          : "Complete published table";
    }
    const plotItems = document.getElementById("plot-export-items");
    if (plotItems) {
      const plotMode = state.tablePlotMode === "plot";
      const available = plotMode && state.tablePlotLastResult && state.tablePlotLastResult.ok === true;
      plotItems.hidden = !plotMode;
      Array.from(plotItems.querySelectorAll("[data-export-scope]")).forEach(function (item) {
        item.disabled = !available;
        item.title = available ? "" : "Render a plot before exporting it.";
      });
    }
  }

  function bindBottomBar() {
    bindDockClearance();
    const button = document.getElementById("export-button");
    if (!button || button.dataset.plotsrvBound === "1") return;

    const menu = document.getElementById("export-menu");
    if (menu) {
      button.addEventListener("click", function () {
        const willOpen = menu.hidden;
        menu.hidden = !willOpen;
        button.setAttribute("aria-expanded", willOpen ? "true" : "false");
        if (willOpen) {
          const first = menu.querySelector("[data-export-scope]");
          if (first) first.focus();
        }
      });

      menu.addEventListener("click", function (event) {
        const item = event.target.closest("[data-export-scope]");
        if (!item) return;
        closeExportMenu();
        runExport(item.getAttribute("data-export-scope"));
      });

      document.addEventListener("click", function (event) {
        const control = document.getElementById("export-control");
        if (control && !menu.hidden && !control.contains(event.target)) {
          closeExportMenu();
        }
      });

      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !menu.hidden) {
          closeExportMenu({ restoreFocus: true });
        }
      });
    } else {
      button.addEventListener("click", function () {
        runExport(button.getAttribute("data-export-action"));
      });
    }

    button.dataset.plotsrvBound = "1";
    configureBottomBar();
  }

  core.bindBottomBar = bindBottomBar;
  core.configureBottomBar = configureBottomBar;
  core.syncDockClearance = syncDockClearance;
})();
