// src/plotsrv/static/plotsrv.js
(function () {
  "use strict";

  // This object is injected by html.py
  const CFG = window.PLOTSRV_CONFIG || {};
  const ACTIVE_VIEW = CFG.active_view_id || "default";
  const max_table_rows_rich = CFG.max_table_rows_rich || 1000;

  const LS_AUTO_ENABLED = "plotsrv:auto_refresh_enabled";
  const LS_AUTO_INTERVAL = "plotsrv:auto_refresh_interval";

  // Phase 1 local storage keys
  const LS_TEXT_WRAP = "plotsrv:text_wrap_enabled"; // global (simple for now)
  const LS_JSON_FIND = "plotsrv:json_find_query";   // remember last query

  let _autoRefreshTimer = null;
  let _tabulatorInstance = null;

  function _saveAutoRefreshState() {
    const toggle = document.getElementById("auto-refresh-toggle");
    const interval = document.getElementById("auto-refresh-interval");
    if (toggle) localStorage.setItem(LS_AUTO_ENABLED, toggle.checked ? "1" : "0");
    if (interval) localStorage.setItem(LS_AUTO_INTERVAL, String(interval.value || "5"));
  }

  function _getAutoRefreshMs() {
    const sel = document.getElementById("auto-refresh-interval");
    if (!sel) return 5000;
    const seconds = Number(sel.value || 5);
    return Math.max(1, seconds) * 1000;
  }

  function _stopAutoRefresh() {
    if (_autoRefreshTimer !== null) {
      clearInterval(_autoRefreshTimer);
      _autoRefreshTimer = null;
    }
  }

  function _startAutoRefresh() {
    _stopAutoRefresh();
    const ms = _getAutoRefreshMs();
    _autoRefreshTimer = setInterval(_tickAutoRefresh, ms);
  }

  function _restoreAutoRefreshState() {
    const toggle = document.getElementById("auto-refresh-toggle");
    const interval = document.getElementById("auto-refresh-interval");

    if (interval) {
      const savedInterval = localStorage.getItem(LS_AUTO_INTERVAL);
      if (savedInterval) interval.value = savedInterval;
    }

    if (toggle) {
      const savedEnabled = localStorage.getItem(LS_AUTO_ENABLED);
      if (savedEnabled === "1") {
        toggle.checked = true;
        _tickAutoRefresh();
        _startAutoRefresh();
      }
    }
  }

  function _fmtLocalTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  }

  function _fmtAgo(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 0) return "";
    if (s < 60) return "(" + s + "s ago)";
    const m = Math.floor(s / 60);
    if (m < 60) return "(" + m + "m ago)";
    const h = Math.floor(m / 60);
    return "(" + h + "h ago)";
  }

  async function refreshStatus() {
    try {
      const res = await fetch("/status?view=" + encodeURIComponent(ACTIVE_VIEW) + "&_ts=" + Date.now());
      if (!res.ok) return;
      const s = await res.json();

      const updated = document.getElementById("status-updated");
      const updatedAgo = document.getElementById("status-updated-ago");
      const duration = document.getElementById("status-duration");
      const errWrap = document.getElementById("status-error-wrap");
      const err = document.getElementById("status-error");

      const mode = document.getElementById("status-mode");
      const srvRate = document.getElementById("status-srv-refresh");

      if (updated) updated.textContent = _fmtLocalTime(s.last_updated);
      if (updatedAgo) updatedAgo.textContent = _fmtAgo(s.last_updated);

      if (duration) {
        duration.textContent = s.last_duration_s == null ? "—" : Number(s.last_duration_s).toFixed(3) + "s";
      }

      if (errWrap && err) {
        if (s.last_error) {
          err.textContent = s.last_error;
          errWrap.style.display = "inline";
        } else {
          err.textContent = "";
          errWrap.style.display = "none";
        }
      }

      if (mode) mode.textContent = s.service_mode ? "service" : "interactive";

      if (srvRate) {
        if (s.service_mode && s.service_refresh_rate_s) {
          srvRate.textContent = "every " + s.service_refresh_rate_s + "s";
        } else if (s.service_mode) {
          srvRate.textContent = "once";
        } else {
          srvRate.textContent = "—";
        }
      }
    } catch (e) {
      // ignore
    }
  }

  function refreshPlot() {
    const img = document.getElementById("plot");
    if (!img) return;
    img.src = "/plot?view=" + encodeURIComponent(ACTIVE_VIEW) + "&_ts=" + Date.now();
    refreshStatus();
  }

  function exportImage() {
    window.location.href = "/plot?view=" + encodeURIComponent(ACTIVE_VIEW) + "&download=1&_ts=" + Date.now();
  }

  function exportTable() {
    window.location.href =
      "/table/export?view=" + encodeURIComponent(ACTIVE_VIEW) + "&format=csv&_ts=" + Date.now();
  }

  function terminateServer() {
    fetch("/shutdown", { method: "POST" })
      .then(() => {
        const status = document.getElementById("status");
        if (status) status.textContent = "plotsrv is shutting down…";
      })
      .catch(() => {
        const status = document.getElementById("status");
        if (status) status.textContent = "Failed to contact server (it may already be down).";
      });
  }

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    if (!grid) return;

    const res = await fetch("/table/data?view=" + encodeURIComponent(ACTIVE_VIEW) + "&_ts=" + Date.now());
    if (!res.ok) {
      console.error("Failed to load table data");
      return;
    }

    const data = await res.json();

    const status = document.getElementById("status");
    if (status) {
      const total = Number(data.total_rows ?? 0);
      const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

      if (total > 0 && returned > 0) {
        const isTrunc = returned < total;
        status.innerHTML =
          `Showing ${returned} of ${total} rows (rich table mode).` +
          (isTrunc
            ? ` <span class="badge" title="This view is showing a sampled subset of the full data.">TRUNCATED</span>`
            : "");
      } else {
        status.textContent = `Showing up to ${max_table_rows_rich} rows (rich table mode).`;
      }
    }

    const columns = (data.columns || []).map((col) => ({ title: col, field: col }));
    const rows = data.rows || [];

    if (_tabulatorInstance) {
      _tabulatorInstance.setColumns(columns);
      _tabulatorInstance.replaceData(rows);
      return;
    }

    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      return;
    }

    _tabulatorInstance = new Tabulator("#table-grid", {
      data: rows,
      columns: columns,
      height: "600px",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 20,
      paginationSizeSelector: [10, 20, 50, 100],
      movableColumns: true,
    });
  }

  function _tickAutoRefresh() {
    const img = document.getElementById("plot");
    if (img) {
      refreshPlot();
      return;
    }

    if (document.getElementById("artifact-root")) {
      loadArtifact().then(() => refreshStatus());
      return;
    }

    if (document.getElementById("table-grid")) {
      loadTable().then(() => refreshStatus());
      return;
    }

    refreshStatus();
  }

  function _bindAutoRefreshControls() {
    const toggle = document.getElementById("auto-refresh-toggle");
    const interval = document.getElementById("auto-refresh-interval");
    if (!toggle) return;

    toggle.addEventListener("change", function () {
      _saveAutoRefreshState();
      if (toggle.checked) {
        _tickAutoRefresh();
        _startAutoRefresh();
      } else {
        _stopAutoRefresh();
      }
    });

    if (interval) {
      interval.addEventListener("change", function () {
        _saveAutoRefreshState();
        if (toggle.checked) _startAutoRefresh();
      });
    }
  }

  function _bindViewDropdown() {
    const sel = document.getElementById("view-select");
    if (!sel) return;

    sel.addEventListener("change", function () {
      _saveAutoRefreshState();
      const v = sel.value;
      window.location.href = "/?view=" + encodeURIComponent(v);
    });
  }

  function _escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function _renderTruncationBadge(trunc) {
    const el = document.getElementById("artifact-truncation");
    if (!el) return;

    if (!trunc || !trunc.truncated) {
      el.innerHTML = "";
      return;
    }

    const reason = trunc.reason ? " — " + _escapeHtml(trunc.reason) : "";
    let details = "";

    // If details is an object, try to show a compact single-line summary.
    if (trunc.details && typeof trunc.details === "object") {
      try {
        const parts = [];
        for (const [k, v] of Object.entries(trunc.details)) {
          if (v == null) continue;
          if (typeof v === "object") continue;
          parts.push(`${k}=${v}`);
          if (parts.length >= 4) break;
        }
        if (parts.length) details = " (" + _escapeHtml(parts.join(", ")) + ")";
      } catch (e) {
        // ignore
      }
    } else if (typeof trunc.details === "string") {
      details = " (" + _escapeHtml(trunc.details) + ")";
    }

    el.innerHTML =
      `<span class="badge">TRUNCATED</span>` +
      `<span class="note" style="margin-left:0.35rem;">${reason}${details}</span>`;
  }

  // ---------------------------------------------------------------------------
  // Phase 1: Artifact UX enhancements (text + json)
  // ---------------------------------------------------------------------------

  function _findNearest(el, selector) {
    if (!el) return null;
    if (el.closest) return el.closest(selector);
    return null;
  }

  async function _copyTextToClipboard(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {
      // fall back below
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
  }

  function _initTextToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="text"]');
    const pre = root.querySelector('[data-plotsrv-pre="1"]');
    if (!toolbar || !pre) return;

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    // Restore wrap state
    const wrapEnabled = localStorage.getItem(LS_TEXT_WRAP) === "1";
    if (wrapEnabled) pre.classList.add("plotsrv-pre--wrap");

    toolbar.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";
      if (action === "wrap") {
        pre.classList.toggle("plotsrv-pre--wrap");
        localStorage.setItem(LS_TEXT_WRAP, pre.classList.contains("plotsrv-pre--wrap") ? "1" : "0");
        return;
      }

      if (action === "copy") {
        const ok = await _copyTextToClipboard(pre.textContent || "");
        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(() => {
          btn.textContent = "Copy";
        }, 900);
        return;
      }
    });
  }

  function _clearJsonHits(tree) {
    const hits = tree.querySelectorAll(".json-hit, .json-hit-current");
    hits.forEach((el) => {
      el.classList.remove("json-hit");
      el.classList.remove("json-hit-current");
    });
  }

  function _initJsonToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const tree = root.querySelector('[data-plotsrv-json="1"]');
    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");
    if (!toolbar || !tree || !input) return;

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const state = {
      hits: [],
      idx: -1,
    };

    function _setCounter() {
      if (!countEl) return;
      if (!state.hits.length) {
        countEl.textContent = "";
        return;
      }
      countEl.textContent = `${state.idx + 1}/${state.hits.length}`;
    }

    function _openParents(el) {
      let cur = el;
      while (cur) {
        const det = _findNearest(cur, "details");
        if (!det) break;
        det.open = true;
        cur = det.parentElement;
      }
    }

    function _goto(i) {
      if (!state.hits.length) return;

      state.hits.forEach((el) => el.classList.remove("json-hit-current"));
      state.idx = (i + state.hits.length) % state.hits.length;

      const el = state.hits[state.idx];
      el.classList.add("json-hit-current");
      _openParents(el);
      try {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch (e) {
        el.scrollIntoView();
      }
      _setCounter();
    }

    function _runFind() {
      const q = String(input.value || "").trim();
      localStorage.setItem(LS_JSON_FIND, q);

      _clearJsonHits(tree);
      state.hits = [];
      state.idx = -1;
      _setCounter();

      if (!q) return;

      const qLower = q.toLowerCase();
      const candidates = tree.querySelectorAll("[data-json-text]");
      candidates.forEach((el) => {
        const t = (el.getAttribute("data-json-text") || "").toLowerCase();
        if (!t) return;
        if (t.includes(qLower)) {
          el.classList.add("json-hit");
          state.hits.push(el);
        }
      });

      if (state.hits.length) _goto(0);
    }

    // Restore last query
    const saved = localStorage.getItem(LS_JSON_FIND);
    if (saved && !input.value) input.value = saved;

    // Initial find if there is a saved query
    if (String(input.value || "").trim()) _runFind();

    toolbar.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";
      if (action === "find-next") {
        if (!state.hits.length) _runFind();
        if (state.hits.length) _goto(state.idx + 1);
        return;
      }
      if (action === "find-prev") {
        if (!state.hits.length) _runFind();
        if (state.hits.length) _goto(state.idx - 1);
        return;
      }
    });

    input.addEventListener("input", function () {
      // light debounce
      if (input._plotsrvTimer) clearTimeout(input._plotsrvTimer);
      input._plotsrvTimer = setTimeout(_runFind, 120);
    });

    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (!state.hits.length) _runFind();
        if (state.hits.length) _goto(state.idx + 1);
      }
    });
  }

  function _initArtifactEnhancements(root) {
    if (!root) return;
    _initTextToolbar(root);
    _initJsonToolbar(root);
  }

  // ---------------------------------------------------------------------------
  // Artifact loading
  // ---------------------------------------------------------------------------

  async function loadArtifact() {
    const root = document.getElementById("artifact-root");
    if (!root) return;

    try {
      const res = await fetch("/artifact?view=" + encodeURIComponent(ACTIVE_VIEW) + "&_ts=" + Date.now());
      if (!res.ok) {
        root.innerHTML = `<div class="note">Failed to load artifact (${res.status}).</div>`;
        _renderTruncationBadge(null);
        return;
      }

      const data = await res.json();

      const kindEl = document.getElementById("artifact-kind");
      if (kindEl) kindEl.textContent = data.kind ? "Kind: " + data.kind : "";

      root.innerHTML = data.html || "";
      _renderTruncationBadge(data.truncation || null);

      // bind toolbars etc
      _initArtifactEnhancements(root);

      // if artifact renders a table placeholder, ensure data loads
      if (document.getElementById("table-grid")) {
        await loadTable();
      }
    } catch (e) {
      root.innerHTML = `<div class="note">Failed to load artifact (network error).</div>`;
      _renderTruncationBadge(null);
    }
  }

  function refreshArtifact() {
    loadArtifact().then(() => refreshStatus());
  }

  // Expose functions used by inline onclick handlers
  window.refreshPlot = refreshPlot;
  window.exportImage = exportImage;
  window.exportTable = exportTable;
  window.terminateServer = terminateServer;
  window.refreshArtifact = refreshArtifact;

  document.addEventListener("DOMContentLoaded", function () {
    refreshStatus();

    if (document.getElementById("artifact-root")) {
      loadArtifact().then(() => refreshStatus());
    } else if (document.getElementById("table-grid")) {
      loadTable().then(() => refreshStatus());
    }

    _bindAutoRefreshControls();
    _bindViewDropdown();
    _restoreAutoRefreshState();
  });
})();
