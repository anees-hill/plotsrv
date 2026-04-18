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

  async function handleMissingSnapshot(kindLabel) {
    const msg =
      "Selected snapshot is no longer available and may have been pruned by storage policy.";

    if (document.getElementById("artifact-root")) {
      const root = document.getElementById("artifact-root");
      if (root) {
        root.innerHTML = `<div class="note">Snapshot deleted. ${core.escapeHtml(msg)}</div>`;
      }
    }

    if (document.getElementById("table-grid")) {
      core.setStatusMessage(
        `<span class="badge">SNAPSHOT DELETED</span> ${core.escapeHtml(msg)}`
      );
    }

    if (document.getElementById("plot")) {
      const img = document.getElementById("plot");
      if (img) {
        img.removeAttribute("src");
        img.alt = "Snapshot deleted";
      }
      core.setStatusMessage(
        `<span class="badge">SNAPSHOT DELETED</span> ${core.escapeHtml(msg)}`
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

  function setHistoryBanner() {
    const banner = document.getElementById("history-banner");
    const text = document.getElementById("history-banner-text");
    const body = document.body;

    if (!banner || !text || !body) return;

    if (!core.isHistoryMode()) {
      banner.hidden = true;
      body.classList.remove("ps-is-history");
      return;
    }

    const meta = core.currentHistoryMeta();
    const when =
      meta && meta.created_at
        ? core.fmtLocalTime(meta.created_at)
        : core.getCurrentSnapshot();

    text.textContent = "Viewing stored snapshot from " + when + ". Live updates are paused.";
    banner.hidden = false;
    body.classList.add("ps-is-history");
  }

  function syncHistoryControls() {
    const sel = document.getElementById("history-select");

    if (sel) {
      const value = core.getCurrentSnapshot() || "";
      if (sel.value !== value) sel.value = value;
    }

    setHistoryBanner();

    if (typeof core.syncAutoRefreshAvailability === "function") {
      core.syncAutoRefreshAvailability();
    }
  }

  function reloadCurrentView() {
    if (document.getElementById("artifact-root")) {
      if (typeof renderers.loadArtifact === "function") {
        renderers.loadArtifact().then(() => {
          if (typeof core.refreshStatus === "function") core.refreshStatus();
        });
      }
      return;
    }

    if (document.getElementById("table-grid")) {
      if (typeof renderers.loadTable === "function") {
        renderers.loadTable().then(() => {
          if (typeof core.refreshStatus === "function") core.refreshStatus();
        });
      }
      return;
    }

    if (document.getElementById("plot")) {
      if (typeof renderers.refreshPlot === "function") {
        renderers.refreshPlot();
      }
      return;
    }

    if (typeof core.refreshStatus === "function") {
      core.refreshStatus();
    }
  }

  function returnToLive() {
    core.setCurrentSnapshot(null);
    core.writeSnapshotToUrl(null);
    syncHistoryControls();
    reloadCurrentView();
  }

  async function loadHistory() {
    const sel = document.getElementById("history-select");
    if (!sel) return;

    try {
      const res = await fetch(
        "/history?view=" + encodeURIComponent(core.getActiveViewId()) + "&_ts=" + Date.now()
      );
      if (!res.ok) throw new Error("history fetch failed");

      const data = await res.json();
      const snapshots = Array.isArray(data.snapshots) ? data.snapshots : [];
      core.setHistoryItems(snapshots);

      const parts = [];
      parts.push('<option value="">Live (latest)</option>');

      if (snapshots.length === 0) {
        parts.push('<option value="__none__" disabled>No previous entries</option>');
      } else {
        for (const snap of snapshots) {
          const ts = snap.created_at
            ? core.fmtLocalTime(snap.created_at)
            : snap.snapshot_id;
          const kind = snap.kind ? ` · ${core.escapeHtml(snap.kind)}` : "";
          parts.push(
            `<option value="${core.escapeHtml(snap.snapshot_id)}">${core.escapeHtml(ts)}${kind}</option>`
          );
        }
      }

      sel.innerHTML = parts.join("");

      if (core.getCurrentSnapshot()) {
        const exists = snapshots.some((x) => x.snapshot_id === core.getCurrentSnapshot());
        if (!exists) core.setCurrentSnapshot(null);
      }

      sel.value = core.getCurrentSnapshot() || "";
      syncHistoryControls();
    } catch (e) {
      sel.innerHTML =
        '<option value="">Live (latest)</option><option value="__err__" disabled>History unavailable</option>';
      core.setHistoryItems([]);
      syncHistoryControls();
    }
  }

  function bindHistoryControls() {
    const sel = document.getElementById("history-select");
    if (!sel) return;

    sel.addEventListener("change", function () {
      const value = String(sel.value || "");
      core.setCurrentSnapshot(value ? value : null);
      core.writeSnapshotToUrl(core.getCurrentSnapshot());
      syncHistoryControls();
      reloadCurrentView();
    });
  }

  core.handleMissingSnapshot = handleMissingSnapshot;
  core.setHistoryBanner = setHistoryBanner;
  core.syncHistoryControls = syncHistoryControls;
  core.reloadCurrentView = reloadCurrentView;
  core.loadHistory = loadHistory;
  core.bindHistoryControls = bindHistoryControls;
  core.returnToLive = returnToLive;

  window.returnToLive = returnToLive;
})();