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
          parts.push(`${k}=${v}`);
          if (parts.length >= 4) break;
        }
        if (parts.length) details = " (" + core.escapeHtml(parts.join(", ")) + ")";
      } catch (e) {
        // ignore
      }
    } else if (typeof trunc.details === "string") {
      details = " (" + core.escapeHtml(trunc.details) + ")";
    }

    el.innerHTML =
      '<span class="badge">TRUNCATED</span>' +
      `<span class="note" style="margin-left:0.35rem;">${reason}${details}</span>`;
  }

  function initArtifactEnhancements(root) {
    if (!root) return;

    if (typeof renderers.initTextToolbar === "function") {
      renderers.initTextToolbar(root);
    }

    if (typeof renderers.initJsonToolbar === "function") {
      renderers.initJsonToolbar(root);
    }

    if (typeof renderers.initCodeToolbar === "function") {
      renderers.initCodeToolbar(root);
    }
  }

  async function loadArtifact() {
    const root = document.getElementById("artifact-root");
    if (!root) return;

    try {
      const res = await fetch(
        "/artifact?view=" +
          encodeURIComponent(core.getActiveViewId()) +
          core.snapshotQuery() +
          "&_ts=" +
          Date.now()
      );

      if (!res.ok) {
        if (res.status === 404 && core.isHistoryMode()) {
          if (typeof core.handleMissingSnapshot === "function") {
            await core.handleMissingSnapshot("artifact");
          }
          return;
        }
        root.innerHTML = `<div class="note">Failed to load artifact (${res.status}).</div>`;
        renderTruncationBadge(null);
        return;
      }

      const data = await res.json();

      const kindEl = document.getElementById("artifact-kind");
      if (kindEl) {
        const prefix = data.kind ? "Kind: " + data.kind : "";
        kindEl.textContent = core.isHistoryMode() ? prefix + " · snapshot" : prefix;
      }

      root.innerHTML = data.html || "";
      renderTruncationBadge(data.truncation || null);
      initArtifactEnhancements(root);

      if (
        document.getElementById("table-grid") &&
        typeof renderers.loadTable === "function"
      ) {
        await renderers.loadTable();
      }
    } catch (e) {
      root.innerHTML = '<div class="note">Failed to load artifact (network error).</div>';
      renderTruncationBadge(null);
    }
  }

  function refreshArtifact() {
    loadArtifact().then(() => {
      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
    });
  }

  renderers.renderTruncationBadge = renderTruncationBadge;
  renderers.initArtifactEnhancements = initArtifactEnhancements;
  renderers.loadArtifact = loadArtifact;
  renderers.refreshArtifact = refreshArtifact;

  window.refreshArtifact = refreshArtifact;
})();