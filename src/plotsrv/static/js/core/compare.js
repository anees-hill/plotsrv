(function () {
  "use strict";
  const {core, state, config} = window.PLOTSRV;
  const ui = state.compare = {mode: "timeline", day: new Date().toISOString().slice(0, 10), month: "", rows: [], days: {}, next: null, count: 0, loading: false, error: ""};
  let metadataController = null, metadataRequest = 0, metadataTask = null, desiredMetadata = null;
  const el = id => document.getElementById(id);
  const label = (id, text) => { if (el(id)) el(id).textContent = text; };
  const stamp = value => String(value || "Unknown timestamp").replace("T", " ").replace(/(?:Z|\+00:00)$/, "") + " UTC";
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
  function capture() { return !state.currentSnapshot && (state.compareCandidate || state.compareCapture); }
  async function readBounded(res, limit) {
    if (!res.ok) limit = Math.min(limit, 16 * 1024);
    const reader = res.body.getReader(), chunks = []; let bytes = 0;
    try {
      while (true) {
        const item = await reader.read(); if (item.done) break;
        bytes += item.value.byteLength;
        if (bytes > limit) throw Error("Compare response exceeds its read budget.");
        chunks.push(item.value);
      }
      const all = new Uint8Array(bytes); let offset = 0;
      for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.length; }
      const data = JSON.parse(new TextDecoder().decode(all));
      if (!res.ok) throw Error(typeof data.detail === "string" ? data.detail.slice(0, 500) : "Compare request failed (" + res.status + "). Choose again to retry.");
      return data;
    } finally { await reader.cancel().catch(() => {}); }
  }
  core.prepareComparedSelection = async function () {
    state.compareCandidate = null;
    if (!state.compareActive || state.currentSnapshot) return;
    const load = core.beginSnapshotLoad("compare");
    try {
      const data = await readBounded(await fetch("/compare/latest?view=" + encodeURIComponent(config.activeViewId), {signal: load.signal}), 4 * 1024 * 1024);
      if (!load.current() || load.signal.aborted) throw Error("Latest selection was superseded.");
      if (data.version !== 1 || data.view_id !== config.activeViewId || !Number.isSafeInteger(data.revision)) throw Error("Unsupported Latest inspection response.");
      state.compareCandidate = data;
    } finally { load.finish(); }
  };
  core.completeComparedSelection = function () {
    if (!state.currentSnapshot && state.compareCandidate) state.compareCapture = state.compareCandidate;
    else state.compareCapture = null;
    state.compareCandidate = null;
    const pending = state.pendingBrowserUpdate, pinned = state.compareCapture;
    if (pending && pinned && typeof pinned.server_instance_id === "string" && pending.server_instance_id === pinned.server_instance_id &&
        Number.isSafeInteger(pending.render_revision) && pending.render_revision <= pinned.revision) {
      state.appliedUpdateRevision = Math.max(state.appliedUpdateRevision, pending.revision);
      state.pendingBrowserUpdate = null;
      if (core.setHeaderBrowserDataState) core.setHeaderBrowserDataState("current");
    }
  };
  core.fetchView = function (url, options) {
    const pinned = capture();
    if (!pinned) return fetch(url, options);
    const path = new URL(url, window.location.href).pathname;
    if (path === "/plot" && pinned.plot) {
      const bytes = Uint8Array.from(atob(pinned.plot), c => c.charCodeAt(0));
      return Promise.resolve({ok: true, blob: async () => new Blob([bytes], {type: "image/png"})});
    }
    const data = path === "/artifact" ? pinned.artifact : path === "/table/data" ? pinned.table : null;
    if (!data) return Promise.reject(Error("This captured revision does not support that renderer."));
    return Promise.resolve({ok: true, json: async () => data});
  };
  function sync() {
    if (!el("compare-enter")) return;
    const nav = state.snapshotNavigation, cap = state.snapshotCapability;
    el("compare-enter").hidden = !el("snapshots-control") || config.kind === "stream" || !cap || !cap.enabled;
    el("compare-enter").disabled = !nav.metadata || !(nav.metadata.count || (nav.metadata.snapshots || []).length);
    el("compare-enter").title = el("compare-enter").disabled ? "Compare becomes available when stored snapshots exist." : "Inspect stored snapshots using Timeline or List";
    if (!state.compareActive) return;
    const pinned = capture(), selected = core.currentHistoryMeta();
    label("compare-selected", state.currentSnapshot ? stamp(selected && selected.created_at) + " · " + state.currentSnapshot : pinned ? "Latest captured · " + stamp(pinned.created_at) + " · r" + pinned.revision : "Latest — waiting for capture");
    el("compare-selected").title = el("compare-selected").textContent + (pinned ? " · " + pinned.scope : "");
    for (const dir of ["older", "newer"]) {
      const source = el("snapshot-" + dir), target = el("compare-" + dir);
      target.disabled = !source || source.disabled;
      target.title = source ? source.title : "Unavailable";
    }
    label("compare-message", nav.error || ui.error || (nav.pending ? "Loading selected version…" : ui.loading ? "Loading stored metadata…" : state.currentSnapshot && selected && selected.created_at.slice(0, 10) !== ui.day ? "Selected version is outside this displayed day." : pinned ? pinned.scope + ". Held for inspection; choose Latest again to capture current data." : ""));
    el("compare-day").value = ui.day;
    for (const mode of ["timeline", "list"]) {
      el("compare-" + mode + "-tab").setAttribute("aria-pressed", String(ui.mode === mode));
      el("compare-" + mode).hidden = ui.mode !== mode;
    }
    el("compare-more").hidden = !ui.next;
    el("compare-more").disabled = ui.loading;
    label("compare-count", ui.count + " stored · " + ui.rows.length + " on this page · UTC");
    for (const button of el("compare-results").querySelectorAll("[data-snapshot]")) button.setAttribute("aria-pressed", String(button.dataset.snapshot === state.currentSnapshot));
  }
  function renderRows() {
    const list = el("compare-list"), timeline = el("compare-points");
    list.replaceChildren(); timeline.replaceChildren();
    const [start, end] = bounds(ui.day), span = Date.parse(end) - Date.parse(start);
    for (const row of ui.rows) {
      const button = document.createElement("button"); button.type = "button";
      button.dataset.snapshot = row.snapshot_id;
      button.textContent = stamp(row.created_at) + " · " + row.snapshot_id + " · " + (row.kind || "");
      button.addEventListener("click", () => core.snapshotNavigation.select(row.snapshot_id));
      list.append(button);
      const point = button.cloneNode(false);
      point.title = button.textContent; point.setAttribute("aria-label", button.textContent);
      point.tabIndex = -1; // Exact keyboard selection is provided by List and previous/next.
      point.style.left = Math.max(0, Math.min(100, (Date.parse(row.created_at) - Date.parse(start)) / span * 100)) + "%";
      point.addEventListener("click", () => core.snapshotNavigation.select(row.snapshot_id));
      timeline.append(point);
    }
    if (!ui.rows.length) { const empty = document.createElement("span"); empty.textContent = "No stored snapshots on this UTC day."; list.append(empty); }
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
          if (data.capability && !data.capability.enabled) throw Error(data.capability.message || "Snapshot comparison is unavailable for this view.");
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
    core.bottomBar.setCollapsed(false);
    const selected = core.currentHistoryMeta(); if (selected) ui.day = selected.created_at.slice(0, 10);
    ui.month = ui.day.slice(0, 7); metadata(); sync();
    if (!state.currentSnapshot) core.snapshotNavigation.select(null);
    el("compare-latest").focus();
  }
  function exit() {
    state.compareActive = false; document.body.classList.remove("ps-compare");
    el("compare-dock").hidden = true; metadataRequest++; desiredMetadata = null;
    if (metadataController) metadataController.abort(); ui.rows = []; ui.days = {}; ui.next = null;
    renderRows(); el("compare-calendar").hidden = true; el("compare-calendar-toggle").setAttribute("aria-expanded", "false");
    core.bottomBar.setCollapsed(false); sync(); el("compare-enter").focus();
  }
  function bind() {
    if (!el("compare-enter")) return;
    el("compare-enter").addEventListener("click", enter); el("compare-exit").addEventListener("click", exit);
    for (const direction of ["older", "newer"]) el("compare-" + direction).addEventListener("click", () => core.snapshotNavigation.move(direction));
    el("compare-latest").addEventListener("click", () => core.snapshotNavigation.select(null));
    for (const mode of ["timeline", "list"]) el("compare-" + mode + "-tab").addEventListener("click", () => {ui.mode = mode; sync();});
    el("compare-day").addEventListener("change", event => setDay(event.target.value));
    for (const [id, step] of [["compare-day-prev", -1], ["compare-day-next", 1]]) el(id).addEventListener("click", () => {const d = civil(ui.day); d.setUTCDate(d.getUTCDate() + step); setDay(d.toISOString().slice(0, 10));});
    for (const [id, step] of [["compare-month-prev", -1], ["compare-month-next", 1]]) el(id).addEventListener("click", () => {const d = civil(ui.month + "-01"); d.setUTCMonth(d.getUTCMonth() + step); ui.month = d.toISOString().slice(0, 7); metadata();});
    el("compare-calendar-toggle").addEventListener("click", () => {const calendar = el("compare-calendar"); calendar.hidden = !calendar.hidden; el("compare-calendar-toggle").setAttribute("aria-expanded", String(!calendar.hidden));});
    el("compare-more").addEventListener("click", () => metadata(ui.next));
    el("compare-first").addEventListener("click", () => metadata());
    el("compare-calendar").addEventListener("keydown", event => {if (event.key === "Escape") {event.preventDefault(); el("compare-calendar").hidden = true; el("compare-calendar-toggle").setAttribute("aria-expanded", "false"); el("compare-calendar-toggle").focus();}});
    window.addEventListener("pagehide", event => {metadataRequest++; desiredMetadata = null; if (metadataController) metadataController.abort(); if (!event.persisted) state.compareCapture = state.compareCandidate = null;});
    sync();
  }
  core.compare = {state: ui, enter, exit, setDay, bounds, sync};
  core.inspectionCapture = capture;
  core.syncCompare = sync; core.bindCompare = bind;
})();
