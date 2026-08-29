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
    const historical = data.historical === true;
    if (historical) {
      if (badge) {
        badge.className = "ps-stream-badge ps-stream-badge--historical";
        badge.textContent = "STORED SESSION";
      }
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
  }

  function comparisonUnavailableExplanation(reason) {
    if (reason === "session_changed") {
      return "the producer session changed";
    }
    if (reason === "stream_state_changed") {
      return "plotsrv's in-memory stream state was recreated";
    }
    if (reason === "checkpoint_missing") {
      return "this browser has no earlier compatible checkpoint";
    }
    if (reason === "checkpoint_storage_unavailable") {
      return "this browser could not read its saved checkpoint";
    }
    if (reason === "counter_regressed") {
      return "the saved and current counters cannot be compared safely";
    }
    if (reason === "continuity_uncertain") {
      return "plotsrv reported a continuity gap while you were away";
    }
    if (reason === "checkpoint_continuity_insufficient") {
      return "the prior browser checkpoint recorded incomplete source continuity";
    }
    if (reason === "source_unavailable") {
      return "the source is currently unavailable";
    }
    return "the saved browser checkpoint is not compatible with the current observation state";
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

  function renderVisitComparison(comparison) {
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
      detail.className = "ps-stream-returning__detail ps-stream-returning__detail--unavailable";
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-title",
        incomplete ? "Exact comparison incomplete" : "Exact comparison unavailable"
      );
      const message = "Exact since-last-visit comparison is " +
        (incomplete ? "incomplete" : "unavailable") + " because " +
        comparisonUnavailableExplanation(reason) + ". No zero-change conclusion is shown.";
      status.textContent = message;
      addSurfaceText(detail, "ps-stream-returning__detail-copy", message);
      target.appendChild(detail);
      return;
    }

    detail.className = "ps-stream-returning__detail ps-stream-returning__detail--available";
    addSurfaceText(detail, "ps-stream-returning__detail-title", "Exact accepted-observation change");
    const total = exactCountText(deltas.total_records);
    const severity = exactCountText(deltas.recognized_severity_records);
    const continuity = comparison && comparison.continuity;
    const continuityStatus = continuity && typeof continuity.status === "string"
      ? continuity.status
      : "unknown";
    const base = "Exact change since this browser's last compatible visit: " +
      total + " source observation(s) accepted by plotsrv, including " + severity +
      " recognised severity observation(s).";
    let caveat = "";
    if (continuityStatus === "continuity_uncertain") {
      caveat = " Source continuity is uncertain; plotsrv may not have observed every source event while you were away.";
      if (continuity && typeof continuity.warning === "string" && continuity.warning) {
        caveat += " " + continuity.warning;
      }
    } else if (continuityStatus === "source_unavailable") {
      caveat = " The source is currently unavailable; these counts cover only observations plotsrv accepted.";
    } else {
      caveat = " This does not establish that plotsrv observed every source event.";
    }
    const message = base + caveat;
    status.textContent = message;
    addSurfaceText(detail, "ps-stream-returning__detail-copy", message);

    const severityCounts = deltas.recognized_severity_counts;
    const labels = [];
    for (const severityName of ["warning", "emergency", "alert", "critical", "fatal", "error"]) {
      const count = exactCountText(severityCounts[severityName]);
      if (count !== "0" && count !== "unknown") {
        labels.push(severityName + " " + count);
      }
    }
    if (labels.length) {
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-copy",
        "Recognised severity breakdown: " + labels.join(", ") + "."
      );
    }
    const rejected = exactCountText(deltas.rejected_source_records);
    if (rejected !== "0" && rejected !== "unknown") {
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-copy",
        rejected + " malformed or oversized completed source record(s) were reported while you were away."
      );
    }
    const noteworthy = exactCountText(deltas.noteworthy_items);
    if (noteworthy !== "0" && noteworthy !== "unknown") {
      addSurfaceText(
        detail,
        "ps-stream-returning__detail-copy",
        noteworthy + " noteworthy observation(s) were classified; the retained Noteworthy selection is bounded."
      );
    }
    target.appendChild(detail);
  }

  function renderHistoricalVisitNotice() {
    const status = document.getElementById("stream-since-visit-status");
    const target = document.getElementById("stream-since-visit-details");
    if (status) {
      status.textContent = "Stored sessions are fixed historical observations, not live continuity state.";
    }
    if (target) target.replaceChildren();
  }

  function systemNoticeLabel(event) {
    if (event === "source_continuity_uncertain") return "Source continuity is uncertain";
    if (event === "source_continuity_transition") return "Source continuity changed";
    if (event === "source_record_rejection_reported") return "Source record rejection reported";
    if (event === "source_rejection_counter_reset") return "Source rejection counter reset";
    if (event === "stream_schema_changed") return "Retained stream schema changed";
    return "plotsrv system event";
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

  function noteworthySourceLabel(item) {
    const reason = typeof item.noteworthy_reason === "string" ? item.noteworthy_reason : "";
    const field = typeof item.field_name === "string" ? item.field_name : "field";
    if (reason === "structured_severity") {
      return "Source record — recognised severity: " + item.severity;
    }
    if (reason === "first_low_cardinality_value") {
      return "Source record — first retained " + field + " value";
    }
    if (reason === "numeric_minimum") return "Source record — new " + field + " minimum";
    if (reason === "numeric_maximum") return "Source record — new " + field + " maximum";
    return "Source record — noteworthy observation";
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
    article.className = "ps-stream-noteworthy__item ps-stream-noteworthy__item--source";
    article.dataset.noteworthyKind = "source_record";
    article.dataset.noteworthyObjectType = String(item.object_type || "unknown");
    addSurfaceText(article, "ps-stream-noteworthy__item-title", noteworthySourceLabel(item));
    const sequence = exactCountText(item.source_browser_sequence);
    const observedAt = typeof item.observed_at === "string" ? item.observed_at : "time unavailable";
    addSurfaceText(
      article,
      "ps-stream-noteworthy__item-meta",
      "Source browser sequence " + sequence + "; observed " + observedAt + "."
    );
    addSurfaceText(article, "ps-stream-noteworthy__item-data", stableJson(item.data));
    target.appendChild(article);
    return true;
  }

  function appendNoteworthySystemItem(target, item) {
    if (item.object_type !== "stream_system_notice" || item.kind !== "system_notice") {
      return false;
    }
    const article = document.createElement("article");
    article.className = "ps-stream-noteworthy__item ps-stream-noteworthy__item--system";
    article.dataset.noteworthyKind = "system_notice";
    article.dataset.noteworthyObjectType = String(item.object_type || "unknown");
    addSurfaceText(
      article,
      "ps-stream-noteworthy__item-title",
      "plotsrv system notice — " + systemNoticeLabel(item.event)
    );
    const facts = [];
    if (typeof item.continuity_warning === "string" && item.continuity_warning) {
      facts.push(item.continuity_warning);
    }
    if (typeof item.source_transition === "string" && item.source_transition) {
      facts.push("Source transition: " + item.source_transition + ".");
    }
    const rejected = safeNonNegativeInteger(item.rejected_record_count);
    if (rejected !== null) {
      facts.push(rejected + " rejected completed source record(s) reported.");
    }
    const schemaRevision = safeNonNegativeInteger(item.schema_revision);
    if (schemaRevision !== null) {
      facts.push("Retained schema revision: " + schemaRevision + ".");
    }
    if (!facts.length) facts.push("plotsrv reported this system event.");
    addSurfaceText(article, "ps-stream-noteworthy__item-meta", facts.join(" "));
    target.appendChild(article);
    return true;
  }

  function renderNoteworthy(payload) {
    const status = document.getElementById("stream-noteworthy-status");
    const target = document.getElementById("stream-noteworthy-items");
    if (!status || !target) return;

    target.replaceChildren();
    if (!payload || payload.object_type !== "stream_noteworthy_collection" ||
        !Array.isArray(payload.items)) {
      status.textContent = "Noteworthy state is unavailable or invalid; no conclusion is drawn from it.";
      return;
    }

    let shown = 0;
    for (const item of payload.items) {
      if (!item || typeof item !== "object" || Array.isArray(item)) continue;
      if (item.kind === "source_record") {
        shown += appendNoteworthySourceItem(target, item) ? 1 : 0;
      } else if (item.kind === "system_notice") {
        shown += appendNoteworthySystemItem(target, item) ? 1 : 0;
      }
    }

    const maximum = safeNonNegativeInteger(payload.max_retained_items);
    if (shown === 0) {
      status.textContent = "No noteworthy items are retained in the current bounded selection; earlier items may have aged out.";
      return;
    }
    status.textContent = shown + " retained noteworthy item" + (shown === 1 ? " is" : "s are") +
      " shown from a bounded selection" +
      (maximum === null ? "." : " (maximum " + maximum + ").");
  }

  function addSummaryText(parent, className, text) {
    const paragraph = document.createElement("p");
    paragraph.className = className;
    paragraph.textContent = text;
    parent.appendChild(paragraph);
  }

  function appendSummaryFields(windowElement, fields) {
    if (!Array.isArray(fields) || fields.length === 0) return;
    const list = document.createElement("ul");
    list.className = "ps-stream-summary__fields";
    for (const field of fields) {
      if (!field || typeof field !== "object") continue;
      const name = typeof field.field === "string" ? field.field : "unnamed field";
      const item = document.createElement("li");
      item.className = "ps-stream-summary__field";
      const lines = ["Field “" + name + "”: " + exactCountText(field.observed_count) + " observation(s)."];
      const numeric = field.numeric;
      if (numeric && typeof numeric === "object") {
        lines.push(
          "Numeric (" + exactCountText(numeric.included_finite_count) + " finite): " +
          "sum " + exactFractionText(numeric.sum) +
          ", mean " + exactFractionText(numeric.mean) +
          ", min " + exactFractionText(numeric.minimum) +
          ", max " + exactFractionText(numeric.maximum) +
          ", first " + exactFractionText(numeric.first) +
          ", last " + exactFractionText(numeric.last) + "."
        );
      }
      const categorical = field.categorical;
      if (categorical && typeof categorical === "object") {
        const tracked = Array.isArray(categorical.tracked_values)
          ? categorical.tracked_values.map(function (entry) {
              if (!entry || typeof entry !== "object") return null;
              const value = typeof entry.value_json === "string" ? entry.value_json : "?";
              return value + " (" + exactCountText(entry.count) + ")";
            }).filter(Boolean)
          : [];
        const untracked = exactCountText(categorical.untracked_observations);
        lines.push(
          "Opaque scalar counts: " +
          (tracked.length ? tracked.join(", ") : "no retained exact values") +
          "; " + untracked + " untracked/other observation(s). " +
          (categorical.exact_per_value_counts_complete === true
            ? "Per-value counts are complete."
            : "Per-value counts are incomplete after categorical reduction.")
        );
      }
      const nonScalar = exactCountText(field.non_scalar_observations);
      if (nonScalar !== "unknown" && nonScalar !== "0") {
        lines.push(nonScalar + " nested value(s) were not semantically summarised.");
      }
      item.textContent = lines.join(" ");
      list.appendChild(item);
    }
    windowElement.appendChild(list);
  }

  function renderSummary(payload) {
    if (typeof core.setTablePlotSummaryRows === "function") {
      core.setTablePlotSummaryRows(payload);
    }
    const status = document.getElementById("stream-summary-status");
    const target = document.getElementById("stream-summary-windows");
    if (!status || !target) return;

    const windows = Array.isArray(payload && payload.windows) ? payload.windows : [];
    target.replaceChildren();
    if (!windows.length) {
      status.textContent = "No derived windows yet; the table above contains only recent raw observations.";
      return;
    }

    status.textContent = windows.length + " derived window" +
      (windows.length === 1 ? " is" : "s are") +
      " shown below; none are source log rows.";
    for (const window of windows) {
      if (!window || typeof window !== "object" || window.derived !== true) continue;
      const tier = typeof window.tier === "string" ? window.tier : "unknown";
      const article = document.createElement("article");
      article.className = "ps-stream-summary__window ps-stream-summary__window--" + tier;
      article.dataset.derivedSummary = "true";
      article.dataset.summaryObjectType = String(window.object_type || "unknown");
      addSummaryText(article, "ps-stream-summary__window-title", summaryTierLabel(window));
      const range = window.observation_window;
      const from = range && typeof range.from === "string" ? range.from : "unknown start";
      const until = range && typeof range.until === "string" ? range.until : "unknown end";
      const first = exactCountText(window.first_browser_sequence);
      const last = exactCountText(window.last_browser_sequence);
      addSummaryText(
        article,
        "ps-stream-summary__window-meta",
        "Derived boundary: " + from + " to " + until + ". " +
        summaryResolutionLabel(window) + ". " +
        exactCountText(window.record_count) + " source observation(s) aggregated" +
        (first === "unknown" || last === "unknown" ? "." : " (browser sequences " + first + "–" + last + ").")
      );
      const truncation = window.truncation;
      const untrackedFields = exactCountText(
        truncation && truncation.untracked_field_observations
      );
      const maxFields = safeNonNegativeInteger(truncation && truncation.max_fields);
      if (untrackedFields === "unknown" || maxFields === null) {
        addSummaryText(article, "ps-stream-summary__truncation", "Truncation details unavailable.");
      } else if (untrackedFields !== "0") {
        addSummaryText(
          article,
          "ps-stream-summary__truncation",
          "Truncation: " + untrackedFields + " field observation(s) are untracked after the " +
          maxFields + "-field summary limit."
        );
      } else {
        addSummaryText(
          article,
          "ps-stream-summary__truncation",
          "Truncation: no field observations were omitted by the " + maxFields + "-field limit."
        );
      }
      appendSummaryFields(article, window.fields);
      target.appendChild(article);
    }
  }

  function showSummaryError() {
    const status = document.getElementById("stream-summary-status");
    if (status) status.textContent = "Unable to load derived compact history; recent raw observations remain separate above.";
  }

  function loadSummaryIfChanged(data) {
    if (data && data.historical === true && data.historical_summary) {
      const payload = data.historical_summary;
      if (!payload || payload.derived !== true || payload.object_type !== "derived_stream_summary_collection") {
        return Promise.reject(new Error("historical summary response is invalid"));
      }
      renderSummary(payload);
      state.streamSummaryRevision = summaryRevision(payload);
      return Promise.resolve();
    }
    const revision = summaryRevision(data);
    if (revision === null || revision === state.streamSummaryRevision) {
      return Promise.resolve();
    }
    if (state.streamSummaryLoadPromise) return state.streamSummaryLoadPromise;

    const url = "/stream/summary?view=" + encodeURIComponent(config.activeViewId) + "&_ts=" + Date.now();
    const request = fetch(url)
      .then(function (response) {
        if (!response.ok) throw new Error("summary request failed");
        return response.json();
      })
      .then(function (payload) {
        if (!payload || payload.derived !== true || payload.object_type !== "derived_stream_summary_collection") {
          throw new Error("summary response is not derived history");
        }
        renderSummary(payload);
        state.streamSummaryRevision = summaryRevision(payload);
      });
    state.streamSummaryLoadPromise = request;
    function finish() {
      if (state.streamSummaryLoadPromise === request) {
        state.streamSummaryLoadPromise = null;
      }
    }
    request.then(finish, finish);
    return request;
  }

  function historicalSessionLabel(session) {
    const id = session && typeof session.session_id === "string"
      ? session.session_id
      : "unknown session";
    const updated = session && typeof session.updated_at === "string" && session.updated_at
      ? session.updated_at
      : "time unavailable";
    const incomplete = session && session.durable_history && session.durable_history.state === "incomplete"
      ? " — persistence incomplete"
      : "";
    return id + " — " + updated + incomplete;
  }

  async function resetStreamSessionPresentation() {
    state.streamCursor = null;
    state.streamSessionId = null;
    state.streamSchemaRevision = null;
    state.streamSummaryRevision = null;
    state.streamColumnsSignature = null;
    state.streamRowsBySequence = Object.create(null);
    state.streamForceTableReplace = true;

    // Browser sequence numbers are session-local. Clear the visible table
    // before loading another stored session (or returning to the current
    // observation) so an empty compact-only session cannot retain rows from a
    // previous one while its STORED SESSION badge is visible.
    await replaceTableData(state.streamTabulatorInstance, []);
  }

  function renderHistoryPicker(data, sessions) {
    const picker = document.getElementById("stream-history-picker");
    const select = document.getElementById("stream-history-session-select");
    const status = document.getElementById("stream-history-picker-status");
    if (!picker || !select) return;

    const items = Array.isArray(sessions) ? sessions : [];
    state.streamHistorySessions = items;
    if (!items.length) {
      picker.hidden = true;
      return;
    }

    const showingHistorical = data && data.historical === true;
    if (showingHistorical && !state.streamHistoricalSessionId &&
        typeof data.session_id === "string" && data.session_id) {
      state.streamHistoricalSessionId = data.session_id;
    }
    picker.hidden = false;
    select.replaceChildren();
    // Keep a route back to the current observation while browsing history.
    // A live producer may have registered after this stored session was saved.
    const current = document.createElement("option");
    current.value = "";
    current.textContent = "Current observation";
    select.appendChild(current);
    for (const session of items) {
      if (!session || typeof session.session_id !== "string" || !session.session_id) continue;
      const option = document.createElement("option");
      option.value = session.session_id;
      option.textContent = historicalSessionLabel(session);
      select.appendChild(option);
    }
    select.value = state.streamHistoricalSessionId || "";
    if (status) {
      status.textContent = showingHistorical
        ? "Viewing stored history. Stored sessions are not live producers."
        : items.length + " stored session" + (items.length === 1 ? " is" : "s are") + " available to inspect.";
    }
    select.onchange = async function () {
      const next = select.value || null;
      if (next === state.streamHistoricalSessionId) return;
      state.streamHistoricalSessionId = next;
      if (typeof core.renderHeaderStatus === "function") core.renderHeaderStatus();
      try {
        await resetStreamSessionPresentation();
        await loadStream();
        if (typeof core.notifyUpdateEligibilityChanged === "function") {
          core.notifyUpdateEligibilityChanged();
        }
      } catch (error) {
        showStreamError();
      }
    };
  }

  function loadHistoryCatalogue(data) {
    if (state.streamHistoryCatalogPromise) return state.streamHistoryCatalogPromise;
    const url = "/stream/history?view=" + encodeURIComponent(config.activeViewId) + "&_ts=" + Date.now();
    const request = fetch(url)
      .then(function (response) {
        if (response.status === 404) return [];
        if (!response.ok) throw new Error("stream history request failed");
        return response.json();
      })
      .then(function (payload) {
        const sessions = payload && Array.isArray(payload.sessions) ? payload.sessions : [];
        state.streamHistoryCatalogViewId = config.activeViewId;
        renderHistoryPicker(data, sessions);
      });
    state.streamHistoryCatalogPromise = request;
    function finish() {
      if (state.streamHistoryCatalogPromise === request) {
        state.streamHistoryCatalogPromise = null;
      }
    }
    request.then(finish, finish);
    return request;
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

    const historicalSessionId = typeof state.streamHistoricalSessionId === "string" &&
      state.streamHistoricalSessionId
      ? state.streamHistoricalSessionId
      : null;
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

    const response = await fetch(url);
    if (!response.ok) {
      showStreamError();
      return;
    }

    const payload = await response.json();
    const data = historicalSessionId
      ? payload && payload.data
      : payload;
    if (!data || typeof data !== "object") {
      showStreamError();
      return;
    }
    if (historicalSessionId) {
      data.historical_summary = payload.summary;
    }
    if (data.historical === true && !state.streamHistoricalSessionId &&
        typeof data.session_id === "string" && data.session_id) {
      state.streamHistoricalSessionId = data.session_id;
    }
    const records = normaliseRecords(data.records);
    const columns = Array.isArray(data.columns) ? data.columns : [];
    let visitComparison = null;
    if (data.historical === true) {
      renderHistoricalVisitNotice();
    } else if (typeof core.updateStreamVisitComparison === "function") {
      visitComparison = core.updateStreamVisitComparison(data);
    }
    if (data.historical !== true) renderVisitComparison(visitComparison);
    renderNoteworthy(data.noteworthy);
    setInlineStatus(data);
    loadSummaryIfChanged(data).catch(showSummaryError);
    if (state.streamHistoryCatalogViewId !== config.activeViewId || data.historical === true) {
      loadHistoryCatalogue(data).catch(function () {
        // Browsing the current stream remains available if the optional
        // historical catalogue cannot be loaded.
      });
    }

    if (typeof Tabulator === "undefined") {
      showStreamError();
      return;
    }

    const serverSessionId = typeof data.session_id === "string" ? data.session_id : null;
    const sessionChanged =
      !!state.streamSessionId &&
      !!serverSessionId &&
      state.streamSessionId !== serverSessionId;
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
    state.streamForceTableReplace = false;
    updateCursor(data, records, resetRequired);
  }

  core.loadStream = loadStream;
  window.refreshStream = function () {
    return loadStream();
  };
})();
