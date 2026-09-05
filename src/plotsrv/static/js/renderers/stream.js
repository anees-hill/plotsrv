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
  const LIFECYCLE_PRESENTATION = {
    live: {
      text: "Live observation — producer heartbeats are current.",
    },
    retrying: {
      text: "Retrying delivery — recent observations may still be pending.",
    },
    ended: {
      text: "Observation ended — the producer explicitly stopped after its bounded final drain.",
    },
    disconnected: {
      text: "Observer disconnected — heartbeats stopped; application state is unknown.",
    },
    incomplete: {
      text: "Incomplete observation — some observations may be pending; application state is unknown.",
    },
  };
  const INSIGHTS_TABS = ["since", "noteworthy", "history"];
  const STREAM_DATA_REQUEST_TIMEOUT_MS = 15000;
  const STREAM_CONTROLS_PREFERENCE_PREFIX = "plotsrv:v1:stream_controls:";

  function streamControlsPreferenceKey() {
    return STREAM_CONTROLS_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function streamControlsCollapsed() {
    if (typeof state.streamControlsCollapsed === "boolean") {
      return state.streamControlsCollapsed;
    }
    let collapsed = false;
    try {
      collapsed = localStorage.getItem(streamControlsPreferenceKey()) === "collapsed";
    } catch (e) {
      collapsed = false;
    }
    state.streamControlsCollapsed = collapsed;
    return collapsed;
  }

  function syncStreamControlsDisclosure() {
    const panel = document.querySelector(".ps-stream-controls");
    const content = document.getElementById("stream-controls-content");
    const toggle = document.getElementById("stream-controls-toggle");
    if (!panel || !content || !toggle) return;
    const collapsed = streamControlsCollapsed();
    content.hidden = collapsed;
    if (panel.classList && typeof panel.classList.toggle === "function") {
      panel.classList.toggle("is-collapsed", collapsed);
    }
    toggle.textContent = collapsed ? "+" : "−";
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      (collapsed ? "Expand" : "Collapse") + " Stream controls"
    );
    toggle.title = (collapsed ? "Expand" : "Collapse") + " Stream controls";
  }

  function setStreamControlsCollapsed(collapsed) {
    state.streamControlsCollapsed = collapsed === true;
    try {
      localStorage.setItem(
        streamControlsPreferenceKey(),
        state.streamControlsCollapsed ? "collapsed" : "expanded"
      );
    } catch (e) {
      // The disclosure still works when browser-local preferences are blocked.
    }
    syncStreamControlsDisclosure();
  }

  function bindStreamControlsDisclosure() {
    const toggle = document.getElementById("stream-controls-toggle");
    if (!toggle) return;
    if (!toggle.dataset.plotsrvBound) {
      toggle.addEventListener("click", function () {
        setStreamControlsCollapsed(!streamControlsCollapsed());
      });
      toggle.dataset.plotsrvBound = "1";
    }
    syncStreamControlsDisclosure();
  }

  function normalizeInsightsTab(value) {
    const tab = String(value || "");
    return INSIGHTS_TABS.includes(tab) ? tab : "since";
  }

  function setStreamInsightsTab(value, options) {
    const tab = normalizeInsightsTab(value);
    state.streamInsightsTab = tab;
    document.querySelectorAll("[data-stream-insights-tab]").forEach(function (button) {
      const selected = button.getAttribute("data-stream-insights-tab") === tab;
      button.setAttribute("aria-selected", selected ? "true" : "false");
      button.tabIndex = selected ? 0 : -1;
      if (selected && options && options.focus === true) button.focus();
    });
    document.querySelectorAll("[data-stream-insights-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-stream-insights-panel") !== tab;
    });
    return tab;
  }

  function openStreamInsights(value) {
    const drawer = document.getElementById("stream-insights-drawer");
    const trigger = document.getElementById("stream-insights-button");
    const close = document.getElementById("stream-insights-close");
    if (!drawer) return;

    state.streamInsightsReturnFocus = document.activeElement;
    state.streamInsightsOpen = true;
    drawer.hidden = false;
    if (trigger) trigger.setAttribute("aria-expanded", "true");
    setStreamInsightsTab(value || state.streamInsightsTab);
    if (close) close.focus();
    else drawer.focus();
  }

  function closeStreamInsights(options) {
    const drawer = document.getElementById("stream-insights-drawer");
    const trigger = document.getElementById("stream-insights-button");
    if (!drawer || drawer.hidden) return;

    drawer.hidden = true;
    state.streamInsightsOpen = false;
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    if (!options || options.restoreFocus !== false) {
      const target = state.streamInsightsReturnFocus;
      if (target && typeof target.focus === "function") target.focus();
      else if (trigger) trigger.focus();
    }
  }

  function bindStreamInsights() {
    const drawer = document.getElementById("stream-insights-drawer");
    const trigger = document.getElementById("stream-insights-button");
    const close = document.getElementById("stream-insights-close");
    if (!drawer || !trigger || drawer.dataset.plotsrvBound === "1") return;

    drawer.querySelectorAll(".ps-stream-insights-help").forEach(function (help) {
      const summary = help.querySelector("summary");
      help.addEventListener("pointerenter", function (event) {
        if (event.pointerType === "mouse") help.open = true;
      });
      help.addEventListener("pointerleave", function (event) {
        if (event.pointerType === "mouse" && !help.contains(document.activeElement)) help.open = false;
      });
      summary.addEventListener("focus", function () { help.open = true; });
      help.addEventListener("focusout", function (event) {
        if (!help.contains(event.relatedTarget)) help.open = false;
      });
      help.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopPropagation();
        summary.focus();
        help.open = false;
      });
    });

    trigger.addEventListener("click", function () {
      if (drawer.hidden) openStreamInsights();
      else closeStreamInsights();
    });
    if (close) close.addEventListener("click", function () { closeStreamInsights(); });

    const tabs = Array.from(drawer.querySelectorAll("[data-stream-insights-tab]"));
    tabs.forEach(function (tabButton) {
      tabButton.addEventListener("click", function () {
        setStreamInsightsTab(tabButton.getAttribute("data-stream-insights-tab"));
      });
      tabButton.addEventListener("keydown", function (event) {
        const current = INSIGHTS_TABS.indexOf(
          normalizeInsightsTab(tabButton.getAttribute("data-stream-insights-tab"))
        );
        let next = null;
        if (event.key === "ArrowRight") next = (current + 1) % INSIGHTS_TABS.length;
        else if (event.key === "ArrowLeft") {
          next = (current - 1 + INSIGHTS_TABS.length) % INSIGHTS_TABS.length;
        } else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = INSIGHTS_TABS.length - 1;
        if (next === null) return;
        event.preventDefault();
        setStreamInsightsTab(INSIGHTS_TABS[next], {focus: true});
      });
    });

    drawer.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeStreamInsights();
    });
    setStreamInsightsTab(state.streamInsightsTab);
    drawer.dataset.plotsrvBound = "1";
  }

  function stableJson(value) {
    if (value === null) return "null";

    if (Array.isArray(value)) {
      return "[" + value.map(stableJson).join(",") + "]";
    }

    if (typeof value === "object") {
      return (
        "{" +
        Object.keys(value)
          .sort()
          .map(function (key) {
            return JSON.stringify(key) + ":" + stableJson(value[key]);
          })
          .join(",") +
        "}"
      );
    }

    // JSON.stringify keeps nested scalars unambiguous: for example, the
    // string "null" remains distinct from the JSON null value. Source data
    // arrives through JSON, so undefined is not a supported value here.
    return JSON.stringify(value);
  }

  function textFormatter(cell) {
    const element = document.createElement("span");
    element.textContent = stableJson(cell.getValue());
    return element;
  }

  function buildColumn(field) {
    const name = String(field);
    return {
      // Tabulator assigns plain string titles through innerHTML. Stream field
      // names are logfile-controlled, so hand it an inert title and return a
      // DOM node whose textContent holds the actual label instead.
      title: "",
      titleFormatter: function () {
        const element = document.createElement("span");
        element.textContent = name;
        return element;
      },
      field: name,
      formatter: textFormatter,
    };
  }

  function buildColumns(columns) {
    return (Array.isArray(columns) ? columns : []).map(buildColumn);
  }

  function normaliseRecords(records) {
    if (!Array.isArray(records)) return [];

    return records.reduce(function (result, record) {
      if (!record || typeof record !== "object" || Array.isArray(record)) {
        return result;
      }
      const data = record.data;
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        return result;
      }

      const sequence = Number(record.browser_sequence);
      result.push({
        sequence:
          Number.isSafeInteger(sequence) && sequence >= 1 ? sequence : null,
        // Keep the producer payload separate from browser bookkeeping. In
        // particular, a producer may legitimately have a field called
        // browser_sequence without affecting the server-owned cursor.
        data: data,
      });
      return result;
    }, []);
  }

  function validStreamDataPayload(data) {
    return !!data && typeof data === "object" && !Array.isArray(data) &&
      Array.isArray(data.records) && Array.isArray(data.columns) &&
      typeof data.session_id === "string" && !!data.session_id;
  }

  function firstAvailableSequence(data) {
    const rawWindow = data && data.raw_window;
    const candidate = Number(
      rawWindow && rawWindow.first_browser_sequence != null
        ? rawWindow.first_browser_sequence
        : data && data.first_available_browser_sequence
    );
    return Number.isSafeInteger(candidate) && candidate >= 1 ? candidate : null;
  }

  function lastAvailableSequence(data) {
    const rawWindow = data && data.raw_window;
    const candidate = Number(
      rawWindow && rawWindow.last_browser_sequence != null
        ? rawWindow.last_browser_sequence
        : data && data.last_available_browser_sequence
    );
    return Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : null;
  }

  function streamRowsFromState() {
    const stored = state.streamRowsBySequence || {};
    return Object.keys(stored)
      .map(Number)
      .filter(Number.isSafeInteger)
      .sort(function (left, right) {
        return left - right;
      })
      .map(function (sequence) {
        return stored[sequence];
      });
  }

  function replaceStreamRows(records) {
    const stored = Object.create(null);
    for (const record of records) {
      if (record.sequence !== null) stored[record.sequence] = record.data;
    }
    state.streamRowsBySequence = stored;
    return streamRowsFromState();
  }

  function mergeStreamRows(records, firstAvailable) {
    const stored = state.streamRowsBySequence || Object.create(null);
    const additions = [];
    let evictedRows = false;

    for (const record of records) {
      if (
        record.sequence === null ||
        Object.prototype.hasOwnProperty.call(stored, record.sequence)
      ) {
        continue;
      }
      stored[record.sequence] = record.data;
      additions.push(record.data);
    }

    if (firstAvailable !== null) {
      for (const key of Object.keys(stored)) {
        if (Number(key) < firstAvailable) {
          delete stored[key];
          evictedRows = true;
        }
      }
    }

    state.streamRowsBySequence = stored;
    return { additions: additions, evictedRows: evictedRows };
  }

  function schemaSignature(columns) {
    return JSON.stringify(
      (Array.isArray(columns) ? columns : []).map(function (field) {
        return String(field);
      })
    );
  }

  function explorerFields(columns) {
    // Match the bounded server window, not the union of every schema ever
    // seen by this tab (including previously selected stored runs).
    const fields = [];
    for (const column of Array.isArray(columns) ? columns : []) {
      const field = String(column);
      if (!fields.includes(field)) fields.push(field);
      if (fields.length === 200) break;
    }
    return fields;
  }

  async function extendColumns(table, columns) {
    if (!table || typeof table.getColumns !== "function" || typeof table.addColumn !== "function") {
      return;
    }

    const fields = explorerFields(columns);
    const retained = new Set(fields);
    const present = new Set();
    const widths = new Map();
    try {
      for (const column of table.getColumns()) {
        if (!column || typeof column.getField !== "function") continue;
        const field = column.getField();
        if (typeof field === "string") present.add(field);
        if (retained.has(field) && typeof column.getWidth === "function") {
          widths.set(field, column.getWidth());
        }
      }
    } catch (e) {
      return;
    }

    if (state.tableUiState && state.tableUiState.groupBy &&
        !retained.has(state.tableUiState.groupBy) &&
        typeof core.setTableGrouping === "function") {
      core.setTableGrouping(null);
    }
    // Remove expired fields before adding new ones. Surviving Column objects
    // retain their order, widths and visibility; stale DOM/cells are released.
    for (const field of present) {
      if (!retained.has(field) && typeof table.deleteColumn === "function") {
        await Promise.resolve(table.deleteColumn(field));
        present.delete(field);
      }
    }
    const additions = [];
    for (const field of fields) {
      const name = String(field);
      if (present.has(name)) continue;
      present.add(name);
      try {
        additions.push(Promise.resolve(table.addColumn(buildColumn(name))));
      } catch (e) {
        // A schema extension must not turn a live row update into a full
        // table rebuild. The next poll can retry if Tabulator is transiently
        // unable to add the column.
      }
    }
    await Promise.all(additions);
    // fitDataStretch can temporarily stretch a survivor when the old last
    // column is removed. Do not let that erase a user's chosen column width.
    if (typeof table.getColumn === "function") {
      for (const [field, width] of widths) {
        const column = table.getColumn(field);
        if (column && width > 0 && typeof column.setWidth === "function" &&
            column.getWidth() !== width) column.setWidth(width);
      }
    }
  }

  function queueStreamTableMutation(operation) {
    const previous = state.streamTableMutationPromise || Promise.resolve();
    const queued = previous
      .catch(function () {
        // A failed older mutation must not prevent a newer session boundary
        // from clearing and replacing the table.
      })
      .then(operation);
    state.streamTableMutationPromise = queued;
    function finish() {
      if (state.streamTableMutationPromise === queued) {
        state.streamTableMutationPromise = null;
      }
    }
    queued.then(finish, finish);
    return queued;
  }

  async function replaceTableData(table, rows) {
    if (!table || typeof table.replaceData !== "function") return;
    await queueStreamTableMutation(function () {
      return Promise.resolve(table.replaceData(rows));
    });
  }

  async function appendTableData(table, rows) {
    if (!rows.length) return;
    if (table && typeof table.addData === "function") {
      await queueStreamTableMutation(function () {
        return Promise.resolve(table.addData(rows));
      });
      return;
    }
    // This only supports reduced test doubles and older Tabulator surfaces;
    // normal stream updates use addData and retain all table interaction.
    await replaceTableData(table, streamRowsFromState());
  }

  function updateCursor(data, records, replacing) {
    let latest = null;
    for (const record of records) {
      if (record.sequence !== null && (latest === null || record.sequence > latest)) {
        latest = record.sequence;
      }
    }

    if (latest !== null) {
      state.streamCursor = replacing || state.streamCursor === null
        ? latest
        : Math.max(state.streamCursor, latest);
      return;
    }

    const lastAvailable = lastAvailableSequence(data);
    if (replacing && lastAvailable !== null) {
      state.streamCursor = lastAvailable;
    }
  }

  function configureExplorer(table, data, rows, fields) {
    if (typeof core.configureTableExplorer !== "function") return;
    core.configureTableExplorer({
      table: table,
      payload: {
        total_rows: rows.length,
        returned_rows: rows.length,
        rows: rows,
      },
      rows: rows,
      fields: fields,
      columnDefs: buildColumns(fields),
      plotCapabilities: {
        sources: ["table", "summary"],
        liveUpdates: true,
        tableLabel: "Filtered retained rows",
        summaryLabel: "Derived summary windows",
        tableScopeDescription:
          "Stream source: the retained recent raw observation window currently loaded in this table.",
        summaryScopeDescription:
          "Stream source: currently loaded derived summary windows with their displayed aggregate bounds.",
      },
    });
  }

  function safeNonNegativeInteger(value) {
    const candidate = Number(value);
    return Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : null;
  }

  function formatByteCount(value) {
    if (value < 1024) return value + " B";
    if (value < 1024 * 1024) return (value / 1024).toFixed(1) + " KiB";
    return (value / (1024 * 1024)).toFixed(1) + " MiB";
  }

  function rawWindowSummary(data) {
    const rawWindow = data && data.raw_window;
    const count = safeNonNegativeInteger(rawWindow && rawWindow.record_count);
    const maximum = safeNonNegativeInteger(rawWindow && rawWindow.max_record_count);
    const first = firstAvailableSequence(data);
    const last = lastAvailableSequence(data);

    if (count === null) {
      return " This table is the bounded recent raw observation window.";
    }
    if (count === 0) {
      return " This table is the bounded recent raw observation window; it is currently empty.";
    }

    let summary = " This table is the bounded recent raw observation window: " + count;
    summary += maximum === null ? " retained records" : " of " + maximum + " retained records";
    if (first !== null && last !== null && last >= first) {
      summary += " (records " + first + "–" + last + ")";
    }
    return summary + ".";
  }

  function resetSummary(data) {
    if (!data || data.reset_required !== true) return null;
    const reason = data.reset_reason;
    if (reason === "session_changed") {
      return "Cursor reset: the producer session changed, so the table was replaced with its current retained window.";
    }
    if (reason === "cursor_aged_out") {
      return "Cursor reset: the earlier browser position aged out of retained raw records, so the table was replaced.";
    }
    if (reason === "cursor_ahead_of_window") {
      return "Cursor reset: the browser position could not establish continuity, so the table was replaced.";
    }
    return "Cursor reset: the table was replaced with the current retained raw window.";
  }

  function healthSummary(data) {
    const health = data && data.source_health;
    if (!health || typeof health !== "object" || Array.isArray(health)) return "";

    const unacknowledged = safeNonNegativeInteger(health.unacknowledged_source_bytes);
    const unread = safeNonNegativeInteger(health.unread_source_bytes);
    const inFlight = safeNonNegativeInteger(health.in_flight_records);
    const rejected = safeNonNegativeInteger(health.records_rejected);
    const continuityWarning = typeof data.continuity_warning === "string";
    const sourceAvailable = data.source_available;
    const sourceTransition = typeof data.source_transition === "string"
      ? data.source_transition
      : "unknown";
    const details = [];

    if (unacknowledged !== null && unacknowledged > 0) {
      details.push("Backlog: " + formatByteCount(unacknowledged) + " awaiting server acknowledgement.");
    } else if (unread !== null && unread > 0) {
      details.push("Backlog: " + formatByteCount(unread) + " awaiting source observation.");
    } else if (unacknowledged === 0 || unread === 0) {
      details.push("Backlog: caught up.");
    }

    if (inFlight !== null && inFlight > 0) {
      details.push(inFlight + " record" + (inFlight === 1 ? " is" : "s are") + " awaiting delivery.");
    }
    if (rejected !== null && rejected > 0) {
      details.push("Parser: " + rejected + " malformed or oversized source record" + (rejected === 1 ? " was" : "s were") + " skipped.");
    } else if (rejected === 0) {
      details.push("Parser: no completed source records skipped.");
    }
    if (!continuityWarning && sourceAvailable !== false && sourceTransition !== "unknown") {
      details.push("Continuity: no interruption reported by the source observer.");
    }
    return details.join(" ");
  }

  function durableHistorySummary(data) {
    const history = data && data.durable_history;
    if (!history || typeof history !== "object" || Array.isArray(history)) return "";

    const state = typeof history.state === "string" ? history.state : "unknown";
    if (state === "disabled") return "Durable history: disabled.";
    if (state === "pending") {
      return "Durable history: bounded persistence is pending.";
    }
    if (state === "complete") {
      return "Durable history: bounded observed state was persisted; it is not an audit log.";
    }
    if (state === "not_persisted") {
      return "Durable history: enabled, awaiting the first completed persistence write.";
    }
    if (state === "incomplete") {
      const message = typeof history.last_error === "string" && history.last_error
        ? " " + history.last_error
        : "";
      if (data && data.historical === true) {
        return "Durable history incomplete: this stored session has a persistence gap." + message;
      }
      return "Durable history incomplete: live observation continues, but some observed state was not persisted." + message;
    }
    return "Durable history status is unavailable.";
  }

  function setInlineStatus(data) {
    const target = document.getElementById("stream-status-inline");
    const healthTarget = document.getElementById("stream-health-inline");
    if (!target) return;

    const accepted = Number(data.accepted_records || 0);
    const lifecycle = typeof data.lifecycle === "string" ? data.lifecycle : "unknown";
    const presentation = LIFECYCLE_PRESENTATION[lifecycle];
    const continuityWarning = typeof data.continuity_warning === "string"
      ? data.continuity_warning
      : null;
    const sourceUnavailable = data.source_available === false;
    const historical = data.historical === true;
    if (historical) {
      state.streamPauseAvailable = false;
      syncStreamPauseControl();
    }
    if (typeof core.setHeaderStreamSessionState === "function") {
      core.setHeaderStreamSessionState(historical);
    }
    if (!historical && typeof core.setHeaderStreamStatus === "function") {
      core.setHeaderStreamStatus(data);
    }
    if (historical) {
      target.textContent = "Stored historical session — no current producer is represented.";
      if (healthTarget) {
        const details = [];
        const health = healthSummary(data);
        if (health) details.push(health);
        const durableHistory = durableHistorySummary(data);
        if (durableHistory) details.push(durableHistory);
        healthTarget.textContent = details.join(" ");
      }
      return;
    }
    const sourcePresentation = continuityWarning
      ? { text: continuityWarning }
      : sourceUnavailable
        ? {
            text: "Active JSONL source is unavailable; waiting for it to return.",
          }
        : presentation;
    const recordSummary = accepted <= 0
      ? " Waiting for appended JSON objects."
      : rawWindowSummary(data);
    target.textContent = sourcePresentation
      ? sourcePresentation.text + recordSummary
      : "Lifecycle status is unavailable; application state is unknown." + recordSummary;
    if (healthTarget) {
      const details = [];
      const reset = resetSummary(data);
      if (reset) details.push(reset);
      const health = healthSummary(data);
      if (health) details.push(health);
      const durableHistory = durableHistorySummary(data);
      if (durableHistory) details.push(durableHistory);
      healthTarget.textContent = details.join(" ");
    }
  }

  function summaryRevision(data) {
    const revision = Number(data && data.summary_revision);
    return Number.isSafeInteger(revision) && revision >= 0 ? revision : null;
  }

  function summaryTierLabel(window) {
    const tier = window && typeof window.tier === "string" ? window.tier : "unknown";
    if (tier === "cumulative") return "Cumulative derived history";
    if (tier === "coarse") return "Coarse derived window";
    if (tier === "fine") return "Fine derived window";
    return "Derived summary window";
  }

  function summaryResolutionLabel(window) {
    const resolution = window && window.resolution;
    if (!resolution || typeof resolution !== "object") return "Resolution unavailable";
    if (resolution.kind === "cumulative") return "Cumulative oldest history";
    const seconds = safeNonNegativeInteger(resolution.seconds);
    return seconds === null ? "Fixed resolution unavailable" : "Fixed " + seconds + " second resolution";
  }

  function exactFractionText(value) {
    if (!value || typeof value !== "object") return "not available";
    const numerator = typeof value.numerator === "string" ? value.numerator : null;
    const denominator = typeof value.denominator === "string" ? value.denominator : null;
    if (!numerator || !denominator) return "not available";
    return denominator === "1" ? numerator : numerator + "/" + denominator;
  }

  function exactCountText(value) {
    if (typeof value === "string" && /^\d+$/.test(value)) return value;
    const safe = safeNonNegativeInteger(value);
    return safe === null ? "unknown" : String(safe);
  }

  function addSurfaceText(parent, className, text) {
    const paragraph = document.createElement("p");
    paragraph.className = className;
    paragraph.textContent = text;
    parent.appendChild(paragraph);
    return paragraph;
  }

  function countLabel(value, singular, plural) {
    const count = exactCountText(value);
    return count + " " + (count === "1" ? singular : plural);
  }

  function formatObservedTime(value) {
    if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) {
      return "Time unavailable";
    }
    if (typeof core.fmtLocalTime === "function") return core.fmtLocalTime(value);
    return new Date(value).toLocaleString();
  }

  function appendTechnicalDetails(parent, rows, rawValue) {
    const details = document.createElement("details");
    details.className = "ps-stream-technical";
    const summary = document.createElement("summary");
    summary.textContent = "Technical details";
    details.appendChild(summary);

    const list = document.createElement("dl");
    list.className = "ps-stream-technical__facts";
    for (const row of rows) {
      if (!Array.isArray(row) || row.length !== 2 || row[1] == null || row[1] === "") continue;
      const item = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = String(row[0]);
      description.textContent = String(row[1]);
      item.appendChild(term);
      item.appendChild(description);
      list.appendChild(item);
    }
    details.appendChild(list);

    if (rawValue !== undefined) {
      const rawLabel = document.createElement("p");
      rawLabel.className = "ps-stream-technical__raw-label";
      rawLabel.textContent = "Raw observed data";
      details.appendChild(rawLabel);
      const raw = document.createElement("pre");
      raw.className = "ps-stream-technical__raw";
      raw.textContent = stableJson(rawValue);
      details.appendChild(raw);
    }
    parent.appendChild(details);
    return details;
  }

  function comparisonUnavailableExplanation(reason) {
    if (reason === "session_changed") {
      return "the producer started a different stream session";
    }
    if (reason === "stream_state_changed") {
      return "plotsrv restarted its observation of this stream";
    }
    if (reason === "checkpoint_missing") {
      return "this browser has no earlier visit to compare with yet";
    }
    if (reason === "checkpoint_storage_unavailable") {
      return "this browser could not read the previous visit information";
    }
    if (reason === "counter_regressed") {
      return "the earlier and current stream counts do not form a safe comparison";
    }
    if (reason === "continuity_uncertain") {
      return "stream continuity may have been interrupted while you were away";
    }
    if (reason === "checkpoint_continuity_insufficient") {
      return "continuity during the previous visit was not certain";
    }
    if (reason === "source_unavailable") {
      return "the source is currently unavailable";
    }
    return "the previous visit information is not compatible with the current stream";
  }

  function unavailableVisitTitle(reason, incomplete) {
    if (reason === "session_changed") return "A new stream session is active";
    if (reason === "stream_state_changed") return "The comparison has restarted";
    if (reason === "checkpoint_missing") return "Comparison starts with this visit";
    if (reason === "checkpoint_storage_unavailable") return "Previous visit unavailable";
    if (reason === "source_unavailable") return "The stream source is unavailable";
    if (reason === "continuity_uncertain" ||
        reason === "checkpoint_continuity_insufficient") {
      return "Some activity may be missing";
    }
    return incomplete ? "An exact comparison is not possible" : "No reliable comparison yet";
  }

  function visitTechnicalRows(comparison, data) {
    const deltas = comparison && comparison.deltas;
    const checkpoint = comparison && comparison.checkpoint_identity;
    const current = comparison && comparison.current_identity;
    const cumulative = data && data.cumulative;
    const rows = [
      ["Comparison status", comparison && comparison.status],
      ["Exact deltas", comparison && comparison.exact_deltas === true ? "yes" : "no"],
      ["Checkpoint reason", comparison && comparison.unavailable_reason],
      ["Continuity", comparison && comparison.continuity && comparison.continuity.status],
      ["Continuity detail", comparison && comparison.continuity && comparison.continuity.warning],
      ["Checkpoint session", checkpoint && checkpoint.session_id],
      ["Current session", current && current.session_id],
      ["Checkpoint stream instance", checkpoint && checkpoint.stream_instance_id],
      ["Current stream instance", current && current.stream_instance_id],
      ["Counter schema", current && current.counter_schema_version],
      ["Accepted-record delta", deltas && deltas.total_records],
      ["Noteworthy-item delta", deltas && deltas.noteworthy_items],
      ["Recognised-severity delta", deltas && deltas.recognized_severity_records],
      ["Rejected-record delta", deltas && deltas.rejected_source_records],
      ["Continuity-event delta", deltas && deltas.continuity_events],
      ["Latest sequence delta", deltas && deltas.latest_server_sequence],
      ["First session observation", cumulative && cumulative.first_observed_at],
      ["Latest session observation", cumulative && cumulative.last_observed_at],
    ];
    if (deltas && deltas.recognized_severity_counts) {
      for (const severity of ["warning", "emergency", "alert", "critical", "fatal", "error"]) {
        rows.push([severity + " delta", deltas.recognized_severity_counts[severity]]);
      }
    }
    return rows;
  }

  function validVisitDeltas(comparison) {
    const deltas = comparison && comparison.deltas;
    if (!deltas || typeof deltas !== "object" || Array.isArray(deltas)) return null;
    if (typeof deltas.total_records !== "string" ||
        typeof deltas.recognized_severity_records !== "string" ||
        typeof deltas.rejected_source_records !== "string" ||
        typeof deltas.continuity_events !== "string" ||
        typeof deltas.noteworthy_items !== "string" ||
        typeof deltas.noteworthy_source_records !== "string" ||
        typeof deltas.system_notices !== "string" ||
        typeof deltas.latest_server_sequence !== "string" ||
        !deltas.recognized_severity_counts ||
        typeof deltas.recognized_severity_counts !== "object" ||
        Array.isArray(deltas.recognized_severity_counts)) {
      return null;
    }
    const decimal = /^(?:0|[1-9]\d*)$/;
    if (!decimal.test(deltas.total_records) || !decimal.test(deltas.recognized_severity_records) ||
        !decimal.test(deltas.rejected_source_records) || !decimal.test(deltas.continuity_events) ||
        !decimal.test(deltas.noteworthy_items) || !decimal.test(deltas.noteworthy_source_records) ||
        !decimal.test(deltas.system_notices) || !decimal.test(deltas.latest_server_sequence)) {
      return null;
    }
    for (const severityName of ["warning", "emergency", "alert", "critical", "fatal", "error"]) {
      if (typeof deltas.recognized_severity_counts[severityName] !== "string" ||
          !decimal.test(deltas.recognized_severity_counts[severityName])) {
        return null;
      }
    }
    return deltas;
  }

  function renderVisitComparison(comparison, data) {
    const status = document.getElementById("stream-since-visit-status");
    const target = document.getElementById("stream-since-visit-details");
    if (!status || !target) return;

    target.replaceChildren();
    const available = comparison && comparison.status === "available" &&
      comparison.exact_deltas === true;
    const deltas = available ? validVisitDeltas(comparison) : null;
    const detail = document.createElement("article");
    const incomplete = comparison && comparison.status === "incomplete";
    detail.dataset.comparisonStatus = deltas ? "available" : (incomplete ? "incomplete" : "unavailable");

    if (!deltas) {
      const reason = comparison && typeof comparison.unavailable_reason === "string"
        ? comparison.unavailable_reason
        : "checkpoint_missing";
      const title = unavailableVisitTitle(reason, incomplete);
      detail.className = "ps-stream-returning__detail ps-stream-returning__detail--unavailable";
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-title",
        title
      );
      const message = "plotsrv cannot give an exact since-last-visit count because " +
        comparisonUnavailableExplanation(reason) + ".";
      status.textContent = title;
      addSurfaceText(detail, "ps-stream-returning__detail-copy", message);
      const latest = data && data.cumulative && data.cumulative.last_observed_at;
      if (latest) {
        addSurfaceText(
          detail,
          "ps-stream-returning__detail-meta",
          "Latest observed stream activity: " + formatObservedTime(latest) + "."
        );
      }
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-note",
        "No record count is shown: an unavailable comparison is not the same as no change."
      );
      appendTechnicalDetails(detail, visitTechnicalRows(comparison, data));
      target.appendChild(detail);
      return;
    }

    detail.className = "ps-stream-returning__detail ps-stream-returning__detail--available";
    const total = exactCountText(deltas.total_records);
    const title = total === "0"
      ? "No new records observed"
      : countLabel(total, "new record", "new records");
    status.textContent = title;
    addSurfaceText(detail, "ps-stream-returning__detail-title", title);
    addSurfaceText(
      detail,
      "ps-stream-returning__detail-copy",
      total === "0"
        ? "plotsrv accepted no new records during this exact comparison."
        : "plotsrv accepted these records since this browser's previous compatible visit."
    );

    const noteworthy = exactCountText(deltas.noteworthy_items);
    if (noteworthy === "0") {
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-copy",
        "No noteworthy activity was classified during this comparison."
      );
    } else if (noteworthy !== "unknown") {
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-copy",
        countLabel(noteworthy, "noteworthy item was", "noteworthy items were") +
          " observed; the Noteworthy tab shows the retained selection."
      );
    }

    const latest = data && data.cumulative && data.cumulative.last_observed_at;
    if (total !== "0" && latest) {
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-meta",
        "Latest relevant activity: " + formatObservedTime(latest) + "."
      );
    }
    addSurfaceText(
      detail,
      "ps-stream-returning__detail-note",
      "No continuity interruption was reported for this comparison."
    );
    appendTechnicalDetails(detail, visitTechnicalRows(comparison, data));
    target.appendChild(detail);
  }

  function renderHistoricalVisitNotice(data) {
    const status = document.getElementById("stream-since-visit-status");
    const target = document.getElementById("stream-since-visit-details");
    if (status) status.textContent = "Stored session selected";
    if (!target) return;
    target.replaceChildren();
    const detail = document.createElement("article");
    detail.className = "ps-stream-returning__detail ps-stream-returning__detail--historical";
    detail.dataset.comparisonStatus = "historical";
    addSurfaceText(detail, "ps-stream-returning__detail-title", "Since last visit does not apply");
    addSurfaceText(
      detail,
      "ps-stream-returning__detail-copy",
      "You are viewing a fixed stored session rather than the current live stream."
    );
    appendTechnicalDetails(detail, [
      ["Session mode", "stored historical session"],
      ["Session ID", data && data.session_id],
      ["Stored update", data && data.historical_updated_at],
      ["Lifecycle at storage", data && data.lifecycle],
    ]);
    target.appendChild(detail);
  }

  function systemNoticeLabel(event) {
    if (event === "source_continuity_uncertain") return "Continuity may have been interrupted";
    if (event === "source_continuity_transition") return "Source continuity changed";
    if (event === "source_record_rejection_reported") return "Some source records were skipped";
    if (event === "source_rejection_counter_reset") return "Source parser count restarted";
    if (event === "stream_schema_changed") return "Data structure changed";
    return "Stream notice";
  }

  function systemNoticeExplanation(item) {
    const event = item && item.event;
    if (event === "source_continuity_uncertain") {
      return "plotsrv could not confirm uninterrupted observation of the source.";
    }
    if (event === "source_continuity_transition") {
      return "The observed source was replaced, truncated, or otherwise changed.";
    }
    if (event === "source_record_rejection_reported") {
      const rejected = exactCountText(item.rejected_record_count);
      return rejected === "unknown"
        ? "The source parser reported records it could not accept."
        : countLabel(rejected, "completed source record was", "completed source records were") +
          " malformed or too large to accept.";
    }
    if (event === "source_rejection_counter_reset") {
      return "The producer's rejected-record counter began a new count.";
    }
    if (event === "stream_schema_changed") {
      return "One or more fields appeared in the retained stream data.";
    }
    return "plotsrv retained a typed stream event this browser does not yet recognise.";
  }

  function systemNoticeCategory(event) {
    if (event === "source_continuity_uncertain" ||
        event === "source_continuity_transition" ||
        event === "source_record_rejection_reported") return "warning";
    if (event === "stream_schema_changed") return "information";
    return "neutral";
  }

  function recognizedStructuredSeverity(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    for (const field of ["severity", "level"]) {
      if (typeof data[field] !== "string") continue;
      const value = data[field].toLowerCase();
      if (value === "warn") return "warning";
      if (["warning", "emergency", "alert", "critical", "fatal", "error"].includes(value)) {
        return value;
      }
    }
    return null;
  }

  function sentenceCase(value) {
    const text = String(value || "");
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }

  function friendlyObservedValue(value) {
    const rendered = stableJson(value);
    return rendered.length > 100 ? rendered.slice(0, 97) + "…" : rendered;
  }

  function noteworthySourcePresentation(item) {
    const reason = typeof item.noteworthy_reason === "string" ? item.noteworthy_reason : "";
    const field = typeof item.field_name === "string" ? item.field_name : "field";
    if (reason === "structured_severity") {
      const severity = sentenceCase(item.severity || "Warning");
      return {
        title: severity + " · source",
        explanation: "A source record reported the recognised structured severity “" +
          String(item.severity) + "”.",
        category: item.severity === "warning" ? "warning" : "critical",
      };
    }
    if (reason === "first_low_cardinality_value") {
      return {
        title: "New " + field + " appeared",
        explanation: "plotsrv observed the value " + friendlyObservedValue(item.field_value) +
          " for “" + field + "” for the first time in this session.",
        category: "information",
      };
    }
    if (reason === "numeric_minimum") {
      return {
        title: "A new low value was observed",
        explanation: "“" + field + "” reached a new observed low of " +
          friendlyObservedValue(item.field_value) + ".",
        category: "information",
      };
    }
    if (reason === "numeric_maximum") {
      return {
        title: "A new high value was observed",
        explanation: "“" + field + "” reached a new observed high of " +
          friendlyObservedValue(item.field_value) + ".",
        category: "information",
      };
    }
    return {
      title: "Noteworthy source record",
      explanation: "plotsrv retained this record using a classification this browser does not yet recognise.",
      category: "neutral",
    };
  }

  function appendNoteworthyTime(article, value) {
    const meta = document.createElement("div");
    meta.className = "ps-stream-noteworthy__item-meta";
    const time = document.createElement("time");
    time.textContent = formatObservedTime(value);
    const parsed = typeof value === "string" ? Date.parse(value) : NaN;
    if (Number.isFinite(parsed)) {
      time.dateTime = value;
      time.title = "Observed at " + value;
    }
    meta.appendChild(time);
    if (Number.isFinite(parsed)) {
      const seconds = Math.max(0, Math.floor((Date.now() - parsed) / 1000));
      const age = seconds < 60 ? seconds + "s ago" : seconds < 3600 ? Math.floor(seconds / 60) + "m ago" : seconds < 86400 ? Math.floor(seconds / 3600) + "h ago" : Math.floor(seconds / 86400) + "d ago";
      addSurfaceText(meta, "ps-stream-noteworthy__age", parsed > Date.now() ? "future timestamp" : age);
    }
    article.appendChild(meta);
  }

  function noteworthyValue(item) {
    const scalar = function (value) { return value !== null && value !== undefined && ["string", "number", "boolean"].includes(typeof value); };
    if (scalar(item.field_value)) return String(item.field_name || "Value") + ": " + String(item.field_value).slice(0, 240);
    if (scalar(item.data.value)) return "Value: " + String(item.data.value).slice(0, 240);
    // Generic logs need not contain a field literally named "value".
    const fields = Object.keys(item.data).filter(function (key) {
      return !["timestamp", "time", "level", "severity", "log_level", "message", "sequence"].includes(key) && scalar(item.data[key]);
    }).slice(0, 3);
    return fields.map(function (key) { return key.slice(0, 60) + ": " + String(item.data[key]).slice(0, 80); }).join(" · ");
  }

  function appendNoteworthySourceItem(target, item) {
    if (item.object_type !== "stream_noteworthy_source_record" ||
        item.kind !== "source_record" || !item.data ||
        typeof item.data !== "object" || Array.isArray(item.data)) {
      return false;
    }
    if (item.noteworthy_reason === "structured_severity" &&
        (typeof item.severity !== "string" ||
          recognizedStructuredSeverity(item.data) !== item.severity)) {
      // The server has already classified this from an allowlisted field, but
      // do not let a malformed transport payload manufacture a severity label.
      return false;
    }
    const article = document.createElement("article");
    const presentation = noteworthySourcePresentation(item);
    article.className = "ps-stream-noteworthy__item ps-stream-noteworthy__item--" +
      presentation.category;
    article.dataset.noteworthyKind = "source_record";
    article.dataset.noteworthyObjectType = String(item.object_type || "unknown");
    article.dataset.noteworthyCategory = presentation.category;
    appendNoteworthyTime(article, item.observed_at);
    addSurfaceText(article, "ps-stream-noteworthy__item-title", presentation.title);
    const value = noteworthyValue(item);
    if (value) addSurfaceText(article, "ps-stream-noteworthy__value", value);
    if (typeof item.data.message === "string" && item.data.message) {
      addSurfaceText(article, "ps-stream-noteworthy__item-copy", item.data.message.slice(0, 300));
    }
    const sequence = exactCountText(item.source_browser_sequence);
    const observedAt = typeof item.observed_at === "string" ? item.observed_at : "time unavailable";
    appendTechnicalDetails(article, [
      ["Why retained", presentation.explanation],
      ["Object type", item.object_type],
      ["Noteworthy reason", item.noteworthy_reason],
      ["Noteworthy sequence", item.noteworthy_sequence],
      ["Source browser sequence", sequence],
      ["Observed at", observedAt],
      ["Structured severity", item.severity],
      ["Field", item.field_name],
      ["Observed field value", item.field_value === undefined ? null : stableJson(item.field_value)],
    ], item.data);
    target.appendChild(article);
    return true;
  }

  function appendNoteworthySystemItem(target, item) {
    if (item.object_type !== "stream_system_notice" || item.kind !== "system_notice") {
      return false;
    }
    const article = document.createElement("article");
    const category = systemNoticeCategory(item.event);
    article.className = "ps-stream-noteworthy__item ps-stream-noteworthy__item--" + category;
    article.dataset.noteworthyKind = "system_notice";
    article.dataset.noteworthyObjectType = String(item.object_type || "unknown");
    article.dataset.noteworthyCategory = category;
    appendNoteworthyTime(article, item.observed_at);
    addSurfaceText(article, "ps-stream-noteworthy__item-title", systemNoticeLabel(item.event));
    addSurfaceText(article, "ps-stream-noteworthy__item-copy", systemNoticeExplanation(item));
    appendTechnicalDetails(article, [
      ["Object type", item.object_type],
      ["Event type", item.event],
      ["Noteworthy sequence", item.noteworthy_sequence],
      ["Observed at", item.observed_at],
      ["Source transition", item.source_transition],
      ["Continuity detail", item.continuity_warning],
      ["Rejected-record count", item.rejected_record_count],
      ["Schema revision", item.schema_revision],
    ], item);
    target.appendChild(article);
    return true;
  }

  function appendUnknownNoteworthyItem(target, item) {
    if (typeof item.object_type !== "string" || !item.object_type ||
        typeof item.kind !== "string" || !item.kind) return false;
    const article = document.createElement("article");
    article.className = "ps-stream-noteworthy__item ps-stream-noteworthy__item--neutral";
    article.dataset.noteworthyKind = "unknown";
    article.dataset.noteworthyObjectType = item.object_type;
    article.dataset.noteworthyCategory = "neutral";
    appendNoteworthyTime(article, item.observed_at);
    addSurfaceText(article, "ps-stream-noteworthy__item-title", "Noteworthy stream item");
    addSurfaceText(
      article,
      "ps-stream-noteworthy__item-copy",
      "plotsrv retained an item type this browser does not yet recognise."
    );
    appendTechnicalDetails(article, [
      ["Object type", item.object_type],
      ["Item kind", item.kind],
      ["Observed at", item.observed_at],
    ], item);
    target.appendChild(article);
    return true;
  }

  function decimalCountGreaterThan(left, right) {
    const leftText = exactCountText(left);
    const rightText = exactCountText(right);
    if (leftText === "unknown" || rightText === "unknown" || typeof BigInt !== "function") {
      return false;
    }
    try {
      return BigInt(leftText) > BigInt(rightText);
    } catch (e) {
      return false;
    }
  }

  function renderNoteworthy(payload, cumulative) {
    const status = document.getElementById("stream-noteworthy-status");
    const target = document.getElementById("stream-noteworthy-items");
    if (!status || !target) return;

    target.replaceChildren();
    if (!payload || payload.object_type !== "stream_noteworthy_collection" ||
        !Array.isArray(payload.items)) {
      status.textContent = "Noteworthy activity could not be loaded.";
      const empty = document.createElement("div");
      empty.className = "ps-stream-insight-empty ps-stream-insight-empty--error";
      addSurfaceText(empty, "ps-stream-insight-empty__title", "Unable to show noteworthy activity");
      addSurfaceText(
        empty,
        "ps-stream-insight-empty__copy",
        "The stream itself may still be available. Try reopening Insights after the next update."
      );
      target.appendChild(empty);
      return;
    }

    let shown = 0;
    let invalid = 0;
    let sourceWarnings = 0;
    for (const item of payload.items) {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        invalid += 1;
        continue;
      }
      let appended = false;
      if (item.object_type === "stream_noteworthy_source_record") {
        appended = appendNoteworthySourceItem(target, item);
      } else if (item.object_type === "stream_system_notice") {
        appended = appendNoteworthySystemItem(target, item);
      } else {
        appended = appendUnknownNoteworthyItem(target, item);
      }
      shown += appended ? 1 : 0;
      if (appended && item.object_type === "stream_noteworthy_source_record" && item.noteworthy_reason === "structured_severity" && item.severity === "warning") sourceWarnings += 1;
      invalid += appended ? 0 : 1;
    }

    const maximum = safeNonNegativeInteger(payload.max_retained_items);
    const retained = safeNonNegativeInteger(payload.retained_item_count);
    const total = cumulative && cumulative.noteworthy_items;
    if (shown === 0) {
      const agedOut = decimalCountGreaterThan(total, "0");
      status.textContent = agedOut ? "No recent noteworthy items" : "Nothing noteworthy retained yet";
      const empty = document.createElement("div");
      empty.className = "ps-stream-insight-empty";
      addSurfaceText(
        empty,
        "ps-stream-insight-empty__title",
        agedOut ? "Earlier items have aged out" : "No noteworthy activity yet"
      );
      addSurfaceText(
        empty,
        "ps-stream-insight-empty__copy",
        agedOut
          ? "Noteworthy activity occurred earlier in this session, but it is no longer in the bounded selection."
          : "plotsrv has not retained any deterministically classified noteworthy items for this session."
      );
      if (invalid > 0) {
        addSurfaceText(
          empty,
          "ps-stream-insight-empty__note",
          "Some retained item data was incomplete and could not be displayed."
        );
      }
      target.appendChild(empty);
      return;
    }
    status.textContent = countLabel(shown, "recent item to review", "recent items to review");
    if (sourceWarnings) status.textContent += " · " + sourceWarnings + " source-reported warnings. A warning label does not necessarily mean a rare event.";
    const agedOut = decimalCountGreaterThan(total, retained === null ? shown : retained);
    if (agedOut || invalid > 0) {
      const note = document.createElement("p");
      note.className = "ps-stream-noteworthy__retention-note";
      const messages = [];
      if (agedOut) messages.push("Earlier noteworthy items have aged out of this bounded selection.");
      if (invalid > 0) messages.push("Some retained item data was incomplete and could not be displayed.");
      if (maximum !== null) messages.push("Up to " + maximum + " items are retained.");
      note.textContent = messages.join(" ");
      target.appendChild(note);
    }
  }

  function addSummaryText(parent, className, text) {
    return addSurfaceText(parent, className, text);
  }

  function friendlyDuration(seconds) {
    const value = safeNonNegativeInteger(seconds);
    if (value === null) return "resolution unavailable";
    if (value < 60) return value + "-second summaries";
    if (value % 86400 === 0) {
      const days = value / 86400;
      return days + "-day summaries";
    }
    if (value % 3600 === 0) {
      const hours = value / 3600;
      return hours + "-hour summaries";
    }
    if (value % 60 === 0) {
      const minutes = value / 60;
      return minutes + "-minute summaries";
    }
    return value + "-second summaries";
  }

  function friendlySummaryResolution(window) {
    const resolution = window && window.resolution;
    if (!resolution || typeof resolution !== "object") return "Resolution unavailable";
    if (resolution.kind === "cumulative") return "Combined oldest period";
    return friendlyDuration(resolution.seconds);
  }

  function friendlyFractionText(value) {
    if (!value || typeof value !== "object") return "not available";
    const numerator = typeof value.numerator === "string" ? value.numerator : null;
    const denominator = typeof value.denominator === "string" ? value.denominator : null;
    if (!numerator || !denominator || denominator === "0") return "not available";
    if (denominator === "1") return numerator;
    const approximate = Number(numerator) / Number(denominator);
    if (!Number.isFinite(approximate)) return exactFractionText(value);
    return "≈" + String(Math.round(approximate * 1000) / 1000);
  }

  function sumWindowCounts(windows) {
    if (typeof BigInt !== "function") return "unknown";
    let total = BigInt(0);
    try {
      for (const window of windows) {
        const count = exactCountText(window.record_count);
        if (count === "unknown") return "unknown";
        total += BigInt(count);
      }
    } catch (e) {
      return "unknown";
    }
    return total.toString();
  }

  function appendSummaryOverview(target, payload, windows, data) {
    const historical = payload.historical === true || (data && data.historical === true);
    const overview = document.createElement("article");
    overview.className = "ps-stream-summary__overview";
    overview.dataset.sessionMode = historical ? "stored" : "current";
    addSummaryText(
      overview,
      "ps-stream-summary__overview-title",
      historical ? "History for this stored session" : "Older history is available"
    );
    addSummaryText(
      overview,
      "ps-stream-summary__overview-copy",
      historical
        ? "These summaries describe older observations retained with this fixed session."
        : "Older observations have been summarised as they left the recent-data window."
    );

    let from = null;
    let until = null;
    for (const window of windows) {
      const range = window && window.observation_window;
      const candidateFrom = range && typeof range.from === "string" ? range.from : null;
      const candidateUntil = range && typeof range.until === "string" ? range.until : null;
      if (candidateFrom && Number.isFinite(Date.parse(candidateFrom)) &&
          (!from || Date.parse(candidateFrom) < Date.parse(from))) {
        from = candidateFrom;
      }
      if (candidateUntil && Number.isFinite(Date.parse(candidateUntil)) &&
          (!until || Date.parse(candidateUntil) > Date.parse(until))) {
        until = candidateUntil;
      }
    }
    const resolutions = [];
    for (const window of windows) {
      const label = friendlySummaryResolution(window);
      if (!resolutions.includes(label)) resolutions.push(label);
    }
    const facts = document.createElement("dl");
    facts.className = "ps-stream-summary__overview-facts";
    const factRows = [
      ["Period", from && until
        ? formatObservedTime(from) + " to " + formatObservedTime(until)
        : "Time range unavailable"],
      ["Older records represented", exactCountText(sumWindowCounts(windows))],
      ["Detail", resolutions.join(", ")],
      ["Session", historical ? "Stored session" : "Current session"],
    ];
    for (const row of factRows) {
      const item = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = row[0];
      description.textContent = row[1];
      item.appendChild(term);
      item.appendChild(description);
      facts.appendChild(item);
    }
    overview.appendChild(facts);

    const durable = data && data.durable_history;
    if (durable && durable.state === "incomplete") {
      addSummaryText(
        overview,
        "ps-stream-summary__caveat ps-stream-summary__caveat--warning",
        historical
          ? "Some persisted history for this stored session is incomplete."
          : "Live observation continues, but some history could not be saved."
      );
    }
    if (data && (data.continuity_warning || data.source_transition === "replaced" ||
        data.source_transition === "truncated")) {
      addSummaryText(
        overview,
        "ps-stream-summary__caveat",
        "Source continuity may be incomplete for part of this history."
      );
    }
    const truncated = windows.some(function (window) {
      const truncation = window && window.truncation;
      const count = exactCountText(truncation && truncation.untracked_field_observations);
      return count !== "unknown" && count !== "0";
    });
    if (truncated) {
      addSummaryText(
        overview,
        "ps-stream-summary__caveat",
        "Some field-level detail was omitted to keep this history bounded."
      );
    }

    const retention = payload.summary_retention || {};
    appendTechnicalDetails(overview, [
      ["Object type", payload.object_type],
      ["Session ID", payload.session_id],
      ["Session mode", historical ? "stored" : "current"],
      ["Summary revision", payload.summary_revision],
      ["Summary window count", payload.summary_window_count],
      ["Maximum fine windows", retention.max_fine_windows],
      ["Maximum coarse windows", retention.max_coarse_windows],
      ["Maximum retained windows", retention.max_retained_windows],
      ["Coarse window factor", retention.coarse_window_factor],
      ["Maximum fields per window", retention.max_fields_per_window],
      ["Maximum categories per field", retention.max_categories_per_field],
      ["Persistent history state", durable && durable.state],
      ["Persistent history error", durable && durable.last_error],
    ], retention);
    target.appendChild(overview);
  }

  function appendPrimarySummaryFields(windowElement, fields) {
    if (!Array.isArray(fields) || fields.length === 0) return;
    const list = document.createElement("ul");
    list.className = "ps-stream-summary__highlights";
    let shown = 0;
    for (const field of fields) {
      if (!field || typeof field !== "object" || !field.numeric ||
          typeof field.numeric !== "object") continue;
      const name = typeof field.field === "string" ? field.field : "unnamed field";
      const item = document.createElement("li");
      const numeric = field.numeric;
      item.className = "ps-stream-summary__highlight";
      item.textContent = "“" + name + "”: average " + friendlyFractionText(numeric.mean) +
        ", range " + friendlyFractionText(numeric.minimum) + "–" +
        friendlyFractionText(numeric.maximum) + ".";
      list.appendChild(item);
      shown += 1;
      if (shown >= 3) break;
    }
    if (shown > 0) windowElement.appendChild(list);
  }

  function summaryWindowTitle(window) {
    const tier = window && window.tier;
    if (tier === "cumulative") return "Oldest available period";
    if (tier === "coarse") return "Earlier activity";
    if (tier === "fine") return "Recent older activity";
    return "Older activity summary";
  }

  function appendSummaryWindow(target, window) {
    const rawTier = typeof window.tier === "string" ? window.tier : "unknown";
    const tier = ["fine", "coarse", "cumulative"].includes(rawTier)
      ? rawTier
      : "unknown";
    const article = document.createElement("article");
    article.className = "ps-stream-summary__window ps-stream-summary__window--" + tier;
    article.dataset.derivedSummary = "true";
    article.dataset.summaryObjectType = String(window.object_type || "unknown");
    addSummaryText(article, "ps-stream-summary__window-title", summaryWindowTitle(window));
    const range = window.observation_window;
    const from = range && typeof range.from === "string" ? range.from : null;
    const until = range && typeof range.until === "string" ? range.until : null;
    addSummaryText(
      article,
      "ps-stream-summary__window-meta",
      countLabel(window.record_count, "older record", "older records") + " represented · " +
        friendlySummaryResolution(window)
    );
    if (from && until) {
      addSummaryText(
        article,
        "ps-stream-summary__window-period",
        formatObservedTime(from) + " to " + formatObservedTime(until)
      );
    }
    appendPrimarySummaryFields(article, window.fields);

    const truncation = window.truncation || {};
    appendTechnicalDetails(article, [
      ["Object type", window.object_type],
      ["Derived aggregate", window.derived === true ? "yes" : "no"],
      ["Internal tier", summaryTierLabel(window)],
      ["Internal resolution", summaryResolutionLabel(window)],
      ["Boundary from", from],
      ["Boundary until", until],
      ["Record count", window.record_count],
      ["Record bytes", window.record_bytes],
      ["First browser sequence", window.first_browser_sequence],
      ["Last browser sequence", window.last_browser_sequence],
      ["Field observation count", window.field_observation_count],
      ["Maximum tracked fields", truncation.max_fields],
      ["Untracked field observations", truncation.untracked_field_observations],
    ], window);
    target.appendChild(article);
  }

  function renderSummary(payload, data) {
    if (typeof core.setTablePlotSummaryRows === "function") {
      core.setTablePlotSummaryRows(payload);
    }
    const status = document.getElementById("stream-summary-status");
    const target = document.getElementById("stream-summary-windows");
    if (!status || !target) return;

    const rawWindows = Array.isArray(payload && payload.windows) ? payload.windows : [];
    const windows = rawWindows.filter(function (window) {
      return window && typeof window === "object" && !Array.isArray(window) &&
        window.derived === true &&
        window.object_type === "derived_stream_summary_window";
    });
    target.replaceChildren();
    if (!windows.length) {
      const invalid = rawWindows.length > 0;
      status.textContent = invalid ? "History information could not be read" : "No older history yet";
      const empty = document.createElement("div");
      empty.className = invalid
        ? "ps-stream-insight-empty ps-stream-insight-empty--error"
        : "ps-stream-insight-empty";
      addSummaryText(
        empty,
        "ps-stream-insight-empty__title",
        invalid ? "Unable to show older history" : "No older history yet"
      );
      addSummaryText(
        empty,
        "ps-stream-insight-empty__copy",
        invalid
          ? "The returned summary data was not in a recognised derived-history format."
          : data && data.historical === true
            ? "This stored session has no older summary windows."
            : "Recent records remain in the table. Older records will be summarised here as the recent-data window advances."
      );
      appendTechnicalDetails(empty, [
        ["Session", payload && payload.session_id],
        ["Session mode", data && data.historical === true ? "stored" : "current"],
        ["Summary revision", payload && payload.summary_revision],
        ["Returned window count", rawWindows.length],
        ["Persistent history state", data && data.durable_history && data.durable_history.state],
      ]);
      target.appendChild(empty);
      return;
    }

    const historical = payload.historical === true || (data && data.historical === true);
    status.textContent = countLabel(
      windows.length,
      historical ? "summary for this stored session" : "older summary available",
      historical ? "summaries for this stored session" : "older summaries available"
    );
    appendSummaryOverview(target, payload, windows, data);
    for (const window of windows) {
      appendSummaryWindow(target, window);
    }
  }

  function showSummaryError() {
    const status = document.getElementById("stream-summary-status");
    const target = document.getElementById("stream-summary-windows");
    if (status) status.textContent = "Unable to load history";
    if (target && target.children.length === 0) {
      const empty = document.createElement("div");
      empty.className = "ps-stream-insight-empty ps-stream-insight-empty--error";
      addSummaryText(empty, "ps-stream-insight-empty__title", "History could not be loaded");
      addSummaryText(
        empty,
        "ps-stream-insight-empty__copy",
        "Recent raw records remain available in the table."
      );
      target.appendChild(empty);
    }
  }

  function summaryScope(data) {
    const historical = !!(data && data.historical === true);
    const sessionId = data && typeof data.session_id === "string" && data.session_id
      ? data.session_id
      : null;
    return {
      historical: historical,
      sessionId: sessionId,
      key: (historical ? "stored:" : "current:") + (sessionId || "unknown"),
    };
  }

  function invalidateStreamSummaryLoads() {
    state.streamSummaryGeneration = Number.isSafeInteger(state.streamSummaryGeneration)
      ? state.streamSummaryGeneration + 1
      : 1;
    state.streamSummaryDesired = null;
    const controller = state.streamSummaryLoadController;
    state.streamSummaryLoadController = null;
    state.streamSummaryLoadPromise = null;
    if (controller && typeof controller.abort === "function") controller.abort();
  }

  function summaryWorkIsCurrent(work) {
    if (!work || work.generation !== state.streamSummaryGeneration) return false;
    const selected = selectedHistoricalSessionId();
    return work.scope.historical
      ? selected === work.scope.sessionId || (selected === null && state.streamAwaitingReceiverSession === true)
      : selected === null;
  }

  function startSummaryDrain() {
    const generation = Number.isSafeInteger(state.streamSummaryGeneration)
      ? state.streamSummaryGeneration
      : 0;
    const request = (async function () {
      while (state.streamSummaryDesired && generation === state.streamSummaryGeneration) {
        const desired = state.streamSummaryDesired;
        if (desired.generation !== generation || !summaryWorkIsCurrent(desired)) return;
        if (state.streamSummaryScopeKey === desired.scope.key &&
            Number.isSafeInteger(state.streamSummaryRevision) &&
            state.streamSummaryRevision >= desired.revision) {
          if (state.streamSummaryDesired === desired) state.streamSummaryDesired = null;
          continue;
        }

        const controller = typeof window.AbortController === "function"
          ? new window.AbortController()
          : null;
        state.streamSummaryLoadController = controller;
        const url = "/stream/summary?view=" + encodeURIComponent(config.activeViewId) +
          "&_ts=" + Date.now();
        let response;
        try {
          response = await fetch(
            url,
            controller ? {signal: controller.signal} : undefined
          );
        } catch (error) {
          if (!summaryWorkIsCurrent(desired) || (error && error.name === "AbortError")) {
            return;
          }
          throw error;
        } finally {
          if (state.streamSummaryLoadController === controller) {
            state.streamSummaryLoadController = null;
          }
        }
        if (!summaryWorkIsCurrent(desired)) return;
        if (!response.ok) throw new Error("summary request failed");
        let payload;
        try {
          payload = await response.json();
        } catch (error) {
          if (!summaryWorkIsCurrent(desired)) return;
          throw error;
        }
        if (!summaryWorkIsCurrent(desired)) return;
        if (!payload || payload.derived !== true ||
            payload.object_type !== "derived_stream_summary_collection") {
          throw new Error("summary response is not derived history");
        }
        const payloadRevision = summaryRevision(payload);
        const payloadSessionId = typeof payload.session_id === "string"
          ? payload.session_id
          : null;
        if (payloadRevision === null || (desired.scope.sessionId &&
            payloadSessionId !== desired.scope.sessionId)) {
          throw new Error("summary response identity is invalid");
        }

        const latest = state.streamSummaryDesired;
        if (!latest || latest.generation !== generation ||
            latest.scope.key !== desired.scope.key) {
          continue;
        }
        if (payloadRevision < latest.revision) {
          // A newer data response arrived while this summary was loading. Keep
          // draining immediately; do not wait for another stream event.
          continue;
        }
        renderSummary(payload, latest.data);
        state.streamSummaryRevision = payloadRevision;
        state.streamSummaryScopeKey = latest.scope.key;
        if (state.streamSummaryDesired === latest) state.streamSummaryDesired = null;
      }
    })();
    state.streamSummaryLoadPromise = request;
    function finish() {
      if (state.streamSummaryLoadPromise === request) {
        state.streamSummaryLoadPromise = null;
      }
    }
    request.then(finish, finish);
    return request;
  }

  function loadSummaryIfChanged(data) {
    const scope = summaryScope(data);
    if (scope.historical && data.historical_summary) {
      const payload = data.historical_summary;
      if (!payload || payload.derived !== true ||
          payload.object_type !== "derived_stream_summary_collection" ||
          (scope.sessionId && payload.session_id !== scope.sessionId)) {
        return Promise.reject(new Error("historical summary response is invalid"));
      }
      renderSummary(payload, data);
      state.streamSummaryRevision = summaryRevision(payload);
      state.streamSummaryScopeKey = scope.key;
      return Promise.resolve();
    }
    const revision = summaryRevision(data);
    if (revision === null || (state.streamSummaryScopeKey === scope.key &&
        Number.isSafeInteger(state.streamSummaryRevision) &&
        state.streamSummaryRevision >= revision)) {
      return Promise.resolve();
    }
    state.streamSummaryDesired = {
      generation: Number.isSafeInteger(state.streamSummaryGeneration)
        ? state.streamSummaryGeneration
        : 0,
      scope: scope,
      revision: revision,
      data: data,
    };
    if (state.streamSummaryLoadPromise) return state.streamSummaryLoadPromise;
    return startSummaryDrain();
  }

  function historicalSessionLabel(session) {
    const updated = session && typeof session.updated_at === "string" && session.updated_at
      ? typeof core.fmtLocalTime === "function"
        ? core.fmtLocalTime(session.updated_at)
        : session.updated_at
      : "time unavailable";
    const incomplete = session && session.durable_history && session.durable_history.state === "incomplete"
      ? " — incomplete"
      : "";
    return "Past run — " + updated + incomplete;
  }

  function selectedHistoricalSessionId() {
    return typeof state.streamHistoricalSessionId === "string" &&
      state.streamHistoricalSessionId
      ? state.streamHistoricalSessionId
      : null;
  }

  function syncStreamPauseControl() {
    const button = document.getElementById("stream-pause-button");
    if (!button) return;
    const label = document.getElementById("stream-pause-label");
    const paused = state.streamPaused === true;
    const historical = !!selectedHistoricalSessionId();
    const available = state.streamPauseAvailable === true && !historical;
    const action = paused ? "Resume stream" : "Pause stream";
    const description = historical
      ? "Live table updates are unavailable while viewing a stored session"
      : paused
        ? "Resume stream"
        : "Pause stream";

    button.disabled = !available;
    button.setAttribute("aria-pressed", paused ? "true" : "false");
    button.setAttribute("aria-label", description);
    button.title = description;
    if (label) label.textContent = action;
  }

  function setStreamPaused(paused) {
    const next = paused === true;
    if (!state.streamPauseAvailable || selectedHistoricalSessionId()) {
      syncStreamPauseControl();
      return false;
    }
    if (state.streamPaused === next) {
      syncStreamPauseControl();
      return next;
    }

    state.streamPaused = next;
    syncStreamPauseControl();
    if (typeof core.notifyHeaderStreamPauseChanged === "function") {
      core.notifyHeaderStreamPauseChanged();
    }
    if (next) {
      // Stop a response already on the wire as well as future automatic
      // updates. auto_refresh keeps its revision pending when this clean
      // cancellation resolves.
      invalidateStreamLoads();
      if (typeof core.cancelScheduledTablePlotRefresh === "function") {
        core.cancelScheduledTablePlotRefresh();
      }
      if (state.pendingBrowserUpdate &&
          typeof core.setHeaderBrowserDataState === "function") {
        core.setHeaderBrowserDataState("update_available");
      }
      return true;
    }

    if (state.pendingBrowserUpdate &&
        typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    } else if (typeof core.setHeaderBrowserDataState === "function") {
      core.setHeaderBrowserDataState("current");
    }
    return false;
  }

  function bindStreamPauseControl() {
    const button = document.getElementById("stream-pause-button");
    if (!button) return;
    button.onclick = function () {
      setStreamPaused(state.streamPaused !== true);
    };
    syncStreamPauseControl();
  }

  function invalidateStreamLoads() {
    state.streamLoadGeneration = Number.isSafeInteger(state.streamLoadGeneration)
      ? state.streamLoadGeneration + 1
      : 1;
    const controller = state.streamLoadController;
    state.streamLoadController = null;
    if (state.streamLoadTimeoutTimer != null &&
        typeof window.clearTimeout === "function") {
      window.clearTimeout(state.streamLoadTimeoutTimer);
    }
    state.streamLoadTimeoutTimer = null;
    if (controller && typeof controller.abort === "function") {
      controller.abort();
    }
  }

  function beginStreamLoad(historicalSessionId) {
    invalidateStreamLoads();
    const generation = state.streamLoadGeneration;
    const controller = typeof window.AbortController === "function"
      ? new window.AbortController()
      : null;
    state.streamLoadController = controller;
    const load = {
      generation: generation,
      historicalSessionId: historicalSessionId,
      controller: controller,
      timedOut: false,
      timeoutTimer: null,
    };
    if (controller && typeof window.setTimeout === "function") {
      load.timeoutTimer = window.setTimeout(function () {
        if (!streamLoadIsCurrent(load) || state.streamLoadController !== controller) return;
        load.timedOut = true;
        controller.abort();
      }, STREAM_DATA_REQUEST_TIMEOUT_MS);
      state.streamLoadTimeoutTimer = load.timeoutTimer;
    }
    return load;
  }

  function streamLoadIsCurrent(load) {
    return !!load && load.generation === state.streamLoadGeneration &&
      load.historicalSessionId === selectedHistoricalSessionId();
  }

  function clearStreamLoadTimeout(load) {
    if (load && load.timeoutTimer != null && typeof window.clearTimeout === "function") {
      window.clearTimeout(load.timeoutTimer);
      if (state.streamLoadTimeoutTimer === load.timeoutTimer) {
        state.streamLoadTimeoutTimer = null;
      }
      load.timeoutTimer = null;
    }
  }

  function finishStreamLoad(load) {
    clearStreamLoadTimeout(load);
    if (load && state.streamLoadController === load.controller) {
      state.streamLoadController = null;
    }
  }

  async function resetStreamSessionPresentation() {
    // Invalidate before the first await. Otherwise an older live response can
    // finish while the table is being cleared and overwrite the newly selected
    // stored session (or vice versa).
    invalidateStreamLoads();
    invalidateStreamSummaryLoads();
    if (typeof core.cancelScheduledTablePlotRefresh === "function") {
      core.cancelScheduledTablePlotRefresh();
    }
    state.streamCursor = null;
    state.streamSessionId = null;
    state.streamSchemaRevision = null;
    state.streamSummaryRevision = null;
    state.streamSummaryScopeKey = null;
    state.streamColumnsSignature = null;
    state.streamRowsBySequence = Object.create(null);
    state.streamForceTableReplace = true;
    state.streamPauseAvailable = false;
    syncStreamPauseControl();

    // Browser sequence numbers are session-local. Clear the visible table
    // before loading another stored session (or returning to the current
    // observation) so an empty compact-only session cannot retain rows from a
    // previous one while its STORED SESSION badge is visible.
    await replaceTableData(state.streamTabulatorInstance, []);
  }

  function syncSessionControl(data) {
    const select = document.getElementById("stream-history-session-select");
    const status = document.getElementById("stream-history-picker-status");
    if (!select) return;

    const showingHistorical = data && data.historical === true;
    select.value = state.streamHistoricalSessionId || "";
    if (status && showingHistorical) {
      status.textContent = "Viewing a stored run. Stored runs are not live producers.";
    }
  }

  function renderHistoryPicker(data, sessions, capability) {
    const picker = document.getElementById("stream-history-picker");
    const select = document.getElementById("stream-history-session-select");
    const status = document.getElementById("stream-history-picker-status");
    if (!picker || !select) return;

    const items = (Array.isArray(sessions) ? sessions : []).filter(function (session) {
      return session && typeof session.session_id === "string" && session.session_id;
    });
    state.streamHistorySessions = items;

    const showingHistorical = data && data.historical === true;
    if (showingHistorical && !state.streamHistoricalSessionId &&
        typeof data.session_id === "string" && data.session_id) {
      state.streamHistoricalSessionId = data.session_id;
    }
    const durable = data && data.durable_history;
    const enabled = capability && typeof capability.enabled === "boolean"
      ? capability.enabled
      : !(durable && durable.state === "disabled");
    const unavailableReason = !enabled
      ? String(
          (capability && capability.message) ||
          "Stored runs are unavailable because plotsrv disk storage is disabled in configuration."
        )
      : "";
    picker.dataset.state = enabled ? (items.length ? "enabled" : "empty") : "unavailable";
    select.replaceChildren();
    const current = document.createElement("option");
    current.value = "";
    current.textContent = "Current run";
    select.appendChild(current);
    for (const session of items) {
      if (!session || typeof session.session_id !== "string" || !session.session_id) continue;
      const option = document.createElement("option");
      option.value = session.session_id;
      option.textContent = historicalSessionLabel(session);
      select.appendChild(option);
    }
    select.value = state.streamHistoricalSessionId || "";
    select.disabled = !enabled;
    select.title = unavailableReason;
    if (typeof select.setAttribute === "function") {
      select.setAttribute(
        "aria-label",
        unavailableReason ? "Run. " + unavailableReason : "Run"
      );
    }
    if (status) {
      status.textContent = unavailableReason || (showingHistorical
        ? "Viewing a stored run. Stored runs are not live producers."
        : items.length
          ? items.length + " past run" + (items.length === 1 ? " is" : "s are") + " available to inspect."
          : "Current run. No past runs have been saved yet.");
    }
    select.onchange = async function () {
      const next = select.value || null;
      if (next === state.streamHistoricalSessionId) return;
      state.streamHistoricalSessionId = next;
      select.disabled = true;
      if (typeof select.setAttribute === "function") {
        select.setAttribute("aria-busy", "true");
      }
      if (typeof core.setHeaderStreamSessionState === "function") {
        core.setHeaderStreamSessionState(!!next);
      }
      try {
        await resetStreamSessionPresentation();
        await loadStream();
        if (typeof core.markBrowserViewApplied === "function") {
          core.markBrowserViewApplied();
        }
        if (typeof core.notifyUpdateEligibilityChanged === "function") {
          core.notifyUpdateEligibilityChanged();
        }
      } catch (error) {
        showStreamError();
      } finally {
        select.disabled = false;
        if (typeof select.removeAttribute === "function") {
          select.removeAttribute("aria-busy");
        }
      }
    };
  }

  function renderRawHistoryNotice(data, records) {
    const notice = document.getElementById("stream-raw-history-notice");
    if (!notice) return;
    const unavailable = data && data.historical === true &&
      (!Array.isArray(records) || records.length === 0);
    notice.hidden = !unavailable;
    notice.textContent = unavailable
      ? "No original log rows are available for this stored run. Its compact summaries and noteworthy history remain available in Insights."
      : "";
  }

  async function returnToCurrentStream() {
    state.streamHistoricalSessionId = null;
    if (typeof core.setHeaderStreamSessionState === "function") {
      core.setHeaderStreamSessionState(false);
    }
    await resetStreamSessionPresentation();
    await loadStream();
    if (typeof core.markBrowserViewApplied === "function") {
      core.markBrowserViewApplied();
    }
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function rememberHistoryControlData(data) {
    if (!data || typeof data !== "object") return;
    state.streamHistoryControlData = {
      historical: data.historical === true,
      session_id: typeof data.session_id === "string" ? data.session_id : null,
      durable_history: data.durable_history || null,
    };
  }

  function loadHistoryCatalogue(data, options) {
    rememberHistoryControlData(data);
    if (state.streamHistoryCatalogPromise) {
      if (options && options.force) state.streamHistoryCatalogRefreshRequested = true;
      return state.streamHistoryCatalogPromise;
    }
    const url = "/stream/history?view=" + encodeURIComponent(config.activeViewId) + "&_ts=" + Date.now();
    const request = fetch(url)
      .then(function (response) {
        if (response.status === 404) return {sessions: [], capability: null};
        if (!response.ok) throw new Error("stream history request failed");
        return response.json();
      })
      .then(function (payload) {
        const sessions = payload && Array.isArray(payload.sessions) ? payload.sessions : [];
        state.streamHistoryCatalogViewId = config.activeViewId;
        state.streamHistoryCatalogRevision = payload && Number.isSafeInteger(payload.revision)
          ? payload.revision
          : state.streamHistoryCatalogRevision;
        renderHistoryPicker(
          data || state.streamHistoryControlData,
          sessions,
          payload && payload.capability
        );
      });
    state.streamHistoryCatalogPromise = request;
    function finish() {
      if (state.streamHistoryCatalogPromise === request) {
        state.streamHistoryCatalogPromise = null;
      }
      if (state.streamHistoryCatalogRefreshRequested) {
        state.streamHistoryCatalogRefreshRequested = false;
        window.setTimeout(function () {
          loadHistoryCatalogue(state.streamHistoryControlData, {force: true}).catch(function () {});
        }, 0);
      }
    }
    request.then(finish, finish);
    return request;
  }

  function scheduleStreamHistoryCatalogueRefresh() {
    if (state.streamHistoryCatalogRefreshTimer != null) return;
    state.streamHistoryCatalogRefreshTimer = window.setTimeout(function () {
      state.streamHistoryCatalogRefreshTimer = null;
      loadHistoryCatalogue(state.streamHistoryControlData, {force: true}).catch(function () {
        // A transient history failure never interrupts the current live table.
      });
    }, 250);
  }

  function showStreamError() {
    const target = document.getElementById("stream-status-inline");
    if (target) target.textContent = "Unable to load the live stream.";
    const healthTarget = document.getElementById("stream-health-inline");
    if (healthTarget) healthTarget.textContent = "";
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("Unable to load the live stream.");
    }
    const noteworthyItems = document.getElementById("stream-noteworthy-items");
    if (noteworthyItems && noteworthyItems.children.length === 0) {
      renderNoteworthy(null, null);
    }
    showSummaryError();
  }

  async function loadStream() {
    const grid = document.getElementById("stream-grid");
    if (!grid) return false;

    const historicalSessionId = selectedHistoricalSessionId();
    const load = beginStreamLoad(historicalSessionId);
    let url = historicalSessionId
      ? "/stream/history?view=" + encodeURIComponent(config.activeViewId) +
        "&session_id=" + encodeURIComponent(historicalSessionId)
      : "/stream/data?view=" + encodeURIComponent(config.activeViewId);
    if (Number.isSafeInteger(state.streamCursor) && state.streamCursor >= 0) {
      url += "&after=" + encodeURIComponent(state.streamCursor);
    }
    if (!historicalSessionId && typeof state.streamSessionId === "string" && state.streamSessionId) {
      url += "&session_id=" + encodeURIComponent(state.streamSessionId);
    }
    url += "&_ts=" + Date.now();

    let response;
    try {
      response = await fetch(
        url,
        load.controller ? {signal: load.controller.signal} : undefined
      );
    } catch (error) {
      if (load.timedOut && streamLoadIsCurrent(load)) {
        finishStreamLoad(load);
        showStreamError();
        throw new Error("stream data request timed out");
      }
      if (!streamLoadIsCurrent(load) || (error && error.name === "AbortError")) {
        finishStreamLoad(load);
        return false;
      }
      finishStreamLoad(load);
      throw error;
    }
    if (!streamLoadIsCurrent(load)) {
      finishStreamLoad(load);
      return false;
    }
    if (!response.ok) {
      finishStreamLoad(load);
      showStreamError();
      throw new Error("stream data request failed with status " + response.status);
    }

    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      finishStreamLoad(load);
      throw error;
    }
    if (!streamLoadIsCurrent(load)) {
      finishStreamLoad(load);
      return false;
    }
    // The liveness bound covers the network response and JSON parsing. Table
    // mutations are local and already serialize through one bounded chain.
    clearStreamLoadTimeout(load);
    const data = historicalSessionId
      ? payload && payload.data
      : payload;
    if (!validStreamDataPayload(data)) {
      finishStreamLoad(load);
      showStreamError();
      throw new Error("stream data response is invalid");
    }
    if (historicalSessionId) {
      data.historical_summary = payload.summary;
    }
    if (data.historical !== true) state.streamAwaitingReceiverSession = false;
    if (data.historical === true && !state.streamHistoricalSessionId &&
        !state.streamAwaitingReceiverSession &&
        typeof data.session_id === "string" && data.session_id) {
      state.streamHistoricalSessionId = data.session_id;
    }
    const records = normaliseRecords(data.records);
    const columns = Array.isArray(data.columns) ? data.columns : [];
    const serverSessionId = typeof data.session_id === "string" ? data.session_id : null;
    const sessionChanged =
      !!state.streamSessionId &&
      !!serverSessionId &&
      state.streamSessionId !== serverSessionId;
    rememberHistoryControlData(data);
    renderRawHistoryNotice(data, records);
    let visitComparison = null;
    if (data.historical === true) {
      renderHistoricalVisitNotice(data);
    } else if (typeof core.updateStreamVisitComparison === "function") {
      visitComparison = core.updateStreamVisitComparison(data);
    }
    if (data.historical !== true) renderVisitComparison(visitComparison, data);
    renderNoteworthy(data.noteworthy, data.cumulative);
    setInlineStatus(data);
    // Keep selection aligned immediately when a return-to-current action
    // originates outside the selector, without rebuilding an open dropdown.
    syncSessionControl(data);
    loadSummaryIfChanged(data).catch(showSummaryError);
    if (state.streamHistoryCatalogViewId !== config.activeViewId || data.historical === true) {
      loadHistoryCatalogue(data).catch(function () {
        // Browsing the current stream remains available if the optional
        // historical catalogue cannot be loaded.
      });
    }

    if (typeof Tabulator === "undefined") {
      finishStreamLoad(load);
      showStreamError();
      throw new Error("Tabulator is not available");
    }

    const resetRequired = data.reset_required === true || sessionChanged ||
      state.streamForceTableReplace === true;
    const firstAvailable = firstAvailableSequence(data);
    const currentSchemaSignature = schemaSignature(columns);

    if (!state.streamTabulatorInstance) {
      const rows = replaceStreamRows(records);
      const fields = explorerFields(columns);
      state.streamTabulatorInstance = new Tabulator("#stream-grid", {
        data: rows,
        columns: buildColumns(fields),
        height: "72vh",
        layout: "fitDataStretch",
        movableColumns: true,
        // The server already bounds this recent window to 200 rows. Rendering
        // that complete window keeps newly appended records visibly advancing
        // instead of leaving a viewer on a stale first pagination page.
        // JSONL object keys are flat field names. In particular, a legal key
        // such as "http.status" must not be interpreted as a nested lookup.
        nestedFieldSeparator: false,
        placeholder: "Waiting for appended JSON objects…",
      });
      configureExplorer(state.streamTabulatorInstance, data, rows, fields);
      state.streamSchemaRevision = Number.isInteger(data.schema_revision)
        ? data.schema_revision
        : null;
      state.streamColumnsSignature = currentSchemaSignature;
      state.streamSessionId = serverSessionId;
      state.streamForceTableReplace = false;
      updateCursor(data, records, true);
      finishStreamLoad(load);
      state.streamPauseAvailable = data.historical !== true;
      syncStreamPauseControl();
      return true;
    }

    const table = state.streamTabulatorInstance;
    const schemaChanged = state.streamColumnsSignature !== currentSchemaSignature;
    if (schemaChanged) {
      await queueStreamTableMutation(function () {
        if (!streamLoadIsCurrent(load)) return;
        return extendColumns(table, columns);
      });
      if (!streamLoadIsCurrent(load)) {
        finishStreamLoad(load);
        return false;
      }
    }

    let rows;
    if (resetRequired) {
      rows = replaceStreamRows(records);
      // A reset is an explicit loss of continuity, so replacement is correct;
      // Tabulator retains active filters and explicit sorting across replaceData.
      await replaceTableData(table, rows);
      if (!streamLoadIsCurrent(load)) {
        finishStreamLoad(load);
        return false;
      }
    } else {
      const merged = mergeStreamRows(records, firstAvailable);
      rows = streamRowsFromState();
      if (merged.evictedRows) {
        // The retained raw window advanced. Rebuild from the browser's local
        // sequence-indexed rows, not a re-downloaded raw window.
        await replaceTableData(table, rows);
      } else {
        await appendTableData(table, merged.additions);
      }
      if (!streamLoadIsCurrent(load)) {
        finishStreamLoad(load);
        return false;
      }
    }

    const fields = explorerFields(columns);
    configureExplorer(table, data, rows, fields);
    state.streamSchemaRevision = Number.isInteger(data.schema_revision)
      ? data.schema_revision
      : null;
    state.streamColumnsSignature = currentSchemaSignature;
    state.streamSessionId = serverSessionId;
    state.streamForceTableReplace = false;
    updateCursor(data, records, resetRequired);
    finishStreamLoad(load);
    state.streamPauseAvailable = data.historical !== true;
    syncStreamPauseControl();
    return true;
  }

  core.loadStream = loadStream;
  core.returnToCurrentStream = returnToCurrentStream;
  core.normalizeInsightsTab = normalizeInsightsTab;
  core.setStreamInsightsTab = setStreamInsightsTab;
  core.openStreamInsights = openStreamInsights;
  core.closeStreamInsights = closeStreamInsights;
  core.bindStreamInsights = bindStreamInsights;
  core.bindStreamPauseControl = bindStreamPauseControl;
  core.bindStreamControlsDisclosure = bindStreamControlsDisclosure;
  core.loadStreamHistoryCatalogue = loadHistoryCatalogue;
  core.scheduleStreamHistoryCatalogueRefresh = scheduleStreamHistoryCatalogueRefresh;
  core.setStreamPaused = setStreamPaused;
  core.renderStreamVisitComparison = renderVisitComparison;
  core.renderHistoricalStreamVisitNotice = renderHistoricalVisitNotice;
  core.renderStreamNoteworthy = renderNoteworthy;
  core.renderStreamSummary = renderSummary;
  window.refreshStream = function () {
    return loadStream();
  };
})();
