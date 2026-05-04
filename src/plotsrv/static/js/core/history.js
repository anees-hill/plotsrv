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
      parts.push('<option value="">Live (latest)</option>');

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
          const kind = snap.kind ? " · " + core.escapeHtml(snap.kind) : "";
          parts.push(
            '<option value="' +
              core.escapeHtml(snap.snapshot_id) +
              '">' +
              core.escapeHtml(ts) +
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
        '<option value="">Live (latest)</option>' +
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