// Browser-local attention. No polling, event queue, source data or server acknowledgement.
(function () {
  "use strict";
  const { core, state, config } = window.PLOTSRV;
  const MAX_SEEN = 128;
  let latest = null, latestView = null, shown = null, request = null;
  let epoch = 0, seenKey = null, seen = [], persistent = true;
  const retiredGenerations = [];
  const el = id => document.getElementById(id);
  const cursor = n => Number.isSafeInteger(n) && n >= 0;
  function namespace() {
    return "plotsrv:v1:check_seen:" + encodeURIComponent(location.pathname.replace(/\/+$/, "") || "/") +
      ":" + encodeURIComponent(config.dashboardName || "default");
  }
  function loadSeen() {
    const key = namespace();
    if (seenKey === key) return;
    seenKey = key;
    seen = [];
    try {
      const raw = localStorage.getItem(key);
      if (raw && raw.length <= 262144) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) seen = parsed.slice(-MAX_SEEN).filter(row =>
          Array.isArray(row) && row.length === 4 && typeof row[0] === "string" && row[0].length <= 512 &&
          typeof row[1] === "string" && row[1].length <= 128 && typeof row[2] === "string" &&
          row[2].length <= 64 && cursor(row[3]));
      }
    } catch (_) { persistent = false; }
  }
  function watermark(view, check, generation) {
    loadSeen();
    const row = seen.find(row => row[0] === view && row[1] === check && row[2] === generation);
    return row ? row[3] : 0;
  }
  function markPresented(data, view) {
    loadSeen();
    for (const event of data.events) {
      const value = Math.max(watermark(view, event.check_id, data.generation), event.cursor);
      // A generation supersedes the older watermark for this exact logical check.
      seen = seen.filter(row => !(row[0] === view && row[1] === event.check_id));
      seen.push([view, event.check_id, data.generation, value]);
    }
    seen = seen.slice(-MAX_SEEN);
    if (data.events.length) {
      try { localStorage.setItem(seenKey, JSON.stringify(seen)); }
      catch (_) { persistent = false; }
    }
    const note = el("status-checks-personal");
    if (note) note.textContent = "Reading check activity clears attention only in this browser. Seen does not mean resolved." +
      (persistent ? "" : " Browser storage is unavailable; attention is remembered only on this page.");
  }
  function renderAttention() {
    const marker = el("header-check-attention");
    if (!marker) return;
    const unseen = latest && latestView === config.activeViewId && latest.states.some(rule =>
      (rule.last_event_cursor || 0) > watermark(latestView, rule.id, latest.generation));
    marker.hidden = !unseen;
    const announcement = el("header-check-announcement");
    const message = unseen ? "Unseen check activity. Open view status to read checks." : "";
    if (announcement && announcement.textContent !== message) announcement.textContent = message;
    const button = el("header-status-button");
    if (button) {
      const label = (button.getAttribute("aria-label") || "View status").replace(/; unseen check activity$/, "");
      button.setAttribute("aria-label", label + (unseen ? "; unseen check activity" : ""));
    }
  }
  function valid(data, view, withEvents) {
    return data && data.version === 1 && typeof data.generation === "string" && data.generation.length <= 64 &&
      cursor(data.cursor) && Array.isArray(data.states) && data.states.length <= 64 &&
      data.states.every(r => r.source === view && typeof r.id === "string" && r.id.length <= 128 &&
        (r.last_event_cursor == null || (cursor(r.last_event_cursor) && r.last_event_cursor <= data.cursor))) &&
      (!withEvents || (Array.isArray(data.events) && data.events.length <= 256 && data.events.every(e =>
        e.view_id === view && e.generation === data.generation && cursor(e.cursor) && e.cursor <= data.cursor &&
        data.states.some(r => r.id === e.check_id))));
  }
  function receive(data) {
    const view = config.activeViewId;
    if (!valid(data, view, false) || retiredGenerations.includes(data.generation)) return;
    if (latest && latest.generation !== data.generation) {
      retiredGenerations.push(latest.generation);
      if (retiredGenerations.length > 4) retiredGenerations.shift();
    }
    if (latestView === view && latest && latest.generation === data.generation && data.cursor < latest.cursor) return;
    latest = Object.assign({}, data, { events: [] });
    latestView = view;
    renderAttention();
    renderContext();
  }
  function renderContext() {
    const context = el("status-checks-context");
    if (!context) return;
    const historical = !!state.currentSnapshot || !!state.streamHistoricalSessionId;
    context.textContent = historical
      ? "Checks refer to the latest accepted live data, not this historical snapshot or stored session."
      : "Checks refer to accepted live data. The results below stay fixed while you read.";
    const button = el("status-checks-load");
    if (button) {
      const changed = shown && latest && (shown.generation !== latest.generation || shown.cursor < latest.cursor ||
        JSON.stringify(shown.states) !== JSON.stringify(latest.states));
      button.textContent = changed ? "Show updated checks and activity" : "Refresh checks";
    }
  }
  const scopes = {
    supplied_value: "Supplied value", base_sample: "Inspected sample",
    complete_small_inspection: "Complete small inspection", source_metadata: "Source metadata"
  };
  const ops = { eq: "=", ne: "≠", lt: "<", le: "≤", gt: ">", ge: "≥" };
  function value(v) {
    if (v == null) return "Unavailable";
    if (typeof v === "object") {
      if (v.type === "integer") return String(v.value).slice(0, 320);
      if (v.type === "rational") return String(v.numerator).slice(0, 320) + " / " + String(v.denominator).slice(0, 320);
      return "Unavailable";
    }
    return String(v).slice(0, 512);
  }
  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text != null) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function card(rule, item, event) {
    const box = node("article", null, "ps-check-card");
    const severity = ["critical", "warning", "noteworthy"].includes(item.severity) ? item.severity : "noteworthy";
    const labels = { triggered: "Active failure", unknown: "Unavailable", disabled: "Disabled", ok: rule.kind === "event" ? "Event check ready" : "OK" };
    const eventLabels = { triggered: "Triggered", recovered: "Recovered", unavailable: "Became unavailable", available: "Evidence available", match: "Event match" };
    const label = event ? eventLabels[item.event_type] || "Check activity" : labels[item.state] || "Unavailable";
    box.dataset.severity = severity;
    box.dataset.active = String(!event && item.state === "triggered" && rule.kind === "state");
    const heading = node("div", null, "ps-check-card__heading");
    heading.append(node("strong", String(rule.name || rule.id).slice(0, 128)),
      node("span", severity[0].toUpperCase() + severity.slice(1) + " · " + label, "ps-check-card__pill"));
    box.append(heading);
    box.append(node("p", "Triggers when " + (rule.metric || "value") + " " + (ops[rule.op] || "?") + " " + value(item.threshold) +
      " · Observed: " + (item.state === "unknown" ? "Unavailable" : value(item.observed_value)) + (item.unit ? " " + item.unit : "")));
    const time = item.context && item.context.received_at;
    const parsed = time && new Date(time);
    box.append(node("p", (event ? "Received " : "Evidence received ") +
      (parsed && Number.isFinite(parsed.getTime()) ? parsed.toLocaleString() : "not yet") + " · " + (scopes[item.evidence_scope] || "Scope unavailable"), "ps-status-modal__caveat"));
    if (!event && item.state === "unknown") box.append(node("p", item.reason === "awaiting_live_data"
      ? "Waiting for eligible live data."
      : item.reason === "coverage_gap" ? "Some input could not be evaluated. Coverage is incomplete."
        : "The configured value could not be evaluated from the available evidence."));
    const details = node("details");
    details.append(node("summary", "Technical details"));
    details.append(node("pre", JSON.stringify({check_id: rule.id, view_id: rule.source, kind: rule.kind,
      path: rule.path, input: rule.input, metric: rule.metric, selection_path: rule.selection_path,
      event_id: item.event_id, reason: event ? undefined : item.reason,
      inspected: item.inspected, not_inspected: item.not_inspected, coverage_lost: item.coverage_lost, notifications: item.notifications,
      context: item.context}, null, 2)));
    box.append(details);
    return box;
  }
  function render(data) {
    const current = el("status-checks-current"), events = el("status-checks-events");
    if (!current || !events) return false;
    current.replaceChildren(); events.replaceChildren();
    const failures = data.states.filter(r => r.kind === "state" && r.state === "triggered").length;
    const unknown = data.states.filter(r => r.state === "unknown").length;
    const disabled = data.states.filter(r => r.state === "disabled").length;
    el("status-checks-summary").textContent = !data.states.length ? "No checks configured for this view." :
      disabled === data.states.length ? "Checks are disabled for this view." :
        failures + " active " + (failures === 1 ? "failure" : "failures") + " · " + unknown + " unavailable · " + disabled + " disabled";
    for (const rule of data.states) current.append(card(rule, rule, false));
    if (data.history_gap) events.append(node("p", "Earlier check activity is unavailable in the bounded history. This is not a complete activity record.", "ps-check-gap"));
    if (data.states.length) events.append(node("h4", "Recent check activity"));
    if (!data.events.length && data.states.length) events.append(node("p", "No retained check activity for this view. Initial state establishes a baseline without an event."));
    for (const event of data.events.slice().reverse()) {
      events.append(card(data.states.find(r => r.id === event.check_id), event, true));
    }
    return true;
  }
  async function fetchChecks() {
    if (request || !state.statusModalOpen) return;
    const view = config.activeViewId, opened = epoch;
    const startGeneration = latest && latest.generation;
    const serverEpoch = state.browserUpdateGeneration;
    const controller = new AbortController();
    request = controller;
    const button = el("status-checks-load");
    if (button) {
      // Keep keyboard focus inside the modal while the one request is active.
      button.setAttribute("aria-disabled", "true");
      button.setAttribute("aria-busy", "true");
    }
    const deadline = setTimeout(() => controller.abort(), 10000);
    try {
      // One bounded retained history read, only on opening or an explicit read action.
      const response = await fetch("/checks?view=" + encodeURIComponent(view), { signal: controller.signal });
      if (!response.ok) throw new Error("checks unavailable");
      const data = await response.json();
      if (opened !== epoch || view !== config.activeViewId || !state.statusModalOpen) return;
      if (serverEpoch !== state.browserUpdateGeneration || retiredGenerations.includes(data.generation))
        throw new Error("receiver changed while opening");
      if (!valid(data, view, true)) throw new Error("incompatible checks");
      if (latest && latest.generation !== startGeneration && latest.generation !== data.generation)
        throw new Error("generation changed while opening");
      shown = data;
      if (!latest || latestView !== view || latest.generation !== data.generation || latest.cursor <= data.cursor) receive(data);
      if (render(data)) markPresented(data, view);
      renderAttention(); renderContext();
    } catch (_) {
      if (opened === epoch && view === config.activeViewId && state.statusModalOpen) {
        el("status-checks-summary").textContent = "Check activity could not be loaded. Refresh checks to try again.";
        // Preserve previously displayed evidence and watermarks; never infer an all-clear.
      }
    } finally {
      clearTimeout(deadline);
      if (request === controller) {
        request = null;
        if (button) {
          button.removeAttribute("aria-disabled");
          button.removeAttribute("aria-busy");
        }
      }
    }
  }
  core.openCheckStatus = function () {
    epoch++;
    shown = null;
    el("status-checks-current").replaceChildren();
    el("status-checks-events").replaceChildren();
    el("status-checks-summary").textContent = "Loading checks…";
    el("status-checks-load").onclick = fetchChecks;
    renderContext();
    fetchChecks();
  };
  core.closeCheckStatus = function () {
    epoch++;
    if (request) request.abort();
    request = null;
    shown = null;
    el("status-checks-current").replaceChildren();
    el("status-checks-events").replaceChildren();
  };
  core.receiveCheckStatus = receive;
  core.renderCheckAttention = renderAttention;
  core.renderCheckContext = renderContext;
  window.addEventListener("storage", function (event) {
    if (event.key === namespace() || event.key === null) {
      seenKey = null;
      renderAttention();
    }
  });
})();
