// src/plotsrv/static/plotsrv.js
(function () {
  "use strict";

  // This object is injected by html.py
  const CFG = window.PLOTSRV_CONFIG || {};
  const ACTIVE_VIEW = CFG.active_view_id || "default";
  const max_table_rows_rich = CFG.max_table_rows_rich || 1000;

  const LS_AUTO_ENABLED = "plotsrv:auto_refresh_enabled";
  const LS_AUTO_INTERVAL = "plotsrv:auto_refresh_interval";

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
      const res = await fetch(
        "/status?view=" + encodeURIComponent(ACTIVE_VIEW) + "&_ts=" + Date.now()
      );
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
        duration.textContent =
          s.last_duration_s == null ? "—" : Number(s.last_duration_s).toFixed(3) + "s";
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

      if (mode) {
        mode.textContent = s.service_mode ? "service" : "interactive";
      }

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
    window.location.href =
      "/plot?view=" + encodeURIComponent(ACTIVE_VIEW) + "&download=1&_ts=" + Date.now();
  }

  function exportTable() {
    window.location.href =
      "/table/export?view=" +
      encodeURIComponent(ACTIVE_VIEW) +
      "&format=csv&_ts=" +
      Date.now();
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

    const res = await fetch(
      "/table/data?view=" + encodeURIComponent(ACTIVE_VIEW) + "&_ts=" + Date.now()
    );
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
    const details = trunc.details ? " (" + _escapeHtml(trunc.details) + ")" : "";
    el.innerHTML =
      `<span class="badge">TRUNCATED</span>` +
      `<span class="note" style="margin-left:0.35rem;">${reason}${details}</span>`;
  }

  async function loadArtifact() {
    const root = document.getElementById("artifact-root");
    if (!root) return;

    try {
      const res = await fetch(
        "/artifact?view=" + encodeURIComponent(ACTIVE_VIEW) + "&_ts=" + Date.now()
      );
      if (!res.ok) {
        root.innerHTML = `<div class="note">Failed to load artifact (${res.status}).</div>`;
        _renderTruncationBadge(null);
        return;
      }

      const data = await res.json();

      const kindEl = document.getElementById("artifact-kind");
      if (kindEl) {
        kindEl.textContent = data.kind ? "Kind: " + data.kind : "";
      }

      root.innerHTML = data.html || "";
      _renderTruncationBadge(data.truncation || null);

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
