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

  async function refreshViewIcons() {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (!wrap) return;

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
    } catch (e) {
      // ignore
    }
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

  async function refreshStatus() {
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

      if (errWrap && err) {
        if (s.last_error) {
          err.textContent = s.last_error;
          errWrap.style.display = "inline";
        } else {
          err.textContent = "";
          errWrap.style.display = "none";
        }
      }

      refreshViewIcons();
    } catch (e) {
      // ignore
    }
  }

  core.fmtLocalTime = fmtLocalTime;
  core.fmtAgo = fmtAgo;
  core.formatAgeShort = formatAgeShort;
  core.setStatusMessage = setStatusMessage;
  core.clearPlotObjectUrl = clearPlotObjectUrl;
  core.refreshViewIcons = refreshViewIcons;
  core.refreshStatus = refreshStatus;
})();
