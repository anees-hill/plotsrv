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

  const bar = state.bottomBar = {pinned: false, collapsed: false};
  const barKey = "plotsrv:bottom-bar:" + encodeURIComponent(window.PLOTSRV.config.dashboardName || "default") + ":" + location.pathname;
  let geometryFrame = null, barBound = false;
  function geometry() {
    if (geometryFrame !== null) return;
    geometryFrame = requestAnimationFrame(() => {
      geometryFrame = null; syncDockClearance();
      for (const table of new Set([state.tabulatorInstance, state.streamTabulatorInstance])) {
        if (!table || !table.initialized || !table.element || !table.element.isConnected) continue;
        if (state.compareActive) {
          const clearance = parseFloat(getComputedStyle(document.body).getPropertyValue("--ps-bottom-dock-clearance")) || 0;
          table.element.style.setProperty("--ps-table-available", Math.max(100, innerHeight - clearance - Math.max(0, table.element.getBoundingClientRect().top) - 12) + "px");
        }
        const holder = table.element.querySelector(".tabulator-tableholder");
        const pos = holder && [holder.scrollLeft, holder.scrollTop];
        table.redraw(false);
        if (holder && pos) {holder.scrollLeft = pos[0]; holder.scrollTop = pos[1];}
      }
    });
  }
  function presentBar() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock) return;
    const expanded = state.expandedView && state.expandedView.active;
    dock.hidden = bar.collapsed || !!expanded;
    document.getElementById("bottom-restore").hidden = !bar.collapsed || !!expanded;
    document.body.classList.toggle("ps-bar-pinned", bar.pinned);
    document.body.classList.toggle("ps-bar-collapsed", bar.collapsed);
    const pin = document.getElementById("bottom-pin");
    const name = bar.pinned ? "Unpin bar" : "Pin bar to bottom";
    pin.setAttribute("aria-label", name); pin.title = name; pin.setAttribute("aria-pressed", String(bar.pinned));
    if (barBound) {try {sessionStorage.setItem(barKey, JSON.stringify(bar));} catch (_) {}}
    geometry();
  }
  function setCollapsed(value) {
    if (core.closeExportMenu) core.closeExportMenu();
    bar.collapsed = !!value; presentBar();
    document.getElementById(value ? "bottom-restore" : "bottom-collapse").focus({preventScroll: true});
  }
  core.bottomBar = {state: bar, setCollapsed, present: presentBar};

  function syncDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || !document.body) return;
    const rect = dock.getBoundingClientRect();
    const height = Math.ceil(rect.height);
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const clearance = dock.hidden ? 0 : Math.ceil(Math.max(height, viewportHeight - rect.top));
    document.body.style.setProperty("--ps-bottom-dock-height", height + "px");
    document.body.style.setProperty("--ps-bottom-dock-clearance", clearance + "px");
  }

  function bindDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || dock.dataset.plotsrvClearanceBound === "1") return;
    syncDockClearance();
    window.addEventListener("resize", geometry);
    if (typeof window.ResizeObserver === "function") {
      state.bottomDockResizeObserver = new window.ResizeObserver(geometry);
      state.bottomDockResizeObserver.observe(dock);
    }
    window.addEventListener("pagehide", () => {
      if (state.bottomDockResizeObserver) state.bottomDockResizeObserver.disconnect();
      if (geometryFrame !== null) cancelAnimationFrame(geometryFrame);
      geometryFrame = null;
    });
    window.addEventListener("pageshow", () => {
      if (state.bottomDockResizeObserver) state.bottomDockResizeObserver.observe(dock);
      geometry();
    });
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
    const navigation = state.snapshotNavigation;
    if (navigation && (navigation.pending || navigation.error)) return;
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
    if (core.syncViewExplanation) core.syncViewExplanation();
    if (core.syncExpandedView) core.syncExpandedView();
    if (core.syncCompare) core.syncCompare();
    const complete = document.querySelector('[data-export-scope="complete"]');
    if (complete) {
      const sourceDownload =
        state.tableLastPayload &&
        state.tableLastPayload.meta &&
        state.tableLastPayload.meta.source_download_url;
      const isHistory =
        typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
      complete.textContent = core.inspectionCapture && core.inspectionCapture() ? "Captured table preview" :
        !isHistory && typeof sourceDownload === "string" && sourceDownload
          ? "Complete source CSV file"
          : (!isHistory && state.tableLastPayload && state.tableLastPayload.meta &&
              state.tableLastPayload.meta.materialization === "remote"
            ? "Hosted table preview" : "Complete published table");
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
    const pin = document.getElementById("bottom-pin");
    if (pin && !pin.dataset.bound) {
      pin.dataset.bound = "1"; barBound = true;
      try {const raw = sessionStorage.getItem(barKey); const saved = raw && raw.length < 128 ? JSON.parse(raw) : {};
        bar.pinned = saved.pinned === true; bar.collapsed = saved.collapsed === true;} catch (_) {}
      pin.addEventListener("click", () => {bar.pinned = !bar.pinned; presentBar();});
      document.getElementById("bottom-collapse").addEventListener("click", () => setCollapsed(true));
      document.getElementById("bottom-restore").addEventListener("click", () => setCollapsed(false));
      presentBar();
    }
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
  core.closeExportMenu = closeExportMenu;
  core.configureBottomBar = configureBottomBar;
  core.syncDockClearance = syncDockClearance;
})();
