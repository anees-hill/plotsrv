(function () {
  "use strict";
  const {core, state, config} = window.PLOTSRV;
  const ui = state.compare = {day: new Date().toISOString().slice(0, 10), month: "", rows: [], days: {}, next: null, count: 0, loading: false, error: ""};
  let metadataController = null, metadataRequest = 0, metadataTask = null, desiredMetadata = null;
  let exportAnchor = null;
  const el = id => document.getElementById(id);
  const label = (id, text) => { if (el(id)) el(id).textContent = text; };
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function stamp(value) {
    const date = new Date(value);
    if (!Number.isFinite(+date)) return "Unknown time";
    return date.getUTCDate() + " " + months[date.getUTCMonth()] + " " + date.getUTCFullYear() + ", " +
      String(date.getUTCHours()).padStart(2, "0") + ":" +
      String(date.getUTCMinutes()).padStart(2, "0") + ":" +
      String(date.getUTCSeconds()).padStart(2, "0") + " UTC";
  }
  function dayLabel(value) {
    const date = civil(value);
    return date.getUTCDate() + " " + months[date.getUTCMonth()] + " " + date.getUTCFullYear();
  }
  function civil(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw Error("Invalid UTC date");
    const d = new Date(value + "T00:00:00Z");
    if (!Number.isFinite(+d) || d.toISOString().slice(0, 10) !== value) throw Error("Invalid UTC date");
    return d;
  }
  function bounds(day) {
    const start = civil(day), end = civil(day);
    end.setUTCDate(end.getUTCDate() + 1);
    return [start.toISOString(), end.toISOString()];
  }
  async function readBounded(res, limit) {
    if (!res.ok) limit = Math.min(limit, 16 * 1024);
    const reader = res.body.getReader(), chunks = []; let bytes = 0;
    try {
      while (true) {
        const item = await reader.read(); if (item.done) break;
        bytes += item.value.byteLength;
        if (bytes > limit) throw Error("History response exceeds its read budget.");
        chunks.push(item.value);
      }
      const all = new Uint8Array(bytes); let offset = 0;
      for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.length; }
      const data = JSON.parse(new TextDecoder().decode(all));
      if (!res.ok) throw Error(typeof data.detail === "string" ? data.detail.slice(0, 500) : "History request failed (" + res.status + "). Choose again to retry.");
      return data;
    } finally { await reader.cancel().catch(() => {}); }
  }
  function moveExportIntoHistory() {
    const control = el("export-control"), slot = el("history-export-slot");
    if (!control || !slot || control.parentElement === slot) return;
    exportAnchor = document.createComment("export control position");
    control.before(exportAnchor);
    slot.append(control);
  }
  function restoreExport() {
    const control = el("export-control");
    if (control && exportAnchor && exportAnchor.isConnected) exportAnchor.replaceWith(control);
    exportAnchor = null;
  }
  function sync() {
    if (!el("compare-enter")) return;
    const nav = state.snapshotNavigation, cap = state.snapshotCapability;
    el("compare-enter").hidden = !el("snapshots-control") || config.kind === "stream" || !cap || !cap.enabled;
    el("compare-enter").disabled = !nav.metadata || !(nav.metadata.count || (nav.metadata.snapshots || []).length);
    el("compare-enter").title = el("compare-enter").disabled ? "History becomes available when stored snapshots exist." : "Browse stored snapshots on a timeline";
    if (!state.compareActive) return;
    const selected = core.currentHistoryMeta();
    label("compare-selected", state.currentSnapshot
      ? selected && selected.created_at ? stamp(selected.created_at) : "Loading snapshot…"
      : "Live view");
    el("compare-selected").title = el("compare-selected").textContent;
    for (const dir of ["older", "newer"]) {
      const source = el("snapshot-" + dir), target = el("compare-" + dir);
      target.disabled = !source || source.disabled;
      target.title = source ? source.title : "Unavailable";
    }
    const message = nav.error || ui.error || (nav.loadingVisible ? "Loading selected version…" : ui.loading ? "Loading stored metadata…" : state.currentSnapshot && selected && selected.created_at.slice(0, 10) !== ui.day ? "Selected version is outside this displayed day." : "");
    label("compare-message", message);
    el("compare-message").title = message;
    label("compare-day", dayLabel(ui.day));
    el("compare-more").hidden = !ui.next;
    el("compare-more").disabled = ui.loading;
    label("compare-count", ui.count + (ui.count === 1 ? " snapshot" : " snapshots") + " · " + ui.rows.length + " shown · UTC");
    for (const button of el("compare-results").querySelectorAll("[data-snapshot]")) button.setAttribute("aria-pressed", String(button.dataset.snapshot === state.currentSnapshot));
  }
  function renderRows() {
    const timeline = el("compare-points");
    timeline.replaceChildren();
    const [start, end] = bounds(ui.day), span = Date.parse(end) - Date.parse(start);
    for (const row of ui.rows) {
      const point = document.createElement("button"); point.type = "button";
      point.dataset.snapshot = row.snapshot_id;
      point.title = stamp(row.created_at) + (row.kind ? " · " + row.kind : "");
      point.setAttribute("aria-label", point.title);
      point.style.left = Math.max(0, Math.min(100, (Date.parse(row.created_at) - Date.parse(start)) / span * 100)) + "%";
      point.addEventListener("click", () => core.snapshotNavigation.select(row.snapshot_id));
      timeline.append(point);
    }
    label("compare-timeline-empty", ui.rows.length ? "" : "No stored snapshots on this UTC day.");
    sync();
  }
  function renderCalendar() {
    label("compare-month-label", ui.month + " · UTC");
    const grid = el("compare-calendar-days"); grid.replaceChildren();
    const first = civil(ui.month + "-01"), month = first.getUTCMonth();
    const spacer = document.createElement("span"); spacer.style.gridColumn = "span " + (first.getUTCDay() || 7);
    // Monday-first grid; leave no leading spacer on Monday.
    const offset = (first.getUTCDay() + 6) % 7;
    if (offset) { spacer.style.gridColumn = "span " + offset; grid.append(spacer); }
    for (const d = first; d.getUTCMonth() === month; d.setUTCDate(d.getUTCDate() + 1)) {
      const day = d.toISOString().slice(0, 10), count = ui.days[day] || 0;
      const button = document.createElement("button"); button.type = "button";
      button.textContent = String(d.getUTCDate()); button.dataset.day = day;
      button.classList.toggle("has-snapshots", count > 0);
      button.setAttribute("aria-label", day + " UTC, " + count + " stored snapshots");
      button.setAttribute("aria-pressed", String(day === ui.day));
      button.tabIndex = day === ui.day || (!ui.day.startsWith(ui.month) && d.getUTCDate() === 1) ? 0 : -1;
      button.addEventListener("click", () => { setDay(day); el("compare-day").focus(); });
      button.addEventListener("keydown", event => {
        const step = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}[event.key];
        if (!step) return; event.preventDefault();
        const next = civil(day); next.setUTCDate(next.getUTCDate() + step);
        const target = grid.querySelector('[data-day="' + next.toISOString().slice(0, 10) + '"]');
        if (target) { button.tabIndex = -1; target.tabIndex = 0; target.focus(); }
      });
      grid.append(button);
    }
  }
  // One active request and one replaceable intent; no request queue or accumulated pages.
  function metadata(before) {
    desiredMetadata = {day: ui.day, month: ui.month, before, view: config.activeViewId, revision: ++metadataRequest};
    if (metadataController) metadataController.abort();
    if (metadataTask) return metadataTask;
    metadataTask = (async () => {
      while (desiredMetadata && state.compareActive) {
        const wanted = desiredMetadata; desiredMetadata = null;
        const controller = metadataController = new AbortController();
        const timer = setTimeout(() => controller.abort(), 10000);
        ui.loading = true; ui.error = ""; sync();
        try {
          const [start, end] = bounds(wanted.day);
          const query = new URLSearchParams({view: wanted.view, limit: "100", start, end});
          if (wanted.before) query.set("before", wanted.before);
          const data = await readBounded(await fetch("/history/navigation?" + query, {signal: controller.signal}), 128 * 1024);
          if (data.capability && !data.capability.enabled) throw Error(data.capability.message || "History is unavailable for this view.");
          const month = await readBounded(await fetch("/history/month?" + new URLSearchParams({view: wanted.view, month: wanted.month}), {signal: controller.signal}), 16 * 1024);
          if (wanted.revision !== metadataRequest || wanted.view !== config.activeViewId || !state.compareActive) continue;
          if (month.capability && !month.capability.enabled) throw Error(month.capability.message || "Calendar availability is unavailable for this view.");
          ui.rows = (data.snapshots || []).slice(0, 100); ui.count = data.count || 0; ui.next = data.next_cursor || null;
          ui.days = month.days || {}; renderRows(); renderCalendar();
        } catch (error) {
          if (wanted.revision === metadataRequest && state.compareActive) {
            ui.rows = []; ui.days = {}; ui.next = null; ui.count = 0;
            ui.error = error.message || "Stored metadata is unavailable. Choose the day again to retry.";
            renderRows(); renderCalendar();
          }
        } finally { clearTimeout(timer); if (metadataController === controller) metadataController = null; }
      }
    })().finally(() => { metadataTask = null; ui.loading = false; sync(); });
    return metadataTask;
  }
  function setDay(day) {
    try { civil(day); } catch (_) { return; }
    ui.day = day; ui.month = day.slice(0, 7); ui.rows = []; ui.next = null; ui.count = 0; renderRows(); metadata();
  }
  function enter() {
    if (el("compare-enter").disabled || config.kind === "stream" || !state.snapshotCapability || !state.snapshotCapability.enabled) return;
    core.expandedView.prepareForCompare(); state.compareActive = true;
    document.body.classList.add("ps-compare");
    el("compare-dock").hidden = false; el("compare-enter").hidden = true;
    moveExportIntoHistory();
    core.bottomBar.setCollapsed(false);
    const selected = core.currentHistoryMeta(); if (selected) ui.day = selected.created_at.slice(0, 10);
    ui.month = ui.day.slice(0, 7); metadata(); sync();
    el("compare-latest").focus();
  }
  function exit() {
    if (core.closeExportMenu) core.closeExportMenu();
    state.compareActive = false; document.body.classList.remove("ps-compare");
    el("compare-dock").hidden = true; metadataRequest++; desiredMetadata = null;
    if (metadataController) metadataController.abort(); ui.rows = []; ui.days = {}; ui.next = null;
    renderRows(); el("compare-calendar").hidden = true; el("compare-calendar-toggle").setAttribute("aria-expanded", "false");
    restoreExport(); core.bottomBar.setCollapsed(false); sync(); el("compare-enter").focus();
  }
  function bind() {
    if (!el("compare-enter")) return;
    el("compare-enter").addEventListener("click", enter); el("compare-exit").addEventListener("click", exit);
    for (const direction of ["older", "newer"]) el("compare-" + direction).addEventListener("click", () => core.snapshotNavigation.move(direction));
    el("compare-latest").addEventListener("click", () => {
      if (state.currentSnapshot || state.snapshotNavigation.error) core.returnToLive();
      else if (state.pendingBrowserUpdate && core.applyPendingUpdate) core.applyPendingUpdate({force: true});
    });
    for (const [id, step] of [["compare-day-prev", -1], ["compare-day-next", 1]]) el(id).addEventListener("click", () => {const d = civil(ui.day); d.setUTCDate(d.getUTCDate() + step); setDay(d.toISOString().slice(0, 10));});
    for (const [id, step] of [["compare-month-prev", -1], ["compare-month-next", 1]]) el(id).addEventListener("click", () => {const d = civil(ui.month + "-01"); d.setUTCMonth(d.getUTCMonth() + step); ui.month = d.toISOString().slice(0, 7); metadata();});
    el("compare-calendar-toggle").addEventListener("click", () => {const calendar = el("compare-calendar"); calendar.hidden = !calendar.hidden; el("compare-calendar-toggle").setAttribute("aria-expanded", String(!calendar.hidden));});
    el("compare-more").addEventListener("click", () => metadata(ui.next));
    el("compare-first").addEventListener("click", () => metadata());
    el("compare-calendar").addEventListener("keydown", event => {if (event.key === "Escape") {event.preventDefault(); el("compare-calendar").hidden = true; el("compare-calendar-toggle").setAttribute("aria-expanded", "false"); el("compare-calendar-toggle").focus();}});
    window.addEventListener("pagehide", () => {metadataRequest++; desiredMetadata = null; if (metadataController) metadataController.abort();});
    sync();
  }
  core.compare = {state: ui, enter, exit, setDay, bounds, sync};
  core.syncCompare = sync; core.bindCompare = bind;
})();
