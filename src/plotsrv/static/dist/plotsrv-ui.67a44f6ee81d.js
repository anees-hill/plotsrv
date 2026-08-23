/* plotsrv source: js/core/dom.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  core.escapeHtml = function (s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  };

  core.findNearest = function (el, selector) {
    if (!el) return null;
    if (el.closest) return el.closest(selector);
    return null;
  };

  core.setStatusMessage = function (html) {
    const status = document.getElementById("status");
    if (status) status.innerHTML = html || "";
  };

  core.copyTextToClipboard = async function (text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {
      // ignore
    }

    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "readonly");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return !!ok;
    } catch (e) {
      return false;
    }
  };
})();

/* plotsrv source: js/core/state.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const raw = window.PLOTSRV_CONFIG || {};
  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;

  function readSnapshotFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      const val = params.get("snapshot");
      return val ? String(val) : null;
    } catch (e) {
      return null;
    }
  }

  function writeSnapshotToUrl(snapshotId) {
    try {
      const url = new URL(window.location.href);
      if (snapshotId) url.searchParams.set("snapshot", snapshotId);
      else url.searchParams.delete("snapshot");
      window.history.replaceState({}, "", url.toString());
    } catch (e) {
      // ignore
    }
  }

  config.activeViewId = raw.active_view_id || "default";
  config.kind = raw.kind || "none";
  config.tableViewMode = raw.table_view_mode || "rich";
  config.maxTableRowsSimple = raw.max_table_rows_simple || 200;
  config.maxTableRowsRich = raw.max_table_rows_rich || 1000;

  state.historyItems = [];
  state.currentSnapshot = readSnapshotFromUrl();
  state.plotObjectUrl = null;
  state.autoRefreshTimer = null;
  state.autoRefreshGeneration = 0;
  state.reloadCurrentViewPromise = null;
  state.statusRefreshPromise = null;
  state.viewMenuRefreshPromise = null;
  state.viewMenuRevision = Number.isInteger(raw.view_menu_revision)
    ? raw.view_menu_revision
    : null;
  state.tabulatorInstance = null;

  core.getActiveViewId = function () {
    return config.activeViewId;
  };

  core.readSnapshotFromUrl = readSnapshotFromUrl;

  core.writeSnapshotToUrl = writeSnapshotToUrl;

  core.getCurrentSnapshot = function () {
    return state.currentSnapshot;
  };

  core.setCurrentSnapshot = function (snapshotId) {
    state.currentSnapshot = snapshotId ? String(snapshotId) : null;
    return state.currentSnapshot;
  };

  core.snapshotQuery = function () {
    return state.currentSnapshot
      ? "&snapshot=" + encodeURIComponent(state.currentSnapshot)
      : "";
  };

  core.isHistoryMode = function () {
    return !!state.currentSnapshot;
  };

  core.getHistoryItems = function () {
    return state.historyItems;
  };

  core.setHistoryItems = function (items) {
    state.historyItems = Array.isArray(items) ? items : [];
  };

  core.currentHistoryMeta = function () {
    if (!state.currentSnapshot) return null;
    for (const item of state.historyItems) {
      if (item.snapshot_id === state.currentSnapshot) return item;
    }
    return null;
  };
})();

/* plotsrv source: js/core/storage.js */
// src/plotsrv/static/js/core/storage.js
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  core.storageKeys = {
   autoRefreshEnabled: "plotsrv:v2:auto_refresh_enabled",
   autoRefreshInterval: "plotsrv:v2:auto_refresh_interval",
   textWrapEnabled: "plotsrv:v1:text_wrap_enabled",
   jsonFindQuery: "plotsrv:v1:json_find_query",
   tablePrefsPrefix: "plotsrv:v2:table_prefs:",
   jsonPrefsPrefix: "plotsrv:v2:json_prefs:",
   textPrefsPrefix: "plotsrv:v2:text_prefs:",
 };   

  core.loadPref = function (key, fallbackValue) {
    try {
      const val = localStorage.getItem(key);
      return val == null ? fallbackValue : val;
    } catch (e) {
      return fallbackValue;
    }
  };

  core.savePref = function (key, value) {
    try {
      localStorage.setItem(key, String(value));
    } catch (e) {
      // ignore
    }
  };

  core.getTablePrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.tablePrefsPrefix + safeViewId;
  };

  core.loadTablePrefs = function (viewId) {
    const fallback = {
      column_order: [],
      hidden_fields: [],
      search_query: "",
      header_filters: {},
    };

    try {
      const raw = localStorage.getItem(core.getTablePrefsKey(viewId));
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      const headerFilters =
        parsed.header_filters && typeof parsed.header_filters === "object"
          ? parsed.header_filters
          : {};

      const cleanHeaderFilters = {};
      for (const [key, value] of Object.entries(headerFilters)) {
        cleanHeaderFilters[String(key)] = String(value ?? "");
      }

      return {
        column_order: Array.isArray(parsed.column_order)
          ? parsed.column_order.map(String)
          : [],
        hidden_fields: Array.isArray(parsed.hidden_fields)
          ? parsed.hidden_fields.map(String)
          : [],
        search_query:
          typeof parsed.search_query === "string" ? parsed.search_query : "",
        header_filters: cleanHeaderFilters,
      };
    } catch (e) {
      return fallback;
    }
  };

  core.saveTablePrefs = function (viewId, prefs) {
    const headerFilters = {};
    if (prefs && prefs.header_filters && typeof prefs.header_filters === "object") {
      for (const [key, value] of Object.entries(prefs.header_filters)) {
        headerFilters[String(key)] = String(value ?? "");
      }
    }

    const payload = {
      column_order: Array.isArray(prefs && prefs.column_order)
        ? prefs.column_order.map(String)
        : [],
      hidden_fields: Array.isArray(prefs && prefs.hidden_fields)
        ? prefs.hidden_fields.map(String)
        : [],
      search_query:
        prefs && typeof prefs.search_query === "string"
          ? prefs.search_query
          : "",
      header_filters: headerFilters,
    };

    try {
      localStorage.setItem(
        core.getTablePrefsKey(viewId),
        JSON.stringify(payload)
      );
    } catch (e) {
      // ignore
    }
  };

  core.clearTablePrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getTablePrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };

  core.getTextPrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.textPrefsPrefix + safeViewId;
  };
  
  core.loadTextPrefs = function (viewId) {
    const fallback = {
      wrap_enabled: false,
      reverse_enabled: false,
      colour_enabled: true,
    };
  
    try {
      const raw = localStorage.getItem(core.getTextPrefsKey(viewId));
      if (!raw) {
        return {
          wrap_enabled: core.loadPref(core.storageKeys.textWrapEnabled, "0") === "1",
          reverse_enabled: false,
          colour_enabled: true,
        };
      }
  
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;
  
      return {
        wrap_enabled:
          typeof parsed.wrap_enabled === "boolean"
            ? parsed.wrap_enabled
            : fallback.wrap_enabled,
        reverse_enabled:
          typeof parsed.reverse_enabled === "boolean"
            ? parsed.reverse_enabled
            : fallback.reverse_enabled,
        colour_enabled:
          typeof parsed.colour_enabled === "boolean"
            ? parsed.colour_enabled
            : fallback.colour_enabled,
      };
    } catch (e) {
      return fallback;
    }
  };
  
  core.saveTextPrefs = function (viewId, prefs) {
  
    const payload = {
      wrap_enabled: !!(prefs && prefs.wrap_enabled),
      reverse_enabled: !!(prefs && prefs.reverse_enabled),
      colour_enabled: prefs && prefs.colour_enabled !== false,
    };

    try {
      localStorage.setItem(core.getTextPrefsKey(viewId), JSON.stringify(payload));
    } catch (e) {
      // ignore
    }
  
    try {
      localStorage.setItem(
        core.storageKeys.textWrapEnabled,
        payload.wrap_enabled ? "1" : "0"
      );
    } catch (e) {
      // ignore
    }
  };
  
  core.clearTextPrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getTextPrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };
  

  core.getJsonPrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.jsonPrefsPrefix + safeViewId;
  };

  core.loadJsonPrefs = function (viewId) {
    const fallback = {
      mode: "json",
      level_limit: "2",
      find_query: "",
      pinned_values: [],
    };

    try {
      const raw = localStorage.getItem(core.getJsonPrefsKey(viewId));
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      return {
        mode:
          typeof parsed.mode === "string" && parsed.mode
            ? parsed.mode
            : fallback.mode,
        level_limit:
          typeof parsed.level_limit === "string" && parsed.level_limit
            ? parsed.level_limit
            : fallback.level_limit,
        find_query:
          typeof parsed.find_query === "string"
            ? parsed.find_query
            : fallback.find_query,
        pinned_values: Array.isArray(parsed.pinned_values)
          ? parsed.pinned_values.map(String)
          : [],
      };
    } catch (e) {
      return fallback;
    }
  };

  core.saveJsonPrefs = function (viewId, prefs) {
    const payload = {
      mode:
        prefs && typeof prefs.mode === "string" && prefs.mode
          ? prefs.mode
          : "json",
      level_limit:
        prefs && typeof prefs.level_limit === "string" && prefs.level_limit
          ? prefs.level_limit
          : "2",
      find_query:
        prefs && typeof prefs.find_query === "string"
          ? prefs.find_query
          : "",
      pinned_values: Array.isArray(prefs && prefs.pinned_values)
        ? Array.from(new Set(prefs.pinned_values.map(String)))
        : [],
    };

    try {
      localStorage.setItem(core.getJsonPrefsKey(viewId), JSON.stringify(payload));
    } catch (e) {
      // ignore
    }
  };

  core.clearJsonPrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getJsonPrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };
})();

/* plotsrv source: js/core/history.js */
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

  function writeSnapshotToUrl(snapshotId) {
    try {
      const url = new URL(window.location.href);
      if (snapshotId) {
        url.searchParams.set("snapshot", snapshotId);
      } else {
        url.searchParams.delete("snapshot");
      }
      window.history.replaceState({}, "", url.toString());
    } catch (e) {
      // ignore
    }
  }

  function snapshotQuery() {
    return state.currentSnapshot
      ? "&snapshot=" + encodeURIComponent(state.currentSnapshot)
      : "";
  }

  function isHistoryMode() {
    return !!state.currentSnapshot;
  }

  function currentHistoryMeta() {
    if (!state.currentSnapshot) return null;

    for (const item of state.historyItems || []) {
      if (item.snapshot_id === state.currentSnapshot) {
        return item;
      }
    }
    return null;
  }

  function syncHistoryUi() {
    const sel = document.getElementById("history-select");
    const headerHistory = document.getElementById("header-history");
    const headerHistoryLabel = document.getElementById("header-history-label");
    const isHistory = isHistoryMode();

    if (sel) {
      sel.value = state.currentSnapshot || "";
    }

    if (headerHistory) {
      headerHistory.hidden = !isHistory;
    }

    if (headerHistoryLabel) {
      headerHistoryLabel.textContent = "Historical mode";
      const meta = currentHistoryMeta();
      if (meta && meta.created_at && typeof core.fmtLocalTime === "function") {
        headerHistoryLabel.title =
          "Snapshot from " + core.fmtLocalTime(meta.created_at);
      } else {
        headerHistoryLabel.removeAttribute("title");
      }
    }

    if (document.body) {
      document.body.classList.toggle("ps-is-history", isHistory);
    }

    if (typeof core.syncAutoRefreshAvailability === "function") {
      core.syncAutoRefreshAvailability();
    }
  }

  async function loadHistory() {
    const sel = document.getElementById("history-select");
    if (!sel) return;

    try {
      const res = await fetch(
        "/history?view=" +
          encodeURIComponent(config.activeViewId) +
          "&_ts=" +
          Date.now()
      );
      if (!res.ok) throw new Error("history fetch failed");

      const data = await res.json();
      const snapshots = Array.isArray(data.snapshots) ? data.snapshots : [];
      state.historyItems = snapshots;

      const parts = [];
      parts.push('<option value="">Live</option>');

      if (snapshots.length === 0) {
        parts.push(
          '<option value="__none__" disabled>No previous entries</option>'
        );
      } else {
        for (const snap of snapshots) {
          const ts =
            snap.created_at && typeof core.fmtLocalTime === "function"
              ? core.fmtLocalTime(snap.created_at)
              : snap.snapshot_id;
          let label = ts;
          
          if (snap.is_live_equivalent) {
            label = "Latest snapshot (same as Live)";
          } else if (snap.is_latest) {
            label = "Latest snapshot · " + ts;
          }
          
          const kind = snap.kind ? " · " + core.escapeHtml(snap.kind) : "";
          
          parts.push(
            '<option value="' +
              core.escapeHtml(snap.snapshot_id) +
              '">' +
              core.escapeHtml(label) +
              kind +
              "</option>"
          );
        }
      }

      sel.innerHTML = parts.join("");

      if (state.currentSnapshot) {
        const exists = snapshots.some(function (x) {
          return x.snapshot_id === state.currentSnapshot;
        });
        if (!exists) {
          state.currentSnapshot = null;
        }
      }

      sel.value = state.currentSnapshot || "";
      syncHistoryUi();
    } catch (e) {
      sel.innerHTML =
        '<option value="">Live</option>' +
        '<option value="__err__" disabled>History unavailable</option>';
      state.historyItems = [];
      syncHistoryUi();
    }
  }

  async function handleMissingSnapshot(kindLabel) {
    state.currentSnapshot = null;
    writeSnapshotToUrl(null);
    syncHistoryUi();

    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage(
        '<span class="badge">SNAPSHOT DELETED</span> ' +
          "Selected " +
          core.escapeHtml(kindLabel) +
          " snapshot is no longer available."
      );
    }

    try {
      await loadHistory();
    } catch (e) {
      // ignore
    }

    if (typeof core.refreshStatus === "function") {
      core.refreshStatus();
    }
  }

  function returnToLive() {
    state.currentSnapshot = null;
    writeSnapshotToUrl(null);
    syncHistoryUi();

    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("");
    }

    if (typeof core.reloadCurrentView === "function") {
      core.reloadCurrentView();
    }

    if (typeof core.restoreAutoRefreshState === "function") {
      core.restoreAutoRefreshState();
    }
  }

  function bindHistoryControls() {
    const sel = document.getElementById("history-select");
    if (!sel) return;

    sel.addEventListener("change", function () {
      const value = String(sel.value || "");
      state.currentSnapshot = value ? value : null;
      writeSnapshotToUrl(state.currentSnapshot);
      syncHistoryUi();

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (typeof core.reloadCurrentView === "function") {
        core.reloadCurrentView();
      }
    });
  }

  core.writeSnapshotToUrl = writeSnapshotToUrl;
  core.snapshotQuery = snapshotQuery;
  core.isHistoryMode = isHistoryMode;
  core.currentHistoryMeta = currentHistoryMeta;
  core.syncHistoryUi = syncHistoryUi;
  core.loadHistory = loadHistory;
  core.handleMissingSnapshot = handleMissingSnapshot;
  core.bindHistoryControls = bindHistoryControls;
  core.returnToLive = returnToLive;

  window.returnToLive = returnToLive;
})();

/* plotsrv source: js/core/status.js */
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
          if (img && ICONS[iconKey] && img.getAttribute("src") !== ICONS[iconKey]) {
            img.setAttribute("src", ICONS[iconKey]);
          }
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

  function setFreshnessDot(freshness, isHistory) {
    const dot = document.getElementById("header-freshness-dot");
    if (!dot) return;

    dot.hidden = true;
    dot.classList.remove("is-warn");
    dot.classList.remove("is-error");
    dot.removeAttribute("title");

    if (isHistory) return;
    if (!freshness || freshness.enabled === false) return;

    const stateName = String(freshness.state || "");
    if (stateName === "ok" || stateName === "disabled" || stateName === "unknown") {
      return;
    }

    dot.hidden = false;
    if (stateName === "error") {
      dot.classList.add("is-error");
    } else {
      dot.classList.add("is-warn");
    }

    const label = freshness.label || "Not fresh";
    const age =
      typeof freshness.age_s === "number"
        ? " (" + formatAgeShort(freshness.age_s) + ")"
        : "";
    dot.title = label + age;
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

      const updated = document.getElementById("status-updated");
      const updatedAgo = document.getElementById("status-updated-ago");
      const freshness = document.getElementById("status-freshness");
      const errWrap = document.getElementById("status-error-wrap");
      const err = document.getElementById("status-error");

      if (updated) {
        updated.textContent = fmtLocalTime(s.last_updated);
      }

      if (updatedAgo) {
        updatedAgo.textContent = fmtAgo(s.last_updated);
      }

      const restored = !!s.restored_from_storage;
      const restoredAt = s.restored_at || null;
      const restoreSource = s.restore_source || "storage";

      const isHistory =
        typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;

      if (freshness) {
        const f = s.freshness || null;
        if (isHistory) {
          freshness.textContent = "Historical snapshot";
        } else if (!f || f.enabled === false) {
          freshness.textContent = "—";
        } else {
          const emoji = f.emoji || "";
          const label = f.label || "Unknown";
          const age =
            typeof f.age_s === "number"
              ? " (" + formatAgeShort(f.age_s) + ")"
              : "";
          freshness.textContent = (emoji + " " + label + age).trim();
        }

        setFreshnessDot(s.freshness || null, isHistory);
      }

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
  core.refreshViewIcons = refreshViewIcons;
  core.setFileBackedIndicator = setFileBackedIndicator;
  core.refreshStatus = refreshStatus;
})();

/* plotsrv source: js/core/auto_refresh.js */
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

  function getSelect() {
    return document.getElementById("auto-refresh-select");
  }

  function getSelectedSeconds() {
    const sel = getSelect();
    if (!sel) return 0;
    const raw = String(sel.value || "off").trim().toLowerCase();
    if (raw === "off" || raw === "") return 0;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function stopAutoRefresh() {
    if (state.autoRefreshTimer !== null) {
      clearTimeout(state.autoRefreshTimer);
      state.autoRefreshTimer = null;
    }
    state.autoRefreshGeneration += 1;
  }

  function canAutoRefresh() {
    if (document.hidden) return false;
    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      return false;
    }
    return getSelectedSeconds() > 0;
  }

  function scheduleAutoRefresh(generation) {
    if (generation !== state.autoRefreshGeneration || !canAutoRefresh()) {
      return;
    }

    const seconds = getSelectedSeconds();
    state.autoRefreshTimer = window.setTimeout(function () {
      state.autoRefreshTimer = null;
      tickAutoRefresh(generation);
    }, seconds * 1000);
  }

  function tickAutoRefresh(generation) {
    const refreshGeneration =
      typeof generation === "number" ? generation : state.autoRefreshGeneration;

    if (refreshGeneration !== state.autoRefreshGeneration || !canAutoRefresh()) {
      return Promise.resolve();
    }

    if (typeof core.reloadCurrentView === "function") {
      return Promise.resolve(core.reloadCurrentView())
        .catch(function () {
          // The current renderer shows its own visible failure state.
        })
        .then(function () {
          scheduleAutoRefresh(refreshGeneration);
        });
    }

    scheduleAutoRefresh(refreshGeneration);
    return Promise.resolve();
  }

  function startAutoRefresh(options) {
    const immediate = !!(options && options.immediate);
    if (getSelectedSeconds() <= 0) {
      stopAutoRefresh();
      return;
    }

    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      stopAutoRefresh();
      return;
    }

    stopAutoRefresh();
    const generation = state.autoRefreshGeneration;
    if (immediate && !document.hidden) {
      tickAutoRefresh(generation);
      return;
    }
    scheduleAutoRefresh(generation);
  }

  function saveAutoRefreshState() {
    const sel = getSelect();
    if (!sel || !core.storageKeys || typeof core.savePref !== "function") return;
    core.savePref(core.storageKeys.autoRefreshInterval, sel.value || "off");
  }

  function restoreAutoRefreshState() {
    const sel = getSelect();
    if (!sel || !core.storageKeys || typeof core.loadPref !== "function") return;

    const savedValue = core.loadPref(core.storageKeys.autoRefreshInterval, "off");
    sel.value = savedValue ? String(savedValue) : "off";

    if (typeof core.syncAutoRefreshAvailability === "function") {
      core.syncAutoRefreshAvailability();
    }

    if (getSelectedSeconds() > 0) {
      startAutoRefresh({ immediate: true });
    } else {
      stopAutoRefresh();
    }
  }

  function syncAutoRefreshAvailability() {
    const sel = getSelect();
    if (!sel) return;

    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;

    sel.disabled = isHistory;

    const wrap = sel.closest(".ps-auto-refresh");
    if (wrap) {
      wrap.classList.toggle("ps-disabled-control", isHistory);
    }

    if (isHistory) {
      stopAutoRefresh();
      return;
    }

    if (getSelectedSeconds() > 0) {
      startAutoRefresh();
    } else {
      stopAutoRefresh();
    }
  }

  function bindAutoRefreshControls() {
    const sel = getSelect();
    if (!sel) return;

    sel.addEventListener("change", function () {
      saveAutoRefreshState();
      if (typeof core.syncAutoRefreshAvailability === "function") {
        core.syncAutoRefreshAvailability();
      }
    });

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        stopAutoRefresh();
        return;
      }

      if (getSelectedSeconds() > 0) {
        startAutoRefresh({ immediate: true });
      }
    });
  }

  core.getSelectedSeconds = getSelectedSeconds;
  core.stopAutoRefresh = stopAutoRefresh;
  core.startAutoRefresh = startAutoRefresh;
  core.tickAutoRefresh = tickAutoRefresh;
  core.saveAutoRefreshState = saveAutoRefreshState;
  core.restoreAutoRefreshState = restoreAutoRefreshState;
  core.syncAutoRefreshAvailability = syncAutoRefreshAvailability;
  core.bindAutoRefreshControls = bindAutoRefreshControls;
})();

/* plotsrv source: js/core/view_selector.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  function bindViewDropdown() {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (wrap) {
      const btn = wrap.querySelector(".ps-viewselect__btn");
      const menu = wrap.querySelector(".ps-viewselect__menu");
      if (!btn || !menu) return;

      function openMenu() {
        menu.hidden = false;
        btn.setAttribute("aria-expanded", "true");
      
        try {
          menu.focus();
        } catch (e) {
          // ignore
        }
      
        requestAnimationFrame(function () {
          clampMenuToViewport(menu);
        });
      }

      function closeMenu() {
        menu.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      }

      function clampMenuToViewport(menuEl) {
        if (!menuEl) return;
      
        menuEl.classList.remove("ps-viewselect__menu--clamped-left");
        menuEl.classList.remove("ps-viewselect__menu--clamped-right");
      
        const rect = menuEl.getBoundingClientRect();
        const pad = 8;
      
        if (rect.left < pad) {
          menuEl.classList.add("ps-viewselect__menu--clamped-left");
        }
      
        if (rect.right > window.innerWidth - pad) {
          menuEl.classList.add("ps-viewselect__menu--clamped-right");
        }
      }

      btn.addEventListener("click", function () {
        if (menu.hidden) {
          openMenu();
        } else {
          closeMenu();
        }
      });

      document.addEventListener("click", function (ev) {
        if (!wrap.contains(ev.target)) {
          closeMenu();
        }
      });

      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") {
          closeMenu();
        }
      });

      window.addEventListener("resize", function () {
        if (!menu.hidden) {
          clampMenuToViewport(menu);
        }
      });

      menu.addEventListener("click", function (ev) {
        const item =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-plotsrv-view]")
            : null;
        if (!item) return;

        const v = item.getAttribute("data-plotsrv-view");
        if (!v) return;

        window.location.href = "/?view=" + encodeURIComponent(v);
      });

      return;
    }

    const sel = document.getElementById("view-select");
    if (!sel) return;

    sel.addEventListener("change", function () {
      const v = sel.value;
      window.location.href = "/?view=" + encodeURIComponent(v);
    });
  }

  core.bindViewDropdown = bindViewDropdown;
})();

/* plotsrv source: js/renderers/artifact.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const config = window.PLOTSRV.config;

  function renderTruncationBadge(trunc) {
    const el = document.getElementById("artifact-truncation");
    if (!el) return;

    if (!trunc || !trunc.truncated) {
      el.innerHTML = "";
      return;
    }

    const reason = trunc.reason ? " — " + core.escapeHtml(trunc.reason) : "";
    let details = "";

    if (trunc.details && typeof trunc.details === "object") {
      try {
        const parts = [];
        for (const [k, v] of Object.entries(trunc.details)) {
          if (v == null) continue;
          if (typeof v === "object") continue;
          parts.push(k + "=" + v);
          if (parts.length >= 4) break;
        }
        if (parts.length) {
          details = " (" + core.escapeHtml(parts.join(", ")) + ")";
        }
      } catch (e) {
        // ignore
      }
    } else if (typeof trunc.details === "string") {
      details = " (" + core.escapeHtml(trunc.details) + ")";
    }

    el.innerHTML =
      '<span class="badge">TRUNCATED</span>' +
      '<span class="note" style="margin-left:0.35rem;">' +
      reason +
      details +
      "</span>";
  }

  async function loadArtifact() {
    const root = document.getElementById("artifact-root");
    if (!root) return;

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    try {
      const url =
        "/artifact?view=" +
        encodeURIComponent(config.activeViewId) +
        snapshotQuery +
        "&_ts=" +
        Date.now();
      let res = await fetch(url);
      for (let attempt = 0; res.status === 503 && attempt < 2; attempt += 1) {
        await new Promise(function (resolve) {
          window.setTimeout(resolve, 250 * (attempt + 1));
        });
        res = await fetch(url);
      }

      if (!res.ok) {
        if (
          res.status === 404 &&
          typeof core.isHistoryMode === "function" &&
          core.isHistoryMode() &&
          typeof core.handleMissingSnapshot === "function"
        ) {
          await core.handleMissingSnapshot("artifact");
          return;
        }

        root.innerHTML =
          '<div class="note">Failed to load artifact (' + res.status + ").</div>";
        renderTruncationBadge(null);
        return;
      }

      const data = await res.json();
      root.dataset.plotsrvSourceDownloadUrl =
        data.meta && typeof data.meta.source_download_url === "string"
          ? data.meta.source_download_url
          : "";
      
        if (document.body) {
          document.body.classList.remove(
            "ps-has-html-artifact",
            "ps-has-text-artifact",
            "ps-has-markdown-artifact",
            "ps-has-code-artifact"
          );
        
          document.body.classList.toggle("ps-has-html-artifact", data.kind === "html");
          document.body.classList.toggle("ps-has-text-artifact", data.kind === "text");
          document.body.classList.toggle(
            "ps-has-markdown-artifact",
            data.kind === "markdown"
          );
          document.body.classList.toggle("ps-has-code-artifact", data.kind === "python");
        }
      
      const kindEl = document.getElementById("artifact-kind");
      if (kindEl) {
        kindEl.textContent = data.kind ? "Kind: " + data.kind : "";
      }
      
      root.innerHTML = data.html || "";

      renderTruncationBadge(data.truncation || null);

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (
        window.PLOTSRV.renderers &&
        typeof window.PLOTSRV.renderers.initArtifactEnhancements === "function"
      ) {
        window.PLOTSRV.renderers.initArtifactEnhancements(root);
      }

      if (document.getElementById("table-grid") && typeof core.loadTable === "function") {
        await core.loadTable();
      }
    } catch (e) {
      root.innerHTML =
        '<div class="note">Failed to load artifact (network error).</div>';
      renderTruncationBadge(null);
    }
  }

  function refreshArtifact() {
    return loadArtifact().then(function () {
      if (typeof core.refreshStatus === "function") {
        return core.refreshStatus();
      }
    });
  }

  function terminateServer() {
    fetch("/shutdown", { method: "POST" })
      .then(function () {
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage("plotsrv is shutting down…");
        }
      })
      .catch(function () {
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage(
            "Failed to contact server (it may already be down)."
          );
        }
      });
  }

  function parseJsonAttr(raw) {
    if (typeof raw !== "string" || !raw) return null;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function getArtifactExportText() {
    const jsonRoot = document.querySelector('[data-plotsrv-json="1"]');
    if (jsonRoot) {
      const rawText = parseJsonAttr(
        jsonRoot.getAttribute("data-plotsrv-json-raw-text") || "null"
      );
      if (typeof rawText === "string") {
        return rawText;
      }

      const prettyText = parseJsonAttr(
        jsonRoot.getAttribute("data-plotsrv-json-pretty-text") || "null"
      );
      if (typeof prettyText === "string") {
        return prettyText;
      }

      const textView = jsonRoot.querySelector("[data-json-text-view='1']");
      if (textView) {
        return String(textView.textContent || "");
      }
    }

    const pre = document.querySelector('#artifact-root pre');
    if (pre) {
      return String(pre.textContent || "");
    }

    const root = document.getElementById("artifact-root");
    if (root) {
      return String(root.innerText || root.textContent || "");
    }

    return "";
  }

  function downloadTextFile(filename, text) {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function exportArtifact() {
    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
    const root = document.getElementById("artifact-root");
    const sourceDownload = root && root.dataset
      ? root.dataset.plotsrvSourceDownloadUrl
      : "";

    if (!isHistory && sourceDownload) {
      window.location.href = sourceDownload + "&_ts=" + Date.now();
      return;
    }

    const text = getArtifactExportText();
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "artifact").replace(/[^\w.-]+/g, "_");
    const filename = base + "-" + stamp + ".txt";
    downloadTextFile(filename, text);
  }

  core.renderTruncationBadge = renderTruncationBadge;
  core.loadArtifact = loadArtifact;
  core.refreshArtifact = refreshArtifact;
  core.terminateServer = terminateServer;
  core.exportArtifact = exportArtifact;

  window.refreshArtifact = refreshArtifact;
  window.terminateServer = terminateServer;
  window.exportArtifact = exportArtifact;
})();

/* plotsrv source: js/renderers/plot.js */
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

/* plotsrv source: js/renderers/table.js */
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

  const MAX_FILTERS = 10;

  const FILTER_OPS = {
    text: [
      { value: "contains", label: "contains" },
      { value: "eq", label: "is equal to" },
      { value: "neq", label: "is not equal to" },
      { value: "missing", label: "is missing" },
      { value: "not_missing", label: "is not missing" },
    ],
    number: [
      { value: "missing", label: "is missing" },
      { value: "not_missing", label: "is not missing" },
      { value: "lt", label: "is less than" },
      { value: "lte", label: "is less than or equal to" },
      { value: "gt", label: "is greater than" },
      { value: "gte", label: "is greater than or equal to" },
      { value: "eq", label: "is equal to" },
      { value: "neq", label: "is not equal to" },
      { value: "between", label: "is between" },
      { value: "not_between", label: "is not between" },
    ],
  };

  function tablePrefKey() {
    return "plotsrv:v4:table_state:" + String(config.activeViewId || "default");
  }

  function buildColumnDefs(columnNames) {
    const hidden = new Set(getHiddenColumns());

    return (columnNames || []).map(function (col) {
      return {
        title: col,
        field: col,
        visible: !hidden.has(col),
      };
    });
  }

  function defaultTableUiState() {
    return {
      searchQuery: "",
      filtersOpen: false,
      filters: [],
      columnsOpen: false,
      hiddenColumns: [],
    };
  }

  function getTableUiState() {
    if (!state.tableUiState) {
      state.tableUiState = defaultTableUiState();
    }
    return state.tableUiState;
  }

  function saveTableUiState() {
    const ui = getTableUiState();

    try {
      localStorage.setItem(tablePrefKey(), JSON.stringify(ui));
    } catch (e) {
      // ignore
    }
  }

  function newFilterId() {
    return "f_" + Math.random().toString(36).slice(2, 10);
  }

  function normalizeFilter(filter) {
    if (!filter || typeof filter !== "object") return null;

    return {
      id: typeof filter.id === "string" && filter.id ? filter.id : newFilterId(),
      field: typeof filter.field === "string" ? filter.field : "",
      op: typeof filter.op === "string" ? filter.op : "contains",
      value: typeof filter.value === "string" ? filter.value : "",
      valueTo: typeof filter.valueTo === "string" ? filter.valueTo : "",
    };
  }

  function operatorNeedsValue(op) {
    return !["missing", "not_missing"].includes(op);
  }

  function operatorNeedsTwoValues(op) {
    return ["between", "not_between"].includes(op);
  }

  function isFilterComplete(filter) {
    if (!filter.field || !filter.op) return false;
    if (!operatorNeedsValue(filter.op)) return true;
    if (operatorNeedsTwoValues(filter.op)) {
      return (
        String(filter.value || "").trim() !== "" &&
        String(filter.valueTo || "").trim() !== ""
      );
    }
    return String(filter.value || "").trim() !== "";
  }

  function loadTableUiState() {
    let parsed = null;

    try {
      const raw = localStorage.getItem(tablePrefKey());
      if (raw) parsed = JSON.parse(raw);
    } catch (e) {
      parsed = null;
    }

    const base = defaultTableUiState();
    const filters = Array.isArray(parsed && parsed.filters) ? parsed.filters : [];
    const normalizedFilters = filters.map(normalizeFilter).filter(Boolean);
    const hiddenColumns = Array.isArray(parsed && parsed.hiddenColumns)
      ? parsed.hiddenColumns.filter(function (x) {
          return typeof x === "string" && x;
        })
      : [];

    const hasSavedFilters = normalizedFilters.some(isFilterComplete);
    const hasHiddenColumns = hiddenColumns.length > 0;

    state.tableUiState = {
      searchQuery:
        parsed && typeof parsed.searchQuery === "string"
          ? parsed.searchQuery
          : base.searchQuery,

      filtersOpen:
        parsed && typeof parsed.filtersOpen === "boolean"
          ? parsed.filtersOpen
          : hasSavedFilters,

      filters: normalizedFilters,

      columnsOpen:
        parsed && typeof parsed.columnsOpen === "boolean"
          ? parsed.columnsOpen
          : hasHiddenColumns,

      hiddenColumns: hiddenColumns,
    };
  }

  function escapeHtml(s) {
    if (typeof core.escapeHtml === "function") {
      return core.escapeHtml(s);
    }
    return String(s);
  }

  function getFieldType(field) {
    const map = state.tableFieldTypes || {};
    return map[field] === "number" ? "number" : "text";
  }

  function inferFieldTypes(columns, rows) {
    const out = {};
    const fields = Array.isArray(columns) ? columns.slice() : [];
    const sampleRows = Array.isArray(rows) ? rows.slice(0, 50) : [];

    for (const field of fields) {
      let numericHits = 0;
      let textHits = 0;

      for (const row of sampleRows) {
        const value = row ? row[field] : null;
        if (value == null || value === "") continue;

        if (typeof value === "number" && Number.isFinite(value)) {
          numericHits += 1;
          continue;
        }

        const n = Number(value);
        if (typeof value === "string" && value.trim() !== "" && Number.isFinite(n)) {
          numericHits += 1;
        } else {
          textHits += 1;
        }
      }

      out[field] = numericHits > 0 && textHits === 0 ? "number" : "text";
    }

    return out;
  }

  function getActiveRowCount() {
    if (!state.tabulatorInstance) return null;

    try {
      const active = state.tabulatorInstance.getData("active");
      if (Array.isArray(active)) return active.length;
    } catch (e) {
      // ignore
    }

    try {
      const allRows = state.tabulatorInstance.getData();
      if (Array.isArray(allRows)) return allRows.length;
    } catch (e) {
      // ignore
    }

    return null;
  }

  function updateTableStatus(data, activeCount) {
    const status = document.getElementById("status");
    const inline = document.getElementById("table-status-inline");

    const targetEls = [status, inline].filter(Boolean);
    if (!targetEls.length) return;

    const totalKnown = data.total_rows_known !== false;
    const total = totalKnown ? Number(data.total_rows ?? 0) : null;
    const loaded = Number(data.loaded_rows ?? data.returned_rows ?? 0);
    const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

    let html = "";

    if (total <= 0 && returned <= 0) {
      html = "";
    } else {
      const isTrunc =
        !!(data.meta && data.meta.truncated) ||
        (totalKnown && returned < total);
      const hasFilter = typeof activeCount === "number" && activeCount !== returned;

      if (hasFilter) {
        html =
          "Showing " +
          activeCount +
          " filtered rows of " +
          returned +
          " loaded";
        if (totalKnown && total > returned) {
          html += " (" + total + " total)";
        } else if (!totalKnown) {
          html += " (" + loaded + " loaded; full count unknown)";
        } else {
          html += ".";
        }
      } else if (!totalKnown) {
        html =
          "Showing " +
          returned +
          (loaded > returned ? " of " + loaded : "") +
          " loaded rows (full count unknown).";
      } else {
        html =
          "Showing " +
          returned +
          (total > returned ? " of " + total : "") +
          " rows.";
      }

      if (isTrunc) {
        html +=
          ' <span class="badge" title="This view is showing a sampled subset of the full data.">TRUNCATED</span>';
      }
    }

    for (const el of targetEls) {
      el.innerHTML = html;
    }
  }

  function refreshTableStatus() {
    if (!state.tableLastPayload) return;
    updateTableStatus(state.tableLastPayload, getActiveRowCount());
  }

  function getSearchQuery() {
    return getTableUiState().searchQuery || "";
  }

  function setSearchQuery(value) {
    const ui = getTableUiState();
    ui.searchQuery = String(value || "");
    saveTableUiState();
  }

  function getFilters() {
    return Array.isArray(getTableUiState().filters) ? getTableUiState().filters : [];
  }

  function setFilters(filters) {
    const ui = getTableUiState();
    ui.filters = Array.isArray(filters) ? filters.map(normalizeFilter).filter(Boolean) : [];
    saveTableUiState();
  }

  function setFiltersOpen(isOpen) {
    const ui = getTableUiState();
    ui.filtersOpen = !!isOpen;
    saveTableUiState();
  }

  function getHiddenColumns() {
    return Array.isArray(getTableUiState().hiddenColumns)
      ? getTableUiState().hiddenColumns
      : [];
  }

  function setHiddenColumns(fields) {
    const ui = getTableUiState();
    ui.hiddenColumns = Array.isArray(fields)
      ? fields.filter(function (x) {
          return typeof x === "string" && x;
        })
      : [];
    saveTableUiState();
  }

  function setColumnsOpen(isOpen) {
    const ui = getTableUiState();
    ui.columnsOpen = !!isOpen;
    saveTableUiState();
  }

  function hasHiddenColumns() {
    return getHiddenColumns().length > 0;
  }

  function getOperatorOptions(field) {
    const fieldType = getFieldType(field);
    return fieldType === "number" ? FILTER_OPS.number : FILTER_OPS.text;
  }

  function renderOperatorOptions(field, selectedOp) {
    const options = getOperatorOptions(field);
    return options
      .map(function (op) {
        const sel = op.value === selectedOp ? ' selected="selected"' : "";
        return (
          '<option value="' +
          escapeHtml(op.value) +
          '"' +
          sel +
          ">" +
          escapeHtml(op.label) +
          "</option>"
        );
      })
      .join("");
  }

  function getCompleteFilters() {
    return getFilters().filter(isFilterComplete);
  }

  function hasActiveFilters() {
    return getCompleteFilters().length > 0;
  }

  function renderFilterRows() {
    const wrap = document.getElementById("table-filter-rows");
    if (!wrap) return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const filters = getFilters();

    if (!filters.length) {
      wrap.innerHTML = '<div class="note ps-note">No filters yet.</div>';
      return;
    }

    const fieldOptions = fields.map(function (field) {
      return field;
    });

    wrap.innerHTML = filters
      .map(function (filter) {
        const field = filter.field || fieldOptions[0] || "";
        const op = filter.op || "contains";
        const twoValues = operatorNeedsTwoValues(op);
        const singleClass = twoValues ? "" : " ps-table-filter-row--single";

        const fieldSelect =
          '<select class="ps-table-filter-select" data-filter-part="field" data-filter-id="' +
          escapeHtml(filter.id) +
          '">' +
          fieldOptions
            .map(function (f) {
              const sel = f === field ? ' selected="selected"' : "";
              return (
                '<option value="' +
                escapeHtml(f) +
                '"' +
                sel +
                ">" +
                escapeHtml(f) +
                "</option>"
              );
            })
            .join("") +
          "</select>";

        const opSelect =
          '<select class="ps-table-filter-select" data-filter-part="op" data-filter-id="' +
          escapeHtml(filter.id) +
          '">' +
          renderOperatorOptions(field, op) +
          "</select>";

        const valueInput =
          '<input class="ps-table-filter-value" data-filter-part="value" data-filter-id="' +
          escapeHtml(filter.id) +
          '" type="text" value="' +
          escapeHtml(filter.value || "") +
          '"' +
          (operatorNeedsValue(op) ? "" : ' disabled="disabled"') +
          ' placeholder="Value" />';

        const valueToInput = twoValues
          ? '<input class="ps-table-filter-value" data-filter-part="valueTo" data-filter-id="' +
            escapeHtml(filter.id) +
            '" type="text" value="' +
            escapeHtml(filter.valueTo || "") +
            '" placeholder="And value" />'
          : "";

        const removeBtn =
          '<button type="button" class="ps-btn ps-table-filter-remove" data-filter-action="remove" data-filter-id="' +
          escapeHtml(filter.id) +
          '">Remove</button>';

        return (
          '<div class="ps-table-filter-row' +
          singleClass +
          '" data-filter-row="' +
          escapeHtml(filter.id) +
          '">' +
          fieldSelect +
          opSelect +
          valueInput +
          valueToInput +
          removeBtn +
          "</div>"
        );
      })
      .join("");
  }

  function renderColumnsList() {
    const wrap = document.getElementById("table-columns-list");
    if (!wrap) return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const hidden = new Set(getHiddenColumns());

    if (!fields.length) {
      wrap.innerHTML = '<div class="note ps-note">No columns available.</div>';
      return;
    }

    wrap.innerHTML = fields
      .map(function (field) {
        const checked = hidden.has(field) ? "" : ' checked="checked"';
        return (
          '<label class="ps-table-column-item">' +
          '<input type="checkbox" data-column-field="' +
          escapeHtml(field) +
          '"' +
          checked +
          " />" +
          "<span>" +
          escapeHtml(field) +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function describeFilter(filter) {
    const field = filter.field || "";
    const op = filter.op || "";
    const value = filter.value || "";
    const valueTo = filter.valueTo || "";

    const labelMap = {};
    for (const group of [FILTER_OPS.text, FILTER_OPS.number]) {
      for (const item of group) {
        labelMap[item.value] = item.label;
      }
    }

    const opLabel = labelMap[op] || op;

    if (operatorNeedsTwoValues(op)) {
      return field + " " + opLabel + " " + value + " and " + valueTo;
    }

    if (operatorNeedsValue(op)) {
      return field + " " + opLabel + " " + value;
    }

    return field + " " + opLabel;
  }

  function renderActiveFilters() {
    const wrap = document.getElementById("table-active-filters");
    if (!wrap) return;

    const active = getCompleteFilters();

    if (!active.length) {
      wrap.hidden = true;
      wrap.innerHTML = "";
      return;
    }

    wrap.hidden = false;
    wrap.innerHTML = active
      .map(function (filter) {
        return (
          '<span class="ps-table-filter-chip">' +
          "<span>" +
          escapeHtml(describeFilter(filter)) +
          "</span>" +
          '<button type="button" title="Remove filter" data-filter-chip-remove="' +
          escapeHtml(filter.id) +
          '">×</button>' +
          "</span>"
        );
      })
      .join("");
  }

  function syncFilterButtonUi() {
    const btn = document.getElementById("table-filters-toggle-btn");
    if (!btn) return;

    btn.classList.toggle("is-active", hasActiveFilters());
  }

  function syncColumnsButtonUi() {
    const btn = document.getElementById("table-columns-toggle-btn");
    if (!btn) return;

    btn.classList.toggle("is-active", hasHiddenColumns());
  }

  function syncFilterPanelUi() {
    const panel = document.getElementById("table-filter-panel");
    const btn = document.getElementById("table-filters-toggle-btn");
    const shouldShow = !!getTableUiState().filtersOpen;

    if (panel) {
      panel.hidden = !shouldShow;
    }

    if (btn) {
      btn.setAttribute("aria-expanded", shouldShow ? "true" : "false");
    }

    syncFilterButtonUi();
  }

  function syncColumnsPanelUi() {
    const panel = document.getElementById("table-columns-panel");
    const btn = document.getElementById("table-columns-toggle-btn");
    const shouldShow = !!getTableUiState().columnsOpen;

    if (panel) {
      panel.hidden = !shouldShow;
    }

    if (btn) {
      btn.setAttribute("aria-expanded", shouldShow ? "true" : "false");
    }

    syncColumnsButtonUi();
  }

  function getFieldValueForFilter(rowData, field) {
    return rowData ? rowData[field] : null;
  }

  function isMissing(value) {
    return value == null || String(value).trim() === "";
  }

  function matchesSingleFilter(rowData, filter) {
    if (!isFilterComplete(filter)) return true;

    const raw = getFieldValueForFilter(rowData, filter.field);
    const fieldType = getFieldType(filter.field);
    const op = filter.op;

    if (op === "missing") return isMissing(raw);
    if (op === "not_missing") return !isMissing(raw);

    if (fieldType === "number") {
      const a = Number(raw);
      const b = Number(filter.value);
      const c = Number(filter.valueTo);

      if (!Number.isFinite(a)) return false;

      if (op === "lt") return a < b;
      if (op === "lte") return a <= b;
      if (op === "gt") return a > b;
      if (op === "gte") return a >= b;
      if (op === "eq") return a === b;
      if (op === "neq") return a !== b;
      if (op === "between") return a >= Math.min(b, c) && a <= Math.max(b, c);
      if (op === "not_between") {
        return !(a >= Math.min(b, c) && a <= Math.max(b, c));
      }

      return true;
    }

    const text = String(raw == null ? "" : raw).toLowerCase();
    const q = String(filter.value || "").toLowerCase();

    if (op === "contains") return text.includes(q);
    if (op === "eq") return text === q;
    if (op === "neq") return text !== q;

    return true;
  }

  function applyAllTableFilters() {
    if (!state.tabulatorInstance) return;

    const searchQuery = getSearchQuery().trim().toLowerCase();
    const filters = getCompleteFilters();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (!searchQuery && !filters.length) {
      state.tabulatorInstance.clearFilter(true);
      refreshTableStatus();
      return;
    }

    state.tabulatorInstance.setFilter(function (rowData) {
      if (searchQuery) {
        let matched = false;
        for (const field of fields) {
          const raw = rowData[field];
          const text = String(raw == null ? "" : raw).toLowerCase();
          if (text.includes(searchQuery)) {
            matched = true;
            break;
          }
        }
        if (!matched) return false;
      }

      for (const filter of filters) {
        if (!matchesSingleFilter(rowData, filter)) return false;
      }

      return true;
    });

    refreshTableStatus();
  }

  function getColumnComponentByField(field) {
    if (!state.tabulatorInstance || typeof state.tabulatorInstance.getColumns !== "function") {
      return null;
    }

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        if (col.getField() === field) return col;
      }
    } catch (e) {
      // ignore
    }

    return null;
  }

  function applyColumnVisibilityState() {
    if (!state.tabulatorInstance) return;

    const hidden = new Set(getHiddenColumns());
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    for (const field of fields) {
      const col = getColumnComponentByField(field);
      if (!col) continue;

      try {
        if (hidden.has(field)) {
          if (typeof col.hide === "function") col.hide();
        } else {
          if (typeof col.show === "function") col.show();
        }
      } catch (e) {
        // ignore
      }
    }

    renderColumnsList();
    syncColumnsPanelUi();
  }

  function getVisibleFieldsInCurrentOrder() {
    if (!state.tabulatorInstance || typeof state.tabulatorInstance.getColumns !== "function") {
      return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    }

    const out = [];

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        const field = col.getField();
        if (!field) continue;

        let visible = true;
        try {
          if (typeof col.isVisible === "function") {
            visible = !!col.isVisible();
          }
        } catch (e) {
          visible = true;
        }

        if (visible) out.push(field);
      }
    } catch (e) {
      return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    }

    return out;
  }

  function restoreToolbarInputs() {
    const input = document.getElementById("table-search-input");
    if (input) {
      input.value = getSearchQuery();
    }
  }

  function addFilter(initial) {
    const filters = getFilters().slice();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (filters.length >= MAX_FILTERS) {
      return;
    }

    filters.push(
      normalizeFilter(
        initial || {
          id: newFilterId(),
          field: fields[0] || "",
          op: getFieldType(fields[0] || "") === "number" ? "eq" : "contains",
          value: "",
          valueTo: "",
        }
      )
    );

    setFilters(filters);
    setFiltersOpen(true);
    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
  }

  function removeFilter(filterId) {
    const filters = getFilters().filter(function (f) {
      return f.id !== filterId;
    });

    setFilters(filters);

    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
  }

  function updateFilter(filterId, part, value, options) {
    const shouldRerender = !!(options && options.rerender);

    const filters = getFilters().map(function (filter) {
      if (filter.id !== filterId) return filter;

      const next = {
        id: filter.id,
        field: filter.field,
        op: filter.op,
        value: filter.value,
        valueTo: filter.valueTo,
      };

      next[part] = String(value || "");

      if (part === "field") {
        const allowedOps = getOperatorOptions(next.field).map(function (x) {
          return x.value;
        });

        if (!allowedOps.includes(next.op)) {
          next.op = getFieldType(next.field) === "number" ? "eq" : "contains";
          next.value = "";
          next.valueTo = "";
        }
      }

      if (part === "op") {
        if (!operatorNeedsValue(next.op)) {
          next.value = "";
          next.valueTo = "";
        } else if (!operatorNeedsTwoValues(next.op)) {
          next.valueTo = "";
        }
      }

      return next;
    });

    setFilters(filters);

    if (shouldRerender) {
      renderFilterRows();
    }

    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
  }

  function toggleColumnVisibility(field, shouldBeVisible) {
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const hidden = new Set(getHiddenColumns());

    if (!field || !fields.includes(field)) return;

    if (!shouldBeVisible) {
      const currentlyVisibleCount = fields.filter(function (f) {
        return !hidden.has(f);
      }).length;

      if (currentlyVisibleCount <= 1) {
        renderColumnsList();
        return;
      }

      hidden.add(field);
    } else {
      hidden.delete(field);
    }

    setHiddenColumns(Array.from(hidden));
    applyColumnVisibilityState();
  }

  function showAllColumns() {
    setHiddenColumns([]);
    applyColumnVisibilityState();
  }

  function bindTableToolbar() {
    const input = document.getElementById("table-search-input");
    const resetBtn = document.getElementById("table-reset-btn");
    const filtersToggleBtn = document.getElementById("table-filters-toggle-btn");
    const columnsToggleBtn = document.getElementById("table-columns-toggle-btn");
    const addFilterBtn = document.getElementById("table-filter-add-btn");
    const showAllColumnsBtn = document.getElementById("table-columns-show-all-btn");
    const filterRows = document.getElementById("table-filter-rows");
    const columnsList = document.getElementById("table-columns-list");
    const activeFilters = document.getElementById("table-active-filters");

    restoreToolbarInputs();
    renderFilterRows();
    renderColumnsList();
    renderActiveFilters();
    syncFilterPanelUi();
    syncColumnsPanelUi();

    if (input && !input.dataset.plotsrvBound) {
      let timer = null;

      input.addEventListener("input", function () {
        const q = String(input.value || "");
        setSearchQuery(q);

        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          applyAllTableFilters();
        }, 120);
      });

      input.dataset.plotsrvBound = "1";
    }

    if (resetBtn && !resetBtn.dataset.plotsrvBound) {
      resetBtn.addEventListener("click", function () {
        state.tableUiState = defaultTableUiState();
        saveTableUiState();

        if (input) input.value = "";

        if (state.tabulatorInstance) {
          try {
            state.tabulatorInstance.clearFilter(true);
          } catch (e) {
            // ignore
          }

          try {
            state.tabulatorInstance.clearSort();
          } catch (e) {
            // ignore
          }

          if (Array.isArray(state.tableColumnDefs) && state.tableColumnDefs.length > 0) {
            try {
              state.tabulatorInstance.setColumns(state.tableColumnDefs);
            } catch (e) {
              // ignore
            }
          }

          try {
            state.tabulatorInstance.replaceData(state.tableRows || []);
          } catch (e) {
            // ignore
          }
        }

        renderFilterRows();
        renderColumnsList();
        renderActiveFilters();
        syncFilterPanelUi();
        syncColumnsPanelUi();
        applyColumnVisibilityState();
        applyAllTableFilters();
      });

      resetBtn.dataset.plotsrvBound = "1";
    }

    if (filtersToggleBtn && !filtersToggleBtn.dataset.plotsrvBound) {
      filtersToggleBtn.addEventListener("click", function () {
        const nextOpen = !getTableUiState().filtersOpen;
        setFiltersOpen(nextOpen);
        syncFilterPanelUi();
      });

      filtersToggleBtn.dataset.plotsrvBound = "1";
    }

    if (columnsToggleBtn && !columnsToggleBtn.dataset.plotsrvBound) {
      columnsToggleBtn.addEventListener("click", function () {
        const nextOpen = !getTableUiState().columnsOpen;
        setColumnsOpen(nextOpen);
        syncColumnsPanelUi();
      });

      columnsToggleBtn.dataset.plotsrvBound = "1";
    }

    if (addFilterBtn && !addFilterBtn.dataset.plotsrvBound) {
      addFilterBtn.addEventListener("click", function () {
        addFilter();
        const filters = getFilters();
        const newest = filters[filters.length - 1];
        if (!newest) return;

        window.requestAnimationFrame(function () {
          const firstInput = document.querySelector(
            '[data-filter-id="' + newest.id + '"][data-filter-part="value"]'
          );
          if (firstInput && typeof firstInput.focus === "function") {
            firstInput.focus();
          }
        });
      });

      addFilterBtn.dataset.plotsrvBound = "1";
    }

    if (showAllColumnsBtn && !showAllColumnsBtn.dataset.plotsrvBound) {
      showAllColumnsBtn.addEventListener("click", function () {
        showAllColumns();
      });

      showAllColumnsBtn.dataset.plotsrvBound = "1";
    }

    if (addFilterBtn) {
      addFilterBtn.disabled = getFilters().length >= MAX_FILTERS;
      addFilterBtn.title =
        getFilters().length >= MAX_FILTERS
          ? "Maximum number of filters reached"
          : "";
    }

    if (filterRows && !filterRows.dataset.plotsrvBound) {
      filterRows.addEventListener("change", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const filterId = target.getAttribute("data-filter-id");
        const part = target.getAttribute("data-filter-part");

        if (!filterId || !part) return;

        const rerender = part === "field" || part === "op";
        updateFilter(filterId, part, target.value, { rerender: rerender });
      });

      filterRows.addEventListener("input", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const filterId = target.getAttribute("data-filter-id");
        const part = target.getAttribute("data-filter-part");

        if (!filterId || !part || (part !== "value" && part !== "valueTo")) return;

        updateFilter(filterId, part, target.value, { rerender: false });
      });

      filterRows.addEventListener("click", function (ev) {
        const target =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-filter-action='remove']")
            : null;
        if (!target) return;

        const filterId = target.getAttribute("data-filter-id");
        if (!filterId) return;

        removeFilter(filterId);
      });

      filterRows.dataset.plotsrvBound = "1";
    }

    if (columnsList && !columnsList.dataset.plotsrvBound) {
      columnsList.addEventListener("change", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const field = target.getAttribute("data-column-field");
        if (!field) return;

        toggleColumnVisibility(field, !!target.checked);
      });

      columnsList.dataset.plotsrvBound = "1";
    }

    if (activeFilters && !activeFilters.dataset.plotsrvBound) {
      activeFilters.addEventListener("click", function (ev) {
        const btn =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-filter-chip-remove]")
            : null;
        if (!btn) return;

        const filterId = btn.getAttribute("data-filter-chip-remove");
        if (!filterId) return;

        removeFilter(filterId);
      });

      activeFilters.dataset.plotsrvBound = "1";
    }
  }

  function csvEscape(value) {
    const text = String(value == null ? "" : value);
    if (
      text.includes('"') ||
      text.includes(",") ||
      text.includes("\n") ||
      text.includes("\r")
    ) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  function downloadTextFile(filename, text, mime) {
    const blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function buildCsvFromRows(rows, fields) {
    const lines = [];
    lines.push(fields.map(csvEscape).join(","));

    for (const row of rows) {
      const vals = fields.map(function (field) {
        return csvEscape(row ? row[field] : "");
      });
      lines.push(vals.join(","));
    }

    return lines.join("\r\n");
  }

  function exportFilteredRichTable() {
    if (!state.tabulatorInstance) return false;

    let rows = [];
    try {
      rows = state.tabulatorInstance.getData("active");
      if (!Array.isArray(rows)) rows = [];
    } catch (e) {
      rows = [];
    }

    if (!rows.length) {
      try {
        rows = state.tabulatorInstance.getData();
        if (!Array.isArray(rows)) rows = [];
      } catch (e) {
        rows = [];
      }
    }

    const visibleFields = getVisibleFieldsInCurrentOrder();
    if (!visibleFields.length) return false;

    const csv = buildCsvFromRows(rows, visibleFields);

    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "table").replace(/[^\w.-]+/g, "_");
    const filename = base + "-" + stamp + ".csv";

    downloadTextFile(filename, csv, "text/csv;charset=utf-8");
    return true;
  }

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    if (!grid) return;

    if (!state.tableUiState) {
      loadTableUiState();
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    const url =
      "/table/data?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&_ts=" +
      Date.now();

    let res = await fetch(url);
    // A file-backed server admits only a bounded number of expensive CSV
    // loads. A short retry keeps normal refreshes smooth without hiding a
    // persistent failure behind an endless client loop.
    for (let attempt = 0; res.status === 503 && attempt < 2; attempt += 1) {
      await new Promise(function (resolve) {
        window.setTimeout(resolve, 250 * (attempt + 1));
      });
      res = await fetch(url);
    }

    if (!res.ok) {
      if (
        res.status === 404 &&
        typeof core.isHistoryMode === "function" &&
        core.isHistoryMode() &&
        typeof core.handleMissingSnapshot === "function"
      ) {
        await core.handleMissingSnapshot("table");
        return;
      }

      console.error("Failed to load table data");
      return;
    }

    const data = await res.json();
    const columns = buildColumnDefs(data.columns || []);
    const rows = data.rows || [];

    state.tableLastPayload = data;
    state.tableRows = rows;
    state.tableFields = (data.columns || []).slice();
    state.tableFieldTypes = inferFieldTypes(data.columns || [], rows);
    state.tableColumnDefs = columns;

    if (state.tabulatorInstance) {
      state.tabulatorInstance.setColumns(columns);
      state.tabulatorInstance.replaceData(rows);
      bindTableToolbar();
      applyAllTableFilters();
      refreshTableStatus();
      return;
    }

    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      return;
    }

    state.tabulatorInstance = new Tabulator("#table-grid", {
      data: rows,
      columns: columns,
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 20,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
    });

    if (typeof state.tabulatorInstance.on === "function") {
      state.tabulatorInstance.on("dataFiltered", function () {
        refreshTableStatus();
      });
    }

    bindTableToolbar();
    applyAllTableFilters();
    refreshTableStatus();
  }

  function exportTable() {
    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
    const sourceDownload =
      state.tableLastPayload &&
      state.tableLastPayload.meta &&
      state.tableLastPayload.meta.source_download_url;

    if (!isHistory && typeof sourceDownload === "string" && sourceDownload) {
      window.location.href = sourceDownload + "&_ts=" + Date.now();
      return;
    }

    if (state.tabulatorInstance) {
      const ok = exportFilteredRichTable();
      if (ok) return;
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    window.location.href =
      "/table/export?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&format=csv&_ts=" +
      Date.now();
  }

  core.loadTable = loadTable;
  core.exportTable = exportTable;

  window.exportTable = exportTable;
})();

/* plotsrv source: js/renderers/json.js */
// src/plotsrv/static/js/renderers/json.js
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
  const config = window.PLOTSRV.config;

  function clearJsonHits(scopeEl) {
    if (!scopeEl) return;
    const hits = scopeEl.querySelectorAll(".json-hit, .json-hit-current");
    hits.forEach((el) => {
      el.classList.remove("json-hit");
      el.classList.remove("json-hit-current");
    });
  }

  function getJsonRoot(root) {
    if (!root) return null;
    return root.querySelector('[data-plotsrv-json="1"]');
  }

  function getJsonPrefs() {
    if (typeof core.loadJsonPrefs === "function") {
      return core.loadJsonPrefs(config.activeViewId);
    }
    return {
      mode: "json",
      level_limit: "2",
      find_query: "",
      pinned_values: [],
    };
  }

  function saveJsonPrefs(nextPrefs) {
    if (typeof core.saveJsonPrefs === "function") {
      core.saveJsonPrefs(config.activeViewId, nextPrefs);
    }
  }

  function getPanels(jsonRoot) {
    if (!jsonRoot) return [];
    return Array.from(jsonRoot.querySelectorAll("[data-json-panel]"));
  }

  function getModeButtons(root) {
    return Array.from(root.querySelectorAll("[data-json-mode]"));
  }

  function applyModeButtonState(root, mode) {
    getModeButtons(root).forEach((btn) => {
      const btnMode = String(btn.getAttribute("data-json-mode") || "");
      const isActive = btnMode === mode;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function getToolbarGroup(root, name) {
    return root.querySelector('[data-json-toolbar-group="' + String(name) + '"]');
  }

  function syncToolbarForMode(root, mode) {
    const levelsGroup = getToolbarGroup(root, "levels");
    const findGroup = getToolbarGroup(root, "find");
    const pinsGroup = getToolbarGroup(root, "pins");
    const viewGroup = getToolbarGroup(root, "view");
  
    const isText = mode === "text";
  
    function setGroupVisible(el, shouldShow) {
      if (!el) return;
      el.hidden = !shouldShow;
      el.style.display = shouldShow ? "" : "none";
    }
  
    setGroupVisible(levelsGroup, !isText);
    setGroupVisible(findGroup, !isText);
    setGroupVisible(pinsGroup, !isText);
    setGroupVisible(viewGroup, true);
  }

  function setMode(root, mode) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const allowed = new Set(["json", "simple", "text"]);
    const nextMode = allowed.has(mode) ? mode : "json";

    getPanels(jsonRoot).forEach((panel) => {
      const panelMode = String(panel.getAttribute("data-json-panel") || "");
      panel.hidden = panelMode !== nextMode;
    });

    applyModeButtonState(root, nextMode);
    syncToolbarForMode(root, nextMode);

    if (nextMode === "text") {
      applyTextModeContent(root);
      clearJsonHits(jsonRoot);
      const localState = root._plotsrvJsonState;
      if (localState) {
        localState.hits = [];
        localState.idx = -1;
        setCounter(root, localState);
      }
      closePinnedModal(root);
    }

    const prefs = getJsonPrefs();
    prefs.mode = nextMode;
    saveJsonPrefs(prefs);
  }

  function parseStoredJsonText(raw) {
    if (typeof raw !== "string" || !raw) return null;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function getPreferredTextValue(jsonRoot) {
    if (!jsonRoot) return "";

    const rawText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-raw-text") || "null"
    );
    if (typeof rawText === "string") return rawText;

    const prettyText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-pretty-text") || "null"
    );
    if (typeof prettyText === "string") return prettyText;

    const existing = jsonRoot.querySelector("[data-json-text-view='1']");
    return existing ? String(existing.textContent || "") : "";
  }

  function applyTextModeContent(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const textPre = jsonRoot.querySelector("[data-json-text-view='1']");
    if (!textPre) return;

    textPre.textContent = getPreferredTextValue(jsonRoot);
  }

  function getDetailsNodesForMode(root, mode) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return [];

    return Array.from(
      jsonRoot.querySelectorAll(
        '[data-json-panel="' + String(mode) + '"] details[data-json-depth]'
      )
    );
  }

  function getActiveMode(root) {
    const active = root.querySelector("[data-json-mode].is-active");
    if (!active) return "json";
    return String(active.getAttribute("data-json-mode") || "json");
  }

  function setLevelLimit(root, rawLevelLimit) {
    const mode = getActiveMode(root);
    if (mode === "text") return;

    const levelLimit = String(rawLevelLimit || "2");
    const select = root.querySelector("[data-json-level-limit='1']");
    if (select && String(select.value || "") !== levelLimit) {
      select.value = levelLimit;
    }

    const detailsNodes = getDetailsNodesForMode(root, mode);

    if (!detailsNodes.length) {
      const prefs = getJsonPrefs();
      prefs.level_limit = levelLimit;
      saveJsonPrefs(prefs);
      return;
    }

    if (levelLimit === "all") {
      detailsNodes.forEach((node) => {
        node.open = true;
      });
    } else {
      const n = Number(levelLimit);
      const limit = Number.isFinite(n) && n >= 1 ? n : 2;

      detailsNodes.forEach((node) => {
        const depth = Number(node.getAttribute("data-json-depth") || "0");
        node.open = depth < limit;
      });
    }

    const prefs = getJsonPrefs();
    prefs.level_limit = levelLimit;
    saveJsonPrefs(prefs);
  }

  function expandAll(root) {
    const mode = getActiveMode(root);
    if (mode === "text") return;

    const detailsNodes = getDetailsNodesForMode(root, mode);
    detailsNodes.forEach((node) => {
      node.open = true;
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "all";

    const prefs = getJsonPrefs();
    prefs.level_limit = "all";
    saveJsonPrefs(prefs);
    root._plotsrvCollapseState = {
      lastAction: "expand",
      preservedPinned: [],
    };
  }

  function collapseAll(root) {
    const mode = getActiveMode(root);
    if (mode === "text") return;

    const detailsNodes = getDetailsNodesForMode(root, mode);
    const expandedPinned = getExpandedPinnedPaths(root);

    const previousState = root._plotsrvCollapseState || {
      lastAction: "",
      preservedPinned: [],
    };

    const sameAsLast =
      previousState.lastAction === "collapse-preserve" &&
      Array.isArray(previousState.preservedPinned) &&
      previousState.preservedPinned.length > 0;

    detailsNodes.forEach((node) => {
      const depth = Number(node.getAttribute("data-json-depth") || "0");
      node.open = depth < 1;
    });

    if (sameAsLast) {
      previousState.preservedPinned.forEach((path) => {
        setPinnedValueExpanded(root, path, false);
      });
      root._plotsrvCollapseState = {
        lastAction: "collapse-full",
        preservedPinned: [],
      };
    } else {
      expandedPinned.forEach((path) => {
        setPinnedValueExpanded(root, path, true);
      });
      root._plotsrvCollapseState = {
        lastAction: "collapse-preserve",
        preservedPinned: expandedPinned,
      };
    }

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "1";

    const prefs = getJsonPrefs();
    prefs.level_limit = "1";
    saveJsonPrefs(prefs);
  }

  function getSearchScope(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return null;

    const activePanel = Array.from(
      jsonRoot.querySelectorAll("[data-json-panel]")
    ).find((panel) => !panel.hidden);

    return activePanel || jsonRoot;
  }

  function setCounter(root, localState) {
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");
    if (!countEl) return;

    if (!localState.hits.length) {
      countEl.textContent = "";
      return;
    }

    countEl.textContent =
      String(localState.idx + 1) + "/" + String(localState.hits.length);
  }

  function openParents(el) {
    let cur = el;
    while (cur) {
      const det = core.findNearest(cur, "details");
      if (!det) break;
      det.open = true;
      cur = det.parentElement;
    }
  }

  function gotoIndex(root, localState, i) {
    if (!localState.hits.length) return;

    localState.hits.forEach((el) => el.classList.remove("json-hit-current"));
    localState.idx = (i + localState.hits.length) % localState.hits.length;

    const el = localState.hits[localState.idx];
    el.classList.add("json-hit-current");
    openParents(el);

    try {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (e) {
      el.scrollIntoView();
    }

    setCounter(root, localState);
  }

  function runFind(root, localState) {
    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const searchScope = getSearchScope(root);
    if (!input || !searchScope) return;

    const q = String(input.value || "").trim();

    const prefs = getJsonPrefs();
    prefs.find_query = q;
    saveJsonPrefs(prefs);

    clearJsonHits(searchScope);
    localState.hits = [];
    localState.idx = -1;
    setCounter(root, localState);

    if (!q) return;

    const panelMode = String(searchScope.getAttribute("data-json-panel") || "");
    if (panelMode === "text") {
      return;
    }

    const qLower = q.toLowerCase();
    const candidates = searchScope.querySelectorAll("[data-json-text]");

    candidates.forEach((el) => {
      const t = String(el.getAttribute("data-json-text") || "").toLowerCase();
      if (!t) return;
      if (t.includes(qLower)) {
        el.classList.add("json-hit");
        localState.hits.push(el);
      }
    });

    if (localState.hits.length) {
      gotoIndex(root, localState, 0);
    }
  }

  function getPinnedPaths() {
    const prefs = getJsonPrefs();
    return Array.isArray(prefs.pinned_values) ? prefs.pinned_values.map(String) : [];
  }

  function setPinnedPaths(paths) {
    const prefs = getJsonPrefs();
    prefs.pinned_values = Array.from(new Set((paths || []).map(String).filter(Boolean)));
    saveJsonPrefs(prefs);
  }

  function getExpandedPinnedPaths(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return [];

    const pinned = new Set(getPinnedPaths());

    return Array.from(
      jsonRoot.querySelectorAll(".ps-json-entry.is-pinned[data-json-path]")
    )
      .map((el) => String(el.getAttribute("data-json-path") || ""))
      .filter((path) => {
        if (!path || !pinned.has(path)) return false;
        const entry = jsonRoot.querySelector(
          '[data-json-path="' + CSS.escape(path) + '"]'
        );
        return !!entry;
      });
  }

  function setPinnedValueExpanded(root, path, shouldOpen) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const entry = jsonRoot.querySelector(
      '.ps-json-entry[data-json-path="' + CSS.escape(String(path)) + '"]'
    );
    if (!entry) return;

    entry.classList.toggle("is-pinned-open", shouldOpen);
  }

  function isPinned(path) {
    return new Set(getPinnedPaths()).has(String(path || ""));
  }

  function setPinnedState(root, path, shouldPin) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const btn = jsonRoot.querySelector(
      '[data-json-pin-toggle="' + CSS.escape(String(path)) + '"]'
    );
    const entry = jsonRoot.querySelector(
      '[data-json-path="' + CSS.escape(String(path)) + '"]'
    );

    if (btn) {
      btn.setAttribute("aria-pressed", shouldPin ? "true" : "false");
      btn.classList.toggle("is-pinned", shouldPin);
      btn.title = shouldPin ? "Unpin value" : "Pin value";
    }

    if (entry) {
      entry.classList.toggle("is-pinned", shouldPin);
    }
  }

  function restorePinnedStates(root) {
    const pinned = new Set(getPinnedPaths());
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const pinBtns = jsonRoot.querySelectorAll("[data-json-pin-toggle]");
    pinBtns.forEach((btn) => {
      const path = String(btn.getAttribute("data-json-pin-toggle") || "");
      setPinnedState(root, path, pinned.has(path));
    });
  }

  function getEntryFullValue(entry) {
    if (!entry) return "";
  
    const hiddenValue = entry.querySelector("[data-json-full-value-text='1']");
    if (hiddenValue) {
      return String(hiddenValue.textContent || "");
    }
  
    return String(entry.getAttribute("data-json-full-value") || "");
  }

  function buildPinnedModalList(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return "";

    const pinned = getPinnedPaths();
    if (!pinned.length) {
      return '<div class="note ps-note">No pinned values yet.</div>';
    }

    const parts = [];

    pinned.forEach((path) => {
      const entry = jsonRoot.querySelector(
        '.ps-json-entry[data-json-path="' + CSS.escape(String(path)) + '"]'
      );
      if (!entry) return;

      const key = String(entry.getAttribute("data-json-key") || path);
      const value = getEntryFullValue(entry);

      parts.push(
        '<div class="ps-json-pinneditem">' +
        '<div class="ps-json-pinneditem__meta">' +
        '<div class="ps-json-pinneditem__key">' + core.escapeHtml(key) + '</div>' +
        '<div class="ps-json-pinneditem__path">' + core.escapeHtml(path) + '</div>' +
        '</div>' +
        '<pre class="ps-json-pinneditem__value">' + core.escapeHtml(value) + '</pre>' +
        '</div>'
      );
    });

    if (!parts.length) {
      return '<div class="note ps-note">No pinned values available in this snapshot.</div>';
    }

    return parts.join("");
  }

  function openPinnedModal(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const modal = jsonRoot.querySelector("[data-json-pinned-modal='1']");
    const list = jsonRoot.querySelector("[data-json-pinned-list='1']");
    if (!modal || !list) return;

    list.innerHTML = buildPinnedModalList(root);
    modal.hidden = false;
  }

  function closePinnedModal(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const modal = jsonRoot.querySelector("[data-json-pinned-modal='1']");
    if (!modal) return;

    modal.hidden = true;
  }

  function restorePrefs(root) {
    const prefs = getJsonPrefs();

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    if (input) {
      input.value = prefs.find_query || "";
    }

    applyTextModeContent(root);
    setMode(root, prefs.mode || "json");
    setLevelLimit(root, prefs.level_limit || "2");
    restorePinnedStates(root);
    syncToolbarForMode(root, getActiveMode(root));
  }

  function bindJsonToolbar(root, localState) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const jsonRoot = getJsonRoot(root);
    if (!toolbar || !jsonRoot) return;
    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;

    toolbar.setAttribute("data-plotsrv-bound", "1");

    toolbar.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const mode = String(btn.getAttribute("data-json-mode") || "");
      if (mode) {
        setMode(root, mode);
        if (mode !== "text") {
          runFind(root, localState);
        }
        return;
      }

      const action = String(btn.getAttribute("data-plotsrv-action") || "");

      if (action === "expand-all") {
        expandAll(root);
        return;
      }

      if (action === "collapse-all") {
        collapseAll(root);
        return;
      }

      if (action === "find-next") {
        if (!localState.hits.length) runFind(root, localState);
        if (localState.hits.length) gotoIndex(root, localState, localState.idx + 1);
        return;
      }

      if (action === "find-prev") {
        if (!localState.hits.length) runFind(root, localState);
        if (localState.hits.length) gotoIndex(root, localState, localState.idx - 1);
        return;
      }

      if (action === "open-pinned") {
        openPinnedModal(root);
      }
    });

    jsonRoot.addEventListener("click", function (ev) {
      const pinBtn =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-json-pin-toggle]")
          : null;

      if (pinBtn) {
        const path = String(pinBtn.getAttribute("data-json-pin-toggle") || "");
        if (!path) return;

        const current = new Set(getPinnedPaths());
        const shouldPin = !current.has(path);

        if (shouldPin) {
          current.add(path);
        } else {
          current.delete(path);
        }

        setPinnedPaths(Array.from(current));
        setPinnedState(root, path, shouldPin);
        return;
      }

      const closeEl =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-json-pinned-close]")
          : null;

      if (closeEl) {
        closePinnedModal(root);
      }
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) {
      select.addEventListener("change", function () {
        setLevelLimit(root, String(select.value || "2"));
      });
    }

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    if (input) {
      input.addEventListener("input", function () {
        if (input._plotsrvTimer) clearTimeout(input._plotsrvTimer);
        input._plotsrvTimer = setTimeout(function () {
          runFind(root, localState);
        }, 120);
      });

      input.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") {
          ev.preventDefault();
          if (!localState.hits.length) runFind(root, localState);
          if (localState.hits.length) gotoIndex(root, localState, localState.idx + 1);
        }
      });
    }
  }

  function initJsonToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const jsonRoot = getJsonRoot(root);
    if (!toolbar || !jsonRoot) return;

    const localState = {
      hits: [],
      idx: -1,
    };

    root._plotsrvJsonState = localState;

    bindJsonToolbar(root, localState);
    restorePrefs(root);
    syncToolbarForMode(root, getActiveMode(root));
    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const mode = getActiveMode(root);
    if (mode !== "text" && input && String(input.value || "").trim()) {
      runFind(root, localState);
    }
  }

  function initArtifactEnhancements(root) {
    if (!root) return;

    if (typeof renderers.initTextToolbar === "function") {
      renderers.initTextToolbar(root);
    }

    if (typeof renderers.initCodeToolbar === "function") {
      renderers.initCodeToolbar(root);
    }

    if (root.querySelector('[data-plotsrv-toolbar="json"]')) {
      initJsonToolbar(root);
    }
  }

  renderers.clearJsonHits = clearJsonHits;
  renderers.initJsonToolbar = initJsonToolbar;
  renderers.initArtifactEnhancements = initArtifactEnhancements;
})();

/* plotsrv source: js/renderers/text.js */
// src/plotsrv/static/js/renderers/text.js
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
  const config = window.PLOTSRV.config;

  const MAX_COLOURIZE_CHARS = 300000;

  const LOG_TOKEN_RE =
    /\b(CRITICAL|FATAL|ERROR|EXCEPTION|TRACEBACK|WARNING|WARN|INFO|DEBUG|TRACE|SUCCESS|PASSED|PASS|FAILED|FAIL|OK|[1-5][0-9]{2})\b/gi;

  function getTextPrefs() {
    if (typeof core.loadTextPrefs === "function") {
      return core.loadTextPrefs(config.activeViewId);
    }

    return {
      wrap_enabled: false,
      reverse_enabled: false,
      colour_enabled: true,
    };
  }

  function saveTextPrefs(nextPrefs) {
    if (typeof core.saveTextPrefs === "function") {
      core.saveTextPrefs(config.activeViewId, nextPrefs);
      return;
    }

    if (core.storageKeys && typeof core.savePref === "function") {
      core.savePref(
        core.storageKeys.textWrapEnabled,
        nextPrefs.wrap_enabled ? "1" : "0"
      );
    }
  }

  function splitLinesPreserveEndings(text) {
    return String(text || "").match(/[^\n]*\n|[^\n]+/g) || [];
  }

  function reverseLines(text) {
    const lines = splitLinesPreserveEndings(text);
    return lines.reverse().join("");
  }

  function renderedText(state) {
    const originalText =
      typeof state.originalText === "string" ? state.originalText : "";

    return state.reverseEnabled ? reverseLines(originalText) : originalText;
  }

  function setButtonActive(btn, active) {
    if (!btn) return;
    btn.classList.toggle("is-active", !!active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function syncReverseIndicator(root, reverseEnabled) {
    const indicator = root.querySelector("[data-plotsrv-text-reverse-indicator='1']");
    if (!indicator) return;
    indicator.hidden = !reverseEnabled;
  }

  function tokenClass(token) {
    const upper = String(token || "").toUpperCase();

    if (upper === "CRITICAL" || upper === "FATAL") {
      return "ps-log-token--critical";
    }

    if (
      upper === "ERROR" ||
      upper === "EXCEPTION" ||
      upper === "TRACEBACK" ||
      upper === "FAILED" ||
      upper === "FAIL"
    ) {
      return "ps-log-token--error";
    }

    if (upper === "WARNING" || upper === "WARN") {
      return "ps-log-token--warn";
    }

    if (upper === "INFO") {
      return "ps-log-token--info";
    }

    if (upper === "DEBUG" || upper === "TRACE") {
      return "ps-log-token--debug";
    }

    if (
      upper === "SUCCESS" ||
      upper === "PASSED" ||
      upper === "PASS" ||
      upper === "OK"
    ) {
      return "ps-log-token--success";
    }

    if (/^5[0-9]{2}$/.test(upper)) {
      return "ps-log-token--error";
    }

    if (/^4[0-9]{2}$/.test(upper)) {
      return "ps-log-token--warn";
    }

    if (/^[23][0-9]{2}$/.test(upper)) {
      return "ps-log-token--success";
    }

    if (/^1[0-9]{2}$/.test(upper)) {
      return "ps-log-token--info";
    }

    return "";
  }

  function colourizeLogText(text) {
    const s = String(text || "");

    if (s.length > MAX_COLOURIZE_CHARS) {
      return core.escapeHtml(s);
    }

    let out = "";
    let lastIndex = 0;

    LOG_TOKEN_RE.lastIndex = 0;

    let match;
    while ((match = LOG_TOKEN_RE.exec(s)) !== null) {
      const token = match[0];
      const cls = tokenClass(token);

      out += core.escapeHtml(s.slice(lastIndex, match.index));

      if (cls) {
        out +=
          '<span class="ps-log-token ' +
          cls +
          '">' +
          core.escapeHtml(token) +
          "</span>";
      } else {
        out += core.escapeHtml(token);
      }

      lastIndex = match.index + token.length;
    }

    out += core.escapeHtml(s.slice(lastIndex));
    return out;
  }

  function applyTextState(root, state, opts) {
    const options = opts || {};
    const pre = root.querySelector("[data-plotsrv-pre='1']");
    if (!pre) return;

    const text = renderedText(state);

    if (state.colourEnabled) {
      pre.innerHTML = colourizeLogText(text);
      pre.classList.add("plotsrv-pre--coloured");
    } else {
      pre.textContent = text;
      pre.classList.remove("plotsrv-pre--coloured");
    }

    pre.classList.toggle("plotsrv-pre--wrap", !!state.wrapEnabled);

    const wrapBtn = root.querySelector("[data-plotsrv-action='wrap']");
    const reverseBtn = root.querySelector("[data-plotsrv-action='reverse']");
    const colourBtn = root.querySelector("[data-plotsrv-action='colour']");

    setButtonActive(wrapBtn, state.wrapEnabled);
    setButtonActive(reverseBtn, state.reverseEnabled);
    setButtonActive(colourBtn, state.colourEnabled);

    syncReverseIndicator(root, state.reverseEnabled);

    if (options.scroll !== false) {
      applyInitialScroll(pre, state);
    }
  }

  function applyInitialScroll(pre, state) {
    const anchor = String(pre.getAttribute("data-plotsrv-text-anchor") || "head");

    if (state.reverseEnabled) {
      pre.scrollTop = 0;
      return;
    }

    if (anchor === "tail") {
      pre.scrollTop = pre.scrollHeight;
      return;
    }

    pre.scrollTop = 0;
  }


  function persistState(state) {
    const nextPrefs = getTextPrefs();
    nextPrefs.wrap_enabled = state.wrapEnabled;
    nextPrefs.reverse_enabled = state.reverseEnabled;
    nextPrefs.colour_enabled = state.colourEnabled;
    saveTextPrefs(nextPrefs);
  }

  function initTextToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="text"]');
    const pre = root.querySelector('[data-plotsrv-pre="1"]');
    if (!toolbar || !pre) return;

    let jumpBtn = root.querySelector("[data-plotsrv-text-jump-bottom='1']");
    
    if (!jumpBtn) {
      jumpBtn = document.createElement("button");
      jumpBtn.type = "button";
      jumpBtn.className = "ps-text-jump-bottom";
      jumpBtn.setAttribute("data-plotsrv-text-jump-bottom", "1");
      jumpBtn.setAttribute("aria-label", "Scroll to bottom");
      jumpBtn.title = "Scroll to bottom";
      jumpBtn.textContent = "↓";
    
      const shell = pre.closest(".ps-text-shell") || pre.parentElement;
      if (shell) {
        shell.appendChild(jumpBtn);
      }
    }
    
    function syncJumpButton() {
      if (!jumpBtn) return;
    
      const thresholdPx = 32;
      const distanceFromBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight;
      const canScroll = pre.scrollHeight > pre.clientHeight + thresholdPx;
      const isAwayFromBottom = distanceFromBottom > thresholdPx;
    
      jumpBtn.hidden = !(canScroll && isAwayFromBottom);
    }
    
    jumpBtn.addEventListener("click", function () {
      pre.scrollTo({
        top: pre.scrollHeight,
        behavior: "smooth",
      });
    });
    
    pre.addEventListener("scroll", syncJumpButton);
    window.addEventListener("resize", syncJumpButton);
    setTimeout(syncJumpButton, 0);

    if (document.body) {
      document.body.classList.add("ps-has-text-artifact");
    }

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const prefs = getTextPrefs();

    const state = {
      originalText: pre.textContent || "",
      wrapEnabled: !!prefs.wrap_enabled,
      reverseEnabled: !!prefs.reverse_enabled,
      colourEnabled: prefs.colour_enabled !== false,
    };

    root._plotsrvTextState = state;

    applyTextState(root, state);
    setTimeout(syncJumpButton, 0);

    toolbar.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";

      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;
        persistState(state);
        applyTextState(root, state, { scroll: false });
        setTimeout(syncJumpButton, 0); 
        return;
      }

      if (action === "reverse") {
        state.reverseEnabled = !state.reverseEnabled;
        persistState(state);
        applyTextState(root, state);
        setTimeout(syncJumpButton, 0);  
        return;
      }

      if (action === "colour") {
        state.colourEnabled = !state.colourEnabled;
        persistState(state);
        applyTextState(root, state, { scroll: false });
        setTimeout(syncJumpButton, 0);  
        return;
      }

      if (action === "copy") {
        const ok = await core.copyTextToClipboard(renderedText(state));
        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(() => {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  }

  renderers.initTextToolbar = initTextToolbar;
})();

/* plotsrv source: js/renderers/code.js */
// src/plotsrv/static/js/renderers/code.js
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
  const config = window.PLOTSRV.config;

  const KEYWORDS = new Set([
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "case",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "match",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
  ]);

  const CONSTANTS = new Set(["True", "False", "None", "Ellipsis", "NotImplemented"]);

  const BUILTINS = new Set([
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "callable",
    "dict",
    "dir",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "open",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
  ]);

  function prefsKey() {
    const viewId = String(config.activeViewId || "default").trim() || "default";
    return "plotsrv:v2:code_prefs:" + viewId;
  }

  function loadCodePrefs() {
    const fallback = {
      wrap_enabled: false,
      highlight_enabled: true,
      line_numbers_enabled: true,
    };

    try {
      const raw = localStorage.getItem(prefsKey());
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      return {
        wrap_enabled:
          typeof parsed.wrap_enabled === "boolean"
            ? parsed.wrap_enabled
            : fallback.wrap_enabled,
        highlight_enabled:
          typeof parsed.highlight_enabled === "boolean"
            ? parsed.highlight_enabled
            : fallback.highlight_enabled,
        line_numbers_enabled:
          typeof parsed.line_numbers_enabled === "boolean"
            ? parsed.line_numbers_enabled
            : fallback.line_numbers_enabled,
      };
    } catch (e) {
      return fallback;
    }
  }

  function saveCodePrefs(prefs) {
    try {
      localStorage.setItem(
        prefsKey(),
        JSON.stringify({
          wrap_enabled: !!(prefs && prefs.wrap_enabled),
          highlight_enabled:
            prefs && typeof prefs.highlight_enabled === "boolean"
              ? prefs.highlight_enabled
              : true,
          line_numbers_enabled:
            prefs && typeof prefs.line_numbers_enabled === "boolean"
              ? prefs.line_numbers_enabled
              : true,
        })
      );
    } catch (e) {
      // ignore
    }
  }

  function escapeHtml(s) {
    if (core && typeof core.escapeHtml === "function") {
      return core.escapeHtml(s);
    }

    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function splitLines(text) {
    const normalised = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = normalised.split("\n");

    if (lines.length > 1 && lines[lines.length - 1] === "") {
      lines.pop();
    }

    return lines.length ? lines : [""];
  }

  function isIdentStart(ch) {
    return /[A-Za-z_]/.test(ch);
  }

  function isIdentPart(ch) {
    return /[A-Za-z0-9_]/.test(ch);
  }

  function consumeString(line, start) {
    const quote = line[start];
    const isTriple =
      line[start + 1] === quote &&
      line[start + 2] === quote;

    let i = start + (isTriple ? 3 : 1);

    while (i < line.length) {
      if (line[i] === "\\") {
        i += 2;
        continue;
      }

      if (isTriple) {
        if (
          line[i] === quote &&
          line[i + 1] === quote &&
          line[i + 2] === quote
        ) {
          return i + 3;
        }
        i += 1;
        continue;
      }

      if (line[i] === quote) {
        return i + 1;
      }

      i += 1;
    }

    return line.length;
  }

  function consumeNumber(line, start) {
    const m = line.slice(start).match(/^(0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d[\d_]*)?j?)/);
    return m ? start + m[0].length : start + 1;
  }

  function highlightPythonLine(line) {
    let out = "";
    let i = 0;

    while (i < line.length) {
      const ch = line[i];

      if (ch === "#") {
        out += '<span class="ps-code-token ps-code-token--comment">' +
          escapeHtml(line.slice(i)) +
          "</span>";
        break;
      }

      if (ch === "'" || ch === '"') {
        const end = consumeString(line, i);
        out += '<span class="ps-code-token ps-code-token--string">' +
          escapeHtml(line.slice(i, end)) +
          "</span>";
        i = end;
        continue;
      }

      if (ch === "@" && isIdentStart(line[i + 1] || "")) {
        let j = i + 1;
        while (j < line.length && isIdentPart(line[j])) j += 1;

        out += '<span class="ps-code-token ps-code-token--decorator">' +
          escapeHtml(line.slice(i, j)) +
          "</span>";
        i = j;
        continue;
      }

      if (/[0-9]/.test(ch)) {
        const end = consumeNumber(line, i);
        out += '<span class="ps-code-token ps-code-token--number">' +
          escapeHtml(line.slice(i, end)) +
          "</span>";
        i = end;
        continue;
      }

      if (isIdentStart(ch)) {
        let j = i + 1;
        while (j < line.length && isIdentPart(line[j])) j += 1;

        const word = line.slice(i, j);
        let klass = "";

        if (KEYWORDS.has(word)) klass = "ps-code-token--keyword";
        else if (CONSTANTS.has(word)) klass = "ps-code-token--constant";
        else if (BUILTINS.has(word)) klass = "ps-code-token--builtin";

        if (klass) {
          out += '<span class="ps-code-token ' + klass + '">' +
            escapeHtml(word) +
            "</span>";
        } else {
          out += escapeHtml(word);
        }

        i = j;
        continue;
      }

      out += escapeHtml(ch);
      i += 1;
    }

    return out;
  }

  function renderCode(root, state) {
    const pre = root.querySelector("[data-plotsrv-code-pre='1']");
    const code = root.querySelector("[data-plotsrv-code-content='1']");
    if (!pre || !code) return;

    const lines = splitLines(state.originalText);
    const parts = [];

    for (let i = 0; i < lines.length; i += 1) {
      const rawLine = lines[i];
      const lineHtml = state.highlightEnabled
        ? highlightPythonLine(rawLine)
        : escapeHtml(rawLine);

      parts.push(
        '<span class="ps-code-line" data-line="' +
          String(i + 1) +
          '"><span class="ps-code-line__num">' +
          String(i + 1) +
          '</span><span class="ps-code-line__text">' +
          lineHtml +
          "</span></span>"
      );
    }

    code.innerHTML = parts.join("");
    pre.classList.toggle("ps-code-pre--wrap", !!state.wrapEnabled);
    pre.classList.toggle(
      "ps-code-pre--no-lines",
      !state.lineNumbersEnabled
    );

    setButtonState(
      root.querySelector("[data-plotsrv-code-action='wrap']"),
      state.wrapEnabled
    );
    setButtonState(
      root.querySelector("[data-plotsrv-code-action='highlight']"),
      state.highlightEnabled
    );
    setButtonState(
      root.querySelector("[data-plotsrv-code-action='lines']"),
      state.lineNumbersEnabled
    );
  }

  function setButtonState(btn, active) {
    if (!btn) return;
    btn.classList.toggle("is-active", !!active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function initCodeToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="code"]');
    const pre = root.querySelector("[data-plotsrv-code-pre='1']");
    const code = root.querySelector("[data-plotsrv-code-content='1']");

    if (!toolbar || !pre || !code) return;

    if (document.body) {
      document.body.classList.add("ps-has-code-artifact");
    }

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const prefs = loadCodePrefs();

    const state = {
      originalText: code.textContent || "",
      wrapEnabled: !!prefs.wrap_enabled,
      highlightEnabled: !!prefs.highlight_enabled,
      lineNumbersEnabled: !!prefs.line_numbers_enabled,
    };

    root._plotsrvCodeState = state;
    renderCode(root, state);

    toolbar.addEventListener("click", async function (ev) {
      const btn =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-plotsrv-code-action]")
          : null;

      if (!btn) return;

      const action = String(btn.getAttribute("data-plotsrv-code-action") || "");

      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "highlight") {
        state.highlightEnabled = !state.highlightEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "lines") {
        state.lineNumbersEnabled = !state.lineNumbersEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "copy") {
        const ok =
          core && typeof core.copyTextToClipboard === "function"
            ? await core.copyTextToClipboard(state.originalText)
            : false;

        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(function () {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  }

  renderers.initCodeToolbar = initCodeToolbar;
})();

/* plotsrv source: js/core/app.js */
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

  function reloadCurrentViewNow() {
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
  }

  core.reloadCurrentView = function () {
    if (state.reloadCurrentViewPromise) {
      return state.reloadCurrentViewPromise;
    }

    if (document.hidden) {
      return Promise.resolve();
    }

    const refreshPromise = Promise.resolve().then(reloadCurrentViewNow);
    state.reloadCurrentViewPromise = refreshPromise;

    function clearInFlight() {
      if (state.reloadCurrentViewPromise === refreshPromise) {
        state.reloadCurrentViewPromise = null;
      }
    }

    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
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

