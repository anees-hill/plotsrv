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
    const isHistory = isHistoryMode();

    if (sel) {
      sel.value = state.currentSnapshot || "";
    }

    const snapshotWrap = document.getElementById("snapshots-control");
    const unavailableReturn = document.getElementById("snapshots-return-latest");
    if (unavailableReturn) {
      unavailableReturn.hidden =
        !isHistory || !snapshotWrap || snapshotWrap.dataset.state === "enabled";
    }

    if (typeof core.setHeaderViewState === "function") {
      const meta = currentHistoryMeta();
      core.setHeaderViewState(
        isHistory ? "snapshot" : "latest",
        isHistory
          ? {
              id: state.currentSnapshot,
              createdAt: meta && meta.created_at ? meta.created_at : null,
            }
          : null
      );
    }

    if (document.body) {
      document.body.classList.toggle("ps-is-history", isHistory);
    }

    if (typeof core.syncAutoRefreshAvailability === "function") {
      core.syncAutoRefreshAvailability();
    }
  }

  function setSnapshotControlState(capability, snapshots, failed) {
    const wrap = document.getElementById("snapshots-control");
    const selector = document.getElementById("snapshots-selector");
    const unavailable = document.getElementById("snapshots-unavailable");
    const reason = document.getElementById("snapshots-unavailable-reason");
    const returnLatest = document.getElementById("snapshots-return-latest");
    const sel = document.getElementById("history-select");
    if (!wrap || !selector || !unavailable || !reason || !sel) return;

    const usable = !failed && (!capability || capability.enabled === true);
    wrap.dataset.state = failed ? "error" : usable ? "enabled" : "unavailable";
    selector.hidden = !usable;
    unavailable.hidden = usable;
    if (returnLatest) returnLatest.hidden = usable || !state.currentSnapshot;

    if (!usable) {
      sel.disabled = true;
      reason.textContent = failed
        ? "Snapshot availability could not be loaded."
        : String(
            (capability && capability.message) ||
              "Snapshots are unavailable for this view."
          );
      return;
    }

    sel.disabled = snapshots.length === 0;
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
      const capability =
        data.capability && typeof data.capability === "object"
          ? data.capability
          : null;
      state.historyItems = snapshots;
      state.snapshotCapability = capability;

      const parts = [];

      if (snapshots.length === 0) {
        parts.push('<option value="">No snapshots yet</option>');
      } else {
        parts.push('<option value="">Live (latest)</option>');
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
          const missingSnapshot = state.currentSnapshot;
          state.currentSnapshot = null;
          writeSnapshotToUrl(null);
          state.pendingSnapshotNotice =
            '<span class="badge">SNAPSHOT DELETED</span> ' +
            "Selected snapshot " +
            core.escapeHtml(missingSnapshot) +
            " is no longer available. Showing latest data.";
        }
      }

      setSnapshotControlState(capability, snapshots, false);
      sel.value = state.currentSnapshot || "";
      syncHistoryUi();
    } catch (e) {
      sel.innerHTML = '<option value="">Snapshots unavailable</option>';
      state.historyItems = [];
      state.snapshotCapability = null;
      setSnapshotControlState(null, [], true);
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

    const returnLatest = document.getElementById("snapshots-return-latest");
    if (returnLatest) {
      returnLatest.addEventListener("click", returnToLive);
    }
  }

  function showPendingSnapshotNotice() {
    if (!state.pendingSnapshotNotice) return;
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage(state.pendingSnapshotNotice);
    }
    state.pendingSnapshotNotice = null;
  }

  core.writeSnapshotToUrl = writeSnapshotToUrl;
  core.snapshotQuery = snapshotQuery;
  core.isHistoryMode = isHistoryMode;
  core.currentHistoryMeta = currentHistoryMeta;
  core.syncHistoryUi = syncHistoryUi;
  core.loadHistory = loadHistory;
  core.handleMissingSnapshot = handleMissingSnapshot;
  core.bindHistoryControls = bindHistoryControls;
  core.showPendingSnapshotNotice = showPendingSnapshotNotice;
  core.returnToLive = returnToLive;

  window.returnToLive = returnToLive;
})();
