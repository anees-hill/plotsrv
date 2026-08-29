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

  function fmtLocalTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  }

  function fmtAgo(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 0) return "";
    if (s < 60) return "(" + s + "s ago)";
    const m = Math.floor(s / 60);
    if (m < 60) return "(" + m + "m ago)";
    const h = Math.floor(m / 60);
    if (h < 24) return "(" + h + "h ago)";
    const days = Math.floor(h / 24);
    return "(" + days + "d ago)";
  }

  function formatAgeShort(totalSeconds) {
    if (
      typeof totalSeconds !== "number" ||
      !isFinite(totalSeconds) ||
      totalSeconds < 0
    ) {
      return "";
    }

    const s = Math.floor(totalSeconds);
    if (s < 60) return s + "s old";

    const m = Math.floor(s / 60);
    if (m < 60) return m + "m old";

    const h = Math.floor(m / 60);
    const remM = m % 60;
    if (h < 24) {
      return remM > 0 ? h + "h " + remM + "m old" : h + "h old";
    }

    const d = Math.floor(h / 24);
    const remH = h % 24;
    return remH > 0 ? d + "d " + remH + "h old" : d + "d old";
  }

  function setStatusMessage(html) {
    const status = document.getElementById("status");
    if (status) {
      status.innerHTML = html || "";
      status.hidden = !html;
    }
  }

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

  function applyFreshnessClass(el, freshness) {
    if (!el) return;
  
    el.classList.remove("ps-viewselect__item--warn");
    el.classList.remove("ps-viewselect__item--error");
    el.removeAttribute("data-plotsrv-freshness-state");
    el.removeAttribute("title");
  
    if (!freshness || freshness.enabled === false) {
      return;
    }
  
    const freshnessState = String(freshness.state || "").toLowerCase();
  
    if (
      freshnessState === "warn" ||
      freshnessState === "warning" ||
      freshnessState === "stale"
    ) {
      el.classList.add("ps-viewselect__item--warn");
      el.setAttribute("data-plotsrv-freshness-state", "warn");
    } else if (
      freshnessState === "error" ||
      freshnessState === "overdue" ||
      freshnessState === "old"
    ) {
      el.classList.add("ps-viewselect__item--error");
      el.setAttribute("data-plotsrv-freshness-state", "error");
    }
  
    if (el.hasAttribute("data-plotsrv-freshness-state")) {
      const label = freshness.label || "Not fresh";
      const age =
        typeof freshness.age_s === "number"
          ? " (" + formatAgeShort(freshness.age_s) + ")"
          : "";
      el.title = label + age;
    }
  }

  function normalizeViewMenuRevision(value) {
    return Number.isInteger(value) && value >= 0 ? value : null;
  }

  function refreshViewIcons(viewMenuRevision) {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (!wrap) return;

    const nextRevision = normalizeViewMenuRevision(viewMenuRevision);
    if (
      nextRevision !== null &&
      state.viewMenuRevision !== null &&
      nextRevision === state.viewMenuRevision
    ) {
      return Promise.resolve();
    }

    if (state.viewMenuRefreshPromise) {
      return state.viewMenuRefreshPromise;
    }

    const ICONS = {
      unknown: "/static/logo_unknown.png",
      plot: "/static/logo_plot.png",
      table: "/static/logo_table.png",
      image: "/static/logo_image.png",
      markdown: "/static/logo_markdown.png",
      json: "/static/logo_json.png",
      python: "/static/logo_python.png",
      traceback: "/static/logo_exception.png",
      exception: "/static/logo_exception.png",       
      text: "/static/logo_txt.png",
      html: "/static/logo_html.png",
    };

    const refreshPromise = (async function () {
      try {
        const res = await fetch("/views?_ts=" + Date.now());
        if (!res.ok) return;
        const views = await res.json();

        const byId = {};
        for (const v of views) {
          byId[v.view_id] = v;
        }

        if (typeof core.updateViewSelectorCatalogue === "function") {
          core.updateViewSelectorCatalogue(views);
        }

        const items = wrap.querySelectorAll("[data-plotsrv-view]");
        items.forEach(function (btn) {
          const vid = btn.getAttribute("data-plotsrv-view");
          if (!vid) return;
          const meta = byId[vid];
          if (!meta) return;

          const iconKey = meta.icon_key || "unknown";
          const img = btn.querySelector(".ps-viewselect__itemicon");
          if (img && ICONS[iconKey] && img.getAttribute("src") !== ICONS[iconKey]) {
            img.setAttribute("src", ICONS[iconKey]);
          }

          applyFreshnessClass(btn, meta.freshness || null);
        });

        const activeMeta = byId[config.activeViewId];
        if (activeMeta) {
          const iconKey = activeMeta.icon_key || "unknown";
          const img = wrap.querySelector(".ps-viewselect__icon");
          const label = wrap.querySelector(".ps-viewselect__label");
          if (img && ICONS[iconKey] && img.getAttribute("src") !== ICONS[iconKey]) {
            img.setAttribute("src", ICONS[iconKey]);
          }
          if (label) label.textContent = String(activeMeta.label || activeMeta.view_id);
        }
        if (nextRevision !== null) {
          state.viewMenuRevision = nextRevision;
        }
      } catch (e) {
        // ignore
      }
    })();

    state.viewMenuRefreshPromise = refreshPromise;
    function clearInFlight() {
      if (state.viewMenuRefreshPromise === refreshPromise) {
        state.viewMenuRefreshPromise = null;
      }
    }
    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
  }

  function elapsedLabel(totalSeconds) {
    const age = formatAgeShort(totalSeconds);
    return age ? age.replace(/ old$/, " ago") : "";
  }

  function deriveHeaderStatus(model) {
    if (model.viewMode === "snapshot") {
      const createdAt = model.snapshot && model.snapshot.createdAt;
      return {
        visible: config.showHeaderHistory,
        tone: "history",
        label: "Snapshot",
        context: createdAt ? "From " + fmtLocalTime(createdAt) : "Historical view",
        title: "Historical snapshot",
        copy: createdAt
          ? "Viewing the snapshot saved " + fmtLocalTime(createdAt) + ". Freshness applies only to the latest data."
          : "Viewing a historical snapshot. Freshness applies only to the latest data.",
      };
    }

    if (model.browserData === "update_available") {
      return {
        visible: config.showHeaderFreshness,
        tone: "new-data",
        label: "New data available",
        context: "This view has not applied it yet",
        title: "New data available",
        copy: "The server has newer data than the version currently shown in this browser.",
      };
    }

    const latest = model.latestData || {};
    const freshness = latest.freshness;
    const freshnessState = freshness && freshness.enabled !== false
      ? String(freshness.state || "unknown").toLowerCase()
      : "disabled";
    const elapsed = freshness && typeof freshness.age_s === "number"
      ? elapsedLabel(freshness.age_s)
      : "";
    const updatedContext = elapsed
      ? "Updated " + elapsed
      : latest.lastUpdated
        ? "Updated " + fmtAgo(latest.lastUpdated).replace(/^\(|\)$/g, "")
        : "Update time unavailable";
    const policyLabel = freshness && freshness.label
      ? String(freshness.label)
      : "Freshness policy unavailable";

    if (freshnessState === "error" || freshnessState === "overdue" || freshnessState === "old") {
      return {
        visible: config.showHeaderFreshness,
        tone: "error",
        label: "Very stale",
        context: updatedContext,
        title: "Latest data is very stale",
        copy: policyLabel + (elapsed ? ". Last update was " + elapsed + "." : "."),
      };
    }

    if (freshnessState === "warn" || freshnessState === "warning" || freshnessState === "stale") {
      return {
        visible: config.showHeaderFreshness,
        tone: "warn",
        label: "Stale",
        context: updatedContext,
        title: "Latest data is stale",
        copy: policyLabel + (elapsed ? ". Last update was " + elapsed + "." : "."),
      };
    }

    if (freshnessState === "unknown") {
      return {
        visible: config.showHeaderFreshness,
        tone: "neutral",
        label: "Latest",
        context: policyLabel,
        title: "No latest data yet",
        copy: policyLabel + ". This browser will remain on the latest view while plotsrv waits for data.",
      };
    }

    return {
      visible: config.showHeaderFreshness,
      tone: freshnessState === "ok" ? "live" : "neutral",
      label: freshnessState === "ok" ? "Live" : "Latest",
      context: freshnessState === "ok" && freshness && freshness.age_s < 10
        ? "Updated just now"
        : updatedContext,
      title: freshnessState === "ok" ? "Latest data is up to date" : "Latest view",
      copy: freshnessState === "ok"
        ? policyLabel + (elapsed ? ". Last update was " + elapsed + "." : ".")
        : "This browser is showing the latest applied data. Freshness status is unavailable.",
    };
  }

  function renderHeaderStatus() {
    const wrap = document.getElementById("header-status");
    if (!wrap) return;

    const presentation = deriveHeaderStatus(state.headerStatus);
    wrap.hidden = !presentation.visible;
    wrap.setAttribute("data-status-tone", presentation.tone);

    if (!presentation.visible && typeof core.closeStatusModal === "function") {
      core.closeStatusModal();
    }

    const label = document.getElementById("header-status-label");
    const context = document.getElementById("header-status-context");
    if (label) label.textContent = presentation.label;
    if (context) context.textContent = presentation.context;
    if (typeof core.renderStatusModal === "function") core.renderStatusModal();
  }

  function setHeaderViewState(viewMode, snapshot) {
    state.headerStatus.viewMode = viewMode === "snapshot" ? "snapshot" : "latest";
    state.headerStatus.snapshot = state.headerStatus.viewMode === "snapshot"
      ? snapshot || { id: state.currentSnapshot, createdAt: null }
      : null;
    renderHeaderStatus();
  }

  // Slice 2 can call this when it detects a newer server version without
  // coupling that mechanism to header DOM details.
  function setHeaderBrowserDataState(browserData) {
    state.headerStatus.browserData = browserData === "update_available"
      ? "update_available"
      : "current";
    renderHeaderStatus();
  }

  function setHeaderLatestStatus(statusPayload) {
    state.latestStatusPayload = statusPayload || null;
    state.headerStatus.latestData = {
      lastUpdated: statusPayload && statusPayload.last_updated
        ? statusPayload.last_updated
        : null,
      freshness: statusPayload && statusPayload.freshness
        ? statusPayload.freshness
        : null,
    };
    renderHeaderStatus();
  }

  function refreshLocalFreshness() {
    const latest = state.headerStatus.latestData || {};
    const freshness = latest.freshness;
    const updatedAt = Date.parse(latest.lastUpdated || "");
    if (!freshness || freshness.enabled === false || !Number.isFinite(updatedAt)) {
      renderHeaderStatus();
      return;
    }
    const age = Math.max(0, Math.floor((Date.now() - updatedAt) / 1000));
    const warnRaw = freshness.warn_after_s;
    const overdueRaw = freshness.overdue_after_s ?? freshness.error_after_s;
    const warn = warnRaw == null ? null : Number(warnRaw);
    const overdue = overdueRaw == null ? null : Number(overdueRaw);
    freshness.age_s = age;
    if (overdue !== null && Number.isFinite(overdue) && age >= overdue) {
      Object.assign(freshness, { state: "error", label: "Overdue", emoji: "❌" });
    } else if (warn !== null && Number.isFinite(warn) && age >= warn) {
      Object.assign(freshness, { state: "warn", label: "Stale", emoji: "⚠️" });
    } else {
      Object.assign(freshness, { state: "ok", label: "Fresh", emoji: "✅" });
    }
    renderHeaderStatus();
  }

  function bindHeaderStatus() {
    const button = document.getElementById("header-status-button");
    if (!button) return;

    renderHeaderStatus();
    button.addEventListener("click", function () {
      if (typeof core.openStatusModal === "function") core.openStatusModal();
    });
    if (state.headerFreshnessTimer == null) {
      state.headerFreshnessTimer = window.setInterval(refreshLocalFreshness, 10000);
    }
  }

  function setFileBackedIndicator(statusPayload, isHistory) {
    const marker = document.getElementById("status-file-backed");
    if (!marker) return;

    marker.hidden = true;

    if (isHistory) return;
    if (!statusPayload) return;

    const isWatched = statusPayload.is_watched_file === true;
    const materialization = String(statusPayload.materialization || "").toLowerCase();

    if (!isWatched || materialization !== "file") {
      return;
    }

    marker.hidden = false;
  }

  function refreshStatus() {
    if (state.statusRefreshPromise) {
      return state.statusRefreshPromise;
    }

    const refreshPromise = (async function () {
      try {
        const res = await fetch(
        "/status?view=" + encodeURIComponent(config.activeViewId) + "&_ts=" + Date.now()
        );
        if (!res.ok) return;

        const s = await res.json();

      const errWrap = document.getElementById("status-error-wrap");
      const err = document.getElementById("status-error");

      const restored = !!s.restored_from_storage;
      const restoredAt = s.restored_at || null;
      const restoreSource = s.restore_source || "storage";

      const isHistory =
        typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;

      setHeaderLatestStatus(s);

      setFileBackedIndicator(s, isHistory);

      if (errWrap && err) {
        if (s.last_error) {
          err.textContent = s.last_error;
          errWrap.hidden = false;
        } else {
          err.textContent = "";
          errWrap.hidden = true;
        }
      }

      const isRestoredLive =
        restored &&
        !(typeof core.isHistoryMode === "function" && core.isHistoryMode());
      
      if (isRestoredLive && typeof core.setStatusMessage === "function") {
        const sourceLabel = restoreSource === "latest" ? "latest storage" : "storage";
        const restoredAtText = restoredAt ? " Restored at " + fmtLocalTime(restoredAt) + "." : "";
        core.setStatusMessage(
          '<span class="ps-restored-badge">RESTORED</span> ' +
            "Restored from " +
            core.escapeHtml(sourceLabel) +
            ". Waiting for the next live update." +
            core.escapeHtml(restoredAtText)
        );
      }

        await refreshViewIcons(s.view_menu_revision);
      } catch (e) {
        // ignore
      }
    })();

    state.statusRefreshPromise = refreshPromise;
    function clearInFlight() {
      if (state.statusRefreshPromise === refreshPromise) {
        state.statusRefreshPromise = null;
      }
    }
    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
  }

  core.fmtLocalTime = fmtLocalTime;
  core.fmtAgo = fmtAgo;
  core.formatAgeShort = formatAgeShort;
  core.setStatusMessage = setStatusMessage;
  core.clearPlotObjectUrl = clearPlotObjectUrl;
  core.applyViewFreshness = applyFreshnessClass;
  core.deriveHeaderStatus = deriveHeaderStatus;
  core.renderHeaderStatus = renderHeaderStatus;
  core.setHeaderViewState = setHeaderViewState;
  core.setHeaderBrowserDataState = setHeaderBrowserDataState;
  core.setHeaderLatestStatus = setHeaderLatestStatus;
  core.refreshLocalFreshness = refreshLocalFreshness;
  core.bindHeaderStatus = bindHeaderStatus;
  core.refreshViewIcons = refreshViewIcons;
  core.setFileBackedIndicator = setFileBackedIndicator;
  core.refreshStatus = refreshStatus;
})();
