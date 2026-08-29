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

        if (typeof core.disposeEmbeddedTableExplorer === "function") {
          core.disposeEmbeddedTableExplorer();
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
      
      if (typeof core.disposeEmbeddedTableExplorer === "function") {
        core.disposeEmbeddedTableExplorer();
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
      if (typeof core.disposeEmbeddedTableExplorer === "function") {
        core.disposeEmbeddedTableExplorer();
      }
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

  function getIframeExportHtml(root) {
    if (!root) return "";
    const iframe = root.querySelector(
      ".plotsrv-html-iframe, .plotsrv-markdown-iframe"
    );
    if (!iframe) return "";
    return String(iframe.getAttribute("srcdoc") || "");
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

  function exportEmbeddedImage(root, base, stamp) {
    if (!root) return false;
    const image = root.querySelector('img[src^="data:image/"]');
    if (!image) return false;
    const source = String(image.getAttribute("src") || "");
    const match = /^data:image\/([^;,]+)/i.exec(source);
    if (!match) return false;
    const subtype = match[1].toLowerCase();
    const extension = {
      "svg+xml": "svg",
      jpeg: "jpg",
      jpg: "jpg",
    }[subtype] || subtype;
    const a = document.createElement("a");
    a.href = source;
    a.download = base + "-" + stamp + "." + extension;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return true;
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
      return true;
    }

    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "artifact").replace(/[^\w.-]+/g, "_");
    if (exportEmbeddedImage(root, base, stamp)) return true;

    const iframeHtml = getIframeExportHtml(root);
    if (iframeHtml) {
      downloadTextFile(base + "-" + stamp + ".html", iframeHtml);
      return true;
    }

    const text = getArtifactExportText();
    if (!text) return false;
    const filename = base + "-" + stamp + ".txt";
    downloadTextFile(filename, text);
    return true;
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
