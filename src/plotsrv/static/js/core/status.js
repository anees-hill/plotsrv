(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  const ICONS = {
    unknown: "/static/logo_unknown.png",
    plot: "/static/logo_plot.png",
    table: "/static/logo_table.png",
    image: "/static/logo_image.png",
    markdown: "/static/logo_markdown.png",
    json: "/static/logo_json.png",
    python: "/static/logo_python.png",
    exception: "/static/logo_exception.png",
    text: "/static/logo_txt.png",
    html: "/static/logo_html.png",
  };

  function formatAgeShort(totalSeconds) {
    if (
      typeof totalSeconds !== "number" ||
      !isFinite(totalSeconds) ||
      totalSeconds < 0
    ) {
      return "";
    }

    const s = Math.floor(totalSeconds);
    if (s < 60) return `${s}s old`;

    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m old`;

    const h = Math.floor(m / 60);
    const remM = m % 60;
    if (h < 24) {
      return remM > 0 ? `${h}h ${remM}m old` : `${h}h old`;
    }

    const d = Math.floor(h / 24);
    const remH = h % 24;
    return remH > 0 ? `${d}d ${remH}h old` : `${d}d old`;
  }

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
    return "(" + h + "h ago)";
  }

  async function refreshViewIcons() {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (!wrap) return;

    try {
      const res = await fetch("/views?_ts=" + Date.now());
      if (!res.ok) return;

      const views = await res.json();
      const byId = {};
      for (const v of views) byId[v.view_id] = v;

      const items = wrap.querySelectorAll("[data-plotsrv-view]");
      items.forEach((btn) => {
        const vid = btn.getAttribute("data-plotsrv-view");
        if (!vid) return;

        const meta = byId[vid];
        if (!meta) return;

        const iconKey = meta.icon_key || "unknown";
        const img = btn.querySelector(".ps-viewselect__itemicon");
        if (img && ICONS[iconKey] && img.getAttribute("src") !== ICONS[iconKey]) {
          img.setAttribute("src", ICONS[iconKey]);
        }
      });

      const activeMeta = byId[core.getActiveViewId()];
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

  async function refreshStatus() {
    try {
      const res = await fetch(
        "/status?view=" + encodeURIComponent(core.getActiveViewId()) + "&_ts=" + Date.now()
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
      const freshness = document.getElementById("status-freshness");

      if (updated) updated.textContent = fmtLocalTime(s.last_updated);
      if (updatedAgo) updatedAgo.textContent = fmtAgo(s.last_updated);

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
        mode.textContent = core.isHistoryMode()
          ? "historical"
          : (s.service_mode ? "service" : "interactive");
      }

      if (srvRate) {
        if (core.isHistoryMode()) {
          srvRate.textContent = "paused";
        } else if (s.service_mode && s.service_refresh_rate_s) {
          srvRate.textContent = "every " + s.service_refresh_rate_s + "s";
        } else if (s.service_mode) {
          srvRate.textContent = "once";
        } else {
          srvRate.textContent = "—";
        }
      }

      if (freshness) {
        const f = s.freshness || null;

        if (!f || f.enabled === false) {
          freshness.textContent = "—";
        } else {
          const emoji = f.emoji || "";
          const label = f.label || "Unknown";
          const age =
            typeof f.age_s === "number" ? ` (${formatAgeShort(f.age_s)})` : "";
          freshness.textContent = `${emoji} ${label}${age}`.trim();
        }
      }

      refreshViewIcons();
    } catch (e) {
      // ignore
    }
  }

  core.formatAgeShort = formatAgeShort;
  core.fmtLocalTime = fmtLocalTime;
  core.fmtAgo = fmtAgo;
  core.refreshViewIcons = refreshViewIcons;
  core.refreshStatus = refreshStatus;
})();