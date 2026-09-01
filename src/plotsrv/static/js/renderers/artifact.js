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

  function getScrollMetrics(target) {
    if (target === window) {
      const scrollingElement = document.scrollingElement || document.documentElement;
      return {
        top: window.scrollY || scrollingElement.scrollTop || 0,
        viewport: window.innerHeight || document.documentElement.clientHeight || 0,
        extent: scrollingElement.scrollHeight || 0,
      };
    }
    return {
      top: target.scrollTop || 0,
      viewport: target.clientHeight || 0,
      extent: target.scrollHeight || 0,
    };
  }

  function scrollToEdge(target, edge) {
    const top = edge === "top" ? 0 : getScrollMetrics(target).extent;
    if (target === window) {
      window.scrollTo({ top: top, behavior: "smooth" });
    } else {
      target.scrollTo({ top: top, behavior: "smooth" });
    }
  }

  function disposeArtifactScrollNav() {
    const cleanup = core._artifactScrollNavCleanup;
    if (typeof cleanup === "function") cleanup();
    core._artifactScrollNavCleanup = null;
  }

  function initArtifactScrollNav(root) {
    disposeArtifactScrollNav();
    if (!root) return;

    const textTarget = root.querySelector("[data-plotsrv-pre='1']");
    const markdownRawTarget = root.querySelector(".plotsrv-markdown__raw");
    const markdownInline = root.querySelector(".plotsrv-markdown--sanitized");
    const contentTarget = textTarget || markdownRawTarget || markdownInline;
    const target = textTarget || markdownRawTarget || (markdownInline ? window : null);
    if (!target) return;

    const nav = document.createElement("div");
    nav.className = "ps-scroll-nav";
    nav.setAttribute("data-plotsrv-scroll-nav", "1");
    nav.setAttribute("role", "group");
    nav.setAttribute("aria-label", "Document navigation");
    nav.hidden = true;
    nav.innerHTML =
      '<button type="button" data-plotsrv-scroll-edge="top" ' +
      'aria-label="Jump to top" title="Jump to top">↑</button>' +
      '<button type="button" data-plotsrv-scroll-edge="bottom" ' +
      'aria-label="Jump to bottom" title="Jump to bottom">↓</button>';
    root.appendChild(nav);

    const topButton = nav.querySelector("[data-plotsrv-scroll-edge='top']");
    const bottomButton = nav.querySelector("[data-plotsrv-scroll-edge='bottom']");
    let frame = 0;

    function sync() {
      frame = 0;
      const metrics = getScrollMetrics(target);
      const threshold = 24;
      const canScroll = metrics.extent > metrics.viewport + threshold;
      nav.hidden = !canScroll;
      if (topButton) topButton.disabled = !canScroll || metrics.top <= threshold;
      if (bottomButton) {
        bottomButton.disabled =
          !canScroll || metrics.extent - metrics.viewport - metrics.top <= threshold;
      }
    }

    function scheduleSync() {
      if (frame) return;
      frame = window.requestAnimationFrame(sync);
    }

    function onClick(event) {
      const button = event.target.closest("[data-plotsrv-scroll-edge]");
      if (!button || button.disabled) return;
      scrollToEdge(target, button.getAttribute("data-plotsrv-scroll-edge"));
    }

    const scrollSource = target === window ? window : target;
    nav.addEventListener("click", onClick);
    scrollSource.addEventListener("scroll", scheduleSync, { passive: true });
    window.addEventListener("resize", scheduleSync);

    let resizeObserver = null;
    if (typeof window.ResizeObserver === "function") {
      resizeObserver = new window.ResizeObserver(scheduleSync);
      resizeObserver.observe(contentTarget);
    }

    let mutationObserver = null;
    if (typeof window.MutationObserver === "function") {
      mutationObserver = new window.MutationObserver(scheduleSync);
      mutationObserver.observe(contentTarget, {
        attributes: true,
        childList: true,
        characterData: true,
        subtree: true,
      });
    }

    core._artifactScrollNavCleanup = function () {
      if (frame) window.cancelAnimationFrame(frame);
      nav.removeEventListener("click", onClick);
      scrollSource.removeEventListener("scroll", scheduleSync);
      window.removeEventListener("resize", scheduleSync);
      if (resizeObserver) resizeObserver.disconnect();
      if (mutationObserver) mutationObserver.disconnect();
      if (nav.parentNode) nav.parentNode.removeChild(nav);
    };
    scheduleSync();
  }

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

    disposeArtifactScrollNav();

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

  core.initArtifactScrollNav = initArtifactScrollNav;
  core.disposeArtifactScrollNav = disposeArtifactScrollNav;

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
