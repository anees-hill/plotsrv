/* plotsrv source: js/core/dom.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  core.escapeHtml = function (s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  };

  core.findNearest = function (el, selector) {
    if (!el) return null;
    if (el.closest) return el.closest(selector);
    return null;
  };

  core.setStatusMessage = function (html) {
    const status = document.getElementById("status");
    if (status) status.innerHTML = html || "";
  };

  core.copyTextToClipboard = async function (text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {
      // ignore
    }

    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "readonly");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return !!ok;
    } catch (e) {
      return false;
    }
  };
})();

/* plotsrv source: js/core/state.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const raw = window.PLOTSRV_CONFIG || {};
  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;
  // A checkpoint records whether its own observation interval was sufficient
  // for an exact comparison.  Version 2 did not have that marker, so it must
  // not be reused as an exact baseline after an upgrade.
  const STREAM_CHECKPOINT_SCHEMA_VERSION = 3;
  const STREAM_COUNTER_SCHEMA_VERSION = 2;
  const STREAM_CHECKPOINT_STORAGE_PREFIX = "plotsrv:v1:stream_checkpoint:";
  const STREAM_SEVERITIES = [
    "warning",
    "emergency",
    "alert",
    "critical",
    "fatal",
    "error",
  ];
  const STREAM_CHECKPOINT_CONTINUITY_STATUSES = [
    "no_known_gap",
    "continuity_uncertain",
    "source_unavailable",
  ];
  // Must match MAX_STREAM_ID_CHARS at the Python public and HTTP ingress.
  const MAX_CHECKPOINT_ID_CHARS = 512;
  const CANONICAL_NON_NEGATIVE_DECIMAL = /^(?:0|[1-9]\d*)$/;

  function readSnapshotFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      const val = params.get("snapshot");
      return val ? String(val) : null;
    } catch (e) {
      return null;
    }
  }

  function writeSnapshotToUrl(snapshotId) {
    try {
      const url = new URL(window.location.href);
      if (snapshotId) url.searchParams.set("snapshot", snapshotId);
      else url.searchParams.delete("snapshot");
      window.history.replaceState({}, "", url.toString());
    } catch (e) {
      // ignore
    }
  }

  config.activeViewId = raw.active_view_id || "default";
  config.kind = raw.kind || "none";
  config.tableViewMode = raw.table_view_mode || "rich";
  config.maxTableRowsSimple = raw.max_table_rows_simple || 200;
  config.maxTableRowsRich = raw.max_table_rows_rich || 1000;
  config.showHeaderFreshness = raw.show_header_freshness !== false;
  config.showHeaderHistory = raw.show_header_history !== false;
  config.viewCatalogue = Array.isArray(raw.view_catalogue)
    ? raw.view_catalogue
    : [];
  config.featuredViews = Array.isArray(raw.featured_views)
    ? raw.featured_views
    : [];
  config.browserUpdateRevision = Number.isSafeInteger(raw.browser_update_revision)
    ? raw.browser_update_revision
    : 0;

  state.historyItems = [];
  state.currentSnapshot = readSnapshotFromUrl();
  state.latestStatusPayload = null;
  state.browserLastAppliedAt = null;
  state.statusModalOpen = false;
  state.statusModalReturnFocus = null;
  // Header status has three independent axes. Rendered classes and text are
  // always derived from this model; they are never read back as state.
  state.headerStatus = {
    viewMode: state.currentSnapshot ? "snapshot" : "latest",
    latestData: {
      lastUpdated: null,
      freshness: null,
    },
    browserData: "current",
    snapshot: state.currentSnapshot
      ? { id: state.currentSnapshot, createdAt: null }
      : null,
  };
  state.plotObjectUrl = null;
  state.reloadCurrentViewPromise = null;
  state.statusRefreshPromise = null;
  state.viewMenuRefreshPromise = null;
  state.viewMenuRevision = Number.isInteger(raw.view_menu_revision)
    ? raw.view_menu_revision
    : null;
  state.observedUpdateRevision = config.browserUpdateRevision;
  state.appliedUpdateRevision = config.browserUpdateRevision;
  state.pendingBrowserUpdate = null;
  state.browserUpdateSource = null;
  state.browserUpdateApplying = false;
  state.initialViewLoadComplete = false;
  state.tabulatorInstance = null;
  state.tablePlotCapabilities = null;
  state.streamTabulatorInstance = null;
  state.streamCursor = null;
  state.streamSessionId = null;
  state.streamHistoricalSessionId = null;
  state.streamHistorySessions = [];
  state.streamHistoryCatalogPromise = null;
  state.streamHistoryCatalogViewId = null;
  // A current/history session boundary must replace Tabulator data even when
  // the response's browser cursor happens to be valid for its own session.
  state.streamForceTableReplace = false;
  state.streamSchemaRevision = null;
  state.streamSummaryRevision = null;
  state.streamSummaryLoadPromise = null;
  // The first valid response of a page visit establishes its comparison
  // baseline. It must not move on every live poll or the eventual UI would
  // silently turn “since last visit” into “since the last second”. The latest
  // valid counters are still persisted on every response for the next visit.
  state.streamVisitComparison = null;
  state.streamVisitComparisonViewId = null;
  state.streamVisitCheckpoint = null;
  state.streamVisitCheckpointReason = null;
  state.streamColumnsSignature = null;
  state.streamRowsBySequence = Object.create(null);

  core.getActiveViewId = function () {
    return config.activeViewId;
  };

  core.readSnapshotFromUrl = readSnapshotFromUrl;

  core.writeSnapshotToUrl = writeSnapshotToUrl;

  core.getCurrentSnapshot = function () {
    return state.currentSnapshot;
  };

  core.setCurrentSnapshot = function (snapshotId) {
    state.currentSnapshot = snapshotId ? String(snapshotId) : null;
    return state.currentSnapshot;
  };

  core.snapshotQuery = function () {
    return state.currentSnapshot
      ? "&snapshot=" + encodeURIComponent(state.currentSnapshot)
      : "";
  };

  core.isHistoryMode = function () {
    return !!state.currentSnapshot;
  };

  core.getHistoryItems = function () {
    return state.historyItems;
  };

  core.setHistoryItems = function (items) {
    state.historyItems = Array.isArray(items) ? items : [];
  };

  function safeCheckpointId(value) {
    if (typeof value !== "string" || value.length === 0 ||
        !isWellFormedUnicode(value) ||
        unicodeCodePointLength(value) > MAX_CHECKPOINT_ID_CHARS) {
      return null;
    }
    return value;
  }

  function isWellFormedUnicode(value) {
    for (let index = 0; index < value.length; index += 1) {
      const unit = value.charCodeAt(index);
      if (unit >= 0xD800 && unit <= 0xDBFF) {
        const next = value.charCodeAt(index + 1);
        if (next < 0xDC00 || next > 0xDFFF) return false;
        index += 1;
      } else if (unit >= 0xDC00 && unit <= 0xDFFF) {
        return false;
      }
    }
    return true;
  }

  function unicodeCodePointLength(value) {
    let length = 0;
    for (let index = 0; index < value.length; index += 1) {
      const unit = value.charCodeAt(index);
      if (unit >= 0xD800 && unit <= 0xDBFF) index += 1;
      length += 1;
    }
    return length;
  }

  function streamCheckpointKey(viewId) {
    return STREAM_CHECKPOINT_STORAGE_PREFIX + encodeURIComponent(viewId);
  }

  function exactDecimal(value) {
    if (typeof value !== "string" || !CANONICAL_NON_NEGATIVE_DECIMAL.test(value)) {
      return null;
    }
    if (typeof BigInt !== "function") return null;
    try {
      return { text: value, value: BigInt(value) };
    } catch (e) {
      return null;
    }
  }

  function exactTimestamp(value) {
    if (value === null) return null;
    if (typeof value !== "string" || value.length === 0 || value.length > 64) return undefined;
    const timestamp = Date.parse(value);
    return Number.isFinite(timestamp) ? { text: value, value: timestamp } : undefined;
  }

  function normalizeCounterValues(rawCounters) {
    if (!rawCounters || typeof rawCounters !== "object" || Array.isArray(rawCounters)) {
      return { counters: null, reason: "counter_state_invalid" };
    }
    const totalRecords = exactDecimal(rawCounters.total_records);
    const severityRecords = exactDecimal(rawCounters.recognized_severity_records);
    const rejectedSourceRecords = exactDecimal(rawCounters.rejected_source_records);
    const continuityEvents = exactDecimal(rawCounters.continuity_events);
    const noteworthyItems = exactDecimal(rawCounters.noteworthy_items);
    const noteworthySourceRecords = exactDecimal(rawCounters.noteworthy_source_records);
    const systemNotices = exactDecimal(rawCounters.system_notices);
    const latestServerSequence = exactDecimal(rawCounters.latest_server_sequence);
    const firstObservedAt = exactTimestamp(rawCounters.first_observed_at);
    const lastObservedAt = exactTimestamp(rawCounters.last_observed_at);
    const rawSeverityCounts = rawCounters.recognized_severity_counts;
    if (!totalRecords || !severityRecords || !rejectedSourceRecords || !continuityEvents ||
        !noteworthyItems || !noteworthySourceRecords || !systemNotices ||
        !latestServerSequence || firstObservedAt === undefined ||
        lastObservedAt === undefined || !rawSeverityCounts ||
        typeof rawSeverityCounts !== "object" || Array.isArray(rawSeverityCounts)) {
      return { counters: null, reason: "counter_state_invalid" };
    }

    const counterKeys = Object.keys(rawSeverityCounts);
    if (counterKeys.length !== STREAM_SEVERITIES.length ||
        !STREAM_SEVERITIES.every(function (severity) {
          return Object.prototype.hasOwnProperty.call(rawSeverityCounts, severity);
        })) {
      return { counters: null, reason: "counter_state_invalid" };
    }

    const severityCounts = {};
    let severityTotal = BigInt(0);
    for (const severity of STREAM_SEVERITIES) {
      const count = exactDecimal(rawSeverityCounts[severity]);
      if (!count) return { counters: null, reason: "counter_state_invalid" };
      severityCounts[severity] = count;
      severityTotal += count.value;
    }
    if (severityTotal !== severityRecords.value || severityRecords.value > totalRecords.value ||
        latestServerSequence.value !== totalRecords.value ||
        noteworthySourceRecords.value < severityRecords.value ||
        noteworthyItems.value !== noteworthySourceRecords.value + systemNotices.value) {
      return { counters: null, reason: "counter_state_invalid" };
    }
    if (totalRecords.value === BigInt(0)) {
      if (firstObservedAt !== null || lastObservedAt !== null) {
        return { counters: null, reason: "counter_state_invalid" };
      }
    } else if (firstObservedAt === null || lastObservedAt === null ||
        lastObservedAt.value < firstObservedAt.value) {
      return { counters: null, reason: "counter_state_invalid" };
    }
    return {
      counters: {
        totalRecords: totalRecords,
        severityRecords: severityRecords,
        severityCounts: severityCounts,
        rejectedSourceRecords: rejectedSourceRecords,
        continuityEvents: continuityEvents,
        noteworthyItems: noteworthyItems,
        noteworthySourceRecords: noteworthySourceRecords,
        systemNotices: systemNotices,
        latestServerSequence: latestServerSequence,
        firstObservedAt: firstObservedAt,
        lastObservedAt: lastObservedAt,
      },
      reason: null,
    };
  }

  function normalizeCurrentStreamState(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return { current: null, reason: "current_state_invalid" };
    }
    const configuredViewId = safeCheckpointId(config.activeViewId);
    const viewId = safeCheckpointId(data.view_id);
    const clientId = safeCheckpointId(data.client_id);
    const sessionId = safeCheckpointId(data.session_id);
    const streamInstanceId = safeCheckpointId(data.stream_instance_id);
    if (!configuredViewId || !viewId || viewId !== configuredViewId || !clientId || !sessionId || !streamInstanceId) {
      return { current: null, reason: "current_identity_invalid" };
    }
    const cumulative = data.cumulative;
    if (!cumulative || cumulative.object_type !== "stream_session_counters") {
      return { current: null, reason: "counter_state_invalid" };
    }
    if (cumulative.counter_schema_version !== STREAM_COUNTER_SCHEMA_VERSION) {
      return { current: null, reason: "counter_schema_changed" };
    }
    const parsed = normalizeCounterValues(cumulative);
    if (!parsed.counters) return { current: null, reason: parsed.reason };
    return {
      current: {
        identity: {
          viewId: viewId,
          clientId: clientId,
          sessionId: sessionId,
          streamInstanceId: streamInstanceId,
          counterSchemaVersion: STREAM_COUNTER_SCHEMA_VERSION,
        },
        counters: parsed.counters,
      },
      reason: null,
    };
  }

  function normalizeStoredCheckpoint(rawCheckpoint, expectedViewId) {
    if (!rawCheckpoint || typeof rawCheckpoint !== "object" || Array.isArray(rawCheckpoint)) {
      return { checkpoint: null, reason: "checkpoint_invalid" };
    }
    if (rawCheckpoint.checkpoint_schema_version !== STREAM_CHECKPOINT_SCHEMA_VERSION) {
      return { checkpoint: null, reason: "checkpoint_schema_changed" };
    }
    const viewId = safeCheckpointId(rawCheckpoint.view_id);
    const clientId = safeCheckpointId(rawCheckpoint.client_id);
    const sessionId = safeCheckpointId(rawCheckpoint.session_id);
    const streamInstanceId = safeCheckpointId(rawCheckpoint.stream_instance_id);
    if (!viewId || viewId !== expectedViewId || !clientId || !sessionId || !streamInstanceId) {
      return { checkpoint: null, reason: "checkpoint_identity_invalid" };
    }
    if (rawCheckpoint.counter_schema_version !== STREAM_COUNTER_SCHEMA_VERSION) {
      return { checkpoint: null, reason: "counter_schema_changed" };
    }
    if (!STREAM_CHECKPOINT_CONTINUITY_STATUSES.includes(rawCheckpoint.continuity_status)) {
      return { checkpoint: null, reason: "checkpoint_continuity_invalid" };
    }
    const parsed = normalizeCounterValues(rawCheckpoint.counters);
    if (!parsed.counters) return { checkpoint: null, reason: parsed.reason };
    return {
      checkpoint: {
        identity: {
          viewId: viewId,
          clientId: clientId,
          sessionId: sessionId,
          streamInstanceId: streamInstanceId,
          counterSchemaVersion: STREAM_COUNTER_SCHEMA_VERSION,
        },
        counters: parsed.counters,
        continuityStatus: rawCheckpoint.continuity_status,
      },
      reason: null,
    };
  }

  function loadStoredCheckpoint(viewId) {
    let raw;
    try {
      raw = localStorage.getItem(streamCheckpointKey(viewId));
    } catch (e) {
      return { checkpoint: null, reason: "checkpoint_storage_unavailable" };
    }
    if (raw === null) return { checkpoint: null, reason: "checkpoint_missing" };
    try {
      return normalizeStoredCheckpoint(JSON.parse(raw), viewId);
    } catch (e) {
      return { checkpoint: null, reason: "checkpoint_invalid" };
    }
  }

  function checkpointPayload(current, continuity) {
    const counts = {};
    for (const severity of STREAM_SEVERITIES) {
      counts[severity] = current.counters.severityCounts[severity].text;
    }
    return {
      checkpoint_schema_version: STREAM_CHECKPOINT_SCHEMA_VERSION,
      view_id: current.identity.viewId,
      client_id: current.identity.clientId,
      session_id: current.identity.sessionId,
      stream_instance_id: current.identity.streamInstanceId,
      counter_schema_version: current.identity.counterSchemaVersion,
      // Store a tombstone for a source-unavailable or continuity-uncertain
      // visit.  A later healthy response must not turn that visit into a
      // compatible exact baseline merely because page-memory state was lost.
      continuity_status: continuity && STREAM_CHECKPOINT_CONTINUITY_STATUSES.includes(continuity.status)
        ? continuity.status
        : "continuity_uncertain",
      counters: {
        total_records: current.counters.totalRecords.text,
        recognized_severity_records: current.counters.severityRecords.text,
        recognized_severity_counts: counts,
        rejected_source_records: current.counters.rejectedSourceRecords.text,
        continuity_events: current.counters.continuityEvents.text,
        noteworthy_items: current.counters.noteworthyItems.text,
        noteworthy_source_records: current.counters.noteworthySourceRecords.text,
        system_notices: current.counters.systemNotices.text,
        first_observed_at: current.counters.firstObservedAt === null
          ? null
          : current.counters.firstObservedAt.text,
        last_observed_at: current.counters.lastObservedAt === null
          ? null
          : current.counters.lastObservedAt.text,
        latest_server_sequence: current.counters.latestServerSequence.text,
      },
    };
  }

  function checkpointFromCurrent(current, continuity) {
    return {
      identity: current.identity,
      counters: current.counters,
      continuityStatus: continuity && STREAM_CHECKPOINT_CONTINUITY_STATUSES.includes(continuity.status)
        ? continuity.status
        : "continuity_uncertain",
    };
  }

  function persistCheckpoint(current, continuity) {
    try {
      localStorage.setItem(
        streamCheckpointKey(current.identity.viewId),
        JSON.stringify(checkpointPayload(current, continuity))
      );
      return true;
    } catch (e) {
      return false;
    }
  }

  function checkpointContinuityForStorage(continuity, comparison, checkpoint) {
    if (!continuity || continuity.status !== "no_known_gap") return continuity;
    // A continuity-event counter can make this comparison incomplete even
    // after the follower has recovered and currently reports "continuing".
    // That gap belongs to this baseline interval and must survive a reload.
    if (checkpoint && checkpoint.continuityStatus === "no_known_gap" &&
        comparison && comparison.status === "incomplete" &&
        comparison.unavailable_reason === "continuity_uncertain") {
      return { status: "continuity_uncertain", warning: null };
    }
    return continuity;
  }

  function publicIdentity(identity) {
    if (!identity) return null;
    return {
      view_id: identity.viewId,
      client_id: identity.clientId,
      session_id: identity.sessionId,
      stream_instance_id: identity.streamInstanceId,
      counter_schema_version: identity.counterSchemaVersion,
    };
  }

  function continuityState(data, prior) {
    if (prior && prior.status === "continuity_uncertain") return prior;
    const warning = typeof data.continuity_warning === "string" && data.continuity_warning
      ? data.continuity_warning
      : null;
    const transition = typeof data.source_transition === "string" ? data.source_transition : null;
    if (warning || transition === "replaced" || transition === "truncated") {
      return { status: "continuity_uncertain", warning: warning };
    }
    if (data.source_available === false) {
      return { status: "source_unavailable", warning: null };
    }
    // A source that was unavailable during this page visit cannot later become
    // affirmative merely because it is reachable again.  It may have had an
    // unobserved interval, so the comparison stays incomplete.
    if (prior && prior.status === "source_unavailable") {
      return { status: "continuity_uncertain", warning: null };
    }
    // Exact deltas are for accepted observations, not an audit assertion.
    // Even that narrower statement needs an affirmative current source state:
    // missing producer telemetry, an unknown transition, and recovery after a
    // disappearance do not establish continuous observation while away.
    if (data.source_available !== true ||
        (transition !== "initial" && transition !== "continuing")) {
      return { status: "continuity_uncertain", warning: null };
    }
    return { status: "no_known_gap", warning: null };
  }

  function unavailableComparison(reason, current, checkpoint, continuity) {
    return {
      object_type: "stream_visit_comparison",
      comparison_schema_version: 1,
      status: "unavailable",
      exact_deltas: false,
      unavailable_reason: reason,
      checkpoint_identity: checkpoint ? publicIdentity(checkpoint.identity) : null,
      current_identity: current ? publicIdentity(current.identity) : null,
      deltas: null,
      continuity: continuity,
    };
  }

  function incompleteComparison(reason, current, checkpoint, continuity) {
    const comparison = unavailableComparison(reason, current, checkpoint, continuity);
    comparison.status = "incomplete";
    return comparison;
  }

  function compareCheckpoint(current, checkpoint, continuity) {
    if (checkpoint.identity.viewId !== current.identity.viewId) {
      return unavailableComparison("checkpoint_identity_changed", current, checkpoint, continuity);
    }
    if (checkpoint.identity.sessionId !== current.identity.sessionId) {
      return unavailableComparison("session_changed", current, checkpoint, continuity);
    }
    if (checkpoint.identity.clientId !== current.identity.clientId) {
      return unavailableComparison("checkpoint_identity_changed", current, checkpoint, continuity);
    }
    if (checkpoint.identity.streamInstanceId !== current.identity.streamInstanceId) {
      return unavailableComparison("stream_state_changed", current, checkpoint, continuity);
    }
    if (checkpoint.identity.counterSchemaVersion !== current.identity.counterSchemaVersion) {
      return unavailableComparison("counter_schema_changed", current, checkpoint, continuity);
    }
    // The checkpoint is a baseline for the entire earlier browser visit.  If
    // that visit saw an unavailable source or a continuity warning, preserving
    // only its counters would let a reload silently convert it to an exact
    // zero-delta comparison.  The persisted marker keeps the comparison
    // incomplete until a later healthy visit establishes a new baseline.
    if (checkpoint.continuityStatus !== "no_known_gap") {
      return incompleteComparison(
        "checkpoint_continuity_insufficient",
        current,
        checkpoint,
        { status: "continuity_uncertain", warning: null }
      );
    }

    const checkpointFirst = checkpoint.counters.firstObservedAt;
    const currentFirst = current.counters.firstObservedAt;
    const checkpointLast = checkpoint.counters.lastObservedAt;
    const currentLast = current.counters.lastObservedAt;
    if ((checkpointFirst === null && checkpoint.counters.totalRecords.value !== BigInt(0)) ||
        (checkpointFirst !== null && (currentFirst === null ||
          currentFirst.text !== checkpointFirst.text)) ||
        (checkpointLast !== null && (currentLast === null ||
          currentLast.value < checkpointLast.value))) {
      return unavailableComparison("counter_regressed", current, checkpoint, continuity);
    }

    const deltas = {};
    const totalRecords = current.counters.totalRecords.value - checkpoint.counters.totalRecords.value;
    const severityRecords = current.counters.severityRecords.value - checkpoint.counters.severityRecords.value;
    if (totalRecords < BigInt(0) || severityRecords < BigInt(0)) {
      return unavailableComparison("counter_regressed", current, checkpoint, continuity);
    }
    const severityCounts = {};
    for (const severity of STREAM_SEVERITIES) {
      const value = current.counters.severityCounts[severity].value -
        checkpoint.counters.severityCounts[severity].value;
      if (value < BigInt(0)) {
        return unavailableComparison("counter_regressed", current, checkpoint, continuity);
      }
      severityCounts[severity] = value.toString();
    }
    const severityTotal = STREAM_SEVERITIES.reduce(function (total, severity) {
      return total + BigInt(severityCounts[severity]);
    }, BigInt(0));
    if (severityTotal !== severityRecords) {
      return unavailableComparison("counter_regressed", current, checkpoint, continuity);
    }
    const rejectedSourceRecords = current.counters.rejectedSourceRecords.value -
      checkpoint.counters.rejectedSourceRecords.value;
    const continuityEvents = current.counters.continuityEvents.value -
      checkpoint.counters.continuityEvents.value;
    const noteworthyItems = current.counters.noteworthyItems.value -
      checkpoint.counters.noteworthyItems.value;
    const noteworthySourceRecords = current.counters.noteworthySourceRecords.value -
      checkpoint.counters.noteworthySourceRecords.value;
    const systemNotices = current.counters.systemNotices.value -
      checkpoint.counters.systemNotices.value;
    const latestServerSequence = current.counters.latestServerSequence.value -
      checkpoint.counters.latestServerSequence.value;
    if (rejectedSourceRecords < BigInt(0) || continuityEvents < BigInt(0) ||
        noteworthyItems < BigInt(0) || noteworthySourceRecords < BigInt(0) ||
        systemNotices < BigInt(0) || latestServerSequence < BigInt(0) ||
        latestServerSequence !== totalRecords ||
        noteworthyItems !== noteworthySourceRecords + systemNotices) {
      return unavailableComparison("counter_regressed", current, checkpoint, continuity);
    }
    deltas.total_records = totalRecords.toString();
    deltas.recognized_severity_records = severityRecords.toString();
    deltas.recognized_severity_counts = severityCounts;
    deltas.rejected_source_records = rejectedSourceRecords.toString();
    deltas.continuity_events = continuityEvents.toString();
    deltas.noteworthy_items = noteworthyItems.toString();
    deltas.noteworthy_source_records = noteworthySourceRecords.toString();
    deltas.system_notices = systemNotices.toString();
    deltas.latest_server_sequence = latestServerSequence.toString();
    const comparisonContinuity = continuityEvents > BigInt(0)
      ? {
          status: "continuity_uncertain",
          warning: continuity && typeof continuity.warning === "string"
            ? continuity.warning
            : null,
        }
      : continuity;
    // A gap does not make the independently maintained cumulative counters
    // malformed, but it does make a complete since-last-visit claim unsafe.
    // Keep the numbers internal to this compatibility gate and expose no
    // deltas unless both the counters and continuity are affirmative.
    if (!comparisonContinuity || comparisonContinuity.status !== "no_known_gap") {
      return incompleteComparison(
        comparisonContinuity && comparisonContinuity.status === "source_unavailable"
          ? "source_unavailable"
          : "continuity_uncertain",
        current,
        checkpoint,
        comparisonContinuity
      );
    }
    return {
      object_type: "stream_visit_comparison",
      comparison_schema_version: 1,
      status: "available",
      exact_deltas: true,
      unavailable_reason: null,
      checkpoint_identity: publicIdentity(checkpoint.identity),
      current_identity: publicIdentity(current.identity),
      deltas: deltas,
      continuity: comparisonContinuity,
    };
  }

  core.getStreamCheckpointKey = function (viewId) {
    const safeViewId = safeCheckpointId(viewId);
    return safeViewId ? streamCheckpointKey(safeViewId) : null;
  };

  core.clearStreamCheckpoint = function (viewId) {
    const safeViewId = safeCheckpointId(viewId);
    if (!safeViewId) return false;
    try {
      localStorage.removeItem(streamCheckpointKey(safeViewId));
      return true;
    } catch (e) {
      return false;
    }
  };

  core.getStreamVisitComparison = function () {
    return state.streamVisitComparison;
  };

  core.updateStreamVisitComparison = function (data) {
    const parsedCurrent = normalizeCurrentStreamState(data);
    const previous = state.streamVisitComparison;
    const continuity = continuityState(data || {}, previous && previous.continuity);
    if (!parsedCurrent.current) {
      state.streamVisitComparison = unavailableComparison(
        parsedCurrent.reason,
        null,
        state.streamVisitCheckpoint,
        continuity
      );
      return state.streamVisitComparison;
    }

    const current = parsedCurrent.current;
    if (state.streamVisitComparisonViewId !== current.identity.viewId) {
      const loaded = loadStoredCheckpoint(current.identity.viewId);
      state.streamVisitComparisonViewId = current.identity.viewId;
      state.streamVisitCheckpoint = loaded.checkpoint;
      state.streamVisitCheckpointReason = loaded.reason;
      state.streamVisitComparison = loaded.checkpoint
        ? compareCheckpoint(current, loaded.checkpoint, continuity)
        : unavailableComparison(loaded.reason, current, null, continuity);
    } else if (state.streamVisitCheckpoint) {
      state.streamVisitComparison = compareCheckpoint(
        current,
        state.streamVisitCheckpoint,
        continuity
      );
    } else {
      // A missing, corrupt, or incompatible checkpoint remains unavailable for
      // this visit even though the current state can seed the next visit.
      state.streamVisitComparison = unavailableComparison(
        state.streamVisitCheckpointReason || "checkpoint_missing",
        current,
        null,
        continuity
      );
    }
    const checkpointContinuity = checkpointContinuityForStorage(
      continuity,
      state.streamVisitComparison,
      state.streamVisitCheckpoint
    );
    const checkpointPersisted = persistCheckpoint(current, checkpointContinuity);
    // A first visit has no earlier comparison, but a successfully stored
    // checkpoint is also this open page's fixed leave-and-return baseline.
    // Do not do this for corrupt/incompatible storage or failed writes: those
    // conditions must continue to report an unavailable comparison instead
    // of manufacturing a reassuring zero change.
    if (checkpointPersisted && !state.streamVisitCheckpoint &&
        state.streamVisitCheckpointReason === "checkpoint_missing") {
      state.streamVisitCheckpoint = checkpointFromCurrent(current, checkpointContinuity);
      state.streamVisitCheckpointReason = null;
    }
    return state.streamVisitComparison;
  };

  core.currentHistoryMeta = function () {
    if (!state.currentSnapshot) return null;
    for (const item of state.historyItems) {
      if (item.snapshot_id === state.currentSnapshot) return item;
    }
    return null;
  };
})();

/* plotsrv source: js/core/storage.js */
// src/plotsrv/static/js/core/storage.js
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  core.storageKeys = {
   autoRefreshEnabled: "plotsrv:v2:auto_refresh_enabled",
   autoRefreshInterval: "plotsrv:v2:auto_refresh_interval",
   textWrapEnabled: "plotsrv:v1:text_wrap_enabled",
   jsonFindQuery: "plotsrv:v1:json_find_query",
   tablePrefsPrefix: "plotsrv:v2:table_prefs:",
   jsonPrefsPrefix: "plotsrv:v2:json_prefs:",
   textPrefsPrefix: "plotsrv:v2:text_prefs:",
   viewSelectorMode: "plotsrv:v1:view_selector_mode",
   viewSelectorRecent: "plotsrv:v1:view_selector_recent",
 };   

  core.loadPref = function (key, fallbackValue) {
    try {
      const val = localStorage.getItem(key);
      return val == null ? fallbackValue : val;
    } catch (e) {
      return fallbackValue;
    }
  };

  core.savePref = function (key, value) {
    try {
      localStorage.setItem(key, String(value));
    } catch (e) {
      // ignore
    }
  };

  core.getTablePrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.tablePrefsPrefix + safeViewId;
  };

  core.loadTablePrefs = function (viewId) {
    const fallback = {
      column_order: [],
      hidden_fields: [],
      search_query: "",
      header_filters: {},
    };

    try {
      const raw = localStorage.getItem(core.getTablePrefsKey(viewId));
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      const headerFilters =
        parsed.header_filters && typeof parsed.header_filters === "object"
          ? parsed.header_filters
          : {};

      const cleanHeaderFilters = {};
      for (const [key, value] of Object.entries(headerFilters)) {
        cleanHeaderFilters[String(key)] = String(value ?? "");
      }

      return {
        column_order: Array.isArray(parsed.column_order)
          ? parsed.column_order.map(String)
          : [],
        hidden_fields: Array.isArray(parsed.hidden_fields)
          ? parsed.hidden_fields.map(String)
          : [],
        search_query:
          typeof parsed.search_query === "string" ? parsed.search_query : "",
        header_filters: cleanHeaderFilters,
      };
    } catch (e) {
      return fallback;
    }
  };

  core.saveTablePrefs = function (viewId, prefs) {
    const headerFilters = {};
    if (prefs && prefs.header_filters && typeof prefs.header_filters === "object") {
      for (const [key, value] of Object.entries(prefs.header_filters)) {
        headerFilters[String(key)] = String(value ?? "");
      }
    }

    const payload = {
      column_order: Array.isArray(prefs && prefs.column_order)
        ? prefs.column_order.map(String)
        : [],
      hidden_fields: Array.isArray(prefs && prefs.hidden_fields)
        ? prefs.hidden_fields.map(String)
        : [],
      search_query:
        prefs && typeof prefs.search_query === "string"
          ? prefs.search_query
          : "",
      header_filters: headerFilters,
    };

    try {
      localStorage.setItem(
        core.getTablePrefsKey(viewId),
        JSON.stringify(payload)
      );
    } catch (e) {
      // ignore
    }
  };

  core.clearTablePrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getTablePrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };

  core.getTextPrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.textPrefsPrefix + safeViewId;
  };
  
  core.loadTextPrefs = function (viewId) {
    const fallback = {
      wrap_enabled: false,
      reverse_enabled: false,
      colour_enabled: true,
    };
  
    try {
      const raw = localStorage.getItem(core.getTextPrefsKey(viewId));
      if (!raw) {
        return {
          wrap_enabled: core.loadPref(core.storageKeys.textWrapEnabled, "0") === "1",
          reverse_enabled: false,
          colour_enabled: true,
        };
      }
  
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;
  
      return {
        wrap_enabled:
          typeof parsed.wrap_enabled === "boolean"
            ? parsed.wrap_enabled
            : fallback.wrap_enabled,
        reverse_enabled:
          typeof parsed.reverse_enabled === "boolean"
            ? parsed.reverse_enabled
            : fallback.reverse_enabled,
        colour_enabled:
          typeof parsed.colour_enabled === "boolean"
            ? parsed.colour_enabled
            : fallback.colour_enabled,
      };
    } catch (e) {
      return fallback;
    }
  };
  
  core.saveTextPrefs = function (viewId, prefs) {
  
    const payload = {
      wrap_enabled: !!(prefs && prefs.wrap_enabled),
      reverse_enabled: !!(prefs && prefs.reverse_enabled),
      colour_enabled: prefs && prefs.colour_enabled !== false,
    };

    try {
      localStorage.setItem(core.getTextPrefsKey(viewId), JSON.stringify(payload));
    } catch (e) {
      // ignore
    }
  
    try {
      localStorage.setItem(
        core.storageKeys.textWrapEnabled,
        payload.wrap_enabled ? "1" : "0"
      );
    } catch (e) {
      // ignore
    }
  };
  
  core.clearTextPrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getTextPrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };
  

  core.getJsonPrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.jsonPrefsPrefix + safeViewId;
  };

  core.loadJsonPrefs = function (viewId) {
    const fallback = {
      mode: "json",
      level_limit: "2",
      find_query: "",
      pinned_values: [],
    };

    try {
      const raw = localStorage.getItem(core.getJsonPrefsKey(viewId));
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      return {
        mode:
          typeof parsed.mode === "string" && parsed.mode
            ? parsed.mode
            : fallback.mode,
        level_limit:
          typeof parsed.level_limit === "string" && parsed.level_limit
            ? parsed.level_limit
            : fallback.level_limit,
        find_query:
          typeof parsed.find_query === "string"
            ? parsed.find_query
            : fallback.find_query,
        pinned_values: Array.isArray(parsed.pinned_values)
          ? parsed.pinned_values.map(String)
          : [],
      };
    } catch (e) {
      return fallback;
    }
  };

  core.saveJsonPrefs = function (viewId, prefs) {
    const payload = {
      mode:
        prefs && typeof prefs.mode === "string" && prefs.mode
          ? prefs.mode
          : "json",
      level_limit:
        prefs && typeof prefs.level_limit === "string" && prefs.level_limit
          ? prefs.level_limit
          : "2",
      find_query:
        prefs && typeof prefs.find_query === "string"
          ? prefs.find_query
          : "",
      pinned_values: Array.isArray(prefs && prefs.pinned_values)
        ? Array.from(new Set(prefs.pinned_values.map(String)))
        : [],
    };

    try {
      localStorage.setItem(core.getJsonPrefsKey(viewId), JSON.stringify(payload));
    } catch (e) {
      // ignore
    }
  };

  core.clearJsonPrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getJsonPrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };
})();

/* plotsrv source: js/core/history.js */
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

  function writeSnapshotToUrl(snapshotId) {
    try {
      const url = new URL(window.location.href);
      if (snapshotId) {
        url.searchParams.set("snapshot", snapshotId);
      } else {
        url.searchParams.delete("snapshot");
      }
      window.history.replaceState({}, "", url.toString());
    } catch (e) {
      // ignore
    }
  }

  function snapshotQuery() {
    return state.currentSnapshot
      ? "&snapshot=" + encodeURIComponent(state.currentSnapshot)
      : "";
  }

  function isHistoryMode() {
    return !!state.currentSnapshot;
  }

  function currentHistoryMeta() {
    if (!state.currentSnapshot) return null;

    for (const item of state.historyItems || []) {
      if (item.snapshot_id === state.currentSnapshot) {
        return item;
      }
    }
    return null;
  }

  function syncHistoryUi() {
    const sel = document.getElementById("history-select");
    const isHistory = isHistoryMode();

    if (sel) {
      sel.value = state.currentSnapshot || "";
    }

    const snapshotWrap = document.getElementById("snapshots-control");
    const unavailableReturn = document.getElementById("snapshots-return-latest");
    if (unavailableReturn) {
      unavailableReturn.hidden =
        !isHistory || !snapshotWrap || snapshotWrap.dataset.state === "enabled";
    }

    if (typeof core.setHeaderViewState === "function") {
      const meta = currentHistoryMeta();
      core.setHeaderViewState(
        isHistory ? "snapshot" : "latest",
        isHistory
          ? {
              id: state.currentSnapshot,
              createdAt: meta && meta.created_at ? meta.created_at : null,
            }
          : null
      );
    }

    if (document.body) {
      document.body.classList.toggle("ps-is-history", isHistory);
    }

    if (typeof core.syncAutoRefreshAvailability === "function") {
      core.syncAutoRefreshAvailability();
    }
  }

  function setSnapshotControlState(capability, snapshots, failed) {
    const wrap = document.getElementById("snapshots-control");
    const selector = document.getElementById("snapshots-selector");
    const info = document.getElementById("snapshots-info");
    const returnLatest = document.getElementById("snapshots-return-latest");
    const sel = document.getElementById("history-select");
    if (!wrap || !selector || !info || !sel) return;

    const usable = !failed && (!capability || capability.enabled === true);
    const hasSnapshots = usable && snapshots.length > 0;
    const reason = failed
      ? "Snapshot availability could not be loaded."
      : !usable
        ? String(
            (capability && capability.message) ||
              "Snapshots are unavailable for this view."
          )
        : !hasSnapshots
          ? "No snapshots have been saved for this view yet."
          : "";

    wrap.dataset.state = failed
      ? "error"
      : hasSnapshots
        ? "enabled"
        : usable
          ? "empty"
          : "unavailable";
    selector.hidden = false;
    selector.title = reason;
    sel.title = reason;
    sel.setAttribute("aria-label", reason ? "Snapshots. " + reason : "Snapshots");
    info.hidden = !reason;
    info.title = reason;
    info.setAttribute("aria-label", reason);
    if (returnLatest) returnLatest.hidden = usable || !state.currentSnapshot;
    sel.disabled = !hasSnapshots;
  }

  async function loadHistory() {
    const sel = document.getElementById("history-select");
    if (!sel) return;

    try {
      const res = await fetch(
        "/history?view=" +
          encodeURIComponent(config.activeViewId) +
          "&_ts=" +
          Date.now()
      );
      if (!res.ok) throw new Error("history fetch failed");

      const data = await res.json();
      const snapshots = Array.isArray(data.snapshots) ? data.snapshots : [];
      const capability =
        data.capability && typeof data.capability === "object"
          ? data.capability
          : null;
      state.historyItems = snapshots;
      state.snapshotCapability = capability;

      const parts = [];

      if (snapshots.length === 0) {
        parts.push('<option value="">No snapshots yet</option>');
      } else {
        parts.push('<option value="">Live (latest)</option>');
        for (const snap of snapshots) {
          const ts =
            snap.created_at && typeof core.fmtLocalTime === "function"
              ? core.fmtLocalTime(snap.created_at)
              : snap.snapshot_id;
          let label = ts;
          
          if (snap.is_live_equivalent) {
            label = "Latest snapshot (same as Live)";
          } else if (snap.is_latest) {
            label = "Latest snapshot · " + ts;
          }
          
          const kind = snap.kind ? " · " + core.escapeHtml(snap.kind) : "";
          
          parts.push(
            '<option value="' +
              core.escapeHtml(snap.snapshot_id) +
              '">' +
              core.escapeHtml(label) +
              kind +
              "</option>"
          );
        }
      }

      sel.innerHTML = parts.join("");

      if (state.currentSnapshot) {
        const exists = snapshots.some(function (x) {
          return x.snapshot_id === state.currentSnapshot;
        });
        if (!exists) {
          const missingSnapshot = state.currentSnapshot;
          state.currentSnapshot = null;
          writeSnapshotToUrl(null);
          state.pendingSnapshotNotice =
            '<span class="badge">SNAPSHOT DELETED</span> ' +
            "Selected snapshot " +
            core.escapeHtml(missingSnapshot) +
            " is no longer available. Showing latest data.";
        }
      }

      setSnapshotControlState(capability, snapshots, false);
      sel.value = state.currentSnapshot || "";
      syncHistoryUi();
    } catch (e) {
      sel.innerHTML = '<option value="">Snapshots unavailable</option>';
      state.historyItems = [];
      state.snapshotCapability = null;
      setSnapshotControlState(null, [], true);
      syncHistoryUi();
    }
  }

  async function handleMissingSnapshot(kindLabel) {
    state.currentSnapshot = null;
    writeSnapshotToUrl(null);
    syncHistoryUi();

    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage(
        '<span class="badge">SNAPSHOT DELETED</span> ' +
          "Selected " +
          core.escapeHtml(kindLabel) +
          " snapshot is no longer available."
      );
    }

    try {
      await loadHistory();
    } catch (e) {
      // ignore
    }

    if (typeof core.refreshStatus === "function") {
      core.refreshStatus();
    }
  }

  function returnToLive() {
    state.currentSnapshot = null;
    writeSnapshotToUrl(null);
    syncHistoryUi();

    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("");
    }

    if (typeof core.reloadCurrentView === "function") {
      Promise.resolve(core.reloadCurrentView()).then(function () {
        if (typeof core.markBrowserViewApplied === "function") {
          core.markBrowserViewApplied();
        }
      });
    }

    if (typeof core.restoreAutoRefreshState === "function") {
      core.restoreAutoRefreshState();
    }
  }

  function bindHistoryControls() {
    const sel = document.getElementById("history-select");
    if (!sel) return;

    sel.addEventListener("change", function () {
      const value = String(sel.value || "");
      state.currentSnapshot = value ? value : null;
      writeSnapshotToUrl(state.currentSnapshot);
      syncHistoryUi();

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (typeof core.reloadCurrentView === "function") {
        Promise.resolve(core.reloadCurrentView()).then(function () {
          if (typeof core.markBrowserViewApplied === "function") {
            core.markBrowserViewApplied();
          }
        });
      }
    });

    const returnLatest = document.getElementById("snapshots-return-latest");
    if (returnLatest) {
      returnLatest.addEventListener("click", returnToLive);
    }
  }

  function showPendingSnapshotNotice() {
    if (!state.pendingSnapshotNotice) return;
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage(state.pendingSnapshotNotice);
    }
    state.pendingSnapshotNotice = null;
  }

  core.writeSnapshotToUrl = writeSnapshotToUrl;
  core.snapshotQuery = snapshotQuery;
  core.isHistoryMode = isHistoryMode;
  core.currentHistoryMeta = currentHistoryMeta;
  core.syncHistoryUi = syncHistoryUi;
  core.loadHistory = loadHistory;
  core.handleMissingSnapshot = handleMissingSnapshot;
  core.bindHistoryControls = bindHistoryControls;
  core.showPendingSnapshotNotice = showPendingSnapshotNotice;
  core.returnToLive = returnToLive;

  window.returnToLive = returnToLive;
})();

/* plotsrv source: js/core/status.js */
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
      status.hidden = !html;
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

  function normalizeViewMenuRevision(value) {
    return Number.isInteger(value) && value >= 0 ? value : null;
  }

  function refreshViewIcons(viewMenuRevision) {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (!wrap) return;

    const nextRevision = normalizeViewMenuRevision(viewMenuRevision);
    if (
      nextRevision !== null &&
      state.viewMenuRevision !== null &&
      nextRevision === state.viewMenuRevision
    ) {
      return Promise.resolve();
    }

    if (state.viewMenuRefreshPromise) {
      return state.viewMenuRefreshPromise;
    }

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

    const refreshPromise = (async function () {
      try {
        const res = await fetch("/views?_ts=" + Date.now());
        if (!res.ok) return;
        const views = await res.json();

        const byId = {};
        for (const v of views) {
          byId[v.view_id] = v;
        }

        if (typeof core.updateViewSelectorCatalogue === "function") {
          core.updateViewSelectorCatalogue(views);
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
          const label = wrap.querySelector(".ps-viewselect__label");
          if (img && ICONS[iconKey] && img.getAttribute("src") !== ICONS[iconKey]) {
            img.setAttribute("src", ICONS[iconKey]);
          }
          if (label) label.textContent = String(activeMeta.label || activeMeta.view_id);
        }
        if (nextRevision !== null) {
          state.viewMenuRevision = nextRevision;
        }
      } catch (e) {
        // ignore
      }
    })();

    state.viewMenuRefreshPromise = refreshPromise;
    function clearInFlight() {
      if (state.viewMenuRefreshPromise === refreshPromise) {
        state.viewMenuRefreshPromise = null;
      }
    }
    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
  }

  function elapsedLabel(totalSeconds) {
    const age = formatAgeShort(totalSeconds);
    return age ? age.replace(/ old$/, " ago") : "";
  }

  function deriveHeaderStatus(model) {
    if (model.viewMode === "snapshot") {
      const createdAt = model.snapshot && model.snapshot.createdAt;
      return {
        visible: config.showHeaderHistory,
        tone: "history",
        label: "Snapshot",
        context: createdAt ? "From " + fmtLocalTime(createdAt) : "Historical view",
        title: "Historical snapshot",
        copy: createdAt
          ? "Viewing the snapshot saved " + fmtLocalTime(createdAt) + ". Freshness applies only to the latest data."
          : "Viewing a historical snapshot. Freshness applies only to the latest data.",
      };
    }

    if (model.browserData === "update_available") {
      return {
        visible: config.showHeaderFreshness,
        tone: "new-data",
        label: "New data available",
        context: "This view has not applied it yet",
        title: "New data available",
        copy: "The server has newer data than the version currently shown in this browser.",
      };
    }

    const latest = model.latestData || {};
    const freshness = latest.freshness;
    const freshnessState = freshness && freshness.enabled !== false
      ? String(freshness.state || "unknown").toLowerCase()
      : "disabled";
    const elapsed = freshness && typeof freshness.age_s === "number"
      ? elapsedLabel(freshness.age_s)
      : "";
    const updatedContext = elapsed
      ? "Updated " + elapsed
      : latest.lastUpdated
        ? "Updated " + fmtAgo(latest.lastUpdated).replace(/^\(|\)$/g, "")
        : "Update time unavailable";
    const policyLabel = freshness && freshness.label
      ? String(freshness.label)
      : "Freshness policy unavailable";

    if (freshnessState === "error" || freshnessState === "overdue" || freshnessState === "old") {
      return {
        visible: config.showHeaderFreshness,
        tone: "error",
        label: "Very stale",
        context: updatedContext,
        title: "Latest data is very stale",
        copy: policyLabel + (elapsed ? ". Last update was " + elapsed + "." : "."),
      };
    }

    if (freshnessState === "warn" || freshnessState === "warning" || freshnessState === "stale") {
      return {
        visible: config.showHeaderFreshness,
        tone: "warn",
        label: "Stale",
        context: updatedContext,
        title: "Latest data is stale",
        copy: policyLabel + (elapsed ? ". Last update was " + elapsed + "." : "."),
      };
    }

    if (freshnessState === "unknown") {
      return {
        visible: config.showHeaderFreshness,
        tone: "neutral",
        label: "Latest",
        context: policyLabel,
        title: "No latest data yet",
        copy: policyLabel + ". This browser will remain on the latest view while plotsrv waits for data.",
      };
    }

    return {
      visible: config.showHeaderFreshness,
      tone: freshnessState === "ok" ? "live" : "neutral",
      label: freshnessState === "ok" ? "Live" : "Latest",
      context: freshnessState === "ok" && freshness && freshness.age_s < 10
        ? "Updated just now"
        : updatedContext,
      title: freshnessState === "ok" ? "Latest data is up to date" : "Latest view",
      copy: freshnessState === "ok"
        ? policyLabel + (elapsed ? ". Last update was " + elapsed + "." : ".")
        : "This browser is showing the latest applied data. Freshness status is unavailable.",
    };
  }

  function renderHeaderStatus() {
    const wrap = document.getElementById("header-status");
    if (!wrap) return;

    const presentation = deriveHeaderStatus(state.headerStatus);
    wrap.hidden = !presentation.visible;
    wrap.setAttribute("data-status-tone", presentation.tone);

    if (!presentation.visible && typeof core.closeStatusModal === "function") {
      core.closeStatusModal();
    }

    const label = document.getElementById("header-status-label");
    const context = document.getElementById("header-status-context");
    if (label) label.textContent = presentation.label;
    if (context) context.textContent = presentation.context;
    if (typeof core.renderStatusModal === "function") core.renderStatusModal();
  }

  function setHeaderViewState(viewMode, snapshot) {
    state.headerStatus.viewMode = viewMode === "snapshot" ? "snapshot" : "latest";
    state.headerStatus.snapshot = state.headerStatus.viewMode === "snapshot"
      ? snapshot || { id: state.currentSnapshot, createdAt: null }
      : null;
    renderHeaderStatus();
  }

  // Slice 2 can call this when it detects a newer server version without
  // coupling that mechanism to header DOM details.
  function setHeaderBrowserDataState(browserData) {
    state.headerStatus.browserData = browserData === "update_available"
      ? "update_available"
      : "current";
    renderHeaderStatus();
  }

  function setHeaderLatestStatus(statusPayload) {
    state.latestStatusPayload = statusPayload || null;
    state.headerStatus.latestData = {
      lastUpdated: statusPayload && statusPayload.last_updated
        ? statusPayload.last_updated
        : null,
      freshness: statusPayload && statusPayload.freshness
        ? statusPayload.freshness
        : null,
    };
    renderHeaderStatus();
  }

  function refreshLocalFreshness() {
    const latest = state.headerStatus.latestData || {};
    const freshness = latest.freshness;
    const updatedAt = Date.parse(latest.lastUpdated || "");
    if (!freshness || freshness.enabled === false || !Number.isFinite(updatedAt)) {
      renderHeaderStatus();
      return;
    }
    const age = Math.max(0, Math.floor((Date.now() - updatedAt) / 1000));
    const warnRaw = freshness.warn_after_s;
    const overdueRaw = freshness.overdue_after_s ?? freshness.error_after_s;
    const warn = warnRaw == null ? null : Number(warnRaw);
    const overdue = overdueRaw == null ? null : Number(overdueRaw);
    freshness.age_s = age;
    if (overdue !== null && Number.isFinite(overdue) && age >= overdue) {
      Object.assign(freshness, { state: "error", label: "Overdue", emoji: "❌" });
    } else if (warn !== null && Number.isFinite(warn) && age >= warn) {
      Object.assign(freshness, { state: "warn", label: "Stale", emoji: "⚠️" });
    } else {
      Object.assign(freshness, { state: "ok", label: "Fresh", emoji: "✅" });
    }
    renderHeaderStatus();
  }

  function bindHeaderStatus() {
    const button = document.getElementById("header-status-button");
    if (!button) return;

    renderHeaderStatus();
    button.addEventListener("click", function () {
      if (typeof core.openStatusModal === "function") core.openStatusModal();
    });
    if (state.headerFreshnessTimer == null) {
      state.headerFreshnessTimer = window.setInterval(refreshLocalFreshness, 10000);
    }
  }

  function setFileBackedIndicator(statusPayload, isHistory) {
    const marker = document.getElementById("status-file-backed");
    if (!marker) return;

    marker.hidden = true;

    if (isHistory) return;
    if (!statusPayload) return;

    const isWatched = statusPayload.is_watched_file === true;
    const materialization = String(statusPayload.materialization || "").toLowerCase();

    if (!isWatched || materialization !== "file") {
      return;
    }

    marker.hidden = false;
  }

  function refreshStatus() {
    if (state.statusRefreshPromise) {
      return state.statusRefreshPromise;
    }

    const refreshPromise = (async function () {
      try {
        const res = await fetch(
        "/status?view=" + encodeURIComponent(config.activeViewId) + "&_ts=" + Date.now()
        );
        if (!res.ok) return;

        const s = await res.json();

      const errWrap = document.getElementById("status-error-wrap");
      const err = document.getElementById("status-error");

      const restored = !!s.restored_from_storage;
      const restoredAt = s.restored_at || null;
      const restoreSource = s.restore_source || "storage";

      const isHistory =
        typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;

      setHeaderLatestStatus(s);

      setFileBackedIndicator(s, isHistory);

      if (errWrap && err) {
        if (s.last_error) {
          err.textContent = s.last_error;
          errWrap.hidden = false;
        } else {
          err.textContent = "";
          errWrap.hidden = true;
        }
      }

      const isRestoredLive =
        restored &&
        !(typeof core.isHistoryMode === "function" && core.isHistoryMode());
      
      if (isRestoredLive && typeof core.setStatusMessage === "function") {
        const sourceLabel = restoreSource === "latest" ? "latest storage" : "storage";
        const restoredAtText = restoredAt ? " Restored at " + fmtLocalTime(restoredAt) + "." : "";
        core.setStatusMessage(
          '<span class="ps-restored-badge">RESTORED</span> ' +
            "Restored from " +
            core.escapeHtml(sourceLabel) +
            ". Waiting for the next live update." +
            core.escapeHtml(restoredAtText)
        );
      }

        await refreshViewIcons(s.view_menu_revision);
      } catch (e) {
        // ignore
      }
    })();

    state.statusRefreshPromise = refreshPromise;
    function clearInFlight() {
      if (state.statusRefreshPromise === refreshPromise) {
        state.statusRefreshPromise = null;
      }
    }
    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
  }

  core.fmtLocalTime = fmtLocalTime;
  core.fmtAgo = fmtAgo;
  core.formatAgeShort = formatAgeShort;
  core.setStatusMessage = setStatusMessage;
  core.clearPlotObjectUrl = clearPlotObjectUrl;
  core.applyViewFreshness = applyFreshnessClass;
  core.deriveHeaderStatus = deriveHeaderStatus;
  core.renderHeaderStatus = renderHeaderStatus;
  core.setHeaderViewState = setHeaderViewState;
  core.setHeaderBrowserDataState = setHeaderBrowserDataState;
  core.setHeaderLatestStatus = setHeaderLatestStatus;
  core.refreshLocalFreshness = refreshLocalFreshness;
  core.bindHeaderStatus = bindHeaderStatus;
  core.refreshViewIcons = refreshViewIcons;
  core.setFileBackedIndicator = setFileBackedIndicator;
  core.refreshStatus = refreshStatus;
})();

/* plotsrv source: js/core/status_modal.js */
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
  const AUTO_RANGES = [900, 3600, 21600, 86400, 604800];

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return "Not configured";
    if (value < 60) return value + " second" + (value === 1 ? "" : "s");
    if (value < 3600) {
      const minutes = Math.round(value / 60);
      return minutes + " minute" + (minutes === 1 ? "" : "s");
    }
    if (value < 86400) {
      const hours = Math.round(value / 3600);
      return hours + " hour" + (hours === 1 ? "" : "s");
    }
    const days = Math.round(value / 86400);
    return days + " day" + (days === 1 ? "" : "s");
  }

  function relativeTime(iso) {
    const milliseconds = Date.parse(iso || "");
    if (!Number.isFinite(milliseconds)) return "Unknown";
    if (Math.max(0, Date.now() - milliseconds) < 10000) return "Just now";
    return String(core.fmtAgo(iso) || core.fmtLocalTime(iso)).replace(/^\(|\)$/g, "");
  }

  function validActivityEvents(payload) {
    const activity = payload && payload.data_activity;
    const events = activity && Array.isArray(activity.events) ? activity.events : [];
    return events
      .map(function (event) {
        const time = Date.parse(event && event.received_at);
        const count = Number(event && event.count);
        return {
          time: time,
          receivedAt: event && event.received_at,
          count: Number.isSafeInteger(count) && count > 0 ? count : 1,
          source: event && event.source,
        };
      })
      .filter(function (event) {
        return Number.isFinite(event.time);
      })
      .sort(function (left, right) {
        return left.time - right.time;
      });
  }

  function autoRangeSeconds(events, now) {
    if (!events.length) return 3600;
    const spanSeconds = Math.max(1, Math.ceil((now - events[0].time) / 1000));
    for (const seconds of AUTO_RANGES) {
      if (spanSeconds <= seconds) return seconds;
    }
    return null;
  }

  function formatAxisTime(milliseconds, rangeMilliseconds) {
    const date = new Date(milliseconds);
    if (!Number.isFinite(date.getTime())) return "—";
    if (rangeMilliseconds <= 86400000) {
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function renderArrivalTimeline(payload) {
    const track = document.getElementById("status-modal-activity-dots");
    const empty = document.getElementById("status-modal-activity-empty");
    const rangeSelect = document.getElementById("status-modal-range");
    const chart = track && track.closest(".ps-arrival-chart");
    if (!track || !empty || !rangeSelect) return;

    const events = validActivityEvents(payload);
    const now = Date.now();
    const selected = String(rangeSelect.value || "auto");
    const automatic = selected === "auto" ? autoRangeSeconds(events, now) : null;
    const seconds = selected === "all" ? null : selected === "auto"
      ? automatic
      : Number(selected);
    let start = seconds === null
      ? events.length ? events[0].time : now - 3600000
      : now - seconds * 1000;
    if (start >= now) start = now - 1000;
    const visible = events.filter(function (event) {
      return event.time >= start && event.time <= now + 1000;
    });

    track.replaceChildren();
    visible.forEach(function (event, index) {
      const dot = document.createElement("span");
      const position = Math.max(1.5, Math.min(98.5, ((event.time - start) / (now - start)) * 100));
      const size = Math.min(13, 6 + Math.log2(event.count));
      dot.className = "ps-arrival-chart__dot";
      dot.style.left = position + "%";
      dot.style.width = size + "px";
      dot.style.height = size + "px";
      dot.style.bottom = 13 + (index % 3) * 9 + "px";
      dot.title = config.kind === "stream"
        ? event.count + " accepted stream record" + (event.count === 1 ? "" : "s") +
          " · " + core.fmtLocalTime(event.receivedAt)
        : "Published update · " + core.fmtLocalTime(event.receivedAt);
      dot.setAttribute("aria-hidden", "true");
      track.appendChild(dot);
    });

    empty.hidden = visible.length !== 0;
    const rangeMilliseconds = now - start;
    setText("status-modal-range-start", formatAxisTime(start, rangeMilliseconds));
    setText("status-modal-range-end", formatAxisTime(now, rangeMilliseconds));
    if (chart) {
      chart.setAttribute(
        "aria-label",
        visible.length + " data arrival event" + (visible.length === 1 ? "" : "s") +
          " in the selected time range."
      );
    }
  }

  function renderPolicy(freshness, historical) {
    const values = document.getElementById("status-modal-policy-values");
    if (!values) return;
    values.replaceChildren();
    if (!freshness || freshness.enabled === false) {
      setText(
        "status-modal-policy-copy",
        freshness && freshness.reason === "watch_source_without_view_freshness"
          ? "This watched source has no view-specific freshness policy."
          : "Freshness monitoring is disabled for this view."
      );
      return;
    }

    setText(
      "status-modal-policy-copy",
      historical
        ? "These thresholds apply to latest data, not the selected historical view."
        : "Age is evaluated locally as time passes, without polling the server."
    );
    const entries = [
      ["Expected interval", freshness.expected_every_s],
      ["Stale after", freshness.warn_after_s],
      ["Very stale after", freshness.overdue_after_s ?? freshness.error_after_s],
    ];
    entries.forEach(function (entry) {
      const wrap = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = entry[0];
      description.textContent = formatDuration(entry[1]);
      wrap.appendChild(term);
      wrap.appendChild(description);
      values.appendChild(wrap);
    });
  }

  function renderStreamStatus(payload) {
    const section = document.getElementById("status-modal-stream");
    if (!section) return;
    const stream = payload && payload.stream_status;
    section.hidden = config.kind !== "stream";
    if (section.hidden) return;

    const lifecycle = String((stream && stream.lifecycle) || "unknown");
    const lifecycleLabels = {
      live: "Live producer connection",
      retrying: "Producer retrying delivery",
      disconnected: "Producer disconnected",
      incomplete: "Disconnected with pending delivery",
      ended: "Producer ended",
    };
    setText("status-modal-stream-lifecycle", lifecycleLabels[lifecycle] || "Unknown");
    setText(
      "status-modal-stream-heartbeat",
      stream && stream.last_heartbeat_at
        ? relativeTime(stream.last_heartbeat_at)
        : "Not observed"
    );

    let continuity = "Not reported";
    if (stream) {
      if (stream.continuity_warning) continuity = String(stream.continuity_warning);
      else if (stream.source_available === false) continuity = "Source unavailable";
      else if (stream.source_transition === "replaced") continuity = "Source replaced; continuity uncertain";
      else if (stream.source_transition === "truncated") continuity = "Source truncated; continuity uncertain";
      else if (stream.source_available === true) continuity = "No known continuity gap";
    }
    setText("status-modal-stream-continuity", continuity);
  }

  function renderStatusModal() {
    const modal = document.getElementById("status-modal");
    if (!modal || !state.statusModalOpen) return;
    const payload = state.latestStatusPayload || {};
    const snapshot = state.currentSnapshot;
    const historicalStream = state.streamHistoricalSessionId;
    const historical = !!snapshot || !!historicalStream;
    const snapshotMeta = typeof core.currentHistoryMeta === "function"
      ? core.currentHistoryMeta()
      : null;

    if (snapshot) {
      setText("status-modal-viewing", "Snapshot");
      setText(
        "status-modal-viewing-detail",
        snapshotMeta && snapshotMeta.created_at
          ? "Saved " + core.fmtLocalTime(snapshotMeta.created_at) + "."
          : "A fixed historical snapshot is selected."
      );
    } else if (historicalStream) {
      setText("status-modal-viewing", "Stored stream session");
      setText("status-modal-viewing-detail", "A bounded historical observation is selected.");
    } else {
      setText("status-modal-viewing", "Latest data");
      setText("status-modal-viewing-detail", "This view follows accepted live updates.");
    }

    const lastArrival = payload.last_data_arrival_at;
    if (lastArrival) {
      setText("status-modal-received", relativeTime(lastArrival));
      setText("status-modal-received-detail", core.fmtLocalTime(lastArrival));
    } else if (payload.restored_from_storage && payload.last_updated) {
      setText("status-modal-received", "Before this process started");
      setText(
        "status-modal-received-detail",
        "Stored update timestamp: " + core.fmtLocalTime(payload.last_updated)
      );
    } else {
      setText("status-modal-received", "Not yet");
      setText("status-modal-received-detail", "No process-lifetime data arrival recorded.");
    }

    const waiting = state.headerStatus.browserData === "update_available";
    setText("status-modal-browser", waiting ? "Newer update waiting" : "Current");
    setText(
      "status-modal-browser-detail",
      waiting
        ? historical
          ? "Latest data has changed; the historical selection remains fixed."
          : "The server has newer data that this browser has not applied."
        : state.browserLastAppliedAt
          ? "Last applied " + relativeTime(state.browserLastAppliedAt) + "."
          : "The application time is not yet known."
    );

    const freshness = payload.freshness || state.headerStatus.latestData.freshness;
    if (historical) {
      setText("status-modal-freshness", "Not evaluated for history");
      setText("status-modal-freshness-detail", "Freshness applies only to latest data.");
    } else if (!freshness || freshness.enabled === false) {
      setText("status-modal-freshness", "Not configured");
      setText("status-modal-freshness-detail", "No active freshness policy applies.");
    } else {
      setText("status-modal-freshness", String(freshness.label || "Unknown"));
      setText(
        "status-modal-freshness-detail",
        typeof freshness.age_s === "number"
          ? "Latest data is " + core.formatAgeShort(freshness.age_s) + "."
          : "Waiting for the first relevant data arrival."
      );
    }
    renderPolicy(freshness, historical);
    renderStreamStatus(payload);

    const activity = payload.data_activity || {};
    setText(
      "status-modal-activity-copy",
      config.kind === "stream"
        ? "Each dot is an accepted record batch; heartbeats are excluded."
        : "Each dot represents a published update received by plotsrv."
    );
    setText("status-modal-view-id", config.activeViewId);
    setText(
      "status-modal-source",
      payload.data_source && payload.data_source.label
        ? String(payload.data_source.label)
        : "Not known"
    );
    setText(
      "status-modal-applied",
      state.browserLastAppliedAt ? core.fmtLocalTime(state.browserLastAppliedAt) : "Not known"
    );
    const eventCount = Number(activity.event_count) || 0;
    const itemCount = Number(activity.represented_item_count) || 0;
    setText(
      "status-modal-retained",
      config.kind === "stream"
        ? eventCount + " batch event" + (eventCount === 1 ? "" : "s") +
          " representing " + itemCount + " record" + (itemCount === 1 ? "" : "s")
        : eventCount + " update event" + (eventCount === 1 ? "" : "s") +
          " (maximum " + (activity.limit || 256) + ")"
    );
    renderArrivalTimeline(payload);

    const updateNow = document.getElementById("status-modal-update-now");
    const returnLatest = document.getElementById("status-modal-return-latest");
    if (updateNow) updateNow.hidden = !waiting || historical;
    if (returnLatest) {
      returnLatest.hidden = !historical;
      returnLatest.textContent = waiting ? "Return to latest update" : "Return to latest";
    }
  }

  function focusableElements(modal) {
    return Array.from(
      modal.querySelectorAll(
        "button:not([disabled]):not([hidden]), select:not([disabled]), " +
          "summary, [href], [tabindex]:not([tabindex='-1'])"
      )
    ).filter(function (element) {
      return !element.closest("[hidden]");
    });
  }

  function openStatusModal() {
    const backdrop = document.getElementById("status-modal-backdrop");
    const close = document.getElementById("status-modal-close-icon");
    const button = document.getElementById("header-status-button");
    if (!backdrop) return;
    state.statusModalReturnFocus = document.activeElement;
    state.statusModalOpen = true;
    backdrop.hidden = false;
    if (document.body) document.body.classList.add("ps-status-modal-open");
    if (button) button.setAttribute("aria-expanded", "true");
    renderStatusModal();
    if (close) close.focus();
  }

  function closeStatusModal(options) {
    const backdrop = document.getElementById("status-modal-backdrop");
    const button = document.getElementById("header-status-button");
    if (!backdrop || backdrop.hidden) return;
    backdrop.hidden = true;
    state.statusModalOpen = false;
    if (document.body) document.body.classList.remove("ps-status-modal-open");
    if (button) button.setAttribute("aria-expanded", "false");
    if (!options || options.restoreFocus !== false) {
      const target = state.statusModalReturnFocus;
      if (target && typeof target.focus === "function") target.focus();
      else if (button) button.focus();
    }
  }

  function markBrowserViewApplied() {
    state.browserLastAppliedAt = new Date().toISOString();
    renderStatusModal();
  }

  function bindStatusModal() {
    const backdrop = document.getElementById("status-modal-backdrop");
    const modal = document.getElementById("status-modal");
    if (!backdrop || !modal || backdrop.dataset.plotsrvBound === "1") return;

    ["status-modal-close-icon", "status-modal-close"].forEach(function (id) {
      const button = document.getElementById(id);
      if (button) button.addEventListener("click", function () { closeStatusModal(); });
    });
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) closeStatusModal();
    });
    const range = document.getElementById("status-modal-range");
    if (range) range.addEventListener("change", renderStatusModal);

    const updateNow = document.getElementById("status-modal-update-now");
    if (updateNow) {
      updateNow.addEventListener("click", function () {
        if (typeof core.applyPendingUpdate !== "function") return;
        updateNow.disabled = true;
        const finish = function () {
          updateNow.disabled = false;
          renderStatusModal();
        };
        Promise.resolve(core.applyPendingUpdate({ force: true })).then(finish, finish);
      });
    }
    const returnLatest = document.getElementById("status-modal-return-latest");
    if (returnLatest) {
      returnLatest.addEventListener("click", function () {
        closeStatusModal();
        if (state.streamHistoricalSessionId && typeof core.returnToCurrentStream === "function") {
          core.returnToCurrentStream();
        } else if (typeof core.returnToLive === "function") {
          core.returnToLive();
        }
      });
    }

    modal.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeStatusModal();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableElements(modal);
      if (!focusable.length) {
        event.preventDefault();
        modal.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    backdrop.dataset.plotsrvBound = "1";
  }

  core.renderStatusModal = renderStatusModal;
  core.openStatusModal = openStatusModal;
  core.closeStatusModal = closeStatusModal;
  core.markBrowserViewApplied = markBrowserViewApplied;
  core.bindStatusModal = bindStatusModal;
})();

/* plotsrv source: js/core/bottom_bar.js */
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

  function syncDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || !document.body) return;
    const height = Math.ceil(dock.getBoundingClientRect().height);
    document.body.style.setProperty("--ps-bottom-dock-height", height + "px");
  }

  function bindDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || dock.dataset.plotsrvClearanceBound === "1") return;
    syncDockClearance();
    window.addEventListener("resize", syncDockClearance);
    if (typeof window.ResizeObserver === "function") {
      state.bottomDockResizeObserver = new window.ResizeObserver(syncDockClearance);
      state.bottomDockResizeObserver.observe(dock);
    }
    dock.dataset.plotsrvClearanceBound = "1";
  }

  function closeExportMenu(options) {
    const settings = options && typeof options === "object" ? options : {};
    const button = document.getElementById("export-button");
    const menu = document.getElementById("export-menu");
    if (!button || !menu) return;
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (settings.restoreFocus) button.focus();
  }

  function showExportFailure() {
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("Nothing is currently available for that export scope.");
    }
  }

  function runExport(action) {
    let result;
    if (action === "filtered" || action === "retained" || action === "complete") {
      if (typeof core.exportTable === "function") {
        result = core.exportTable(action);
      }
    } else if (action === "table-complete") {
      if (typeof core.exportTable === "function") {
        result = core.exportTable("complete");
      }
    } else if (action === "plot") {
      if (typeof core.exportImage === "function") result = core.exportImage();
    } else if (action === "artifact") {
      if (typeof core.exportArtifact === "function") result = core.exportArtifact();
    }

    if (result === false) showExportFailure();
  }

  function configureBottomBar() {
    const complete = document.querySelector('[data-export-scope="complete"]');
    if (complete) {
      const sourceDownload =
        state.tableLastPayload &&
        state.tableLastPayload.meta &&
        state.tableLastPayload.meta.source_download_url;
      const isHistory =
        typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
      complete.textContent =
        !isHistory && typeof sourceDownload === "string" && sourceDownload
          ? "Complete source CSV file"
          : "Complete published table";
    }
  }

  function bindBottomBar() {
    bindDockClearance();
    const button = document.getElementById("export-button");
    if (!button || button.dataset.plotsrvBound === "1") return;

    const menu = document.getElementById("export-menu");
    if (menu) {
      button.addEventListener("click", function () {
        const willOpen = menu.hidden;
        menu.hidden = !willOpen;
        button.setAttribute("aria-expanded", willOpen ? "true" : "false");
        if (willOpen) {
          const first = menu.querySelector("[data-export-scope]");
          if (first) first.focus();
        }
      });

      menu.addEventListener("click", function (event) {
        const item = event.target.closest("[data-export-scope]");
        if (!item) return;
        closeExportMenu();
        runExport(item.getAttribute("data-export-scope"));
      });

      document.addEventListener("click", function (event) {
        const control = document.getElementById("export-control");
        if (control && !menu.hidden && !control.contains(event.target)) {
          closeExportMenu();
        }
      });

      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !menu.hidden) {
          closeExportMenu({ restoreFocus: true });
        }
      });
    } else {
      button.addEventListener("click", function () {
        runExport(button.getAttribute("data-export-action"));
      });
    }

    button.dataset.plotsrvBound = "1";
    configureBottomBar();
  }

  core.bindBottomBar = bindBottomBar;
  core.configureBottomBar = configureBottomBar;
  core.syncDockClearance = syncDockClearance;
})();

/* plotsrv source: js/core/auto_refresh.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || { core: {}, renderers: {}, state: {}, config: {} };
  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;

  function completeFilter(filter) {
    if (!filter || !filter.field || !filter.op) return false;
    if (filter.op === "missing" || filter.op === "not_missing") return true;
    if (String(filter.value || "").trim() === "") return false;
    if (filter.op === "between" || filter.op === "not_between") {
      return String(filter.valueTo || "").trim() !== "";
    }
    return true;
  }

  function tableHasSorters() {
    const table = state.tabulatorInstance || state.streamTabulatorInstance;
    if (!table || typeof table.getSorters !== "function") return false;
    try {
      const sorters = table.getSorters();
      return Array.isArray(sorters) && sorters.length > 0;
    } catch (e) {
      return false;
    }
  }

  // The single policy boundary for every renderer. Explicit application
  // bypasses interaction blockers, but never changes historical selections.
  function getAutomaticUpdateBlockers() {
    const blockers = [];
    if (document.hidden) blockers.push("hidden_tab");
    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      blockers.push("snapshot");
    }
    if (state.streamHistoricalSessionId) blockers.push("historical_stream_session");

    const ui = state.tableUiState || {};
    if (String(ui.searchQuery || "").trim()) blockers.push("table_search");
    if (Array.isArray(ui.filters) && ui.filters.some(completeFilter)) {
      blockers.push("table_filters");
    }
    if (ui.groupBy) blockers.push("table_grouping");
    if (tableHasSorters()) blockers.push("table_sorting");
    if (state.tablePlotMode === "plot") blockers.push("plot_mode");
    if (ui.filtersOpen || ui.columnsOpen) blockers.push("open_table_panel");

    const main = document.querySelector("main");
    const focused = document.activeElement;
    if (focused && main && main.contains(focused) && focused.matches &&
        focused.matches("input, select, textarea, [contenteditable='true']")) {
      blockers.push("active_editor");
    }
    return blockers;
  }

  function historicalBlocker(blocker) {
    return blocker === "snapshot" || blocker === "historical_stream_session";
  }

  function canApplyPendingUpdate(options) {
    const force = !!(options && options.force);
    const blockers = getAutomaticUpdateBlockers();
    if (blockers.some(historicalBlocker)) return false;
    return force || blockers.length === 0;
  }

  function showPendingUpdate() {
    if (typeof core.setHeaderBrowserDataState === "function") {
      core.setHeaderBrowserDataState("update_available");
    }
  }

  function finishAppliedUpdate(revision) {
    state.appliedUpdateRevision = Math.max(state.appliedUpdateRevision, revision);
    if (typeof core.markBrowserViewApplied === "function") {
      core.markBrowserViewApplied();
    }
    if (state.pendingBrowserUpdate &&
        state.pendingBrowserUpdate.revision <= state.appliedUpdateRevision) {
      state.pendingBrowserUpdate = null;
    }
    if (!state.pendingBrowserUpdate) {
      if (typeof core.setHeaderBrowserDataState === "function") {
        core.setHeaderBrowserDataState("current");
      }
      return;
    }
    showPendingUpdate();
    window.setTimeout(function () { applyPendingUpdate(); }, 0);
  }

  function applyPendingUpdate(options) {
    const pending = state.pendingBrowserUpdate;
    if (!pending || state.browserUpdateApplying) return Promise.resolve(false);
    if (!state.initialViewLoadComplete || !canApplyPendingUpdate(options)) {
      showPendingUpdate();
      return Promise.resolve(false);
    }

    if (pending.kind && pending.kind !== config.kind) {
      window.location.reload();
      return Promise.resolve(true);
    }

    state.browserUpdateApplying = true;
    const revision = pending.revision;
    return Promise.resolve(core.reloadCurrentView())
      .then(function () {
        finishAppliedUpdate(revision);
        return true;
      })
      .catch(function () {
        showPendingUpdate();
        return false;
      })
      .then(function (result) {
        state.browserUpdateApplying = false;
        return result;
      });
  }

  function receiveBrowserUpdate(payload) {
    if (!payload || typeof payload !== "object") return;
    const revision = Number(payload.revision);
    if (!Number.isSafeInteger(revision) || revision <= state.observedUpdateRevision) return;
    state.observedUpdateRevision = revision;

    if (payload.change_type === "catalogue") {
      if (typeof core.refreshViewIcons === "function") core.refreshViewIcons(null);
      return;
    }
    if (payload.view_id && payload.view_id !== config.activeViewId) return;

    // A single assignment coalesces any burst while a fetch is in flight.
    state.pendingBrowserUpdate = payload;
    if (!state.initialViewLoadComplete || !canApplyPendingUpdate()) {
      showPendingUpdate();
      return;
    }
    applyPendingUpdate();
  }

  function bindUpdateNotifications() {
    if (state.browserUpdateSource || typeof window.EventSource !== "function") return;
    const url = "/updates?view=" + encodeURIComponent(config.activeViewId) +
      "&since=" + encodeURIComponent(state.observedUpdateRevision);
    const source = new window.EventSource(url);
    state.browserUpdateSource = source;
    source.addEventListener("update", function (event) {
      try {
        receiveBrowserUpdate(JSON.parse(event.data));
      } catch (e) {
        // A malformed notice is safely ignored; EventSource still reconnects.
      }
    });
  }

  function markInitialViewLoaded() {
    state.initialViewLoadComplete = true;
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  function notifyUpdateEligibilityChanged() {
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) notifyUpdateEligibilityChanged();
  });

  core.getAutomaticUpdateBlockers = getAutomaticUpdateBlockers;
  core.canApplyPendingUpdate = canApplyPendingUpdate;
  core.applyPendingUpdate = applyPendingUpdate;
  core.receiveBrowserUpdate = receiveBrowserUpdate;
  core.bindUpdateNotifications = bindUpdateNotifications;
  core.markInitialViewLoaded = markInitialViewLoaded;
  core.notifyUpdateEligibilityChanged = notifyUpdateEligibilityChanged;

  // Compatibility shims for integrations compiled against the old module.
  core.stopAutoRefresh = function () {};
  core.startAutoRefresh = function () {};
  core.restoreAutoRefreshState = function () {};
  core.syncAutoRefreshAvailability = notifyUpdateEligibilityChanged;
  core.bindAutoRefreshControls = function () {};
})();

/* plotsrv source: js/core/view_selector.js */
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
  const MAX_RECENT_VIEWS = 4;
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
  let activeController = null;

  function cleanText(value, fallback) {
    if (value === null || value === undefined) return fallback || "";
    return String(value).trim() || fallback || "";
  }

  function normalizeViewCatalogue(rawViews) {
    if (!Array.isArray(rawViews)) return [];
    const seen = new Set();
    const views = [];
    for (const raw of rawViews) {
      if (!raw || typeof raw !== "object") continue;
      const viewId = cleanText(raw.view_id, "");
      if (!viewId || seen.has(viewId)) continue;
      seen.add(viewId);
      views.push({
        view_id: viewId,
        label: cleanText(raw.label, viewId),
        section: cleanText(raw.section, "default"),
        kind: cleanText(raw.kind, "none").toLowerCase(),
        icon_key: cleanText(raw.icon_key, "unknown").toLowerCase(),
        freshness:
          raw.freshness && typeof raw.freshness === "object"
            ? raw.freshness
            : null,
      });
    }
    return views;
  }

  function compareViews(a, b) {
    return (
      a.label.localeCompare(b.label, undefined, {
        sensitivity: "base",
        numeric: true,
      }) ||
      a.section.localeCompare(b.section, undefined, { sensitivity: "base" }) ||
      a.view_id.localeCompare(b.view_id, undefined, { sensitivity: "base" })
    );
  }

  function sortViewsAlphabetically(views) {
    return normalizeViewCatalogue(views).slice().sort(compareViews);
  }

  function viewTypeLabel(view) {
    const labels = {
      plot: "Plot",
      table: "Table",
      stream: "Live stream",
      image: "Image",
      markdown: "Markdown",
      json: "JSON",
      python: "Python object",
      traceback: "Traceback",
      exception: "Exception",
      text: "Text",
      html: "HTML",
    };
    return labels[view.icon_key] || labels[view.kind] || "View";
  }

  function filterViewCatalogue(views, query) {
    const words = cleanText(query, "")
      .toLocaleLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    const catalogue = normalizeViewCatalogue(views);
    if (!words.length) return catalogue;
    return catalogue.filter(function (view) {
      const haystack = [
        view.label,
        view.view_id,
        view.section,
        view.kind,
        view.icon_key,
        viewTypeLabel(view),
      ]
        .join(" ")
        .toLocaleLowerCase();
      return words.every(function (word) {
        return haystack.includes(word);
      });
    });
  }

  function safePresentationUrl(value) {
    const url = cleanText(value, "");
    if (!url) return "";
    const scheme = url.match(/^([a-z][a-z0-9+.-]*):/i);
    if (scheme && !/^https?:$/i.test(scheme[0])) return "";
    return url;
  }

  function resolveFeaturedViews(views, rawFeatures) {
    const catalogue = normalizeViewCatalogue(views);
    const byId = new Map(
      catalogue.map(function (view) {
        return [view.view_id, view];
      })
    );
    const seen = new Set();
    const resolved = [];
    if (!Array.isArray(rawFeatures)) return resolved;
    for (const raw of rawFeatures) {
      if (!raw || typeof raw !== "object") continue;
      const viewId = cleanText(raw.view_id || raw.view, "");
      const view = byId.get(viewId);
      if (!view || seen.has(viewId)) continue;
      seen.add(viewId);
      resolved.push({
        view: view,
        title: cleanText(raw.title, view.label),
        caption: cleanText(raw.caption, ""),
        thumbnail_url: safePresentationUrl(raw.thumbnail_url || raw.thumbnail),
      });
    }
    return resolved;
  }

  function storageKey(name, fallback) {
    return core.storageKeys && core.storageKeys[name]
      ? core.storageKeys[name]
      : fallback;
  }

  function loadStoredMode() {
    const key = storageKey("viewSelectorMode", "plotsrv:v1:view_selector_mode");
    if (typeof core.loadPref === "function") return core.loadPref(key, null);
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function saveViewSelectorMode(mode) {
    const key = storageKey("viewSelectorMode", "plotsrv:v1:view_selector_mode");
    if (typeof core.savePref === "function") {
      core.savePref(key, mode);
      return;
    }
    try {
      localStorage.setItem(key, String(mode));
    } catch (e) {
      // Browser storage can be unavailable in private/restricted contexts.
    }
  }

  function initialViewSelectorMode() {
    const stored = loadStoredMode();
    if (stored === "grouped" || stored === "az") return stored;
    return "grouped";
  }

  function recentStorageKey() {
    return storageKey("viewSelectorRecent", "plotsrv:v1:view_selector_recent");
  }

  function loadRecentViews(catalogue) {
    const valid = new Set(catalogue.map(function (view) { return view.view_id; }));
    try {
      const parsed = JSON.parse(localStorage.getItem(recentStorageKey()) || "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map(String)
        .filter(function (viewId, index, items) {
          return valid.has(viewId) && items.indexOf(viewId) === index;
        })
        .slice(0, MAX_RECENT_VIEWS);
    } catch (e) {
      return [];
    }
  }

  function saveRecentViews(viewIds) {
    try {
      localStorage.setItem(
        recentStorageKey(),
        JSON.stringify(viewIds.slice(0, MAX_RECENT_VIEWS))
      );
    } catch (e) {
      // ignore
    }
  }

  function rememberRecentView(viewId, catalogue) {
    if (!viewId) return [];
    const recent = loadRecentViews(catalogue).filter(function (item) {
      return item !== viewId;
    });
    if (catalogue.some(function (view) { return view.view_id === viewId; })) {
      recent.unshift(viewId);
    }
    const bounded = recent.slice(0, MAX_RECENT_VIEWS);
    saveRecentViews(bounded);
    return bounded;
  }

  function iconUrl(view) {
    return ICONS[view.icon_key] || ICONS.unknown;
  }

  function element(tagName, className, textValue) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (textValue !== undefined) node.textContent = textValue;
    return node;
  }

  function applySelection(button, view) {
    const selected = view.view_id === config.activeViewId;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }

  function applyFreshness(button, view) {
    if (typeof core.applyViewFreshness === "function") {
      core.applyViewFreshness(button, view.freshness || null);
    }
  }

  function makeViewItem(view, includeSection) {
    const button = element("button", "ps-viewselect__item");
    button.type = "button";
    button.setAttribute("role", "option");
    button.setAttribute("data-plotsrv-view", view.view_id);
    button.setAttribute("data-view-section", view.section);
    button.setAttribute("data-view-kind", view.kind);
    button.setAttribute("data-view-icon", view.icon_key);
    applySelection(button, view);

    const freshness = element("span", "ps-viewselect__freshness");
    freshness.hidden = true;
    freshness.setAttribute("aria-hidden", "true");
    freshness.setAttribute("data-plotsrv-view-freshness", view.view_id);

    const image = element("img", "ps-viewselect__itemicon");
    image.src = iconUrl(view);
    image.alt = "";

    const copy = element("span", "ps-viewselect__itemcopy");
    copy.appendChild(element("span", "ps-viewselect__itemlabel", view.label));
    const meta = includeSection
      ? view.section + " · " + viewTypeLabel(view)
      : viewTypeLabel(view);
    copy.appendChild(element("span", "ps-viewselect__itemmeta", meta));

    button.appendChild(freshness);
    button.appendChild(image);
    button.appendChild(copy);
    const check = element("span", "ps-viewselect__check", "✓");
    check.setAttribute("aria-hidden", "true");
    button.appendChild(check);
    applyFreshness(button, view);
    return button;
  }

  function makeFeatureFallback(view) {
    const fallback = element("span", "ps-viewselect__feature-fallback");
    const image = element("img");
    image.src = iconUrl(view);
    image.alt = "";
    fallback.appendChild(image);
    return fallback;
  }

  function makeFeatureItem(feature) {
    const view = feature.view;
    const button = element("button", "ps-viewselect__feature");
    button.type = "button";
    button.setAttribute("role", "option");
    button.setAttribute("data-plotsrv-view", view.view_id);
    applySelection(button, view);

    let visual;
    if (feature.thumbnail_url) {
      visual = element("img", "ps-viewselect__feature-thumbnail");
      visual.src = feature.thumbnail_url;
      visual.alt = "";
      visual.loading = "lazy";
      visual.addEventListener(
        "error",
        function () {
          const fallback = makeFeatureFallback(view);
          if (visual.parentNode) visual.parentNode.replaceChild(fallback, visual);
        },
        { once: true }
      );
    } else {
      visual = makeFeatureFallback(view);
    }

    const copy = element("span", "ps-viewselect__feature-copy");
    copy.appendChild(element("span", "ps-viewselect__feature-title", feature.title));
    if (feature.caption) {
      copy.appendChild(
        element("span", "ps-viewselect__feature-caption", feature.caption)
      );
    }
    copy.appendChild(
      element("span", "ps-viewselect__feature-kind", viewTypeLabel(view))
    );

    button.appendChild(visual);
    button.appendChild(copy);
    const check = element("span", "ps-viewselect__check", "✓");
    check.setAttribute("aria-hidden", "true");
    button.appendChild(check);
    applyFreshness(button, view);
    return button;
  }

  function appendGroup(fragment, label, views, includeSection) {
    if (!views.length) return;
    const group = element("section", "ps-viewselect__group");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", label);
    group.appendChild(element("h3", "ps-viewselect__group-label", label));
    const items = element("div", "ps-viewselect__group-items");
    for (const view of views) items.appendChild(makeViewItem(view, includeSection));
    group.appendChild(items);
    fragment.appendChild(group);
  }

  function createController(wrap) {
    const trigger = wrap.querySelector(".ps-viewselect__btn");
    const menu = wrap.querySelector(".ps-viewselect__menu");
    const search = wrap.querySelector(".ps-viewselect__search");
    const tabs = wrap.querySelector(".ps-viewselect__tabs");
    const results = wrap.querySelector(".ps-viewselect__results");
    if (!trigger || !menu || !search || !tabs || !results) return null;

    const controller = {
      catalogue: normalizeViewCatalogue(config.viewCatalogue),
      mode: "grouped",
      query: "",
      recent: [],
      renderFrame: null,
    };
    controller.mode = initialViewSelectorMode();
    controller.recent = rememberRecentView(
      config.activeViewId,
      controller.catalogue
    );

    function availableFeatures() {
      return resolveFeaturedViews(controller.catalogue, config.featuredViews);
    }

    function renderTabs() {
      const modes = [["grouped", "Grouped"], ["az", "A–Z"]];
      const nodes = modes.map(function (entry) {
        const tab = element("button", "ps-viewselect__tab", entry[1]);
        const selected = entry[0] === controller.mode;
        tab.type = "button";
        tab.setAttribute("role", "tab");
        tab.setAttribute("data-view-mode", entry[0]);
        tab.setAttribute("aria-controls", "view-selector-results");
        tab.setAttribute("aria-selected", selected ? "true" : "false");
        tab.tabIndex = selected ? 0 : -1;
        return tab;
      });
      tabs.replaceChildren.apply(tabs, nodes);
    }

    function render() {
      controller.renderFrame = null;
      const features = availableFeatures();
      renderTabs();
      const fragment = document.createDocumentFragment();
      const query = controller.query.trim();

      if (query) {
        appendGroup(
          fragment,
          "Search results",
          filterViewCatalogue(controller.catalogue, query).sort(compareViews),
          true
        );
      } else if (controller.mode === "az") {
        appendGroup(
          fragment,
          "All views",
          controller.catalogue.slice().sort(compareViews),
          true
        );
      } else {
        const featuredIds = new Set(features.map(function (feature) {
          return feature.view.view_id;
        }));
        if (features.length) {
          const featuredGroup = element(
            "section",
            "ps-viewselect__group ps-viewselect__group--featured"
          );
          featuredGroup.setAttribute("role", "group");
          featuredGroup.setAttribute("aria-label", "Featured");
          featuredGroup.appendChild(
            element("h3", "ps-viewselect__group-label", "Featured")
          );
          const featureList = element("div", "ps-viewselect__features");
          for (const feature of features) {
            featureList.appendChild(makeFeatureItem(feature));
          }
          featuredGroup.appendChild(featureList);
          fragment.appendChild(featuredGroup);
        }

        const byId = new Map(controller.catalogue.map(function (view) {
          return [view.view_id, view];
        }));
        const recent = controller.recent
          .map(function (viewId) { return byId.get(viewId); })
          .filter(function (view) {
            return view && !featuredIds.has(view.view_id);
          });
        appendGroup(fragment, "Recent", recent, true);

        const groups = new Map();
        for (const view of controller.catalogue) {
          if (featuredIds.has(view.view_id)) continue;
          if (!groups.has(view.section)) groups.set(view.section, []);
          groups.get(view.section).push(view);
        }
        groups.forEach(function (views, section) {
          appendGroup(fragment, section, views, false);
        });
      }

      if (!fragment.childNodes.length) {
        const empty = element(
          "div",
          "ps-viewselect__empty",
          query ? "No views match your search." : "No views are available."
        );
        empty.setAttribute("role", "status");
        fragment.appendChild(empty);
      }
      results.replaceChildren(fragment);
      const items = Array.from(results.querySelectorAll("[data-plotsrv-view]"));
      const roving = items.find(function (item) {
        return item.getAttribute("aria-selected") === "true";
      }) || items[0];
      items.forEach(function (item) { item.tabIndex = item === roving ? 0 : -1; });
    }

    function scheduleRender() {
      if (controller.renderFrame !== null) cancelAnimationFrame(controller.renderFrame);
      controller.renderFrame = requestAnimationFrame(render);
    }

    function setMode(mode, focusTab) {
      if (mode !== "grouped" && mode !== "az") return;
      controller.mode = mode;
      saveViewSelectorMode(mode);
      render();
      if (focusTab) {
        const selectedTab = tabs.querySelector('[data-view-mode="' + mode + '"]');
        if (selectedTab) selectedTab.focus();
      }
    }

    function clampMenuToViewport() {
      menu.classList.remove("ps-viewselect__menu--clamped-left");
      menu.classList.remove("ps-viewselect__menu--clamped-right");
      const rect = menu.getBoundingClientRect();
      const pad = 8;
      if (rect.left < pad) menu.classList.add("ps-viewselect__menu--clamped-left");
      if (rect.right > window.innerWidth - pad) {
        menu.classList.add("ps-viewselect__menu--clamped-right");
      }
    }

    function openMenu() {
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      render();
      requestAnimationFrame(function () {
        clampMenuToViewport();
        search.focus();
      });
    }

    function closeMenu(restoreFocus) {
      if (menu.hidden) return;
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      if (controller.query) {
        controller.query = "";
        search.value = "";
        render();
      }
      if (restoreFocus) trigger.focus();
    }

    controller.setCatalogue = function (views) {
      controller.catalogue = normalizeViewCatalogue(views);
      config.viewCatalogue = controller.catalogue;
      controller.recent = loadRecentViews(controller.catalogue);
      render();
    };

    trigger.addEventListener("click", function () {
      if (menu.hidden) openMenu();
      else closeMenu(false);
    });
    trigger.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (menu.hidden) openMenu();
        else search.focus();
      }
    });
    search.addEventListener("input", function () {
      controller.query = search.value;
      scheduleRender();
    });
    search.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowDown") return;
      const first = results.querySelector("[data-plotsrv-view]");
      if (first) {
        event.preventDefault();
        first.focus();
      }
    });
    tabs.addEventListener("click", function (event) {
      const tab = event.target.closest && event.target.closest("[data-view-mode]");
      if (tab) {
        event.stopPropagation();
        setMode(tab.getAttribute("data-view-mode"), true);
      }
    });
    tabs.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const allTabs = Array.from(tabs.querySelectorAll("[data-view-mode]"));
      const index = allTabs.indexOf(event.target);
      if (index < 0) return;
      event.preventDefault();
      const offset = event.key === "ArrowRight" ? 1 : -1;
      const next = allTabs[(index + offset + allTabs.length) % allTabs.length];
      setMode(next.getAttribute("data-view-mode"), true);
    });
    results.addEventListener("keydown", function (event) {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const items = Array.from(results.querySelectorAll("[data-plotsrv-view]"));
      if (!items.length) return;
      let index = items.indexOf(event.target.closest("[data-plotsrv-view]"));
      if (event.key === "Home") index = 0;
      else if (event.key === "End") index = items.length - 1;
      else if (event.key === "ArrowDown") index = Math.min(items.length - 1, index + 1);
      else index = Math.max(0, index - 1);
      event.preventDefault();
      items.forEach(function (item, itemIndex) {
        item.tabIndex = itemIndex === index ? 0 : -1;
      });
      items[index].focus();
    });
    results.addEventListener("click", function (event) {
      const item = event.target.closest && event.target.closest("[data-plotsrv-view]");
      if (!item) return;
      const viewId = item.getAttribute("data-plotsrv-view");
      if (!viewId) return;
      controller.recent = rememberRecentView(viewId, controller.catalogue);
      window.location.href = "/?view=" + encodeURIComponent(viewId);
    });
    menu.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu(true);
      }
    });
    document.addEventListener("click", function (event) {
      const path = typeof event.composedPath === "function"
        ? event.composedPath()
        : [];
      const cameFromSelector = path.length
        ? path.includes(wrap)
        : wrap.contains(event.target);
      if (!cameFromSelector) closeMenu(false);
    });
    window.addEventListener("resize", function () {
      if (!menu.hidden) clampMenuToViewport();
    });

    render();
    return controller;
  }

  function updateViewSelectorCatalogue(views) {
    config.viewCatalogue = normalizeViewCatalogue(views);
    if (activeController) activeController.setCatalogue(config.viewCatalogue);
  }

  function bindViewDropdown() {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (wrap) {
      if (wrap.getAttribute("data-view-selector-bound") === "true") return;
      wrap.setAttribute("data-view-selector-bound", "true");
      activeController = createController(wrap);
      return;
    }

    const select = document.getElementById("view-select");
    if (!select) return;
    select.addEventListener("change", function () {
      window.location.href = "/?view=" + encodeURIComponent(select.value);
    });
  }

  core.viewSelectorIcons = ICONS;
  core.normalizeViewCatalogue = normalizeViewCatalogue;
  core.sortViewsAlphabetically = sortViewsAlphabetically;
  core.filterViewCatalogue = filterViewCatalogue;
  core.resolveFeaturedViews = resolveFeaturedViews;
  core.initialViewSelectorMode = initialViewSelectorMode;
  core.saveViewSelectorMode = saveViewSelectorMode;
  core.updateViewSelectorCatalogue = updateViewSelectorCatalogue;
  core.bindViewDropdown = bindViewDropdown;
})();

/* plotsrv source: js/renderers/artifact.js */
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

/* plotsrv source: js/renderers/plot.js */
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

  async function refreshPlot() {
    const img = document.getElementById("plot");
    if (!img) return;

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    const url =
      "/plot?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&_ts=" +
      Date.now();

    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;

    if (!isHistory) {
      if (typeof core.clearPlotObjectUrl === "function") {
        core.clearPlotObjectUrl();
      }
      img.src = url;

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
      return;
    }

    try {
      const res = await fetch(url);
      if (!res.ok) {
        if (
          res.status === 404 &&
          typeof core.handleMissingSnapshot === "function"
        ) {
          await core.handleMissingSnapshot("plot");
          return;
        }
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage("Failed to load plot snapshot (" + res.status + ").");
        }
        return;
      }

      const blob = await res.blob();
      if (typeof core.clearPlotObjectUrl === "function") {
        core.clearPlotObjectUrl();
      }
      state.plotObjectUrl = URL.createObjectURL(blob);
      img.src = state.plotObjectUrl;

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
    } catch (e) {
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to load plot snapshot (network error).");
      }
    }
  }

  function exportImage() {
    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    window.location.href =
      "/plot?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&download=1&_ts=" +
      Date.now();
  }

  core.refreshPlot = refreshPlot;
  core.exportImage = exportImage;

  window.refreshPlot = refreshPlot;
  window.exportImage = exportImage;
})();

/* plotsrv source: js/renderers/table.js */
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

  const MAX_FILTERS = 10;

  const FILTER_OPS = {
    text: [
      { value: "contains", label: "contains" },
      { value: "eq", label: "is equal to" },
      { value: "neq", label: "is not equal to" },
      { value: "missing", label: "is missing" },
      { value: "not_missing", label: "is not missing" },
    ],
    number: [
      { value: "missing", label: "is missing" },
      { value: "not_missing", label: "is not missing" },
      { value: "lt", label: "is less than" },
      { value: "lte", label: "is less than or equal to" },
      { value: "gt", label: "is greater than" },
      { value: "gte", label: "is greater than or equal to" },
      { value: "eq", label: "is equal to" },
      { value: "neq", label: "is not equal to" },
      { value: "between", label: "is between" },
      { value: "not_between", label: "is not between" },
    ],
  };

  function tablePrefKey() {
    return "plotsrv:v4:table_state:" + String(config.activeViewId || "default");
  }

  function buildColumnDefs(columnNames) {
    const hidden = new Set(getHiddenColumns());

    return (columnNames || []).map(function (col) {
      const name = String(col);
      return {
        // Tabulator assigns plain string titles through innerHTML. Column
        // names come from the rendered data, so supply an inert title and
        // return a DOM node whose textContent contains the actual label.
        title: "",
        titleFormatter: function () {
          const element = document.createElement("span");
          element.textContent = name;
          return element;
        },
        field: col,
        visible: !hidden.has(name),
      };
    });
  }

  function preserveColumnOrder(columnDefs, table) {
    if (!table || typeof table.getColumns !== "function") return columnDefs;
    const byField = new Map(columnDefs.map(function (definition) {
      return [definition.field, definition];
    }));
    const ordered = [];
    try {
      table.getColumns().forEach(function (column) {
        const field = column && typeof column.getField === "function"
          ? column.getField()
          : null;
        if (!byField.has(field)) return;
        ordered.push(byField.get(field));
        byField.delete(field);
      });
    } catch (e) {
      return columnDefs;
    }
    byField.forEach(function (definition) { ordered.push(definition); });
    return ordered;
  }

  function currentSorters(table) {
    if (!table || typeof table.getSorters !== "function") return [];
    try {
      return table.getSorters().map(function (sorter) {
        const field = sorter.field ||
          (sorter.column && typeof sorter.column.getField === "function"
            ? sorter.column.getField()
            : null);
        return field ? { column: field, dir: sorter.dir || "asc" } : null;
      }).filter(Boolean);
    } catch (e) {
      return [];
    }
  }

  function defaultTableUiState() {
    return {
      searchQuery: "",
      filtersOpen: false,
      filters: [],
      columnsOpen: false,
      hiddenColumns: [],
      groupBy: null,
    };
  }

  function getTableUiState() {
    if (!state.tableUiState) {
      state.tableUiState = defaultTableUiState();
    }
    return state.tableUiState;
  }

  function saveTableUiState() {
    const ui = getTableUiState();

    try {
      localStorage.setItem(tablePrefKey(), JSON.stringify(ui));
    } catch (e) {
      // ignore
    }
  }

  function newFilterId() {
    return "f_" + Math.random().toString(36).slice(2, 10);
  }

  function normalizeFilter(filter) {
    if (!filter || typeof filter !== "object") return null;

    return {
      id: typeof filter.id === "string" && filter.id ? filter.id : newFilterId(),
      field: typeof filter.field === "string" ? filter.field : "",
      op: typeof filter.op === "string" ? filter.op : "contains",
      value: typeof filter.value === "string" ? filter.value : "",
      valueTo: typeof filter.valueTo === "string" ? filter.valueTo : "",
    };
  }

  function operatorNeedsValue(op) {
    return !["missing", "not_missing"].includes(op);
  }

  function operatorNeedsTwoValues(op) {
    return ["between", "not_between"].includes(op);
  }

  function isFilterComplete(filter) {
    if (!filter.field || !filter.op) return false;
    if (!operatorNeedsValue(filter.op)) return true;
    if (operatorNeedsTwoValues(filter.op)) {
      return (
        String(filter.value || "").trim() !== "" &&
        String(filter.valueTo || "").trim() !== ""
      );
    }
    return String(filter.value || "").trim() !== "";
  }

  function loadTableUiState() {
    let parsed = null;

    try {
      const raw = localStorage.getItem(tablePrefKey());
      if (raw) parsed = JSON.parse(raw);
    } catch (e) {
      parsed = null;
    }

    const base = defaultTableUiState();
    const filters = Array.isArray(parsed && parsed.filters) ? parsed.filters : [];
    const normalizedFilters = filters.map(normalizeFilter).filter(Boolean);
    const hiddenColumns = Array.isArray(parsed && parsed.hiddenColumns)
      ? parsed.hiddenColumns.filter(function (x) {
          return typeof x === "string" && x;
        })
      : [];

    const hasSavedFilters = normalizedFilters.some(isFilterComplete);
    const hasHiddenColumns = hiddenColumns.length > 0;
    const groupBy =
      parsed && typeof parsed.groupBy === "string" && parsed.groupBy
        ? parsed.groupBy
        : null;

    state.tableUiState = {
      searchQuery:
        parsed && typeof parsed.searchQuery === "string"
          ? parsed.searchQuery
          : base.searchQuery,

      filtersOpen:
        parsed && typeof parsed.filtersOpen === "boolean"
          ? parsed.filtersOpen
          : hasSavedFilters,

      filters: normalizedFilters,

      columnsOpen:
        parsed && typeof parsed.columnsOpen === "boolean"
          ? parsed.columnsOpen
          : hasHiddenColumns,

      hiddenColumns: hiddenColumns,

      groupBy: groupBy,
    };
  }

  function escapeHtml(s) {
    if (typeof core.escapeHtml === "function") {
      return core.escapeHtml(s);
    }
    return String(s);
  }

  function getFieldType(field) {
    const map = state.tableFieldTypes || {};
    return map[field] === "number" ? "number" : "text";
  }

  function inferFieldTypes(columns, rows) {
    const out = {};
    const fields = Array.isArray(columns) ? columns.slice() : [];
    const sampleRows = Array.isArray(rows) ? rows.slice(0, 50) : [];

    for (const field of fields) {
      let numericHits = 0;
      let textHits = 0;

      for (const row of sampleRows) {
        const value = row ? row[field] : null;
        if (value == null || value === "") continue;

        if (typeof value === "number" && Number.isFinite(value)) {
          numericHits += 1;
          continue;
        }

        const n = Number(value);
        if (typeof value === "string" && value.trim() !== "" && Number.isFinite(n)) {
          numericHits += 1;
        } else {
          textHits += 1;
        }
      }

      out[field] = numericHits > 0 && textHits === 0 ? "number" : "text";
    }

    return out;
  }

  function getActiveRowCount() {
    if (!state.tabulatorInstance) return null;

    try {
      const active = state.tabulatorInstance.getData("active");
      if (Array.isArray(active)) return active.length;
    } catch (e) {
      // ignore
    }

    try {
      const allRows = state.tabulatorInstance.getData();
      if (Array.isArray(allRows)) return allRows.length;
    } catch (e) {
      // ignore
    }

    return null;
  }

  function updateTableStatus(data, activeCount) {
    const status = document.getElementById("status");
    const inline = document.getElementById("table-status-inline");

    const targetEls = [status, inline].filter(Boolean);
    if (!targetEls.length) return;

    const totalKnown = data.total_rows_known !== false;
    const total = totalKnown ? Number(data.total_rows ?? 0) : null;
    const loaded = Number(data.loaded_rows ?? data.returned_rows ?? 0);
    const returned = Number(data.returned_rows ?? (data.rows ? data.rows.length : 0));

    let html = "";

    if (total <= 0 && returned <= 0) {
      html = "";
    } else {
      const isTrunc =
        !!(data.meta && data.meta.truncated) ||
        (totalKnown && returned < total);
      const hasFilter = typeof activeCount === "number" && activeCount !== returned;

      if (hasFilter) {
        html =
          "Showing " +
          activeCount +
          " filtered rows of " +
          returned +
          " loaded";
        if (totalKnown && total > returned) {
          html += " (" + total + " total)";
        } else if (!totalKnown) {
          html += " (" + loaded + " loaded; full count unknown)";
        } else {
          html += ".";
        }
      } else if (!totalKnown) {
        html =
          "Showing " +
          returned +
          (loaded > returned ? " of " + loaded : "") +
          " loaded rows (full count unknown).";
      } else {
        html =
          "Showing " +
          returned +
          (total > returned ? " of " + total : "") +
          " rows.";
      }

      if (isTrunc) {
        html +=
          ' <span class="badge" title="This view is showing a sampled subset of the full data.">TRUNCATED</span>';
      }
    }

    for (const el of targetEls) {
      el.innerHTML = html;
    }
  }

  function refreshTableStatus() {
    if (!state.tableLastPayload) return;
    updateTableStatus(state.tableLastPayload, getActiveRowCount());
  }

  function refreshActiveTablePlot() {
    if (typeof core.refreshTablePlot === "function") {
      core.refreshTablePlot();
    }
  }

  function getSearchQuery() {
    return getTableUiState().searchQuery || "";
  }

  function setSearchQuery(value) {
    const ui = getTableUiState();
    ui.searchQuery = String(value || "");
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function getFilters() {
    return Array.isArray(getTableUiState().filters) ? getTableUiState().filters : [];
  }

  function setFilters(filters) {
    const ui = getTableUiState();
    ui.filters = Array.isArray(filters) ? filters.map(normalizeFilter).filter(Boolean) : [];
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function setFiltersOpen(isOpen) {
    const ui = getTableUiState();
    ui.filtersOpen = !!isOpen;
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function getHiddenColumns() {
    return Array.isArray(getTableUiState().hiddenColumns)
      ? getTableUiState().hiddenColumns
      : [];
  }

  function setHiddenColumns(fields) {
    const ui = getTableUiState();
    ui.hiddenColumns = Array.isArray(fields)
      ? fields.filter(function (x) {
          return typeof x === "string" && x;
        })
      : [];
    saveTableUiState();
  }

  function setColumnsOpen(isOpen) {
    const ui = getTableUiState();
    ui.columnsOpen = !!isOpen;
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
  }

  function getGroupingField() {
    const field = getTableUiState().groupBy;
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    return typeof field === "string" && fields.includes(field) ? field : null;
  }

  function setGroupingField(field) {
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const next = typeof field === "string" && fields.includes(field) ? field : null;
    const ui = getTableUiState();
    ui.groupBy = next;
    saveTableUiState();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
    return next;
  }

  function normalizeGroupingField() {
    const ui = getTableUiState();
    const groupingField = getGroupingField();
    if (ui.groupBy !== groupingField) {
      ui.groupBy = groupingField;
      saveTableUiState();
    }
    return groupingField;
  }

  function renderGroupingControl() {
    const select = document.getElementById("table-group-by-select");
    if (!select || typeof document.createElement !== "function") return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const selected = normalizeGroupingField();

    while (select.firstChild) {
      select.removeChild(select.firstChild);
    }

    const none = document.createElement("option");
    none.value = "";
    none.textContent = "No grouping";
    select.appendChild(none);

    for (const field of fields) {
      const option = document.createElement("option");
      option.value = field;
      option.textContent = field;
      select.appendChild(option);
    }

    select.value = selected || "";
    select.disabled = fields.length === 0;
  }

  function applyTableGrouping() {
    const table = state.tabulatorInstance;
    const groupingField = normalizeGroupingField();
    if (!table || typeof table.setGroupBy !== "function") return;

    if (state.tableAppliedGrouping === groupingField) return;
    if (!groupingField && state.tableAppliedGrouping == null) return;

    try {
      table.setGroupBy(groupingField || false);
      state.tableAppliedGrouping = groupingField;
    } catch (e) {
      // The shared explorer remains usable with reduced Tabulator surfaces.
    }
  }

  function setTableGrouping(field) {
    const groupingField = setGroupingField(field);
    renderGroupingControl();
    applyTableGrouping();
    refreshTableStatus();
    return groupingField;
  }

  function hasHiddenColumns() {
    return getHiddenColumns().length > 0;
  }

  function getOperatorOptions(field) {
    const fieldType = getFieldType(field);
    return fieldType === "number" ? FILTER_OPS.number : FILTER_OPS.text;
  }

  function renderOperatorOptions(field, selectedOp) {
    const options = getOperatorOptions(field);
    return options
      .map(function (op) {
        const sel = op.value === selectedOp ? ' selected="selected"' : "";
        return (
          '<option value="' +
          escapeHtml(op.value) +
          '"' +
          sel +
          ">" +
          escapeHtml(op.label) +
          "</option>"
        );
      })
      .join("");
  }

  function getCompleteFilters() {
    return getFilters().filter(isFilterComplete);
  }

  function hasActiveFilters() {
    return getCompleteFilters().length > 0;
  }

  function renderFilterRows() {
    const wrap = document.getElementById("table-filter-rows");
    if (!wrap) return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const filters = getFilters();

    if (!filters.length) {
      wrap.innerHTML = '<div class="note ps-note">No filters yet.</div>';
      return;
    }

    const fieldOptions = fields.map(function (field) {
      return field;
    });

    wrap.innerHTML = filters
      .map(function (filter) {
        const field = filter.field || fieldOptions[0] || "";
        const op = filter.op || "contains";
        const twoValues = operatorNeedsTwoValues(op);
        const singleClass = twoValues ? "" : " ps-table-filter-row--single";

        const fieldSelect =
          '<select class="ps-table-filter-select" data-filter-part="field" data-filter-id="' +
          escapeHtml(filter.id) +
          '">' +
          fieldOptions
            .map(function (f) {
              const sel = f === field ? ' selected="selected"' : "";
              return (
                '<option value="' +
                escapeHtml(f) +
                '"' +
                sel +
                ">" +
                escapeHtml(f) +
                "</option>"
              );
            })
            .join("") +
          "</select>";

        const opSelect =
          '<select class="ps-table-filter-select" data-filter-part="op" data-filter-id="' +
          escapeHtml(filter.id) +
          '">' +
          renderOperatorOptions(field, op) +
          "</select>";

        const valueInput =
          '<input class="ps-table-filter-value" data-filter-part="value" data-filter-id="' +
          escapeHtml(filter.id) +
          '" type="text" value="' +
          escapeHtml(filter.value || "") +
          '"' +
          (operatorNeedsValue(op) ? "" : ' disabled="disabled"') +
          ' placeholder="Value" />';

        const valueToInput = twoValues
          ? '<input class="ps-table-filter-value" data-filter-part="valueTo" data-filter-id="' +
            escapeHtml(filter.id) +
            '" type="text" value="' +
            escapeHtml(filter.valueTo || "") +
            '" placeholder="And value" />'
          : "";

        const removeBtn =
          '<button type="button" class="ps-btn ps-table-filter-remove" data-filter-action="remove" data-filter-id="' +
          escapeHtml(filter.id) +
          '">Remove</button>';

        return (
          '<div class="ps-table-filter-row' +
          singleClass +
          '" data-filter-row="' +
          escapeHtml(filter.id) +
          '">' +
          fieldSelect +
          opSelect +
          valueInput +
          valueToInput +
          removeBtn +
          "</div>"
        );
      })
      .join("");
  }

  function renderColumnsList() {
    const wrap = document.getElementById("table-columns-list");
    if (!wrap) return;

    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const hidden = new Set(getHiddenColumns());

    if (!fields.length) {
      wrap.innerHTML = '<div class="note ps-note">No columns available.</div>';
      return;
    }

    wrap.innerHTML = fields
      .map(function (field) {
        const checked = hidden.has(field) ? "" : ' checked="checked"';
        return (
          '<label class="ps-table-column-item">' +
          '<input type="checkbox" data-column-field="' +
          escapeHtml(field) +
          '"' +
          checked +
          " />" +
          "<span>" +
          escapeHtml(field) +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function describeFilter(filter) {
    const field = filter.field || "";
    const op = filter.op || "";
    const value = filter.value || "";
    const valueTo = filter.valueTo || "";

    const labelMap = {};
    for (const group of [FILTER_OPS.text, FILTER_OPS.number]) {
      for (const item of group) {
        labelMap[item.value] = item.label;
      }
    }

    const opLabel = labelMap[op] || op;

    if (operatorNeedsTwoValues(op)) {
      return field + " " + opLabel + " " + value + " and " + valueTo;
    }

    if (operatorNeedsValue(op)) {
      return field + " " + opLabel + " " + value;
    }

    return field + " " + opLabel;
  }

  function renderActiveFilters() {
    const wrap = document.getElementById("table-active-filters");
    if (!wrap) return;

    const active = getCompleteFilters();

    if (!active.length) {
      wrap.hidden = true;
      wrap.innerHTML = "";
      return;
    }

    wrap.hidden = false;
    wrap.innerHTML = active
      .map(function (filter) {
        return (
          '<span class="ps-table-filter-chip">' +
          "<span>" +
          escapeHtml(describeFilter(filter)) +
          "</span>" +
          '<button type="button" title="Remove filter" data-filter-chip-remove="' +
          escapeHtml(filter.id) +
          '">×</button>' +
          "</span>"
        );
      })
      .join("");
  }

  function syncFilterButtonUi() {
    const btn = document.getElementById("table-filters-toggle-btn");
    if (!btn) return;

    btn.classList.toggle("is-active", hasActiveFilters());
  }

  function syncColumnsButtonUi() {
    const btn = document.getElementById("table-columns-toggle-btn");
    if (!btn) return;

    btn.classList.toggle("is-active", hasHiddenColumns());
  }

  function syncFilterPanelUi() {
    const panel = document.getElementById("table-filter-panel");
    const btn = document.getElementById("table-filters-toggle-btn");
    const shouldShow = !!getTableUiState().filtersOpen;

    if (panel) {
      panel.hidden = !shouldShow;
    }

    if (btn) {
      btn.setAttribute("aria-expanded", shouldShow ? "true" : "false");
    }

    syncFilterButtonUi();
  }

  function syncColumnsPanelUi() {
    const panel = document.getElementById("table-columns-panel");
    const btn = document.getElementById("table-columns-toggle-btn");
    const shouldShow = !!getTableUiState().columnsOpen;

    if (panel) {
      panel.hidden = !shouldShow;
    }

    if (btn) {
      btn.setAttribute("aria-expanded", shouldShow ? "true" : "false");
    }

    syncColumnsButtonUi();
  }

  function getFieldValueForFilter(rowData, field) {
    return rowData ? rowData[field] : null;
  }

  function isMissing(value) {
    return value == null || String(value).trim() === "";
  }

  function matchesSingleFilter(rowData, filter) {
    if (!isFilterComplete(filter)) return true;

    const raw = getFieldValueForFilter(rowData, filter.field);
    const fieldType = getFieldType(filter.field);
    const op = filter.op;

    if (op === "missing") return isMissing(raw);
    if (op === "not_missing") return !isMissing(raw);

    if (fieldType === "number") {
      const a = Number(raw);
      const b = Number(filter.value);
      const c = Number(filter.valueTo);

      if (!Number.isFinite(a)) return false;

      if (op === "lt") return a < b;
      if (op === "lte") return a <= b;
      if (op === "gt") return a > b;
      if (op === "gte") return a >= b;
      if (op === "eq") return a === b;
      if (op === "neq") return a !== b;
      if (op === "between") return a >= Math.min(b, c) && a <= Math.max(b, c);
      if (op === "not_between") {
        return !(a >= Math.min(b, c) && a <= Math.max(b, c));
      }

      return true;
    }

    const text = String(raw == null ? "" : raw).toLowerCase();
    const q = String(filter.value || "").toLowerCase();

    if (op === "contains") return text.includes(q);
    if (op === "eq") return text === q;
    if (op === "neq") return text !== q;

    return true;
  }

  function rowMatchesCurrentTableFilters(rowData) {
    const searchQuery = getSearchQuery().trim().toLowerCase();
    const filters = getCompleteFilters();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (searchQuery) {
      let matched = false;
      for (const field of fields) {
        const raw = rowData ? rowData[field] : null;
        const text = String(raw == null ? "" : raw).toLowerCase();
        if (text.includes(searchQuery)) {
          matched = true;
          break;
        }
      }
      if (!matched) return false;
    }

    for (const filter of filters) {
      if (!matchesSingleFilter(rowData, filter)) return false;
    }

    return true;
  }

  function getCurrentFilteredLoadedRows() {
    const table = state.tabulatorInstance;
    if (table && typeof table.getData === "function") {
      try {
        const activeRows = table.getData("active");
        if (Array.isArray(activeRows)) return activeRows.slice();
      } catch (e) {
        // Fall through to the shared predicate for reduced table surfaces.
      }
    }

    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    return rows.filter(rowMatchesCurrentTableFilters);
  }

  function applyAllTableFilters() {
    if (!state.tabulatorInstance) return;

    const searchQuery = getSearchQuery().trim().toLowerCase();
    const filters = getCompleteFilters();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (!searchQuery && !filters.length) {
      state.tabulatorInstance.clearFilter(true);
      refreshTableStatus();
      refreshActiveTablePlot();
      return;
    }

    state.tabulatorInstance.setFilter(rowMatchesCurrentTableFilters);

    refreshTableStatus();
    refreshActiveTablePlot();
  }

  function getColumnComponentByField(field) {
    if (!state.tabulatorInstance || typeof state.tabulatorInstance.getColumns !== "function") {
      return null;
    }

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        if (col.getField() === field) return col;
      }
    } catch (e) {
      // ignore
    }

    return null;
  }

  function applyColumnVisibilityState() {
    if (!state.tabulatorInstance) return;

    const hidden = new Set(getHiddenColumns());
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    for (const field of fields) {
      const col = getColumnComponentByField(field);
      if (!col) continue;

      try {
        if (hidden.has(field)) {
          if (typeof col.hide === "function") col.hide();
        } else {
          if (typeof col.show === "function") col.show();
        }
      } catch (e) {
        // ignore
      }
    }

    renderColumnsList();
    syncColumnsPanelUi();
  }

  function getVisibleFieldsInCurrentOrder() {
    if (!state.tabulatorInstance || typeof state.tabulatorInstance.getColumns !== "function") {
      return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    }

    const out = [];

    try {
      const cols = state.tabulatorInstance.getColumns();
      for (const col of cols) {
        if (!col || typeof col.getField !== "function") continue;
        const field = col.getField();
        if (!field) continue;

        let visible = true;
        try {
          if (typeof col.isVisible === "function") {
            visible = !!col.isVisible();
          }
        } catch (e) {
          visible = true;
        }

        if (visible) out.push(field);
      }
    } catch (e) {
      return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
    }

    return out;
  }

  function restoreToolbarInputs() {
    const input = document.getElementById("table-search-input");
    if (input) {
      input.value = getSearchQuery();
    }
  }

  function addFilter(initial) {
    const filters = getFilters().slice();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (filters.length >= MAX_FILTERS) {
      return;
    }

    filters.push(
      normalizeFilter(
        initial || {
          id: newFilterId(),
          field: fields[0] || "",
          op: getFieldType(fields[0] || "") === "number" ? "eq" : "contains",
          value: "",
          valueTo: "",
        }
      )
    );

    setFilters(filters);
    setFiltersOpen(true);
    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
  }

  function removeFilter(filterId) {
    const filters = getFilters().filter(function (f) {
      return f.id !== filterId;
    });

    setFilters(filters);

    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
  }

  function updateFilter(filterId, part, value, options) {
    const shouldRerender = !!(options && options.rerender);

    const filters = getFilters().map(function (filter) {
      if (filter.id !== filterId) return filter;

      const next = {
        id: filter.id,
        field: filter.field,
        op: filter.op,
        value: filter.value,
        valueTo: filter.valueTo,
      };

      next[part] = String(value || "");

      if (part === "field") {
        const allowedOps = getOperatorOptions(next.field).map(function (x) {
          return x.value;
        });

        if (!allowedOps.includes(next.op)) {
          next.op = getFieldType(next.field) === "number" ? "eq" : "contains";
          next.value = "";
          next.valueTo = "";
        }
      }

      if (part === "op") {
        if (!operatorNeedsValue(next.op)) {
          next.value = "";
          next.valueTo = "";
        } else if (!operatorNeedsTwoValues(next.op)) {
          next.valueTo = "";
        }
      }

      return next;
    });

    setFilters(filters);

    if (shouldRerender) {
      renderFilterRows();
    }

    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters();
  }

  function toggleColumnVisibility(field, shouldBeVisible) {
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    const hidden = new Set(getHiddenColumns());

    if (!field || !fields.includes(field)) return;

    if (!shouldBeVisible) {
      const currentlyVisibleCount = fields.filter(function (f) {
        return !hidden.has(f);
      }).length;

      if (currentlyVisibleCount <= 1) {
        renderColumnsList();
        return;
      }

      hidden.add(field);
    } else {
      hidden.delete(field);
    }

    setHiddenColumns(Array.from(hidden));
    applyColumnVisibilityState();
  }

  function showAllColumns() {
    setHiddenColumns([]);
    applyColumnVisibilityState();
  }

  function bindTableToolbar() {
    const input = document.getElementById("table-search-input");
    const groupBySelect = document.getElementById("table-group-by-select");
    const resetBtn = document.getElementById("table-reset-btn");
    const filtersToggleBtn = document.getElementById("table-filters-toggle-btn");
    const columnsToggleBtn = document.getElementById("table-columns-toggle-btn");
    const addFilterBtn = document.getElementById("table-filter-add-btn");
    const showAllColumnsBtn = document.getElementById("table-columns-show-all-btn");
    const filterRows = document.getElementById("table-filter-rows");
    const columnsList = document.getElementById("table-columns-list");
    const activeFilters = document.getElementById("table-active-filters");

    restoreToolbarInputs();
    renderGroupingControl();
    renderFilterRows();
    renderColumnsList();
    renderActiveFilters();
    syncFilterPanelUi();
    syncColumnsPanelUi();

    if (input && !input.dataset.plotsrvBound) {
      let timer = null;

      input.addEventListener("input", function () {
        const q = String(input.value || "");
        setSearchQuery(q);

        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          applyAllTableFilters();
        }, 120);
      });

      input.dataset.plotsrvBound = "1";
    }

    if (groupBySelect && !groupBySelect.dataset.plotsrvBound) {
      groupBySelect.addEventListener("change", function () {
        setTableGrouping(groupBySelect.value);
      });

      groupBySelect.dataset.plotsrvBound = "1";
    }

    if (resetBtn && !resetBtn.dataset.plotsrvBound) {
      resetBtn.addEventListener("click", function () {
        state.tableUiState = defaultTableUiState();
        saveTableUiState();

        if (input) input.value = "";

        if (state.tabulatorInstance) {
          try {
            state.tabulatorInstance.clearFilter(true);
          } catch (e) {
            // ignore
          }

          try {
            state.tabulatorInstance.clearSort();
          } catch (e) {
            // ignore
          }

          if (Array.isArray(state.tableColumnDefs) && state.tableColumnDefs.length > 0) {
            try {
              state.tabulatorInstance.setColumns(state.tableColumnDefs);
            } catch (e) {
              // ignore
            }
          }

          try {
            state.tabulatorInstance.replaceData(state.tableRows || []);
          } catch (e) {
            // ignore
          }
        }

        renderGroupingControl();
        renderFilterRows();
        renderColumnsList();
        renderActiveFilters();
        syncFilterPanelUi();
        syncColumnsPanelUi();
        applyColumnVisibilityState();
        applyTableGrouping();
        applyAllTableFilters();
      });

      resetBtn.dataset.plotsrvBound = "1";
    }

    if (filtersToggleBtn && !filtersToggleBtn.dataset.plotsrvBound) {
      filtersToggleBtn.addEventListener("click", function () {
        const nextOpen = !getTableUiState().filtersOpen;
        setFiltersOpen(nextOpen);
        syncFilterPanelUi();
      });

      filtersToggleBtn.dataset.plotsrvBound = "1";
    }

    if (columnsToggleBtn && !columnsToggleBtn.dataset.plotsrvBound) {
      columnsToggleBtn.addEventListener("click", function () {
        const nextOpen = !getTableUiState().columnsOpen;
        setColumnsOpen(nextOpen);
        syncColumnsPanelUi();
      });

      columnsToggleBtn.dataset.plotsrvBound = "1";
    }

    if (addFilterBtn && !addFilterBtn.dataset.plotsrvBound) {
      addFilterBtn.addEventListener("click", function () {
        addFilter();
        const filters = getFilters();
        const newest = filters[filters.length - 1];
        if (!newest) return;

        window.requestAnimationFrame(function () {
          const firstInput = document.querySelector(
            '[data-filter-id="' + newest.id + '"][data-filter-part="value"]'
          );
          if (firstInput && typeof firstInput.focus === "function") {
            firstInput.focus();
          }
        });
      });

      addFilterBtn.dataset.plotsrvBound = "1";
    }

    if (showAllColumnsBtn && !showAllColumnsBtn.dataset.plotsrvBound) {
      showAllColumnsBtn.addEventListener("click", function () {
        showAllColumns();
      });

      showAllColumnsBtn.dataset.plotsrvBound = "1";
    }

    if (addFilterBtn) {
      addFilterBtn.disabled = getFilters().length >= MAX_FILTERS;
      addFilterBtn.title =
        getFilters().length >= MAX_FILTERS
          ? "Maximum number of filters reached"
          : "";
    }

    if (filterRows && !filterRows.dataset.plotsrvBound) {
      filterRows.addEventListener("change", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const filterId = target.getAttribute("data-filter-id");
        const part = target.getAttribute("data-filter-part");

        if (!filterId || !part) return;

        const rerender = part === "field" || part === "op";
        updateFilter(filterId, part, target.value, { rerender: rerender });
      });

      filterRows.addEventListener("input", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const filterId = target.getAttribute("data-filter-id");
        const part = target.getAttribute("data-filter-part");

        if (!filterId || !part || (part !== "value" && part !== "valueTo")) return;

        updateFilter(filterId, part, target.value, { rerender: false });
      });

      filterRows.addEventListener("click", function (ev) {
        const target =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-filter-action='remove']")
            : null;
        if (!target) return;

        const filterId = target.getAttribute("data-filter-id");
        if (!filterId) return;

        removeFilter(filterId);
      });

      filterRows.dataset.plotsrvBound = "1";
    }

    if (columnsList && !columnsList.dataset.plotsrvBound) {
      columnsList.addEventListener("change", function (ev) {
        const target = ev.target;
        if (!target || !target.getAttribute) return;

        const field = target.getAttribute("data-column-field");
        if (!field) return;

        toggleColumnVisibility(field, !!target.checked);
      });

      columnsList.dataset.plotsrvBound = "1";
    }

    if (activeFilters && !activeFilters.dataset.plotsrvBound) {
      activeFilters.addEventListener("click", function (ev) {
        const btn =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-filter-chip-remove]")
            : null;
        if (!btn) return;

        const filterId = btn.getAttribute("data-filter-chip-remove");
        if (!filterId) return;

        removeFilter(filterId);
      });

      activeFilters.dataset.plotsrvBound = "1";
    }
  }

  function csvEscape(value) {
    const text = String(value == null ? "" : value);
    if (
      text.includes('"') ||
      text.includes(",") ||
      text.includes("\n") ||
      text.includes("\r")
    ) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  function downloadTextFile(filename, text, mime) {
    const blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
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

  function buildCsvFromRows(rows, fields) {
    const lines = [];
    lines.push(fields.map(csvEscape).join(","));

    for (const row of rows) {
      const vals = fields.map(function (field) {
        return csvEscape(row ? row[field] : "");
      });
      lines.push(vals.join(","));
    }

    return lines.join("\r\n");
  }

  function exportFilteredRichTable() {
    if (!state.tabulatorInstance) return false;

    let rows = [];
    let readActiveRows = false;
    try {
      rows = state.tabulatorInstance.getData("active");
      if (Array.isArray(rows)) readActiveRows = true;
      else rows = [];
    } catch (e) {
      rows = [];
    }

    if (!readActiveRows) {
      try {
        rows = state.tabulatorInstance.getData();
        if (!Array.isArray(rows)) rows = [];
      } catch (e) {
        rows = [];
      }
    }

    const visibleFields = getVisibleFieldsInCurrentOrder();
    if (!visibleFields.length) return false;

    const csv = buildCsvFromRows(rows, visibleFields);

    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "table").replace(/[^\w.-]+/g, "_");
    const filename = base + "-filtered-" + stamp + ".csv";

    downloadTextFile(filename, csv, "text/csv;charset=utf-8");
    return true;
  }

  function exportRetainedRawWindow() {
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];
    if (!fields.length) return false;

    const csv = buildCsvFromRows(rows, fields);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "stream").replace(/[^\w.-]+/g, "_");
    downloadTextFile(
      base + "-retained-window-" + stamp + ".csv",
      csv,
      "text/csv;charset=utf-8"
    );
    return true;
  }

  function configureTableExplorer(options) {
    const settings = options && typeof options === "object" ? options : {};
    const table = settings.table;
    if (!table) return;

    const fields = Array.isArray(settings.fields) ? settings.fields.slice() : [];
    const rows = Array.isArray(settings.rows) ? settings.rows : [];

    if (!state.tableUiState) {
      loadTableUiState();
    }

    // The stream renderer uses the same small controller as a rich static
    // table.  There is only one table surface per page, so this alias lets
    // search, filters, and column controls operate without duplicating their
    // state model or event bindings.
    if (state.tabulatorInstance !== table) {
      state.tableAppliedGrouping = undefined;
    }
    state.tabulatorInstance = table;
    state.tableLastPayload = settings.payload || {};
    state.tableRows = rows;
    state.tableFields = fields;
    state.tableFieldTypes = inferFieldTypes(fields, rows);
    state.tableColumnDefs = Array.isArray(settings.columnDefs)
      ? settings.columnDefs
      : [];
    if (typeof core.setTablePlotCapabilities === "function") {
      core.setTablePlotCapabilities(settings.plotCapabilities || { sources: ["table"] });
    }

    if (typeof table.on === "function" && !table._plotsrvUpdatePolicyBound) {
      table.on("dataSorted", function () {
        if (typeof core.notifyUpdateEligibilityChanged === "function") {
          core.notifyUpdateEligibilityChanged();
        }
      });
      table._plotsrvUpdatePolicyBound = true;
    }

    bindTableToolbar();
    applyTableGrouping();
    applyAllTableFilters();
    refreshTableStatus();
    if (typeof core.configureTablePlotSurface === "function") {
      core.configureTablePlotSurface();
    }
  }

  function destroyMountedTable() {
    const table = state.tabulatorInstance;
    state.tabulatorInstance = null;
    state.tableAppliedGrouping = undefined;

    if (table && typeof table.destroy === "function") {
      try {
        table.destroy();
      } catch (e) {
        // A removed artifact surface may already have been detached.
      }
    }
  }

  function initializeEmbeddedTableExplorer(options) {
    const settings = options && typeof options === "object" ? options : {};
    const grid = settings.grid;
    const data = settings.data && typeof settings.data === "object" ? settings.data : {};
    const fields = Array.isArray(data.columns) ? data.columns.slice() : [];
    const rows = Array.isArray(data.rows) ? data.rows.slice() : [];

    if (!grid || !fields.length || !Array.isArray(data.rows)) return false;
    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      return false;
    }

    destroyMountedTable();
    const columns = buildColumnDefs(fields);
    const table = new Tabulator(grid, {
      data: rows,
      columns: columns,
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 20,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
      // JSON object and table column names are flat keys. In particular,
      // "http.status" is a literal field rather than a nested lookup.
      nestedFieldSeparator: false,
    });

    if (typeof table.on === "function") {
      table.on("dataFiltered", function () {
        refreshTableStatus();
        refreshActiveTablePlot();
      });
    }

    configureTableExplorer({
      table: table,
      payload: data,
      rows: rows,
      fields: fields,
      columnDefs: columns,
      plotCapabilities: settings.plotCapabilities || { sources: ["table"] },
    });
    state.embeddedTableExplorer = true;
    return true;
  }

  function disposeEmbeddedTableExplorer() {
    if (!state.embeddedTableExplorer) return;
    destroyMountedTable();
    state.embeddedTableExplorer = false;
  }

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    if (!grid) return;

    if (!state.tableUiState) {
      loadTableUiState();
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    const url =
      "/table/data?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&_ts=" +
      Date.now();

    let res = await fetch(url);
    // A file-backed server admits only a bounded number of expensive CSV
    // loads. A short retry keeps normal refreshes smooth without hiding a
    // persistent failure behind an endless client loop.
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
        await core.handleMissingSnapshot("table");
        return;
      }

      console.error("Failed to load table data");
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to load table data (" + res.status + ").");
      }
      return;
    }

    const data = await res.json();
    let columns = buildColumnDefs(data.columns || []);
    const rows = data.rows || [];

    if (state.tabulatorInstance) {
      const sorters = currentSorters(state.tabulatorInstance);
      columns = preserveColumnOrder(columns, state.tabulatorInstance);
      state.tableAppliedGrouping = undefined;
      await Promise.resolve(state.tabulatorInstance.setColumns(columns));
      await Promise.resolve(state.tabulatorInstance.replaceData(rows));
      if (sorters.length && typeof state.tabulatorInstance.setSort === "function") {
        await Promise.resolve(state.tabulatorInstance.setSort(sorters));
      }
      configureTableExplorer({
        table: state.tabulatorInstance,
        payload: data,
        rows: rows,
        fields: data.columns || [],
        columnDefs: columns,
        plotCapabilities: { sources: ["table"] },
      });
      return;
    }

    if (typeof Tabulator === "undefined") {
      console.error("Tabulator is not available (did not load).");
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to start the rich table renderer.");
      }
      return;
    }

    state.tabulatorInstance = new Tabulator("#table-grid", {
      data: rows,
      columns: columns,
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 20,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
      // Preserve literal dotted names for ordinary and embedded table data.
      nestedFieldSeparator: false,
    });

    if (typeof state.tabulatorInstance.on === "function") {
      state.tabulatorInstance.on("dataFiltered", function () {
        refreshTableStatus();
        refreshActiveTablePlot();
      });
    }

    configureTableExplorer({
      table: state.tabulatorInstance,
      payload: data,
      rows: rows,
      fields: data.columns || [],
      columnDefs: columns,
      plotCapabilities: { sources: ["table"] },
    });
  }

  function exportCompletePublishedTable() {
    const isHistory =
      typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
    const sourceDownload =
      state.tableLastPayload &&
      state.tableLastPayload.meta &&
      state.tableLastPayload.meta.source_download_url;

    if (!isHistory && typeof sourceDownload === "string" && sourceDownload) {
      window.location.href = sourceDownload + "&_ts=" + Date.now();
      return;
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    window.location.href =
      "/table/export?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      "&format=csv&_ts=" +
      Date.now();
  }

  function exportTable(scope) {
    if (scope === "filtered") {
      return exportFilteredRichTable();
    }
    if (scope === "retained") {
      return exportRetainedRawWindow();
    }
    if (scope === "complete") {
      return exportCompletePublishedTable();
    }

    // Retain the old public helper's behaviour for integrations that invoke
    // exportTable() directly. The bottom dock always supplies an exact scope.
    if (state.tabulatorInstance && exportFilteredRichTable()) return true;
    return exportCompletePublishedTable();
  }

  core.loadTable = loadTable;
  core.exportTable = exportTable;
  core.exportFilteredRichTable = exportFilteredRichTable;
  core.exportRetainedRawWindow = exportRetainedRawWindow;
  core.exportCompletePublishedTable = exportCompletePublishedTable;
  core.configureTableExplorer = configureTableExplorer;
  core.disposeEmbeddedTableExplorer = disposeEmbeddedTableExplorer;
  core.initializeEmbeddedTableExplorer = initializeEmbeddedTableExplorer;
  core.getCurrentFilteredLoadedRows = getCurrentFilteredLoadedRows;
  core.getTableGrouping = normalizeGroupingField;
  core.setTableGrouping = setTableGrouping;

  window.exportTable = exportTable;
})();

/* plotsrv source: js/renderers/table_plot.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  // These limits deliberately refuse to render rather than selecting a
  // subset. Keep them local to the browser renderer: this feature must not
  // introduce a server-side charting or callback API.
  const TABLE_PLOT_LIMITS = {
    maxSourceRows: 10000,
    maxPoints: 1000,
    maxCategories: 40,
  };

  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

  function plural(count, singular, pluralText) {
    return count === 1 ? singular : (pluralText || singular + "s");
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function htmlElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function svgElement(tag, attributes, text) {
    const element = document.createElementNS(SVG_NAMESPACE, tag);
    const attrs = attributes || {};
    for (const key of Object.keys(attrs)) {
      if (attrs[key] != null) element.setAttribute(key, String(attrs[key]));
    }
    if (text != null) element.textContent = text;
    return element;
  }

  function appendSvgText(svg, attributes, text) {
    const label = svgElement("text", attributes, text);
    svg.appendChild(label);
    return label;
  }

  function formatNumber(value) {
    if (!Number.isFinite(value)) return "";
    const absolute = Math.abs(value);
    if ((absolute >= 1000000 || (absolute > 0 && absolute < 0.001))) {
      return value.toExponential(2);
    }
    return String(Math.round(value * 1000) / 1000);
  }

  function fieldLabel(field) {
    return typeof field === "string" && field ? field : "selected field";
  }

  function isMissing(value) {
    return value == null || (typeof value === "string" && value.trim() === "");
  }

  function numericValue(value) {
    if (isMissing(value)) return { kind: "missing" };
    if (typeof value === "boolean" || typeof value === "bigint") {
      return { kind: "invalid" };
    }
    const number = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(number)) return { kind: "invalid" };
    return { kind: "value", value: number };
  }

  function categoricalValue(value) {
    if (isMissing(value)) return { kind: "missing" };
    if (typeof value === "number" && !Number.isFinite(value)) {
      return { kind: "invalid" };
    }
    if (typeof value === "object" || typeof value === "function" ||
        typeof value === "symbol") {
      return { kind: "invalid" };
    }
    return {
      kind: "value",
      key: typeof value + ":" + String(value),
      label: String(value),
    };
  }

  function currentFilteredRows(settings) {
    if (Array.isArray(settings.rows)) return settings.rows.slice();
    if (typeof core.getCurrentFilteredLoadedRows === "function") {
      const rows = core.getCurrentFilteredLoadedRows();
      if (Array.isArray(rows)) return rows;
    }
    return [];
  }

  function sourceScopeText(settings, rowCount, plottedCount) {
    const isSummary = settings.scopeKind === "summary";
    let text = isSummary
      ? "Plot scope: " + rowCount + " loaded derived summary " +
        plural(rowCount, "window") + "; " + plottedCount + " " +
        plural(plottedCount, "value") +
        " plotted. These are selected aggregate records, not source log rows."
      : "Plot scope: " + rowCount + " loaded " +
        plural(rowCount, "row") +
        " passing the current browser filters; " + plottedCount + " " +
        plural(plottedCount, "value") + " plotted.";

    let sourceDescription =
      typeof settings.scopeDescription === "string"
        ? settings.scopeDescription.trim()
        : "";
    if (sourceDescription) text += " " + sourceDescription;
    return text;
  }

  function skippedText(missing, invalid) {
    const details = [];
    if (missing > 0) {
      details.push(missing + " " + plural(missing, "row") + " with missing values");
    }
    if (invalid > 0) {
      details.push(invalid + " " + plural(invalid, "row") + " with invalid values");
    }
    return details.length ? "Excluded " + details.join(" and ") + "." : "";
  }

  function renderNotice(container, kind, title, detail, scope) {
    clearElement(container);
    const notice = htmlElement("section", "ps-table-plot__notice ps-table-plot__notice--" + kind);
    notice.dataset.plotState = kind;
    notice.appendChild(htmlElement("h2", "ps-table-plot__notice-title", title));
    if (detail) notice.appendChild(htmlElement("p", "ps-table-plot__notice-detail", detail));
    if (scope) notice.appendChild(htmlElement("p", "ps-table-plot__scope", scope));
    container.appendChild(notice);
  }

  function refusal(container, reason, detail, settings, rowCount) {
    const scope = sourceScopeText(settings, rowCount, 0);
    renderNotice(container, "refused", "Plot not rendered", detail, scope);
    return {
      ok: false,
      reason: reason,
      rowCount: rowCount,
      plottedCount: 0,
      scope: scope,
    };
  }

  function createFrame(container, type, title) {
    clearElement(container);
    const figure = htmlElement("figure", "ps-table-plot");
    figure.dataset.plotType = type;
    figure.dataset.plotState = "rendered";
    figure.appendChild(htmlElement("h2", "ps-table-plot__title", title));
    container.appendChild(figure);
    return figure;
  }

  function appendPlotSummary(figure, detail, scope) {
    if (detail) figure.appendChild(htmlElement("p", "ps-table-plot__detail", detail));
    figure.appendChild(htmlElement("figcaption", "ps-table-plot__scope", scope));
  }

  function appendBarAxes(svg, dimensions, maxValue) {
    const ticks = 4;
    const width = dimensions.width - dimensions.left - dimensions.right;
    const bottom = dimensions.height - dimensions.bottom;

    for (let index = 0; index <= ticks; index += 1) {
      const fraction = index / ticks;
      const x = dimensions.left + width * fraction;
      const value = maxValue * fraction;
      svg.appendChild(svgElement("line", {
        x1: x,
        y1: dimensions.top,
        x2: x,
        y2: bottom,
        class: "ps-table-plot__grid-line",
      }));
      appendSvgText(svg, {
        x: x,
        y: bottom + 20,
        "text-anchor": "middle",
        class: "ps-table-plot__tick",
      }, formatNumber(value));
    }

    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: dimensions.top,
      x2: dimensions.left,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: bottom,
      x2: dimensions.width - dimensions.right,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
  }

  function renderBarChart(figure, categories, categoryField) {
    const rowHeight = 30;
    const dimensions = {
      width: 820,
      height: Math.max(230, 86 + categories.length * rowHeight),
      left: 280,
      right: 72,
      top: 28,
      bottom: 42,
    };
    const plotWidth = dimensions.width - dimensions.left - dimensions.right;
    const plotHeight = dimensions.height - dimensions.top - dimensions.bottom;
    const maxValue = Math.max.apply(null, categories.map(function (item) {
      return item.count;
    }).concat([1]));
    const svg = svgElement("svg", {
      viewBox: "0 0 " + dimensions.width + " " + dimensions.height,
      role: "img",
      "aria-label": "Categorical count bar chart for " + fieldLabel(categoryField),
      class: "ps-table-plot__svg ps-table-plot__svg--bar",
    });
    svg.appendChild(svgElement("title", null, "Count by " + fieldLabel(categoryField)));
    appendBarAxes(svg, dimensions, maxValue);

    const barHeight = Math.max(10, Math.min(20, plotHeight / categories.length - 6));
    const rowSize = plotHeight / categories.length;
    categories.forEach(function (item, index) {
      const centerY = dimensions.top + rowSize * index + rowSize / 2;
      const width = plotWidth * (item.count / maxValue);
      appendSvgText(svg, {
        x: dimensions.left - 10,
        y: centerY,
        "text-anchor": "end",
        "dominant-baseline": "middle",
        class: "ps-table-plot__category",
      }, item.label);
      svg.appendChild(svgElement("rect", {
        x: dimensions.left,
        y: centerY - barHeight / 2,
        width: width,
        height: barHeight,
        rx: 2,
        class: "ps-table-plot__bar",
      }));
      appendSvgText(svg, {
        x: dimensions.left + width + 7,
        y: centerY,
        "dominant-baseline": "middle",
        class: "ps-table-plot__value",
      }, String(item.count));
    });

    figure.appendChild(svg);
  }

  function numericDomain(points, key) {
    let minimum = Infinity;
    let maximum = -Infinity;
    for (const point of points) {
      minimum = Math.min(minimum, point[key]);
      maximum = Math.max(maximum, point[key]);
    }
    if (minimum === maximum) {
      const padding = minimum === 0 ? 1 : Math.abs(minimum) * 0.1;
      minimum -= padding;
      maximum += padding;
    }
    return { minimum: minimum, maximum: maximum };
  }

  function linearScale(domain, start, end) {
    const span = domain.maximum - domain.minimum;
    return function (value) {
      return start + ((value - domain.minimum) / span) * (end - start);
    };
  }

  function appendNumericAxes(svg, dimensions, xDomain, yDomain, xField, yField) {
    const ticks = 4;
    const right = dimensions.width - dimensions.right;
    const bottom = dimensions.height - dimensions.bottom;
    const plotWidth = right - dimensions.left;
    const plotHeight = bottom - dimensions.top;

    for (let index = 0; index <= ticks; index += 1) {
      const fraction = index / ticks;
      const x = dimensions.left + plotWidth * fraction;
      const y = bottom - plotHeight * fraction;
      const xValue = xDomain.minimum + (xDomain.maximum - xDomain.minimum) * fraction;
      const yValue = yDomain.minimum + (yDomain.maximum - yDomain.minimum) * fraction;
      svg.appendChild(svgElement("line", {
        x1: x,
        y1: dimensions.top,
        x2: x,
        y2: bottom,
        class: "ps-table-plot__grid-line",
      }));
      svg.appendChild(svgElement("line", {
        x1: dimensions.left,
        y1: y,
        x2: right,
        y2: y,
        class: "ps-table-plot__grid-line",
      }));
      appendSvgText(svg, {
        x: x,
        y: bottom + 22,
        "text-anchor": "middle",
        class: "ps-table-plot__tick",
      }, formatNumber(xValue));
      appendSvgText(svg, {
        x: dimensions.left - 10,
        y: y + 4,
        "text-anchor": "end",
        class: "ps-table-plot__tick",
      }, formatNumber(yValue));
    }

    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: dimensions.top,
      x2: dimensions.left,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
    svg.appendChild(svgElement("line", {
      x1: dimensions.left,
      y1: bottom,
      x2: right,
      y2: bottom,
      class: "ps-table-plot__axis",
    }));
    appendSvgText(svg, {
      x: dimensions.left + plotWidth / 2,
      y: dimensions.height - 10,
      "text-anchor": "middle",
      class: "ps-table-plot__axis-label",
    }, fieldLabel(xField));
    appendSvgText(svg, {
      x: 18,
      y: dimensions.top + plotHeight / 2,
      transform: "rotate(-90 18 " + (dimensions.top + plotHeight / 2) + ")",
      "text-anchor": "middle",
      class: "ps-table-plot__axis-label",
    }, fieldLabel(yField));
  }

  function renderPointChart(figure, type, points, xField, yField) {
    const dimensions = {
      width: 780,
      height: 430,
      left: 78,
      right: 32,
      top: 28,
      bottom: 66,
    };
    const xDomain = numericDomain(points, "x");
    const yDomain = numericDomain(points, "y");
    const svg = svgElement("svg", {
      viewBox: "0 0 " + dimensions.width + " " + dimensions.height,
      role: "img",
      "aria-label":
        (type === "line" ? "Line" : "Scatter") +
        " plot of " + fieldLabel(yField) + " by " + fieldLabel(xField),
      class: "ps-table-plot__svg ps-table-plot__svg--points",
    });
    svg.appendChild(svgElement("title", null,
      (type === "line" ? "Line" : "Scatter") +
      " plot: " + fieldLabel(yField) + " by " + fieldLabel(xField)
    ));
    appendNumericAxes(svg, dimensions, xDomain, yDomain, xField, yField);

    const scaleX = linearScale(xDomain, dimensions.left, dimensions.width - dimensions.right);
    const scaleY = linearScale(yDomain, dimensions.height - dimensions.bottom, dimensions.top);
    const renderedPoints = type === "line"
      ? points.slice().sort(function (left, right) {
          return left.x - right.x || left.index - right.index;
        })
      : points;

    if (type === "line") {
      const coordinates = renderedPoints.map(function (point) {
        return scaleX(point.x) + "," + scaleY(point.y);
      }).join(" ");
      svg.appendChild(svgElement("polyline", {
        points: coordinates,
        fill: "none",
        class: "ps-table-plot__line",
      }));
    }

    renderedPoints.forEach(function (point) {
      svg.appendChild(svgElement("circle", {
        cx: scaleX(point.x),
        cy: scaleY(point.y),
        r: type === "line" ? 2.7 : 3.3,
        class: type === "line"
          ? "ps-table-plot__point ps-table-plot__point--line"
          : "ps-table-plot__point",
      }));
    });

    figure.appendChild(svg);
  }

  function buildBarSeries(rows, field) {
    const categories = new Map();
    let missing = 0;
    let invalid = 0;
    let plottedCount = 0;

    for (const row of rows) {
      const value = categoricalValue(row ? row[field] : null);
      if (value.kind === "missing") {
        missing += 1;
        continue;
      }
      if (value.kind === "invalid") {
        invalid += 1;
        continue;
      }
      plottedCount += 1;
      const existing = categories.get(value.key);
      if (existing) existing.count += 1;
      else categories.set(value.key, { label: value.label, count: 1 });
    }

    return {
      categories: Array.from(categories.values()),
      plottedCount: plottedCount,
      missing: missing,
      invalid: invalid,
    };
  }

  function buildPointSeries(rows, xField, yField) {
    const points = [];
    let missing = 0;
    let invalid = 0;

    rows.forEach(function (row, index) {
      const x = numericValue(row ? row[xField] : null);
      const y = numericValue(row ? row[yField] : null);
      if (x.kind === "missing" || y.kind === "missing") {
        missing += 1;
        return;
      }
      if (x.kind !== "value" || y.kind !== "value") {
        invalid += 1;
        return;
      }
      points.push({ x: x.value, y: y.value, index: index });
    });

    return {
      points: points,
      missing: missing,
      invalid: invalid,
    };
  }

  function renderTablePlot(options) {
    const settings = options && typeof options === "object" ? options : {};
    const container = settings.container;
    if (!container || typeof container.appendChild !== "function") {
      return { ok: false, reason: "missing_container", rowCount: 0, plottedCount: 0 };
    }

    const type = String(settings.type || "").toLowerCase();
    const rows = currentFilteredRows(settings);
    if (!rows.length) {
      return refusal(
        container,
        "no_rows",
        settings.scopeKind === "summary"
          ? "No derived summary windows are currently loaded. Raw-table filters do not apply to this source."
          : "No loaded rows pass the current filters. Change or clear filters to plot data.",
        settings,
        0
      );
    }
    if (rows.length > TABLE_PLOT_LIMITS.maxSourceRows) {
      return refusal(
        container,
        "source_limit",
        "This plot has " + rows.length +
          (settings.scopeKind === "summary"
            ? " loaded derived summary windows (limit "
            : " filtered loaded rows (limit ") +
          TABLE_PLOT_LIMITS.maxSourceRows +
          (settings.scopeKind === "summary"
            ? "). Select a narrower summary source; no windows were sampled or plotted."
            : "). Filter the table before plotting; no rows were sampled or plotted."),
        settings,
        rows.length
      );
    }

    if (type === "bar") {
      const categoryField = typeof settings.categoryField === "string"
        ? settings.categoryField
        : settings.xField;
      if (typeof categoryField !== "string" || !categoryField) {
        return refusal(
          container,
          "missing_category_field",
          "Choose a categorical field for the bar chart.",
          settings,
          rows.length
        );
      }
      const series = buildBarSeries(rows, categoryField);
      if (!series.plottedCount) {
        return refusal(
          container,
          "no_valid_values",
          "No usable categorical values were found. " + skippedText(series.missing, series.invalid),
          settings,
          rows.length
        );
      }
      if (series.categories.length > TABLE_PLOT_LIMITS.maxCategories) {
        return refusal(
          container,
          "category_limit",
          "This bar chart has " + series.categories.length + " categories (limit " +
            TABLE_PLOT_LIMITS.maxCategories +
            "). Filter the table or choose a different field; no categories were collapsed or sampled.",
          settings,
          rows.length
        );
      }

      const figure = createFrame(container, "bar", "Count by " + fieldLabel(categoryField));
      renderBarChart(figure, series.categories, categoryField);
      const scope = sourceScopeText(settings, rows.length, series.plottedCount);
      appendPlotSummary(figure, skippedText(series.missing, series.invalid), scope);
      return {
        ok: true,
        type: type,
        rowCount: rows.length,
        plottedCount: series.plottedCount,
        categoryCount: series.categories.length,
        missingCount: series.missing,
        invalidCount: series.invalid,
        scope: scope,
      };
    }

    if (type !== "line" && type !== "scatter") {
      return refusal(
        container,
        "unknown_type",
        "Choose a bar, line, or scatter plot.",
        settings,
        rows.length
      );
    }

    const xField = typeof settings.xField === "string" ? settings.xField : "";
    const yField = typeof settings.yField === "string" ? settings.yField : "";
    if (!xField || !yField) {
      return refusal(
        container,
        "missing_numeric_field",
        "Choose numeric x and y fields for the " + type + " plot.",
        settings,
        rows.length
      );
    }

    const series = buildPointSeries(rows, xField, yField);
    if (!series.points.length) {
      return refusal(
        container,
        "no_valid_points",
        "No usable numeric point pairs were found. " + skippedText(series.missing, series.invalid),
        settings,
        rows.length
      );
    }
    if (series.points.length > TABLE_PLOT_LIMITS.maxPoints) {
      return refusal(
        container,
        "point_limit",
        "This " + type + " plot has " + series.points.length + " valid points (limit " +
          TABLE_PLOT_LIMITS.maxPoints +
          "). Filter the table before plotting; no points were sampled or plotted.",
        settings,
        rows.length
      );
    }

    const figure = createFrame(container, type,
      (type === "line" ? "Line" : "Scatter") + " plot: " +
      fieldLabel(yField) + " by " + fieldLabel(xField)
    );
    renderPointChart(figure, type, series.points, xField, yField);
    const scope = sourceScopeText(settings, rows.length, series.points.length);
    appendPlotSummary(figure, skippedText(series.missing, series.invalid), scope);
    return {
      ok: true,
      type: type,
      rowCount: rows.length,
      plottedCount: series.points.length,
      missingCount: series.missing,
      invalidCount: series.invalid,
      scope: scope,
    };
  }

  core.TABLE_PLOT_LIMITS = TABLE_PLOT_LIMITS;
  core.renderTablePlot = renderTablePlot;
})();

/* plotsrv source: js/renderers/table_plot_controls.js */
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
  const PLOT_PREFERENCE_PREFIX = "plotsrv:v1:table_plot:";
  const PLOT_TYPES = ["bar", "line", "scatter"];

  function normalizeCapabilities(raw) {
    const value = raw && typeof raw === "object" ? raw : {};
    const requestedSources = Array.isArray(value.sources) ? value.sources : ["table"];
    const sources = ["table"];
    if (requestedSources.includes("summary")) sources.push("summary");
    return {
      sources: sources,
      tableLabel: typeof value.tableLabel === "string" && value.tableLabel
        ? value.tableLabel
        : "Filtered loaded rows",
      summaryLabel: typeof value.summaryLabel === "string" && value.summaryLabel
        ? value.summaryLabel
        : "Derived summary windows",
      tableScopeDescription:
        typeof value.tableScopeDescription === "string"
          ? value.tableScopeDescription
          : "",
      summaryScopeDescription:
        typeof value.summaryScopeDescription === "string"
          ? value.summaryScopeDescription
          : "Stream source: currently loaded derived summary windows with their displayed aggregate bounds.",
    };
  }

  function capabilities() {
    if (!state.tablePlotCapabilities) {
      state.tablePlotCapabilities = normalizeCapabilities(null);
    }
    return state.tablePlotCapabilities;
  }

  function setTablePlotCapabilities(raw) {
    state.tablePlotCapabilities = normalizeCapabilities(raw);
  }

  function preferenceKey() {
    return PLOT_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function defaultPreferences() {
    return {
      type: "bar",
      source: "table",
      categoryField: "",
      xField: "",
      yField: "",
    };
  }

  function loadPreferences() {
    let parsed = null;
    try {
      const stored = localStorage.getItem(preferenceKey());
      if (stored) parsed = JSON.parse(stored);
    } catch (e) {
      parsed = null;
    }

    const defaults = defaultPreferences();
    state.tablePlotPreferences = {
      type:
        parsed && typeof parsed.type === "string" && PLOT_TYPES.includes(parsed.type)
          ? parsed.type
          : defaults.type,
      source:
        parsed && typeof parsed.source === "string" &&
        ["table", "summary"].includes(parsed.source)
          ? parsed.source
          : defaults.source,
      categoryField:
        parsed && typeof parsed.categoryField === "string" ? parsed.categoryField : "",
      xField: parsed && typeof parsed.xField === "string" ? parsed.xField : "",
      yField: parsed && typeof parsed.yField === "string" ? parsed.yField : "",
    };
  }

  function preferences() {
    if (!state.tablePlotPreferences) loadPreferences();
    return state.tablePlotPreferences;
  }

  function savePreferences() {
    try {
      localStorage.setItem(preferenceKey(), JSON.stringify(preferences()));
    } catch (e) {
      // Plot preferences are optional browser-local convenience only.
    }
  }

  function tableFields() {
    return Array.isArray(state.tableFields) ? state.tableFields.slice() : [];
  }

  function tableNumericFields() {
    const types = state.tableFieldTypes || {};
    return tableFields().filter(function (field) {
      return types[field] === "number";
    });
  }

  function sourceFields(source) {
    if (source === "summary") {
      return Array.isArray(state.tablePlotSummaryFields)
        ? state.tablePlotSummaryFields.slice()
        : [];
    }
    return tableFields();
  }

  function sourceNumericFields(source) {
    if (source === "summary") {
      const types = state.tablePlotSummaryFieldTypes || {};
      return sourceFields(source).filter(function (field) {
        return types[field] === "number";
      });
    }
    return tableNumericFields();
  }

  function chooseField(saved, candidates, otherField) {
    if (typeof saved === "string" && candidates.includes(saved)) return saved;
    return candidates.find(function (field) {
      return field !== otherField;
    }) || candidates[0] || "";
  }

  function normalizePreferences() {
    const prefs = preferences();
    const availableSources = capabilities().sources;
    const source = prefs.source === "summary" && availableSources.includes("summary")
      ? "summary"
      : "table";
    const allFields = sourceFields(source);
    const numeric = sourceNumericFields(source);
    const nextType = PLOT_TYPES.includes(prefs.type) ? prefs.type : "bar";
    const nextCategory = chooseField(prefs.categoryField, allFields);
    const nextX = chooseField(prefs.xField, numeric);
    const nextY = chooseField(prefs.yField, numeric, nextX);
    const changed =
      prefs.type !== nextType ||
      prefs.source !== source ||
      prefs.categoryField !== nextCategory ||
      prefs.xField !== nextX ||
      prefs.yField !== nextY;

    prefs.type = nextType;
    prefs.source = source;
    prefs.categoryField = nextCategory;
    prefs.xField = nextX;
    prefs.yField = nextY;
    if (changed) savePreferences();
    return prefs;
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function populateSelect(select, values, selected, placeholder) {
    if (!select || typeof document.createElement !== "function") return;
    clearElement(select);

    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    select.appendChild(empty);

    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }

    select.value = selected || "";
    select.disabled = values.length === 0;
  }

  function setButtonState(button, pressed) {
    if (!button) return;
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
    if (button.classList && typeof button.classList.toggle === "function") {
      button.classList.toggle("is-active", pressed);
    }
  }

  function currentMode() {
    return state.tablePlotMode === "plot" ? "plot" : "table";
  }

  function renderControls() {
    const type = document.getElementById("table-plot-type");
    const source = document.getElementById("table-plot-source");
    const category = document.getElementById("table-plot-category");
    const x = document.getElementById("table-plot-x");
    const y = document.getElementById("table-plot-y");
    const categoryControl = document.getElementById("table-plot-category-control");
    const xControl = document.getElementById("table-plot-x-control");
    const yControl = document.getElementById("table-plot-y-control");
    const sourceControl = document.getElementById("table-plot-source-control");
    const scopeNotice = document.getElementById("table-plot-controls-scope");
    if (!type || !source || !category || !x || !y) return;

    const prefs = normalizePreferences();
    const availableCapabilities = capabilities();
    type.value = prefs.type;
    source.value = prefs.source;
    const sourceOptions = Array.from(source.options || []);
    sourceOptions.forEach(function (option) {
      if (option.value === "table") option.textContent = availableCapabilities.tableLabel;
      if (option.value === "summary") option.textContent = availableCapabilities.summaryLabel;
      option.hidden = !availableCapabilities.sources.includes(option.value);
    });
    source.disabled = availableCapabilities.sources.length < 2;
    if (sourceControl) sourceControl.hidden = availableCapabilities.sources.length < 2;
    const availableFields = sourceFields(prefs.source);
    const availableNumericFields = sourceNumericFields(prefs.source);
    populateSelect(category, availableFields, prefs.categoryField, "Choose a category");
    populateSelect(x, availableNumericFields, prefs.xField, "Choose an x field");
    populateSelect(y, availableNumericFields, prefs.yField, "Choose a y field");

    const isBar = prefs.type === "bar";
    if (categoryControl) categoryControl.hidden = !isBar;
    if (xControl) xControl.hidden = isBar;
    if (yControl) yControl.hidden = isBar;
    if (scopeNotice) {
      scopeNotice.textContent = prefs.source === "summary"
        ? "Derived summary plots use only the currently loaded aggregate windows; they are not source log rows and raw-table filters do not apply."
        : availableCapabilities.tableScopeDescription ||
          "Plots use only loaded rows that pass the current browser filters.";
    }
  }

  function renderControllerError(output) {
    output.replaceChildren();
    const notice = document.createElement("section");
    notice.className = "ps-table-plot__notice ps-table-plot__notice--error";
    notice.dataset.plotState = "error";
    const title = document.createElement("h2");
    title.className = "ps-table-plot__notice-title";
    title.textContent = "Unable to render plot";
    const detail = document.createElement("p");
    detail.className = "ps-table-plot__notice-detail";
    detail.textContent = "Return to the table or change the plot selections and try again.";
    notice.appendChild(title);
    notice.appendChild(detail);
    output.appendChild(notice);
  }

  function refreshTablePlot() {
    if (currentMode() !== "plot") return null;
    const output = document.getElementById("table-plot-output");
    if (!output || typeof core.renderTablePlot !== "function") return null;

    renderControls();
    const prefs = normalizePreferences();
    const options = {
      container: output,
      type: prefs.type,
      categoryField: prefs.categoryField,
      xField: prefs.xField,
      yField: prefs.yField,
    };
    if (prefs.source === "summary") {
      options.rows = Array.isArray(state.tablePlotSummaryRows)
        ? state.tablePlotSummaryRows
        : [];
      options.scopeKind = "summary";
      options.scopeDescription = capabilities().summaryScopeDescription;
    } else {
      options.scopeDescription = capabilities().tableScopeDescription;
    }
    try {
      return core.renderTablePlot(options);
    } catch (error) {
      console.error("Unable to render table plot", error);
      renderControllerError(output);
      return { ok: false, reason: "renderer_error", rowCount: 0, plottedCount: 0 };
    }
  }

  function applyMode(mode, options) {
    const nextMode = mode === "plot" ? "plot" : "table";
    const surface = document.getElementById("table-data-surface");
    const controls = document.getElementById("table-plot-controls");
    const output = document.getElementById("table-plot-output");
    const tableButton = document.getElementById("table-mode-table-btn");
    const plotButton = document.getElementById("table-mode-plot-btn");
    if (!surface || !controls || !output || !tableButton || !plotButton) return;

    state.tablePlotMode = nextMode;
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
    const isPlot = nextMode === "plot";
    surface.hidden = isPlot;
    controls.hidden = !isPlot;
    output.hidden = !isPlot;
    setButtonState(tableButton, !isPlot);
    setButtonState(plotButton, isPlot);

    if (isPlot) {
      refreshTablePlot();
      return;
    }

    if (!options || options.redraw !== false) {
      const table = state.tabulatorInstance;
      if (table && typeof table.redraw === "function") {
        try {
          table.redraw(true);
        } catch (e) {
          // A redraw failure must not block returning to the primary table.
        }
      }
    }
  }

  function bindControls() {
    const tableButton = document.getElementById("table-mode-table-btn");
    const plotButton = document.getElementById("table-mode-plot-btn");
    const type = document.getElementById("table-plot-type");
    const source = document.getElementById("table-plot-source");
    const category = document.getElementById("table-plot-category");
    const x = document.getElementById("table-plot-x");
    const y = document.getElementById("table-plot-y");

    if (tableButton && !tableButton.dataset.plotsrvBound) {
      tableButton.addEventListener("click", function () {
        applyMode("table");
      });
      tableButton.dataset.plotsrvBound = "1";
    }

    if (plotButton && !plotButton.dataset.plotsrvBound) {
      plotButton.addEventListener("click", function () {
        applyMode("plot");
      });
      plotButton.dataset.plotsrvBound = "1";
    }

    if (type && !type.dataset.plotsrvBound) {
      type.addEventListener("change", function () {
        preferences().type = PLOT_TYPES.includes(type.value) ? type.value : "bar";
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      type.dataset.plotsrvBound = "1";
    }

    if (source && !source.dataset.plotsrvBound) {
      source.addEventListener("change", function () {
        preferences().source = source.value === "summary" ? "summary" : "table";
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      source.dataset.plotsrvBound = "1";
    }

    function bindField(select, preferenceName) {
      if (!select || select.dataset.plotsrvBound) return;
      select.addEventListener("change", function () {
        preferences()[preferenceName] = String(select.value || "");
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      select.dataset.plotsrvBound = "1";
    }

    bindField(category, "categoryField");
    bindField(x, "xField");
    bindField(y, "yField");
  }

  function safeSummaryNumber(value) {
    const number = Number(value);
    return Number.isSafeInteger(number) && number >= 0 ? number : null;
  }

  function setTablePlotSummaryRows(payload) {
    const windows = Array.isArray(payload && payload.windows) ? payload.windows : [];
    const rows = [];
    const summaryFields = [
      "summary_window",
      "summary_tier",
      "record_count",
      "first_browser_sequence",
      "last_browser_sequence",
      "resolution_seconds",
    ];
    const summaryTypes = {
      summary_window: "number",
      summary_tier: "text",
      record_count: "number",
      first_browser_sequence: "number",
      last_browser_sequence: "number",
      resolution_seconds: "number",
    };

    windows.forEach(function (window) {
      if (!window || typeof window !== "object" || window.derived !== true) return;
      const row = {
        summary_window: rows.length + 1,
        summary_tier: typeof window.tier === "string" ? window.tier : "unknown",
      };
      const metrics = [
        ["record_count", window.record_count],
        ["first_browser_sequence", window.first_browser_sequence],
        ["last_browser_sequence", window.last_browser_sequence],
        [
          "resolution_seconds",
          window.resolution && typeof window.resolution === "object"
            ? window.resolution.seconds
            : null,
        ],
      ];
      for (const metric of metrics) {
        const number = safeSummaryNumber(metric[1]);
        if (number !== null) row[metric[0]] = number;
      }
      rows.push(row);
    });

    state.tablePlotSummaryRows = rows;
    state.tablePlotSummaryFields = summaryFields;
    state.tablePlotSummaryFieldTypes = summaryTypes;
    if (currentMode() === "plot" && preferences().source === "summary") {
      refreshTablePlot();
    }
  }

  function configureTablePlotSurface() {
    const tableButton = document.getElementById("table-mode-table-btn");
    const plotButton = document.getElementById("table-mode-plot-btn");
    const surface = document.getElementById("table-data-surface");
    const output = document.getElementById("table-plot-output");
    if (!tableButton || !plotButton || !surface || !output) return;

    if (state.tablePlotViewId !== config.activeViewId) {
      state.tablePlotViewId = config.activeViewId;
      // Mode is deliberately not a saved preference: every page opens with
      // the primary table visible until the user explicitly switches to Plot.
      state.tablePlotMode = "table";
      state.tablePlotPreferences = null;
    }

    bindControls();
    renderControls();
    applyMode(currentMode(), { redraw: false });
  }

  core.configureTablePlotSurface = configureTablePlotSurface;
  core.refreshTablePlot = refreshTablePlot;
  core.setTablePlotMode = applyMode;
  core.setTablePlotCapabilities = setTablePlotCapabilities;
  core.setTablePlotSummaryRows = setTablePlotSummaryRows;
})();

/* plotsrv source: js/renderers/stream.js */
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
      plotCapabilities: {
        sources: ["table", "summary"],
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
        if (typeof core.markBrowserViewApplied === "function") {
          core.markBrowserViewApplied();
        }
        if (typeof core.notifyUpdateEligibilityChanged === "function") {
          core.notifyUpdateEligibilityChanged();
        }
      } catch (error) {
        showStreamError();
      }
    };
  }

  async function returnToCurrentStream() {
    state.streamHistoricalSessionId = null;
    if (typeof core.renderHeaderStatus === "function") core.renderHeaderStatus();
    await resetStreamSessionPresentation();
    await loadStream();
    if (typeof core.markBrowserViewApplied === "function") {
      core.markBrowserViewApplied();
    }
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
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
  core.returnToCurrentStream = returnToCurrentStream;
  window.refreshStream = function () {
    return loadStream();
  };
})();

/* plotsrv source: js/renderers/json.js */
// src/plotsrv/static/js/renderers/json.js
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const renderers = window.PLOTSRV.renderers;
  const config = window.PLOTSRV.config;

  function clearJsonHits(scopeEl) {
    if (!scopeEl) return;
    const hits = scopeEl.querySelectorAll(".json-hit, .json-hit-current");
    hits.forEach((el) => {
      el.classList.remove("json-hit");
      el.classList.remove("json-hit-current");
    });
  }

  function getJsonRoot(root) {
    if (!root) return null;
    return root.querySelector('[data-plotsrv-json="1"]');
  }

  function getJsonPrefs() {
    if (typeof core.loadJsonPrefs === "function") {
      return core.loadJsonPrefs(config.activeViewId);
    }
    return {
      mode: "json",
      level_limit: "2",
      find_query: "",
      pinned_values: [],
    };
  }

  function saveJsonPrefs(nextPrefs) {
    if (typeof core.saveJsonPrefs === "function") {
      core.saveJsonPrefs(config.activeViewId, nextPrefs);
    }
  }

  function getPanels(jsonRoot) {
    if (!jsonRoot) return [];
    return Array.from(jsonRoot.querySelectorAll("[data-json-panel]"));
  }

  function isExplorerMode(mode) {
    return mode === "table" || mode === "plot";
  }

  function hasTableExplorer(jsonRoot) {
    return !!(jsonRoot && jsonRoot.querySelector('[data-json-panel="table"]'));
  }

  function isJsonTreeMode(mode) {
    return mode === "json" || mode === "simple";
  }

  function getModeButtons(root) {
    return Array.from(root.querySelectorAll("[data-json-mode]"));
  }

  function applyModeButtonState(root, mode) {
    getModeButtons(root).forEach((btn) => {
      const btnMode = String(btn.getAttribute("data-json-mode") || "");
      const isActive = btnMode === mode;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function getToolbarGroup(root, name) {
    return root.querySelector('[data-json-toolbar-group="' + String(name) + '"]');
  }

  function syncToolbarForMode(root, mode) {
    const levelsGroup = getToolbarGroup(root, "levels");
    const findGroup = getToolbarGroup(root, "find");
    const pinsGroup = getToolbarGroup(root, "pins");
    const viewGroup = getToolbarGroup(root, "view");
  
    const isText = mode === "text";
    const isExplorer = isExplorerMode(mode);
  
    function setGroupVisible(el, shouldShow) {
      if (!el) return;
      el.hidden = !shouldShow;
      el.style.display = shouldShow ? "" : "none";
    }
  
    setGroupVisible(levelsGroup, !isText && !isExplorer);
    setGroupVisible(findGroup, !isText && !isExplorer);
    setGroupVisible(pinsGroup, !isText && !isExplorer);
    setGroupVisible(viewGroup, true);
  }

  function setMode(root, mode) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const allowed = new Set(["json", "simple", "text", "table", "plot"]);
    const requestedMode = allowed.has(mode) ? mode : "json";
    const nextMode = isExplorerMode(requestedMode) && !hasTableExplorer(jsonRoot)
      ? "json"
      : requestedMode;

    getPanels(jsonRoot).forEach((panel) => {
      const panelMode = String(panel.getAttribute("data-json-panel") || "");
      panel.hidden = isExplorerMode(nextMode)
        ? panelMode !== "table"
        : panelMode !== nextMode;
    });

    applyModeButtonState(root, nextMode);
    syncToolbarForMode(root, nextMode);

    if (isExplorerMode(nextMode) && typeof core.setTablePlotMode === "function") {
      core.setTablePlotMode(nextMode, { redraw: nextMode === "table" });
    } else if (typeof core.setTablePlotMode === "function") {
      // A hidden JSON explorer must not keep smart updates paused as though
      // its plot were still visible.
      core.setTablePlotMode("table", { redraw: false });
    }

    if (nextMode === "text") {
      applyTextModeContent(root);
      clearJsonHits(jsonRoot);
      const localState = root._plotsrvJsonState;
      if (localState) {
        localState.hits = [];
        localState.idx = -1;
        setCounter(root, localState);
      }
      closePinnedModal(root);
    }

    const prefs = getJsonPrefs();
    prefs.mode = nextMode;
    saveJsonPrefs(prefs);
  }

  function parseStoredJsonText(raw) {
    if (typeof raw !== "string" || !raw) return null;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function getPreferredTextValue(jsonRoot) {
    if (!jsonRoot) return "";

    const rawText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-raw-text") || "null"
    );
    if (typeof rawText === "string") return rawText;

    const prettyText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-pretty-text") || "null"
    );
    if (typeof prettyText === "string") return prettyText;

    const existing = jsonRoot.querySelector("[data-json-text-view='1']");
    return existing ? String(existing.textContent || "") : "";
  }

  function applyTextModeContent(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const textPre = jsonRoot.querySelector("[data-json-text-view='1']");
    if (!textPre) return;

    textPre.textContent = getPreferredTextValue(jsonRoot);
  }

  function getDetailsNodesForMode(root, mode) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return [];

    return Array.from(
      jsonRoot.querySelectorAll(
        '[data-json-panel="' + String(mode) + '"] details[data-json-depth]'
      )
    );
  }

  function getActiveMode(root) {
    const active = root.querySelector("[data-json-mode].is-active");
    if (!active) return "json";
    return String(active.getAttribute("data-json-mode") || "json");
  }

  function setLevelLimit(root, rawLevelLimit) {
    const mode = getActiveMode(root);
    if (!isJsonTreeMode(mode)) return;

    const levelLimit = String(rawLevelLimit || "2");
    const select = root.querySelector("[data-json-level-limit='1']");
    if (select && String(select.value || "") !== levelLimit) {
      select.value = levelLimit;
    }

    const detailsNodes = getDetailsNodesForMode(root, mode);

    if (!detailsNodes.length) {
      const prefs = getJsonPrefs();
      prefs.level_limit = levelLimit;
      saveJsonPrefs(prefs);
      return;
    }

    if (levelLimit === "all") {
      detailsNodes.forEach((node) => {
        node.open = true;
      });
    } else {
      const n = Number(levelLimit);
      const limit = Number.isFinite(n) && n >= 1 ? n : 2;

      detailsNodes.forEach((node) => {
        const depth = Number(node.getAttribute("data-json-depth") || "0");
        node.open = depth < limit;
      });
    }

    const prefs = getJsonPrefs();
    prefs.level_limit = levelLimit;
    saveJsonPrefs(prefs);
  }

  function expandAll(root) {
    const mode = getActiveMode(root);
    if (!isJsonTreeMode(mode)) return;

    const detailsNodes = getDetailsNodesForMode(root, mode);
    detailsNodes.forEach((node) => {
      node.open = true;
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "all";

    const prefs = getJsonPrefs();
    prefs.level_limit = "all";
    saveJsonPrefs(prefs);
    root._plotsrvCollapseState = {
      lastAction: "expand",
      preservedPinned: [],
    };
  }

  function collapseAll(root) {
    const mode = getActiveMode(root);
    if (!isJsonTreeMode(mode)) return;

    const detailsNodes = getDetailsNodesForMode(root, mode);
    const expandedPinned = getExpandedPinnedPaths(root);

    const previousState = root._plotsrvCollapseState || {
      lastAction: "",
      preservedPinned: [],
    };

    const sameAsLast =
      previousState.lastAction === "collapse-preserve" &&
      Array.isArray(previousState.preservedPinned) &&
      previousState.preservedPinned.length > 0;

    detailsNodes.forEach((node) => {
      const depth = Number(node.getAttribute("data-json-depth") || "0");
      node.open = depth < 1;
    });

    if (sameAsLast) {
      previousState.preservedPinned.forEach((path) => {
        setPinnedValueExpanded(root, path, false);
      });
      root._plotsrvCollapseState = {
        lastAction: "collapse-full",
        preservedPinned: [],
      };
    } else {
      expandedPinned.forEach((path) => {
        setPinnedValueExpanded(root, path, true);
      });
      root._plotsrvCollapseState = {
        lastAction: "collapse-preserve",
        preservedPinned: expandedPinned,
      };
    }

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "1";

    const prefs = getJsonPrefs();
    prefs.level_limit = "1";
    saveJsonPrefs(prefs);
  }

  function getSearchScope(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return null;

    const activePanel = Array.from(
      jsonRoot.querySelectorAll("[data-json-panel]")
    ).find((panel) => !panel.hidden);

    return activePanel || jsonRoot;
  }

  function setCounter(root, localState) {
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");
    if (!countEl) return;

    if (!localState.hits.length) {
      countEl.textContent = "";
      return;
    }

    countEl.textContent =
      String(localState.idx + 1) + "/" + String(localState.hits.length);
  }

  function openParents(el) {
    let cur = el;
    while (cur) {
      const det = core.findNearest(cur, "details");
      if (!det) break;
      det.open = true;
      cur = det.parentElement;
    }
  }

  function gotoIndex(root, localState, i) {
    if (!localState.hits.length) return;

    localState.hits.forEach((el) => el.classList.remove("json-hit-current"));
    localState.idx = (i + localState.hits.length) % localState.hits.length;

    const el = localState.hits[localState.idx];
    el.classList.add("json-hit-current");
    openParents(el);

    try {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (e) {
      el.scrollIntoView();
    }

    setCounter(root, localState);
  }

  function runFind(root, localState) {
    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const searchScope = getSearchScope(root);
    if (!input || !searchScope) return;

    const q = String(input.value || "").trim();

    const prefs = getJsonPrefs();
    prefs.find_query = q;
    saveJsonPrefs(prefs);

    clearJsonHits(searchScope);
    localState.hits = [];
    localState.idx = -1;
    setCounter(root, localState);

    if (!q) return;

    const panelMode = String(searchScope.getAttribute("data-json-panel") || "");
    if (panelMode === "text") {
      return;
    }

    const qLower = q.toLowerCase();
    const candidates = searchScope.querySelectorAll("[data-json-text]");

    candidates.forEach((el) => {
      const t = String(el.getAttribute("data-json-text") || "").toLowerCase();
      if (!t) return;
      if (t.includes(qLower)) {
        el.classList.add("json-hit");
        localState.hits.push(el);
      }
    });

    if (localState.hits.length) {
      gotoIndex(root, localState, 0);
    }
  }

  function getPinnedPaths() {
    const prefs = getJsonPrefs();
    return Array.isArray(prefs.pinned_values) ? prefs.pinned_values.map(String) : [];
  }

  function setPinnedPaths(paths) {
    const prefs = getJsonPrefs();
    prefs.pinned_values = Array.from(new Set((paths || []).map(String).filter(Boolean)));
    saveJsonPrefs(prefs);
  }

  function getExpandedPinnedPaths(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return [];

    const pinned = new Set(getPinnedPaths());

    return Array.from(
      jsonRoot.querySelectorAll(".ps-json-entry.is-pinned[data-json-path]")
    )
      .map((el) => String(el.getAttribute("data-json-path") || ""))
      .filter((path) => {
        if (!path || !pinned.has(path)) return false;
        const entry = jsonRoot.querySelector(
          '[data-json-path="' + CSS.escape(path) + '"]'
        );
        return !!entry;
      });
  }

  function setPinnedValueExpanded(root, path, shouldOpen) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const entry = jsonRoot.querySelector(
      '.ps-json-entry[data-json-path="' + CSS.escape(String(path)) + '"]'
    );
    if (!entry) return;

    entry.classList.toggle("is-pinned-open", shouldOpen);
  }

  function isPinned(path) {
    return new Set(getPinnedPaths()).has(String(path || ""));
  }

  function setPinnedState(root, path, shouldPin) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const btn = jsonRoot.querySelector(
      '[data-json-pin-toggle="' + CSS.escape(String(path)) + '"]'
    );
    const entry = jsonRoot.querySelector(
      '[data-json-path="' + CSS.escape(String(path)) + '"]'
    );

    if (btn) {
      btn.setAttribute("aria-pressed", shouldPin ? "true" : "false");
      btn.classList.toggle("is-pinned", shouldPin);
      btn.title = shouldPin ? "Unpin value" : "Pin value";
    }

    if (entry) {
      entry.classList.toggle("is-pinned", shouldPin);
    }
  }

  function restorePinnedStates(root) {
    const pinned = new Set(getPinnedPaths());
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const pinBtns = jsonRoot.querySelectorAll("[data-json-pin-toggle]");
    pinBtns.forEach((btn) => {
      const path = String(btn.getAttribute("data-json-pin-toggle") || "");
      setPinnedState(root, path, pinned.has(path));
    });
  }

  function getEntryFullValue(entry) {
    if (!entry) return "";
  
    const hiddenValue = entry.querySelector("[data-json-full-value-text='1']");
    if (hiddenValue) {
      return String(hiddenValue.textContent || "");
    }
  
    return String(entry.getAttribute("data-json-full-value") || "");
  }

  function buildPinnedModalList(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return "";

    const pinned = getPinnedPaths();
    if (!pinned.length) {
      return '<div class="note ps-note">No pinned values yet.</div>';
    }

    const parts = [];

    pinned.forEach((path) => {
      const entry = jsonRoot.querySelector(
        '.ps-json-entry[data-json-path="' + CSS.escape(String(path)) + '"]'
      );
      if (!entry) return;

      const key = String(entry.getAttribute("data-json-key") || path);
      const value = getEntryFullValue(entry);

      parts.push(
        '<div class="ps-json-pinneditem">' +
        '<div class="ps-json-pinneditem__meta">' +
        '<div class="ps-json-pinneditem__key">' + core.escapeHtml(key) + '</div>' +
        '<div class="ps-json-pinneditem__path">' + core.escapeHtml(path) + '</div>' +
        '</div>' +
        '<pre class="ps-json-pinneditem__value">' + core.escapeHtml(value) + '</pre>' +
        '</div>'
      );
    });

    if (!parts.length) {
      return '<div class="note ps-note">No pinned values available in this snapshot.</div>';
    }

    return parts.join("");
  }

  function openPinnedModal(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const modal = jsonRoot.querySelector("[data-json-pinned-modal='1']");
    const list = jsonRoot.querySelector("[data-json-pinned-list='1']");
    if (!modal || !list) return;

    list.innerHTML = buildPinnedModalList(root);
    modal.hidden = false;
  }

  function closePinnedModal(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const modal = jsonRoot.querySelector("[data-json-pinned-modal='1']");
    if (!modal) return;

    modal.hidden = true;
  }

  function restorePrefs(root) {
    const prefs = getJsonPrefs();

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    if (input) {
      input.value = prefs.find_query || "";
    }

    applyTextModeContent(root);
    const preferredMode = ["json", "simple", "text", "table", "plot"].includes(
      prefs.mode
    )
      ? prefs.mode
      : "json";
    setMode(root, preferredMode);
    setLevelLimit(root, prefs.level_limit || "2");
    restorePinnedStates(root);
    syncToolbarForMode(root, getActiveMode(root));
  }

  function bindJsonToolbar(root, localState) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const jsonRoot = getJsonRoot(root);
    if (!toolbar || !jsonRoot) return;
    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;

    toolbar.setAttribute("data-plotsrv-bound", "1");

    toolbar.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const mode = String(btn.getAttribute("data-json-mode") || "");
      if (mode) {
        setMode(root, mode);
        if (isJsonTreeMode(mode)) {
          runFind(root, localState);
        }
        return;
      }

      const action = String(btn.getAttribute("data-plotsrv-action") || "");

      if (action === "expand-all") {
        expandAll(root);
        return;
      }

      if (action === "collapse-all") {
        collapseAll(root);
        return;
      }

      if (action === "find-next") {
        if (!localState.hits.length) runFind(root, localState);
        if (localState.hits.length) gotoIndex(root, localState, localState.idx + 1);
        return;
      }

      if (action === "find-prev") {
        if (!localState.hits.length) runFind(root, localState);
        if (localState.hits.length) gotoIndex(root, localState, localState.idx - 1);
        return;
      }

      if (action === "open-pinned") {
        openPinnedModal(root);
      }
    });

    jsonRoot.addEventListener("click", function (ev) {
      const pinBtn =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-json-pin-toggle]")
          : null;

      if (pinBtn) {
        const path = String(pinBtn.getAttribute("data-json-pin-toggle") || "");
        if (!path) return;

        const current = new Set(getPinnedPaths());
        const shouldPin = !current.has(path);

        if (shouldPin) {
          current.add(path);
        } else {
          current.delete(path);
        }

        setPinnedPaths(Array.from(current));
        setPinnedState(root, path, shouldPin);
        return;
      }

      const closeEl =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-json-pinned-close]")
          : null;

      if (closeEl) {
        closePinnedModal(root);
      }
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) {
      select.addEventListener("change", function () {
        setLevelLimit(root, String(select.value || "2"));
      });
    }

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    if (input) {
      input.addEventListener("input", function () {
        if (input._plotsrvTimer) clearTimeout(input._plotsrvTimer);
        input._plotsrvTimer = setTimeout(function () {
          runFind(root, localState);
        }, 120);
      });

      input.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") {
          ev.preventDefault();
          if (!localState.hits.length) runFind(root, localState);
          if (localState.hits.length) gotoIndex(root, localState, localState.idx + 1);
        }
      });
    }
  }

  function initJsonToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const jsonRoot = getJsonRoot(root);
    if (!toolbar || !jsonRoot) return;

    const localState = {
      hits: [],
      idx: -1,
    };

    root._plotsrvJsonState = localState;

    bindJsonToolbar(root, localState);
    initJsonTableExplorer(root);
    restorePrefs(root);
    syncToolbarForMode(root, getActiveMode(root));
    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const mode = getActiveMode(root);
    if (isJsonTreeMode(mode) && input && String(input.value || "").trim()) {
      runFind(root, localState);
    }
  }

  function initJsonTableExplorer(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot || typeof core.initializeEmbeddedTableExplorer !== "function") {
      return;
    }

    const dataEl = jsonRoot.querySelector("[data-json-table-data='1']");
    const grid = jsonRoot.querySelector("[data-json-table-grid='1']");
    if (!dataEl || !grid) return;

    const tableData = parseStoredJsonText(String(dataEl.textContent || ""));
    if (!tableData || typeof tableData !== "object") return;

    core.initializeEmbeddedTableExplorer({
      grid: grid,
      data: tableData,
      plotCapabilities: { sources: ["table"] },
    });
  }

  function initArtifactEnhancements(root) {
    if (!root) return;

    if (typeof renderers.initTextToolbar === "function") {
      renderers.initTextToolbar(root);
    }

    if (typeof renderers.initCodeToolbar === "function") {
      renderers.initCodeToolbar(root);
    }

    if (root.querySelector('[data-plotsrv-toolbar="json"]')) {
      initJsonToolbar(root);
    }
  }

  renderers.clearJsonHits = clearJsonHits;
  renderers.initJsonToolbar = initJsonToolbar;
  renderers.initArtifactEnhancements = initArtifactEnhancements;
})();

/* plotsrv source: js/renderers/text.js */
// src/plotsrv/static/js/renderers/text.js
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const renderers = window.PLOTSRV.renderers;
  const config = window.PLOTSRV.config;

  const MAX_COLOURIZE_CHARS = 300000;

  const LOG_TOKEN_RE =
    /\b(CRITICAL|FATAL|ERROR|EXCEPTION|TRACEBACK|WARNING|WARN|INFO|DEBUG|TRACE|SUCCESS|PASSED|PASS|FAILED|FAIL|OK|[1-5][0-9]{2})\b/gi;

  function getTextPrefs() {
    if (typeof core.loadTextPrefs === "function") {
      return core.loadTextPrefs(config.activeViewId);
    }

    return {
      wrap_enabled: false,
      reverse_enabled: false,
      colour_enabled: true,
    };
  }

  function saveTextPrefs(nextPrefs) {
    if (typeof core.saveTextPrefs === "function") {
      core.saveTextPrefs(config.activeViewId, nextPrefs);
      return;
    }

    if (core.storageKeys && typeof core.savePref === "function") {
      core.savePref(
        core.storageKeys.textWrapEnabled,
        nextPrefs.wrap_enabled ? "1" : "0"
      );
    }
  }

  function splitLinesPreserveEndings(text) {
    return String(text || "").match(/[^\n]*\n|[^\n]+/g) || [];
  }

  function reverseLines(text) {
    const lines = splitLinesPreserveEndings(text);
    return lines.reverse().join("");
  }

  function renderedText(state) {
    const originalText =
      typeof state.originalText === "string" ? state.originalText : "";

    return state.reverseEnabled ? reverseLines(originalText) : originalText;
  }

  function setButtonActive(btn, active) {
    if (!btn) return;
    btn.classList.toggle("is-active", !!active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function syncReverseIndicator(root, reverseEnabled) {
    const indicator = root.querySelector("[data-plotsrv-text-reverse-indicator='1']");
    if (!indicator) return;
    indicator.hidden = !reverseEnabled;
  }

  function tokenClass(token) {
    const upper = String(token || "").toUpperCase();

    if (upper === "CRITICAL" || upper === "FATAL") {
      return "ps-log-token--critical";
    }

    if (
      upper === "ERROR" ||
      upper === "EXCEPTION" ||
      upper === "TRACEBACK" ||
      upper === "FAILED" ||
      upper === "FAIL"
    ) {
      return "ps-log-token--error";
    }

    if (upper === "WARNING" || upper === "WARN") {
      return "ps-log-token--warn";
    }

    if (upper === "INFO") {
      return "ps-log-token--info";
    }

    if (upper === "DEBUG" || upper === "TRACE") {
      return "ps-log-token--debug";
    }

    if (
      upper === "SUCCESS" ||
      upper === "PASSED" ||
      upper === "PASS" ||
      upper === "OK"
    ) {
      return "ps-log-token--success";
    }

    if (/^5[0-9]{2}$/.test(upper)) {
      return "ps-log-token--error";
    }

    if (/^4[0-9]{2}$/.test(upper)) {
      return "ps-log-token--warn";
    }

    if (/^[23][0-9]{2}$/.test(upper)) {
      return "ps-log-token--success";
    }

    if (/^1[0-9]{2}$/.test(upper)) {
      return "ps-log-token--info";
    }

    return "";
  }

  function colourizeLogText(text) {
    const s = String(text || "");

    if (s.length > MAX_COLOURIZE_CHARS) {
      return core.escapeHtml(s);
    }

    let out = "";
    let lastIndex = 0;

    LOG_TOKEN_RE.lastIndex = 0;

    let match;
    while ((match = LOG_TOKEN_RE.exec(s)) !== null) {
      const token = match[0];
      const cls = tokenClass(token);

      out += core.escapeHtml(s.slice(lastIndex, match.index));

      if (cls) {
        out +=
          '<span class="ps-log-token ' +
          cls +
          '">' +
          core.escapeHtml(token) +
          "</span>";
      } else {
        out += core.escapeHtml(token);
      }

      lastIndex = match.index + token.length;
    }

    out += core.escapeHtml(s.slice(lastIndex));
    return out;
  }

  function applyTextState(root, state, opts) {
    const options = opts || {};
    const pre = root.querySelector("[data-plotsrv-pre='1']");
    if (!pre) return;

    const text = renderedText(state);

    if (state.colourEnabled) {
      pre.innerHTML = colourizeLogText(text);
      pre.classList.add("plotsrv-pre--coloured");
    } else {
      pre.textContent = text;
      pre.classList.remove("plotsrv-pre--coloured");
    }

    pre.classList.toggle("plotsrv-pre--wrap", !!state.wrapEnabled);

    const wrapBtn = root.querySelector("[data-plotsrv-action='wrap']");
    const reverseBtn = root.querySelector("[data-plotsrv-action='reverse']");
    const colourBtn = root.querySelector("[data-plotsrv-action='colour']");

    setButtonActive(wrapBtn, state.wrapEnabled);
    setButtonActive(reverseBtn, state.reverseEnabled);
    setButtonActive(colourBtn, state.colourEnabled);

    syncReverseIndicator(root, state.reverseEnabled);

    if (options.scroll !== false) {
      applyInitialScroll(pre, state);
    }
  }

  function applyInitialScroll(pre, state) {
    const anchor = String(pre.getAttribute("data-plotsrv-text-anchor") || "head");

    if (state.reverseEnabled) {
      pre.scrollTop = 0;
      return;
    }

    if (anchor === "tail") {
      pre.scrollTop = pre.scrollHeight;
      return;
    }

    pre.scrollTop = 0;
  }


  function persistState(state) {
    const nextPrefs = getTextPrefs();
    nextPrefs.wrap_enabled = state.wrapEnabled;
    nextPrefs.reverse_enabled = state.reverseEnabled;
    nextPrefs.colour_enabled = state.colourEnabled;
    saveTextPrefs(nextPrefs);
  }

  function initTextToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="text"]');
    const pre = root.querySelector('[data-plotsrv-pre="1"]');
    if (!toolbar || !pre) return;

    let jumpBtn = root.querySelector("[data-plotsrv-text-jump-bottom='1']");
    
    if (!jumpBtn) {
      jumpBtn = document.createElement("button");
      jumpBtn.type = "button";
      jumpBtn.className = "ps-text-jump-bottom";
      jumpBtn.setAttribute("data-plotsrv-text-jump-bottom", "1");
      jumpBtn.setAttribute("aria-label", "Scroll to bottom");
      jumpBtn.title = "Scroll to bottom";
      jumpBtn.textContent = "↓";
    
      const shell = pre.closest(".ps-text-shell") || pre.parentElement;
      if (shell) {
        shell.appendChild(jumpBtn);
      }
    }
    
    function syncJumpButton() {
      if (!jumpBtn) return;
    
      const thresholdPx = 32;
      const distanceFromBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight;
      const canScroll = pre.scrollHeight > pre.clientHeight + thresholdPx;
      const isAwayFromBottom = distanceFromBottom > thresholdPx;
    
      jumpBtn.hidden = !(canScroll && isAwayFromBottom);
    }
    
    jumpBtn.addEventListener("click", function () {
      pre.scrollTo({
        top: pre.scrollHeight,
        behavior: "smooth",
      });
    });
    
    pre.addEventListener("scroll", syncJumpButton);
    window.addEventListener("resize", syncJumpButton);
    setTimeout(syncJumpButton, 0);

    if (document.body) {
      document.body.classList.add("ps-has-text-artifact");
    }

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const prefs = getTextPrefs();

    const state = {
      originalText: pre.textContent || "",
      wrapEnabled: !!prefs.wrap_enabled,
      reverseEnabled: !!prefs.reverse_enabled,
      colourEnabled: prefs.colour_enabled !== false,
    };

    root._plotsrvTextState = state;

    applyTextState(root, state);
    setTimeout(syncJumpButton, 0);

    toolbar.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";

      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;
        persistState(state);
        applyTextState(root, state, { scroll: false });
        setTimeout(syncJumpButton, 0); 
        return;
      }

      if (action === "reverse") {
        state.reverseEnabled = !state.reverseEnabled;
        persistState(state);
        applyTextState(root, state);
        setTimeout(syncJumpButton, 0);  
        return;
      }

      if (action === "colour") {
        state.colourEnabled = !state.colourEnabled;
        persistState(state);
        applyTextState(root, state, { scroll: false });
        setTimeout(syncJumpButton, 0);  
        return;
      }

      if (action === "copy") {
        const ok = await core.copyTextToClipboard(renderedText(state));
        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(() => {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  }

  renderers.initTextToolbar = initTextToolbar;
})();

/* plotsrv source: js/renderers/code.js */
// src/plotsrv/static/js/renderers/code.js
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const renderers = window.PLOTSRV.renderers;
  const config = window.PLOTSRV.config;

  const KEYWORDS = new Set([
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "case",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "match",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
  ]);

  const CONSTANTS = new Set(["True", "False", "None", "Ellipsis", "NotImplemented"]);

  const BUILTINS = new Set([
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "callable",
    "dict",
    "dir",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "open",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
  ]);

  function prefsKey() {
    const viewId = String(config.activeViewId || "default").trim() || "default";
    return "plotsrv:v2:code_prefs:" + viewId;
  }

  function loadCodePrefs() {
    const fallback = {
      wrap_enabled: false,
      highlight_enabled: true,
      line_numbers_enabled: true,
    };

    try {
      const raw = localStorage.getItem(prefsKey());
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      return {
        wrap_enabled:
          typeof parsed.wrap_enabled === "boolean"
            ? parsed.wrap_enabled
            : fallback.wrap_enabled,
        highlight_enabled:
          typeof parsed.highlight_enabled === "boolean"
            ? parsed.highlight_enabled
            : fallback.highlight_enabled,
        line_numbers_enabled:
          typeof parsed.line_numbers_enabled === "boolean"
            ? parsed.line_numbers_enabled
            : fallback.line_numbers_enabled,
      };
    } catch (e) {
      return fallback;
    }
  }

  function saveCodePrefs(prefs) {
    try {
      localStorage.setItem(
        prefsKey(),
        JSON.stringify({
          wrap_enabled: !!(prefs && prefs.wrap_enabled),
          highlight_enabled:
            prefs && typeof prefs.highlight_enabled === "boolean"
              ? prefs.highlight_enabled
              : true,
          line_numbers_enabled:
            prefs && typeof prefs.line_numbers_enabled === "boolean"
              ? prefs.line_numbers_enabled
              : true,
        })
      );
    } catch (e) {
      // ignore
    }
  }

  function escapeHtml(s) {
    if (core && typeof core.escapeHtml === "function") {
      return core.escapeHtml(s);
    }

    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function splitLines(text) {
    const normalised = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = normalised.split("\n");

    if (lines.length > 1 && lines[lines.length - 1] === "") {
      lines.pop();
    }

    return lines.length ? lines : [""];
  }

  function isIdentStart(ch) {
    return /[A-Za-z_]/.test(ch);
  }

  function isIdentPart(ch) {
    return /[A-Za-z0-9_]/.test(ch);
  }

  function consumeString(line, start) {
    const quote = line[start];
    const isTriple =
      line[start + 1] === quote &&
      line[start + 2] === quote;

    let i = start + (isTriple ? 3 : 1);

    while (i < line.length) {
      if (line[i] === "\\") {
        i += 2;
        continue;
      }

      if (isTriple) {
        if (
          line[i] === quote &&
          line[i + 1] === quote &&
          line[i + 2] === quote
        ) {
          return i + 3;
        }
        i += 1;
        continue;
      }

      if (line[i] === quote) {
        return i + 1;
      }

      i += 1;
    }

    return line.length;
  }

  function consumeNumber(line, start) {
    const m = line.slice(start).match(/^(0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d[\d_]*)?j?)/);
    return m ? start + m[0].length : start + 1;
  }

  function highlightPythonLine(line) {
    let out = "";
    let i = 0;

    while (i < line.length) {
      const ch = line[i];

      if (ch === "#") {
        out += '<span class="ps-code-token ps-code-token--comment">' +
          escapeHtml(line.slice(i)) +
          "</span>";
        break;
      }

      if (ch === "'" || ch === '"') {
        const end = consumeString(line, i);
        out += '<span class="ps-code-token ps-code-token--string">' +
          escapeHtml(line.slice(i, end)) +
          "</span>";
        i = end;
        continue;
      }

      if (ch === "@" && isIdentStart(line[i + 1] || "")) {
        let j = i + 1;
        while (j < line.length && isIdentPart(line[j])) j += 1;

        out += '<span class="ps-code-token ps-code-token--decorator">' +
          escapeHtml(line.slice(i, j)) +
          "</span>";
        i = j;
        continue;
      }

      if (/[0-9]/.test(ch)) {
        const end = consumeNumber(line, i);
        out += '<span class="ps-code-token ps-code-token--number">' +
          escapeHtml(line.slice(i, end)) +
          "</span>";
        i = end;
        continue;
      }

      if (isIdentStart(ch)) {
        let j = i + 1;
        while (j < line.length && isIdentPart(line[j])) j += 1;

        const word = line.slice(i, j);
        let klass = "";

        if (KEYWORDS.has(word)) klass = "ps-code-token--keyword";
        else if (CONSTANTS.has(word)) klass = "ps-code-token--constant";
        else if (BUILTINS.has(word)) klass = "ps-code-token--builtin";

        if (klass) {
          out += '<span class="ps-code-token ' + klass + '">' +
            escapeHtml(word) +
            "</span>";
        } else {
          out += escapeHtml(word);
        }

        i = j;
        continue;
      }

      out += escapeHtml(ch);
      i += 1;
    }

    return out;
  }

  function renderCode(root, state) {
    const pre = root.querySelector("[data-plotsrv-code-pre='1']");
    const code = root.querySelector("[data-plotsrv-code-content='1']");
    if (!pre || !code) return;

    const lines = splitLines(state.originalText);
    const parts = [];

    for (let i = 0; i < lines.length; i += 1) {
      const rawLine = lines[i];
      const lineHtml = state.highlightEnabled
        ? highlightPythonLine(rawLine)
        : escapeHtml(rawLine);

      parts.push(
        '<span class="ps-code-line" data-line="' +
          String(i + 1) +
          '"><span class="ps-code-line__num">' +
          String(i + 1) +
          '</span><span class="ps-code-line__text">' +
          lineHtml +
          "</span></span>"
      );
    }

    code.innerHTML = parts.join("");
    pre.classList.toggle("ps-code-pre--wrap", !!state.wrapEnabled);
    pre.classList.toggle(
      "ps-code-pre--no-lines",
      !state.lineNumbersEnabled
    );

    setButtonState(
      root.querySelector("[data-plotsrv-code-action='wrap']"),
      state.wrapEnabled
    );
    setButtonState(
      root.querySelector("[data-plotsrv-code-action='highlight']"),
      state.highlightEnabled
    );
    setButtonState(
      root.querySelector("[data-plotsrv-code-action='lines']"),
      state.lineNumbersEnabled
    );
  }

  function setButtonState(btn, active) {
    if (!btn) return;
    btn.classList.toggle("is-active", !!active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function initCodeToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="code"]');
    const pre = root.querySelector("[data-plotsrv-code-pre='1']");
    const code = root.querySelector("[data-plotsrv-code-content='1']");

    if (!toolbar || !pre || !code) return;

    if (document.body) {
      document.body.classList.add("ps-has-code-artifact");
    }

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const prefs = loadCodePrefs();

    const state = {
      originalText: code.textContent || "",
      wrapEnabled: !!prefs.wrap_enabled,
      highlightEnabled: !!prefs.highlight_enabled,
      lineNumbersEnabled: !!prefs.line_numbers_enabled,
    };

    root._plotsrvCodeState = state;
    renderCode(root, state);

    toolbar.addEventListener("click", async function (ev) {
      const btn =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-plotsrv-code-action]")
          : null;

      if (!btn) return;

      const action = String(btn.getAttribute("data-plotsrv-code-action") || "");

      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "highlight") {
        state.highlightEnabled = !state.highlightEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "lines") {
        state.lineNumbersEnabled = !state.lineNumbersEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "copy") {
        const ok =
          core && typeof core.copyTextToClipboard === "function"
            ? await core.copyTextToClipboard(state.originalText)
            : false;

        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(function () {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  }

  renderers.initCodeToolbar = initCodeToolbar;
})();

/* plotsrv source: js/core/app.js */
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

  function refreshChromeAfterLoad() {
    if (typeof core.configureBottomBar === "function") {
      core.configureBottomBar();
    }
    if (typeof core.refreshStatus === "function") {
      return core.refreshStatus();
    }
    return Promise.resolve();
  }

  function reloadCurrentViewNow() {
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("");
    }

    if (document.getElementById("artifact-root")) {
      if (typeof core.loadArtifact === "function") {
        return core.loadArtifact().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("stream-grid")) {
      if (typeof core.loadStream === "function") {
        return core.loadStream().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("table-grid")) {
      if (typeof core.loadTable === "function") {
        return core.loadTable().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("plot")) {
      if (typeof core.refreshPlot === "function") {
        return core.refreshPlot().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (typeof core.refreshStatus === "function") {
      return core.refreshStatus();
    }

    return Promise.resolve();
  }

  core.reloadCurrentView = function () {
    if (state.reloadCurrentViewPromise) {
      return state.reloadCurrentViewPromise;
    }

    if (document.hidden) {
      return Promise.resolve();
    }

    const refreshPromise = Promise.resolve().then(reloadCurrentViewNow);
    state.reloadCurrentViewPromise = refreshPromise;

    function clearInFlight() {
      if (state.reloadCurrentViewPromise === refreshPromise) {
        state.reloadCurrentViewPromise = null;
      }
    }

    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
  };

  core.bootstrap = function () {
    if (typeof core.bindStatusModal === "function") {
      core.bindStatusModal();
    }

    if (typeof core.bindHeaderStatus === "function") {
      core.bindHeaderStatus();
    }

    if (typeof core.bindViewDropdown === "function") {
      core.bindViewDropdown();
    }

    if (typeof core.bindHistoryControls === "function") {
      core.bindHistoryControls();
    }

    if (typeof core.bindBottomBar === "function") {
      core.bindBottomBar();
    }

    if (typeof core.bindAutoRefreshControls === "function") {
      core.bindAutoRefreshControls();
    }
    if (typeof core.bindUpdateNotifications === "function") {
      core.bindUpdateNotifications();
    }

    const loadHistoryPromise =
      typeof core.loadHistory === "function"
        ? core.loadHistory()
        : Promise.resolve();

    loadHistoryPromise
      .then(function () {
        if (typeof core.syncHistoryUi === "function") {
          core.syncHistoryUi();
        }
        return core.reloadCurrentView();
      })
      .then(function () {
        if (typeof core.markInitialViewLoaded === "function") core.markInitialViewLoaded();
        if (typeof core.markBrowserViewApplied === "function") {
          core.markBrowserViewApplied();
        }
        if (typeof core.showPendingSnapshotNotice === "function") {
          core.showPendingSnapshotNotice();
        }
      })
      .catch(function () {
        if (typeof core.markInitialViewLoaded === "function") core.markInitialViewLoaded();
        if (typeof core.refreshStatus === "function") {
          core.refreshStatus();
        }
      });
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof core.bootstrap === "function") {
      core.bootstrap();
    }
  });
})();

