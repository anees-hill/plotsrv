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
  const STREAM_REFRESH_MS = 1000;
  const LIFECYCLE_PRESENTATION = {
    live: {
      badge: "LIVE OBSERVATION",
      text: "Live observation — producer heartbeats are current.",
    },
    retrying: {
      badge: "RETRYING DELIVERY",
      text: "Retrying delivery — recent observations may still be pending.",
    },
    ended: {
      badge: "OBSERVATION ENDED",
      text: "Observation ended — the producer explicitly stopped after its bounded final drain.",
    },
    disconnected: {
      badge: "OBSERVER DISCONNECTED",
      text: "Observer disconnected — heartbeats stopped; application state is unknown.",
    },
    incomplete: {
      badge: "INCOMPLETE OBSERVATION",
      text: "Incomplete observation — some observations may be pending; application state is unknown.",
    },
  };

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
    const fields = Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    for (const column of Array.isArray(columns) ? columns : []) {
      const field = String(column);
      if (!fields.includes(field)) fields.push(field);
    }
    return fields;
  }

  async function extendColumns(table, columns) {
    if (!table || typeof table.getColumns !== "function" || typeof table.addColumn !== "function") {
      return;
    }

    const present = new Set();
    try {
      for (const column of table.getColumns()) {
        if (!column || typeof column.getField !== "function") continue;
        const field = column.getField();
        if (field) present.add(field);
      }
    } catch (e) {
      return;
    }

    const additions = [];
    for (const field of Array.isArray(columns) ? columns : []) {
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
  }

  async function replaceTableData(table, rows) {
    if (!table || typeof table.replaceData !== "function") return;
    await Promise.resolve(table.replaceData(rows));
  }

  async function appendTableData(table, rows) {
    if (!rows.length) return;
    if (table && typeof table.addData === "function") {
      await Promise.resolve(table.addData(rows));
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

  function setInlineStatus(data) {
    const target = document.getElementById("stream-status-inline");
    const badge = document.getElementById("stream-lifecycle-badge");
    const healthTarget = document.getElementById("stream-health-inline");
    if (!target) return;

    const accepted = Number(data.accepted_records || 0);
    const lifecycle = typeof data.lifecycle === "string" ? data.lifecycle : "unknown";
    const presentation = LIFECYCLE_PRESENTATION[lifecycle];
    const continuityWarning = typeof data.continuity_warning === "string"
      ? data.continuity_warning
      : null;
    const sourceUnavailable = data.source_available === false;
    const sourcePresentation = continuityWarning
      ? { badge: "CONTINUITY UNCERTAIN", text: continuityWarning }
      : sourceUnavailable
        ? {
            badge: "SOURCE UNAVAILABLE",
            text: "Active JSONL source is unavailable; waiting for it to return.",
          }
        : presentation;
    if (badge) {
      badge.className = "ps-stream-badge ps-stream-badge--" + lifecycle;
      badge.textContent = sourcePresentation ? sourcePresentation.badge : "STATUS UNAVAILABLE";
    }
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
      healthTarget.textContent = details.join(" ");
    }
  }

  function showStreamError() {
    const target = document.getElementById("stream-status-inline");
    if (target) target.textContent = "Unable to load the live stream.";
    const healthTarget = document.getElementById("stream-health-inline");
    if (healthTarget) healthTarget.textContent = "";
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("Unable to load the live stream.");
    }
  }

  async function loadStream() {
    const grid = document.getElementById("stream-grid");
    if (!grid) return;

    let url =
      "/stream/data?view=" +
      encodeURIComponent(config.activeViewId);
    if (Number.isSafeInteger(state.streamCursor) && state.streamCursor >= 0) {
      url += "&after=" + encodeURIComponent(state.streamCursor);
    }
    if (typeof state.streamSessionId === "string" && state.streamSessionId) {
      url += "&session_id=" + encodeURIComponent(state.streamSessionId);
    }
    url += "&_ts=" + Date.now();

    const response = await fetch(url);
    if (!response.ok) {
      showStreamError();
      return;
    }

    const data = await response.json();
    const records = normaliseRecords(data.records);
    const columns = Array.isArray(data.columns) ? data.columns : [];
    setInlineStatus(data);

    if (typeof Tabulator === "undefined") {
      showStreamError();
      return;
    }

    const serverSessionId = typeof data.session_id === "string" ? data.session_id : null;
    const sessionChanged =
      !!state.streamSessionId &&
      !!serverSessionId &&
      state.streamSessionId !== serverSessionId;
    const resetRequired = data.reset_required === true || sessionChanged;
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
      updateCursor(data, records, true);
      return;
    }

    const table = state.streamTabulatorInstance;
    const schemaChanged = state.streamColumnsSignature !== currentSchemaSignature;
    if (schemaChanged) {
      // Add schema extensions without recreating existing columns: that is
      // what keeps a user's column order and visibility choices intact.
      await extendColumns(table, columns);
    }

    let rows;
    if (resetRequired) {
      rows = replaceStreamRows(records);
      // A reset is an explicit loss of continuity, so replacement is correct;
      // Tabulator retains active filters and explicit sorting across replaceData.
      await replaceTableData(table, rows);
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
    }

    const fields = explorerFields(columns);
    configureExplorer(table, data, rows, fields);
    state.streamSchemaRevision = Number.isInteger(data.schema_revision)
      ? data.schema_revision
      : null;
    state.streamColumnsSignature = currentSchemaSignature;
    state.streamSessionId = serverSessionId;
    updateCursor(data, records, resetRequired);
  }

  function refreshVisibleStream() {
    if (document.hidden) return;
    if (typeof core.reloadCurrentView === "function") {
      core.reloadCurrentView().catch(showStreamError);
      return;
    }
    loadStream().catch(showStreamError);
  }

  function bindStreamVisibilityResume() {
    if (state.streamVisibilityListenerBound) return;
    state.streamVisibilityListenerBound = true;
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) refreshVisibleStream();
    });
  }

  function startStreamRefresh() {
    if (
      !document.getElementById("stream-grid") ||
      state.streamRefreshTimer !== null
    ) {
      return;
    }

    bindStreamVisibilityResume();
    state.streamRefreshTimer = window.setInterval(refreshVisibleStream, STREAM_REFRESH_MS);
  }

  core.loadStream = loadStream;
  core.startStreamRefresh = startStreamRefresh;
  window.refreshStream = function () {
    return loadStream();
  };

  document.addEventListener("DOMContentLoaded", startStreamRefresh);
})();
