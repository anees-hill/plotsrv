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
