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
      const res = await fetch(
        "/artifact?view=" +
          encodeURIComponent(config.activeViewId) +
          snapshotQuery +
          "&_ts=" +
          Date.now()
      );

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

  core.renderTruncationBadge = renderTruncationBadge;
  core.loadArtifact = loadArtifact;
  core.refreshArtifact = refreshArtifact;
  core.terminateServer = terminateServer;

  window.refreshArtifact = refreshArtifact;
  window.terminateServer = terminateServer;
})();