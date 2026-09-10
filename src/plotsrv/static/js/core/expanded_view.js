(function () {
  "use strict";
  const {core, state, config} = window.PLOTSRV;
  const layout = state.expandedView = {active: false, revealed: false};
  const key = "plotsrv:expanded:" + encodeURIComponent(config.dashboardName || "default") + ":" + window.location.pathname;
  const transfers = [];
  let bound = false;
  let frame = null;
  let opener = null;
  let resizeObserver = null;
  let previousHeaderHidden = false;
  let previousDockHidden = false;
  let escapeHadOverlay = false;

  function visible(node) {
    return !!node && !node.closest("[hidden]") && node.getClientRects().length > 0;
  }

  function overlayOpen() {
    return Array.from(document.querySelectorAll(
      'dialog[open], [role="dialog"], [role="menu"], [role="listbox"], [aria-haspopup][aria-expanded="true"]'
    )).some(visible);
  }

  function persist() {
    try {
      if (layout.active) window.sessionStorage.setItem(key, "1");
      else window.sessionStorage.removeItem(key);
    } catch (error) { /* Storage denial leaves a working page-local layout. */ }
  }

  function restoreTransfer(item) {
    if (item.anchor.isConnected) item.anchor.replaceWith(item.node);
    else item.node.remove();
  }

  function transfer(selector, parent, content) {
    const node = document.querySelector(selector);
    if (!node || transfers.some(item => item.node === node)) return false;
    const anchor = document.createComment("expanded control position");
    node.before(anchor);
    parent.append(node);
    transfers.push({node, anchor, content});
    return true;
  }

  // Return renderer-owned controls before its containing DOM is replaced.
  // Static header/snapshot controls keep their original listeners throughout.
  function restoreContentControls() {
    for (let i = transfers.length - 1; i >= 0; i--) {
      if (!transfers[i].content) continue;
      if (layout.active && transfers[i].node.contains(document.activeElement)) {
        document.getElementById("expanded-reveal").focus({preventScroll: true});
      }
      restoreTransfer(transfers[i]);
      transfers.splice(i, 1);
    }
  }

  function scheduleGeometry() {
    if (frame !== null) return;
    frame = window.requestAnimationFrame(function () {
      frame = null;
      const panel = document.getElementById("expanded-controls");
      const top = layout.active && layout.revealed && panel ? Math.ceil(panel.getBoundingClientRect().bottom) + 8 : 52;
      document.body.style.setProperty("--ps-expanded-top", top + "px");
      // CSS sizes plots without rebuilding SVG/zoom state. Tabulator only
      // redraws its existing virtual window; never reload rows for a resize.
      for (const table of new Set([state.tabulatorInstance, state.streamTabulatorInstance])) {
        if (!table || !table.element || !table.element.isConnected || !table.initialized) continue;
        const holder = table.element.querySelector(".tabulator-tableholder");
        const scroll = holder ? [holder.scrollLeft, holder.scrollTop] : null;
        if (typeof table.redraw === "function") table.redraw(false);
        if (holder && scroll) { holder.scrollLeft = scroll[0]; holder.scrollTop = scroll[1]; }
      }
      if (core.syncDockClearance) core.syncDockClearance();
    });
  }

  function sync() {
    if (!layout.active) return;
    const panel = document.getElementById("expanded-controls");
    if (!panel) return;
    for (let i = transfers.length - 1; i >= 0; i--) {
      if (transfers[i].anchor.isConnected) continue;
      transfers[i].node.remove();
      transfers.splice(i, 1);
    }
    let changed = false;
    for (const selector of [".ps-table-mode-switch", "#stream-history-picker", "#stream-pause-button"]) {
      changed = transfer(selector, panel, true) || changed;
    }
    if (changed) scheduleGeometry();
  }

  function reveal(value, options) {
    if (!layout.active) return false;
    const panel = document.getElementById("expanded-controls");
    const button = document.getElementById("expanded-reveal");
    if (!value && overlayOpen()) return false;
    layout.revealed = !!value;
    if (!value && panel.contains(document.activeElement)) button.focus();
    panel.hidden = !value;
    button.setAttribute("aria-expanded", String(!!value));
    button.setAttribute("aria-label", value ? "Hide view controls" : "Show view controls");
    button.title = value ? "Hide view controls" : "Show view controls";
    if (value && !(options && options.keepFocus)) {
      const target = panel.querySelector('.ps-viewselect__btn, #header-status-button, button:not([disabled])');
      if (target) target.focus({preventScroll: true});
    }
    scheduleGeometry();
    return true;
  }

  function setExpanded(active, options) {
    if (!bound || !!active === layout.active) return layout.active;
    // Prompt 17 can call prepareForCompare() before opening its dock, and
    // holds this flag while open. No nested presentation/dock controllers.
    if (active && (state.compareActive || overlayOpen())) return false;
    const header = document.getElementById("site-header");
    const dock = document.querySelector(".ps-bottom-dock");
    const panel = document.getElementById("expanded-controls");
    const handle = document.getElementById("expanded-handle");
    const scroll = [window.scrollX, window.scrollY];
    layout.active = !!active;
    document.body.classList.toggle("ps-expanded", layout.active);
    if (active) {
      opener = document.activeElement;
      previousHeaderHidden = header.hidden;
      previousDockHidden = dock ? dock.hidden : false;
      transfer("#site-header .header-right", panel, false);
      transfer("#snapshots-control", panel, false);
      sync();
      header.hidden = true;
      if (dock) dock.hidden = true;
      handle.hidden = false;
      reveal(false);
      document.getElementById("expanded-reveal").focus({preventScroll: true});
      if (typeof ResizeObserver === "function") {
        resizeObserver = new ResizeObserver(scheduleGeometry);
        resizeObserver.observe(panel);
      }
      window.addEventListener("resize", scheduleGeometry);
    } else {
      if (resizeObserver) resizeObserver.disconnect();
      resizeObserver = null;
      window.removeEventListener("resize", scheduleGeometry);
      for (let i = transfers.length - 1; i >= 0; i--) restoreTransfer(transfers[i]);
      transfers.length = 0;
      header.hidden = previousHeaderHidden;
      if (dock) dock.hidden = previousDockHidden;
      handle.hidden = panel.hidden = true;
      layout.revealed = false;
      if (!(options && options.restoreFocus === false)) {
        const target = visible(opener) ? opener : document.getElementById("expand-view");
        if (target) target.focus({preventScroll: true});
      }
      scheduleGeometry();
    }
    if (core.bottomBar) core.bottomBar.present();
    persist();
    window.scrollTo(scroll[0], scroll[1]);
    return layout.active;
  }

  function bind() {
    if (bound || !document.getElementById("expand-view")) return;
    bound = true;
    document.getElementById("expand-view").addEventListener("click", function () {
      if (state.compareActive && core.compare) {core.compare.exit(); this.focus();}
      setExpanded(true);
    });
    document.getElementById("expanded-exit").addEventListener("click", () => setExpanded(false));
    document.getElementById("expanded-reveal").addEventListener("click", () => reveal(!layout.revealed, {keepFocus: true}));
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") escapeHadOverlay = overlayOpen();
    }, true);
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !layout.active || event.defaultPrevented || escapeHadOverlay) return;
      event.preventDefault();
      setExpanded(false);
    });
    window.addEventListener("pagehide", function () {
      if (resizeObserver) resizeObserver.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
      frame = null;
    });
    window.addEventListener("pageshow", function () {
      if (layout.active) {
        if (resizeObserver) resizeObserver.observe(document.getElementById("expanded-controls"));
        scheduleGeometry();
      }
    });
    try { if (window.sessionStorage.getItem(key) === "1") setExpanded(true); }
    catch (error) { /* No storage requirement. */ }
  }

  core.expandedView = {
    state: layout, set: setExpanded, reveal,
    prepareForCompare: () => setExpanded(false, {restoreFocus: false}),
  };
  core.bindExpandedView = bind;
  core.syncExpandedView = sync;
  core.restoreExpandedContentControls = restoreContentControls;
})();
