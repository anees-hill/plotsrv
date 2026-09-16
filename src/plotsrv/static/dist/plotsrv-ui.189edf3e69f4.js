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

  core.uiImageUrl = function (url) {
    const images = (window.PLOTSRV_CONFIG || {}).ui_image_urls || {};
    return images[url] || url;
  };

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

  config.dashboardName = raw.dashboard_name || "default";
  config.activeViewId = raw.active_view_id || "default";
  config.kind = raw.kind || "none";
  config.tableViewMode = raw.table_view_mode || "rich";
  config.maxTableRowsSimple = raw.max_table_rows_simple || 200;
  config.maxTableRowsRich = raw.max_table_rows_rich || 1000;
  config.tablePlotMaxPoints = Number.isSafeInteger(raw.table_plot_max_points)
    ? Math.max(1, Math.min(25000, raw.table_plot_max_points))
    : 5000;
  config.showHeaderFreshness = raw.show_header_freshness !== false;
  config.showHeaderHistory = raw.show_header_history !== false;
  config.viewCatalogue = Array.isArray(raw.view_catalogue)
    ? raw.view_catalogue
    : [];
  config.featuredViews = Array.isArray(raw.featured_views)
    ? raw.featured_views
    : [];
  config.compactViews = Array.isArray(raw.compact_views)
    ? raw.compact_views
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
    stream: {
      historical: false,
      lifecycle: null,
      lastHeartbeatAt: null,
      sourceAvailable: null,
      continuityWarning: null,
    },
    snapshot: state.currentSnapshot
      ? { id: state.currentSnapshot, createdAt: null }
      : null,
  };
  state.headerStreamPendingStatus = null;
  state.headerStreamTransitionTimer = null;
  state.plotObjectUrl = null;
  state.reloadCurrentViewPromise = null;
  state.statusRefreshPromise = null;
  state.viewMenuRefreshPromise = null;
  state.viewMenuRevision = Number.isInteger(raw.view_menu_revision)
    ? raw.view_menu_revision
    : null;
  state.observedUpdateRevision = config.browserUpdateRevision;
  state.browserUpdateInstanceId = typeof raw.browser_update_instance_id === "string"
    ? raw.browser_update_instance_id : null;
  state.browserUpdateGeneration = 0;
  state.appliedUpdateRevision = config.browserUpdateRevision;
  state.pendingBrowserUpdate = null;
  state.browserUpdateSource = null;
  state.browserUpdateLastEventAt = null;
  state.browserUpdateWatchdogTimer = null;
  state.browserUpdateReconnectTimer = null;
  state.browserUpdateReconnectAttempt = 0;
  state.browserUpdateApplying = false;
  state.browserUpdateRetryTimer = null;
  state.browserUpdateRetryAttempt = 0;
  state.initialViewLoadComplete = false;
  state.initialViewLoadAttempted = false;
  state.initialViewLoadPromise = null;
  state.tabulatorInstance = null;
  state.tablePlotCapabilities = null;
  state.tablePlotSupportingCollapsed = null;
  state.tablePlotControlsCollapsed = null;
  state.streamTabulatorInstance = null;
  state.streamCursor = null;
  state.streamSessionId = null;
  state.streamHistoricalSessionId = null;
  // Pausing is deliberately browser-local and ephemeral. The server keeps
  // accepting records while this table holds its current presentation.
  state.streamPaused = false;
  state.streamPauseAvailable = false;
  state.streamControlsCollapsed = null;
  // Every stream-data request owns one generation. Starting a newer request,
  // or beginning a current/stored session transition, invalidates older
  // responses before they can mutate the table or browser checkpoint.
  state.streamLoadGeneration = 0;
  state.streamLoadController = null;
  state.streamLoadTimeoutTimer = null;
  state.streamTableMutationPromise = null;
  state.streamHistorySessions = [];
  state.streamHistoryCatalogPromise = null;
  state.streamHistoryCatalogViewId = null;
  state.streamHistoryCatalogRevision = null;
  state.streamHistoryCatalogRefreshRequested = false;
  state.streamHistoryCatalogRefreshTimer = null;
  state.streamHistoryControlData = null;
  state.streamInsightsOpen = false;
  state.streamInsightsTab = "since";
  state.streamInsightsReturnFocus = null;
  // A current/history session boundary must replace Tabulator data even when
  // the response's browser cursor happens to be valid for its own session.
  state.streamForceTableReplace = false;
  state.streamSchemaRevision = null;
  state.streamSummaryRevision = null;
  state.streamSummaryScopeKey = null;
  state.streamSummaryGeneration = 0;
  state.streamSummaryLoadPromise = null;
  state.streamSummaryLoadController = null;
  state.streamSummaryDesired = null;
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
   viewSelectorPinned: "plotsrv:v1:view_selector_pinned",
   theme: "plotsrv:v1:theme",
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
      return true;
    } catch (e) {
      return false
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
      style_preset: "auto",
      colour_enabled: true,
    };
  
    try {
      const raw = localStorage.getItem(core.getTextPrefsKey(viewId));
      if (!raw) {
        return {
          wrap_enabled: core.loadPref(core.storageKeys.textWrapEnabled, "0") === "1",
          reverse_enabled: false,
          style_preset: "auto",
          colour_enabled: true,
        };
      }
  
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;
  
      const allowedStyles = [
        "auto", "plain", "code", "http", "application", "timestamp", "syslog",
        "container", "test", "traceback", "keyvalue",
      ];
      const savedStyle =
        typeof parsed.style_preset === "string" &&
        allowedStyles.indexOf(parsed.style_preset) !== -1
          ? parsed.style_preset
          : parsed.colour_enabled === false
            ? "plain"
            : "auto";

      return {
        wrap_enabled:
          typeof parsed.wrap_enabled === "boolean"
            ? parsed.wrap_enabled
            : fallback.wrap_enabled,
        reverse_enabled:
          typeof parsed.reverse_enabled === "boolean"
            ? parsed.reverse_enabled
            : fallback.reverse_enabled,
        style_preset: savedStyle,
        colour_enabled: savedStyle !== "plain",
      };
    } catch (e) {
      return fallback;
    }
  };
  
  core.saveTextPrefs = function (viewId, prefs) {
    const allowedStyles = [
      "auto", "plain", "code", "http", "application", "timestamp", "syslog",
      "container", "test", "traceback", "keyvalue",
    ];
    const requestedStyle = prefs && prefs.style_preset;
    const stylePreset =
      typeof requestedStyle === "string" &&
      allowedStyles.indexOf(requestedStyle) !== -1
        ? requestedStyle
        : prefs && prefs.colour_enabled === false
          ? "plain"
          : "auto";

    const payload = {
      wrap_enabled: !!(prefs && prefs.wrap_enabled),
      reverse_enabled: !!(prefs && prefs.reverse_enabled),
      style_preset: stylePreset,
      // Retained so preferences still make sense to older PlotSrv assets.
      colour_enabled: stylePreset !== "plain",
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

/* plotsrv source: js/core/view_spec.js */
/* A bounded presentation contract shared by personal and future suggested views. */
(function () {
  "use strict";
  const core = window.PLOTSRV.core;
  const MAX_BYTES = 256 * 1024,
    MAX_ITEMS = 64,
    MAX_SPEC = 16 * 1024;
  const fail = (message) => {
    throw new Error(message);
  };
  const object = (value) =>
    value && typeof value === "object" && !Array.isArray(value);
  function keys(value, allowed) {
    if (
      !object(value) ||
      Object.keys(value).some((key) => !allowed.includes(key))
    )
      fail("Unsupported presentation settings.");
  }
  function text(value, limit, empty) {
    if (
      typeof value !== "string" ||
      value.length > limit ||
      (!empty && !value.length)
    )
      fail("Invalid presentation text.");
    return value;
  }
  function list(value, limit) {
    if (!Array.isArray(value) || value.length > limit)
      fail("Too many presentation settings.");
    return value;
  }
  const enums = {
    type: ["bar", "line", "scatter", "histogram", "time-count"],
    source: ["table", "summary"],
    aggregation: ["count", "sum", "mean", "min", "max"],
    bins: ["auto", "5", "10", "20", "40"],
    palette: [
      "plotsrv",
      "accessible",
      "http",
      "ocean",
      "forest",
      "sunset",
      "violet",
      "neutral",
      "viridis",
      "plasma",
      "blues",
      "ember",
    ],
    sort: ["value-desc", "value-asc", "category-asc", "category-desc"],
    display: ["grouped", "stacked"],
    xScale: ["linear", "log"],
    yScale: ["linear", "log"],
    legend: ["top", "right", "bottom"],
    titleAlign: ["left", "center"],
    pointSelection: ["refuse", "sample", "first", "latest"],
  };
  const plotFields = [
    "categoryField",
    "xField",
    "yField",
    "valueField",
    "histogramField",
    "seriesField",
  ];
  function validate(spec) {
    keys(spec, [
      "version",
      "sourceId",
      "name",
      "caption",
      "presentation",
      "requirements",
    ]);
    if (spec.version !== 1)
      fail(
        "This saved view version is not supported. It has not been changed.",
      );
    text(spec.sourceId, 512);
    text(spec.name, 80);
    text(spec.caption, 256, true);
    const p = spec.presentation;
    keys(p, [
      "search",
      "filters",
      "sort",
      "group",
      "columns",
      "hidden",
      "mode",
      "plot",
    ]);
    text(p.search, 1024, true);
    text(p.group, 256, true);
    [p.columns, p.hidden].forEach((value) =>
      list(value, 128).forEach((field) => text(field, 256)),
    );
    list(p.sort, 8).forEach((sort) => {
      keys(sort, ["field", "dir"]);
      text(sort.field, 256);
      if (!["asc", "desc"].includes(sort.dir)) fail("Invalid sort.");
    });
    list(p.filters, 10).forEach((filter) => {
      keys(filter, ["field", "op", "value", "valueTo"]);
      text(filter.field, 256);
      if (
        ![
          "contains",
          "eq",
          "neq",
          "in",
          "not_in",
          "missing",
          "not_missing",
          "lt",
          "lte",
          "gt",
          "gte",
          "between",
          "not_between",
        ].includes(filter.op)
      )
        fail("Unsupported filter.");
      text(filter.value, 2048, true);
      text(filter.valueTo, 2048, true);
      if (
        !["missing", "not_missing"].includes(filter.op) &&
        !filter.value.trim()
      )
        fail("Complete the filter before saving.");
      if (
        ["between", "not_between"].includes(filter.op) &&
        !filter.valueTo.trim()
      )
        fail("Complete the filter range before saving.");
    });
    if (!["table", "plot", "plot+data"].includes(p.mode))
      fail("Unsupported presentation mode.");
    keys(p.plot, [
      ...Object.keys(enums),
      ...plotFields,
      "title",
      "xLabel",
      "yLabel",
      "categoryLimit",
      "zeroBaseline",
      "showPoints",
    ]);
    for (const [key, value] of Object.entries(p.plot)) {
      if (enums[key]) {
        if (!enums[key].includes(value)) fail("Unsupported plot setting.");
      } else if (key === "categoryLimit") {
        if (![5, 10, 20, 40].includes(value)) fail("Invalid plot limit.");
      } else if (["zeroBaseline", "showPoints"].includes(key)) {
        if (typeof value !== "boolean") fail("Invalid plot setting.");
      } else text(value, 256, true);
    }
    if (!p.plot.type || !p.plot.source) fail("Missing plot specification.");
    keys(spec.requirements, ["fields", "plotFields", "plotSource", "capability"]);
    if (spec.requirements.capability !== undefined && spec.requirements.capability !== "observation-v1") fail("Unsupported source capability.");
    for (const requirements of [
      spec.requirements.fields,
      spec.requirements.plotFields,
    ]) {
      list(requirements, 128).forEach((field) => {
        keys(field, ["name", "type"]);
        text(field.name, 256);
        if (!["text", "number", "datetime", "unknown"].includes(field.type))
          fail("Invalid field requirement.");
      });
    }
    if (!["table", "summary"].includes(spec.requirements.plotSource))
      fail("Invalid plot source.");
    if (spec.requirements.plotSource !== p.plot.source)
      fail("Plot source requirement does not match the presentation.");
    const required = new Set(spec.requirements.fields.map((f) => f.name));
    if (
      p.filters.some((f) => !required.has(f.field)) ||
      p.sort.some((s) => !required.has(s.field)) ||
      (p.group && !required.has(p.group))
    )
      fail("Missing field requirements.");
    if (JSON.stringify(spec).length > MAX_SPEC)
      fail("This presentation is too large to save.");
    return JSON.parse(JSON.stringify(spec));
  }
  function compatible(spec, schema) {
    spec = validate(spec);
    const p = spec.presentation,
      notes = [],
      unsafe = [];
    if (spec.requirements.capability && !(schema.capabilities || []).includes(spec.requirements.capability)) unsafe.push("This source no longer provides observation evidence. The presentation is paused.");
    const expected = new Map(
      spec.requirements.fields.map((f) => [f.name, f.type]),
    );
    const expectedPlot = new Map(
      spec.requirements.plotFields.map((f) => [f.name, f.type]),
    );
    function valid(field, types, requirements) {
      return (
        Object.prototype.hasOwnProperty.call(types, field) &&
        (!requirements.has(field) ||
          requirements.get(field) === "unknown" ||
          types[field] === requirements.get(field))
      );
    }
    const okay = (field) => valid(field, schema.fields, expected);
    p.filters = p.filters.filter((filter) => {
      const numeric = schema.fields[filter.field] === "number";
      const numericOp = [
        "lt",
        "lte",
        "gt",
        "gte",
        "between",
        "not_between",
      ].includes(filter.op);
      const textOp = ["contains", "in", "not_in"].includes(filter.op);
      const badNumber =
        numeric &&
        !["missing", "not_missing"].includes(filter.op) &&
        (!Number.isFinite(Number(filter.value)) ||
          (["between", "not_between"].includes(filter.op) &&
            !Number.isFinite(Number(filter.valueTo))));
      if (
        okay(filter.field) &&
        (!numericOp || numeric) &&
        (!textOp || !numeric) &&
        !badNumber
      )
        return true;
      unsafe.push(
        "Filter on “" +
          filter.field +
          "” needs repair (missing field, changed type or invalid value).",
      );
      return false;
    });
    p.sort = p.sort.filter((sort) => {
      if (okay(sort.field)) return true;
      notes.push(
        "Sort field “" + sort.field + "” is unavailable or changed type.",
      );
      return false;
    });
    if (p.group && !okay(p.group)) {
      notes.push(
        "Grouping field “" + p.group + "” is unavailable or changed type.",
      );
      p.group = "";
    }
    ["columns", "hidden"].forEach((key) => {
      p[key] = p[key].filter((field) => {
        if (Object.prototype.hasOwnProperty.call(schema.fields, field))
          return true;
        notes.push("Column “" + field + "” is unavailable.");
        return false;
      });
    });
    const needed =
      p.plot.type === "bar"
        ? [
            "categoryField",
            ...(p.plot.aggregation === "count" ? [] : ["valueField"]),
          ]
        : p.plot.type === "histogram"
          ? ["histogramField"]
          : p.plot.type === "time-count"
            ? ["xField"]
            : ["xField", "yField"];
    if (p.plot.seriesField) needed.push("seriesField");
    const plotTypes =
      p.plot.source === "summary" ? schema.summary : schema.fields;
    const invalidPlot = needed.some((key) => {
      const field = p.plot[key],
        type = plotTypes[field];
      if (!valid(field, plotTypes, expectedPlot)) return true;
      if (["yField", "valueField", "histogramField"].includes(key))
        return type !== "number";
      if (key === "xField")
        return (
          (p.plot.type === "time-count"
            ? type !== "datetime"
            : !["number", "datetime"].includes(type)) ||
          (type === "datetime" && p.plot.xScale === "log")
        );
      return false;
    });
    if (
      p.mode !== "table" &&
      (!schema.sources.includes(p.plot.source) || invalidPlot)
    ) {
      unsafe.push(
        "The saved plot source or fields are unavailable or changed type; choose a compatible plot.",
      );
      p.mode = "table";
    }
    return { spec, notes: [...new Set(notes)], unsafe };
  }
  function namespace() {
    // Browser origin supplies host isolation; base path/name survive server restarts.
    const path = window.location.pathname.replace(/\/+$/, "") || "/";
    return (
      "plotsrv:v1:my_views:" +
      encodeURIComponent(path) +
      ":" +
      encodeURIComponent(window.PLOTSRV.config.dashboardName || "default")
    );
  }
  function read() {
    let raw;
    try {
      raw = localStorage.getItem(namespace());
    } catch (_) {
      return { items: [], error: "Browser storage is unavailable." };
    }
    if (!raw) return { items: [], error: null };
    if (raw.length > MAX_BYTES)
      return {
        items: [],
        error:
          "Saved views storage exceeds its safety limit. It has not been changed.",
      };
    try {
      const doc = JSON.parse(raw);
      keys(doc, ["version", "items"]);
      if (doc.version !== 1)
        fail(
          "Unsupported saved views version. Existing storage has not been changed.",
        );
      const ids = new Set();
      const items = list(doc.items, MAX_ITEMS).map((item) => {
        keys(item, ["id", "spec"]);
        text(item.id, 80);
        if (ids.has(item.id)) fail("Duplicate saved view.");
        ids.add(item.id);
        return { id: item.id, spec: validate(item.spec) };
      });
      return { items, error: null };
    } catch (error) {
      return { items: [], error: "Cannot load saved views: " + error.message };
    }
  }
  function write(item, remove, expected) {
    const loaded = read();
    if (loaded.error) fail(loaded.error);
    const old = loaded.items.find((value) => value.id === item.id);
    if (
      expected !== undefined &&
      JSON.stringify(old || null) !== JSON.stringify(expected)
    )
      fail("This view changed in another tab. Reopen it before updating.");
    const items = loaded.items.filter((value) => value.id !== item.id);
    if (!remove)
      items.push({ id: text(item.id, 80), spec: validate(item.spec) });
    const raw = JSON.stringify({ version: 1, items });
    if (items.length > MAX_ITEMS || raw.length > MAX_BYTES)
      fail(
        "My views is full. Delete a saved configuration before adding another.",
      );
    if (!core.savePref(namespace(), raw))
      fail("Unable to save: browser storage is disabled or full.");
    window.dispatchEvent(new Event("plotsrv-my-views-changed"));
    return item;
  }
  async function change(item, remove, expected) {
    const locks = window.navigator && window.navigator.locks;
    if (!locks) return write(item, remove, expected);
    // Do not queue clicks behind a busy tab. Stale updates still compare their
    // original saved value; new saves merge with the latest bounded catalogue.
    return locks.request(namespace(), { ifAvailable: true }, (lock) => {
      if (!lock)
        fail("My views is being saved in another tab. Please try again.");
      return write(item, remove, expected);
    });
  }
  core.viewSpec = {
    validate,
    compatible,
    namespace,
    read,
    write,
    change,
    plotFields,
  };
})();

/* plotsrv source: js/core/my_views.js */
(function () {
  "use strict";
  const { core, state, config } = window.PLOTSRV;
  const contract = core.viewSpec;
  if (new URL(window.location.href).searchParams.has("my_view"))
    state.myViewBlocked = true;
  let remountSpec = null,
    blockedSpec = null,
    selectedSpec = null;
  let active = null,
    baseline = null,
    lastSchema = null,
    applying = false,
    frame = null,
    requested = false;
  function schema() {
    return {
      capabilities: state.observationProfile ? ["observation-v1"] : [],
      fields: Object.assign({}, state.tableFieldTypes),
      summary: Object.assign({}, state.tablePlotSummaryFieldTypes),
      sources: (state.tablePlotCapabilities || { sources: ["table"] }).sources,
    };
  }
  function capture(name, caption, requirements) {
    const p = Object.assign(
      core.extractTablePresentation(),
      core.extractPlotPresentation(),
    );
    const current = requirements || schema();
    const used = new Set([
      ...p.columns,
      ...p.hidden,
      ...p.sort.map((s) => s.field),
      ...p.filters.map((f) => f.field),
    ]);
    if (p.group) used.add(p.group);
    return contract.validate({
      version: 1,
      sourceId: config.activeViewId,
      name: name == null ? "Untitled" : name,
      caption: caption || "",
      presentation: p,
      requirements: {
        fields: [...used].map((name) => ({
          name,
          type: current.fields[name] || "unknown",
        })),
        plotFields: [
          ...new Set(
            contract.plotFields.map((key) => p.plot[key]).filter(Boolean),
          ),
        ].map((name) => ({
          name,
          type:
            (p.plot.source === "summary" ? current.summary : current.fields)[
              name
            ] || "unknown",
        })),
        plotSource: p.plot.source,
        ...((current.capabilities || []).includes("observation-v1") ? {capability: "observation-v1"} : {}),
      },
    });
  }
  function meaningful(spec) {
    const p = JSON.parse(JSON.stringify(spec.presentation));
    // Column schema facts and inactive plot auto-selection are not user edits.
    if (p.mode === "table") p.plot = null;
    p.hidden.sort();
    p.filters.sort((a, b) =>
      JSON.stringify(a).localeCompare(JSON.stringify(b)),
    );
    return JSON.stringify(p);
  }
  function notice(message, repair) {
    const box = document.getElementById("my-view-notice");
    if (!box) return;
    box.replaceChildren();
    box.hidden = !message;
    if (!message) return;
    const copy = document.createElement("span");
    copy.textContent = message;
    box.appendChild(copy);
    if (repair) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ps-btn";
      button.textContent = "Repair presentation";
      button.addEventListener("click", function () {
        if (
          !window.confirm(
            "Apply compatible settings? Unavailable filters may be removed and more rows may be shown. The saved view will not be changed.",
          )
        )
          return;
        active = null;
        blockedSpec = selectedSpec = null;
        state.myViewBlocked = false;
        clearSelection();
        apply(repair.spec).then(() =>
          notice(
            "Compatible settings applied. Review filters and plot fields, then save as a new view. " +
              repair.notes.join(" "),
          ),
        );
      });
      box.appendChild(button);
    }
  }
  function clearSelection() {
    const url = new URL(window.location.href);
    url.searchParams.delete("my_view");
    window.history.replaceState(null, "", url);
  }
  function refresh() {
    if (core.syncViewExplanation) core.syncViewExplanation();
    frame = null;
    const button = document.getElementById("table-save-view-btn");
    if (!button || !baseline || applying) return;
    try {
      button.disabled =
        state.myViewBlocked || meaningful(capture()) === meaningful(baseline);
      button.textContent = "Save view";
      button.title = button.disabled
        ? "Change table or plot settings to save a presentation"
        : "Save presentation settings on this browser";
    } catch (error) {
      button.disabled = true;
      button.title = error.message;
    }
  }
  core.presentationChanged = function () {
    if (applying || frame !== null) return;
    frame = window.requestAnimationFrame(refresh);
  };
  async function apply(spec) {
    applying = true;
    const owner = state.tabulatorInstance;
    try {
      await core.applyTablePresentation(spec.presentation);
      if (state.tabulatorInstance === owner)
        core.applyPlotPresentation(spec.presentation);
    } catch (error) {
      if (state.tabulatorInstance === owner) throw error;
    } finally {
      applying = false;
      core.presentationChanged();
      if (remountSpec) core.mountPersonalViews();
    }
  }
  async function present(spec, item) {
    if (spec.sourceId !== config.activeViewId) {
      state.myViewBlocked = true;
      notice(
        "This saved presentation belongs to a different source. Open it from My views.",
      );
      return;
    }
    const result = contract.compatible(spec, schema());
    active = item;
    selectedSpec = spec;
    if (item && core.clearHttpSuggestionSelection) core.clearHttpSuggestionSelection();
    if (core.syncViewExplanation) core.syncViewExplanation();
    if (item) baseline = item.spec;
    if (result.unsafe.length) {
      blockedSpec = spec;
      state.myViewBlocked = true;
      await apply(result.spec);
      notice(
        "“" + spec.name + "” is paused. " + result.unsafe.join(" "),
        result,
      );
      return;
    }
    blockedSpec = null;
    state.myViewBlocked = false;
    await apply(result.spec);
    notice(
      (item ? "My view: " : "Presentation: ") +
        spec.name +
        (spec.caption ? " — " + spec.caption : "") +
        ". " +
        result.notes.join(" "),
    );
  }
  function select(item) {
    return present(item.spec, item);
  }
  core.applyViewSpec = function (spec) {
    requested = true;
    clearSelection();
    return present(spec, null);
  };
  core.checkPersonalViewSchema = function () {
    if (!selectedSpec || !lastSchema) return;
    const currentSchema = schema();
    if (JSON.stringify(currentSchema) === JSON.stringify(lastSchema)) return;
    try {
      const working =
        remountSpec ||
        blockedSpec ||
        capture(selectedSpec.name, selectedSpec.caption, lastSchema);
      const result = contract.compatible(working, currentSchema);
      if (result.unsafe.length) {
        blockedSpec = working;
        state.myViewBlocked = true;
        notice(
          "“" + selectedSpec.name + "” is paused. " + result.unsafe.join(" "),
          result,
        );
      } else if (result.notes.length)
        notice(
          (active ? "My view: " : "Presentation: ") +
            selectedSpec.name +
            ". " +
            result.notes.join(" "),
        );
    } catch (error) {
      state.myViewBlocked = true;
      notice(error.message);
    }
  };
  function saveDialog() {
    const opener = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.className = "ps-my-view-dialog";
    dialog.setAttribute("aria-labelledby", "my-view-dialog-title");
    const form = document.createElement("form");
    const title = document.createElement("h2");
    title.id = "my-view-dialog-title";
    title.textContent = active
      ? "Save presentation changes"
      : "Add to My views";
    form.appendChild(title);
    const explanation = document.createElement("p");
    explanation.textContent =
      "This view is saved only in your browser and is not shared with other dashboard users or sent to the server. Anyone using this browser profile can see it. It saves presentation settings for the source’s latest data. It does not save data, a historical snapshot or a stream session. Clearing browser storage removes these settings.";
    form.appendChild(explanation);
    function field(labelText, value, maximum, required) {
      const label = document.createElement("label");
      label.textContent = labelText;
      const input = document.createElement("input");
      input.name = labelText.toLowerCase();
      input.value = value;
      input.maxLength = maximum;
      input.required = required;
      label.appendChild(input);
      form.appendChild(label);
      return input;
    }
    const name = field(
      "Name",
      active ? active.spec.name : selectedSpec ? selectedSpec.name : "",
      80,
      true,
    );
    const caption = field(
      "Caption",
      active ? active.spec.caption : selectedSpec ? selectedSpec.caption : "",
      256,
      false,
    );
    const errorBox = document.createElement("p");
    errorBox.setAttribute("role", "alert");
    form.appendChild(errorBox);
    function close() {
      dialog.close();
      dialog.remove();
      if (opener && opener.isConnected) opener.focus();
    }
    async function save(update) {
      if (form.dataset.saving || !form.reportValidity()) return;
      form.dataset.saving = "1";
      try {
        if (state.myViewBlocked)
          throw new Error(
            "Repair the incompatible presentation before saving.",
          );
        const spec = capture(name.value.trim(), caption.value.trim());
        const item = {
          id: update
            ? active.id
            : window.crypto.randomUUID
              ? window.crypto.randomUUID()
              : Date.now().toString(36) + Math.random().toString(36).slice(2),
          spec,
        };
        await contract.change(item, false, update ? active : undefined);
        active = item;
        selectedSpec = spec;
        if (core.syncViewExplanation) core.syncViewExplanation();
        baseline = spec;
        requested = true;
        const url = new URL(window.location.href);
        url.searchParams.set("my_view", item.id);
        window.history.replaceState(null, "", url);
        close();
        notice("My view: " + spec.name + ". Saved on this browser.");
        refresh();
      } catch (error) {
        errorBox.textContent = error.message;
      } finally {
        delete form.dataset.saving;
      }
    }
    const buttons = document.createElement("div");
    buttons.className = "ps-my-view-dialog__actions";
    function button(label, action) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ps-btn";
      b.textContent = label;
      b.addEventListener("click", action);
      buttons.appendChild(b);
    }
    button("Cancel", close);
    if (active) button("Save as new", () => save(false));
    button(active ? "Update" : "Save view", () => save(!!active));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      save(!!active);
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close();
    });
    form.appendChild(buttons);
    dialog.appendChild(form);
    document.body.appendChild(dialog);
    dialog.showModal();
    name.focus();
  }
  core.capturePersonalBeforeRemount = function () {
    if (!baseline || !state.tabulatorInstance) return;
    try {
      remountSpec =
        blockedSpec ||
        capture(
          selectedSpec ? selectedSpec.name : "Untitled",
          selectedSpec ? selectedSpec.caption : "",
          lastSchema,
        );
    } catch (error) {
      notice(error.message);
    }
  };
  core.mountPersonalViews = function () {
    const unavailable = document.getElementById("my-view-unavailable");
    if (unavailable) unavailable.remove();
    const table = state.tabulatorInstance,
      button = document.getElementById("table-save-view-btn");
    if (!table || !button || table.initialized === false) return;
    if (!button.dataset.personalBound) {
      button.dataset.personalBound = "1";
      button.addEventListener("click", saveDialog);
    }
    if (!table._personalBound && table.on) {
      table._personalBound = true;
      ["dataSorted", "columnMoved", "columnVisibilityChanged"].forEach(
        (event) => table.on(event, core.presentationChanged),
      );
    }
    try {
      if (!baseline && state.observationProfile && !new URL(window.location.href).searchParams.has("my_view")) {
        baseline = state.observationProfile.recipes[0];
        selectedSpec = baseline;
        requested = true;
        lastSchema = schema();
        apply(baseline).then(function () {
          if (core.setTableFiltersOpen) core.setTableFiltersOpen(false);
          baseline = capture(baseline.name, baseline.caption);
          selectedSpec = baseline;
          core.presentationChanged();
        }).catch(error => notice(error.message));
        return;
      }
      if (!baseline) baseline = capture();
    } catch (error) {
      notice(error.message);
      return;
    }
    lastSchema = schema();
    if (remountSpec && !applying) {
      const pending = remountSpec;
      remountSpec = null;
      const result = contract.compatible(pending, lastSchema);
      blockedSpec = result.unsafe.length ? pending : null;
      state.myViewBlocked = !!blockedSpec;
      apply(result.spec)
        .then(function () {
          if (result.unsafe.length)
            notice(
              "“" + pending.name + "” is paused. " + result.unsafe.join(" "),
              result,
            );
        })
        .catch((error) => {
          state.myViewBlocked = true;
          notice(error.message);
        });
    }
    if (!requested) {
      requested = true;
      const id = new URL(window.location.href).searchParams.get("my_view");
      const loaded = contract.read();
      const item = loaded.items.find((value) => value.id === id);
      if (item)
        select(item).catch((error) => {
          state.myViewBlocked = true;
          notice(error.message);
        });
      else if (id || loaded.error) {
        state.myViewBlocked = false;
        notice(
          loaded.error ||
            "This saved view is missing on this browser. Showing the ordinary source.",
        );
        apply(baseline).catch((error) => notice(error.message));
      }
    }
    refresh();
  };
  core.resetPersonalView = function () {
    if (active && !state.myViewBlocked) {
      select(active).catch((error) => notice(error.message));
      return true;
    }
    active = null;
    blockedSpec = remountSpec = selectedSpec = null;
    if (core.clearHttpSuggestionSelection) core.clearHttpSuggestionSelection();
    if (core.syncViewExplanation) core.syncViewExplanation();
    state.myViewBlocked = false;
    requested = true;
    clearSelection();
    notice("");
    if (core.resetPlotPresentation) core.resetPlotPresentation();
    core.presentationChanged();
  };
  core.personalViewUrl = function (item) {
    const url = new URL(window.location.href);
    url.search = "";
    url.hash = "";
    url.searchParams.set("view", item.spec.sourceId);
    url.searchParams.set("my_view", item.id);
    return url.href;
  };
  core.deletePersonalView = async function (item) {
    if (
      !window.confirm(
        "Delete “" +
          item.spec.name +
          "”? This deletes only the saved configuration on this browser. Source data is not deleted.",
      )
    )
      return false;
    try {
      await contract.change(item, true, item);
      if (active && active.id === item.id) {
        active = null;
        selectedSpec = null;
        clearSelection();
        notice("Saved configuration deleted; current working settings remain.");
        core.presentationChanged();
      }
      return true;
    } catch (error) {
      window.alert(error.message);
      return false;
    }
  };
  window.addEventListener("storage", (event) => {
    if (event.key !== null && event.key !== contract.namespace()) return;
    window.dispatchEvent(new Event("plotsrv-my-views-changed"));
    if (active)
      notice(
        "My views changed in another tab. Your working presentation is unchanged; reopen the saved view before updating it.",
      );
  });
  core.checkPersonalViewSurface = function () {
    const id = new URL(window.location.href).searchParams.get("my_view");
    if (!id || state.tabulatorInstance) return;
    let box = document.getElementById("my-view-unavailable");
    if (!box) {
      box = document.createElement("p");
      box.id = "my-view-unavailable";
      box.setAttribute("role", "status");
      const header = document.getElementById("site-header");
      if (header) header.after(box);
      else document.body.prepend(box);
    }
    box.textContent =
      "This saved presentation cannot be applied: the source has no adjustable table or plot surface. The saved configuration is unchanged; open My views to manage it.";
  };
  core.captureViewSpec = capture;
  core.getPresentationExplanation = () => selectedSpec ? {caption: selectedSpec.caption, origin: active ? "My view caption (saved on this browser)" : "Suggested presentation"} : null;
  core.applyPersonalView = select;
})();

/* plotsrv source: js/core/view_explanation.js */
(function () {
  "use strict";
  const {core, state, config} = window.PLOTSRV;
  const text = value => typeof value === "string" ? value.slice(0, 512).trim() : "";
  function sync() {
    const about = document.getElementById("view-about");
    if (!about) return;
    const source = (config.viewCatalogue || []).find(view => view.view_id === config.activeViewId);
    const presentation = core.getPresentationExplanation ? core.getPresentationExplanation() : null;
    const featured = (config.featuredViews || []).find(view => (view.view_id || view.view) === config.activeViewId);
    const caption = presentation ? text(presentation.caption) || text(source && source.description)
      : text(featured && featured.caption) || text(source && source.description);
    const origin = presentation && text(presentation.caption) ? presentation.origin
      : !presentation && text(featured && featured.caption) ? "Featured presentation" : "Source description";
    const historical = state.currentSnapshot || state.compareCapture || state.streamHistoricalSessionId;
    const scope = historical ? "Current description and presentation settings; not stored with the inspected version." : origin;
    if (!caption) {
      if (about.contains(document.activeElement)) {
        const target = document.querySelector('.ps-viewselect__btn') || document.getElementById('header-status-button');
        if (target) target.focus();
      }
      about.open = false;
    }
    about.hidden = !caption;
    for (const [id, value] of [["view-about-text", caption], ["view-about-scope", scope]]) {
      const node = document.getElementById(id);
      if (node.textContent !== value) node.textContent = value;
    }
  }
  function bind() {
    const about = document.getElementById("view-about");
    if (!about || about.dataset.bound) return;
    about.dataset.bound = "1";
    const close = () => {about.open = false; about.querySelector('summary').focus();};
    about.querySelector('button').addEventListener('click', close);
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && about.open) {event.preventDefault(); close();}
    });
    sync();
  }
  core.syncViewExplanation = sync;
  core.bindViewExplanation = bind;
})();

/* plotsrv source: js/core/http_suggestions.js */
/* Optional server-generated presentations of the existing stream source. */
(function () {
  "use strict";
  const { core, state, config } = window.PLOTSRV;
  const derived = new WeakMap();
  let profile = null,
    rawColumns = [],
    opening = false,
    selectedName = null;
  core.tableFieldLabel = function (field) {
    const labels = (state.observationProfile && state.observationProfile.labels) || (state.httpProfile && state.httpProfile.labels) || {};
    return Object.prototype.hasOwnProperty.call(labels, field)
      ? labels[field]
      : field;
  };
  async function open(spec, suggestionName = null) {
    if (opening) return;
    opening = true;
    core.mountHttpSuggestions();
    let errorMessage = null;
    try {
      await core.applyViewSpec(spec);
      selectedName = suggestionName;
    } catch (error) {
      errorMessage = "Presentation unavailable: " + error.message;
    } finally {
      opening = false;
      core.mountHttpSuggestions();
    }
    if (errorMessage)
      document.getElementById("http-suggestions-scope").textContent =
        errorMessage;
  }
  core.clearHttpSuggestionSelection = function () {
    selectedName = null;
    if (document.getElementById("http-suggestions")) core.mountHttpSuggestions();
  };
  core.prepareHttpSuggestions = function (data) {
    rawColumns = data.columns.slice();
    profile =
      data.http_profile && data.http_profile.version === 1
        ? data.http_profile
        : null;
    state.httpProfile = profile;
    const fields = Object.values((profile && profile.fields) || {});
    const allowed = new Set(fields);
    data.columns = rawColumns.concat(fields);
    for (const record of data.records) {
      if (!record.http_projection || !fields.length) continue;
      const row = Object.assign(Object.create(null), record.data),
        keys = [];
      for (const [role, key] of Object.entries(profile.fields)) {
        if (
          Object.prototype.hasOwnProperty.call(record.http_projection, role) &&
          !Object.prototype.hasOwnProperty.call(row, key)
        ) {
          row[key] = record.http_projection[role];
          keys.push(key);
        }
      }
      derived.set(row, keys);
      record.data = row;
    }
    // Only previously generated cells are removed; source keys remain untouched.
    core.expireHttpProjection = function (row, sequence) {
      let changed = false;
      for (const key of derived.get(row) || []) {
        if (
          (!allowed.has(key) || sequence < profile.first_sequence) &&
          Object.prototype.hasOwnProperty.call(row, key)
        ) {
          delete row[key];
          changed = true;
        }
      }
      return changed;
    };
    core.mountHttpSuggestions();
  };
  core.mountHttpSuggestions = function () {
    const save = document.getElementById("table-save-view-btn");
    if (!save) return;
    let area = document.getElementById("http-suggestions");
    if (!area) {
      save.closest(".ps-table-topbar")?.classList.add("ps-http-topbar");
      area = document.createElement("span");
      area.id = "http-suggestions";
      area.className = "ps-http-suggestions";
      const select = document.createElement("select");
      select.id = "http-suggestions-select";
      select.className = "ps-table-select";
      select.setAttribute("aria-label", "Suggested views");
      select.addEventListener("change", async function () {
        if (select.value === "") return;
        const chosen = ((profile && profile.recipes) || [])[
          Number(select.value)
        ];
        if (chosen) await open(chosen, chosen.name);
      });
      const raw = document.createElement("button");
      raw.type = "button";
      raw.className = "ps-btn";
      raw.id = "http-raw-view";
      raw.textContent = "Raw stream";
      raw.addEventListener("click", async function () {
        const spec = {
          version: 1,
          sourceId: config.activeViewId,
          name: "Raw stream",
          caption:
            "Original accepted records, including unknown text and tracebacks.",
          presentation: {
            search: "",
            filters: [],
            sort: [],
            group: "",
            columns: [],
            hidden: Object.values((profile && profile.fields) || {}),
            mode: "table",
            plot: { type: "bar", source: "table" },
          },
          requirements: { fields: [], plotFields: [], plotSource: "table" },
        };
        await open(spec);
      });
      area.append(select, raw);
      save.parentElement.before(area);
      const note = document.createElement("p");
      note.id = "http-suggestions-scope";
      note.className = "ps-http-scope";
      save.closest(".ps-table-toolbar")?.append(note);
      if (!note.parentElement) area.parentElement.after(note);
    }
    const recipes = (profile && profile.recipes) || [];
    const select = area.querySelector("select");
    const signature = JSON.stringify(recipes.map((r) => r.name));
    // Keep keyboard focus/open native menus stable across ordinary appends.
    if (select.dataset.signature !== signature) {
      select.replaceChildren(new Option("Suggested views", ""));
      select.options[0].disabled = true;
      recipes.forEach((recipe, index) =>
        select.add(new Option(recipe.name, String(index))),
      );
      select.dataset.signature = signature;
    }
    // This is the chosen starting presentation, even after manual edits.
    // Match by name because available recipes can change order as data arrives.
    if (!opening) {
      const selected = recipes.findIndex(recipe => recipe.name === selectedName);
      const value = selected < 0 ? "" : String(selected);
      if (select.value !== value) select.value = value;
    }
    select.disabled = opening || !recipes.length;
    area.querySelector("button").disabled = opening;
    select.title = recipes.length
      ? "Choose a starting presentation; its name stays selected when you customise the settings"
      : (profile && profile.unavailable) || "No HTTP suggestions available";
    const message = profile
      ? recipes.length
        ? profile.scope +
          " Endpoint activity shares one plot; filter an endpoint to focus. Time buckets use half-open UTC intervals."
        : profile.unavailable
      : "No HTTP suggestions available from this server.";
    const note = document.getElementById("http-suggestions-scope");
    if (note.textContent !== message) note.textContent = message;
  };
})();

/* plotsrv source: js/core/settings.js */
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const THEMES = ["light", "dark", "system"];
  let returnFocus = null;

  function normalizeTheme(value) {
    const theme = String(value || "").toLowerCase();
    return THEMES.indexOf(theme) >= 0 ? theme : "light";
  }

  function currentTheme() {
    const stored = typeof core.loadPref === "function"
      ? core.loadPref(core.storageKeys.theme, "light")
      : "light";
    return normalizeTheme(stored);
  }

  function updateThemeControls(theme) {
    document.querySelectorAll("[data-theme-option]").forEach(function (button) {
      const selected = button.getAttribute("data-theme-option") === theme;
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
  }

  function applyTheme(value, options) {
    const theme = normalizeTheme(value);
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    root.style.colorScheme = theme === "system" ? "light dark" : theme;
    updateThemeControls(theme);

    if (!options || options.persist !== false) {
      if (typeof core.savePref === "function") {
        core.savePref(core.storageKeys.theme, theme);
      }
    }

    window.dispatchEvent(new CustomEvent("plotsrv:themechange", {
      detail: {theme: theme},
    }));
    return theme;
  }

  function focusableElements(page) {
    return Array.from(
      page.querySelectorAll(
        "button:not([disabled]):not([hidden]), [href], " +
          "input:not([disabled]), select:not([disabled]), " +
          "textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
      )
    ).filter(function (element) {
      return !element.closest("[hidden]");
    });
  }

  function syncSettingsHeaderHeight() {
    const header = document.getElementById("site-header");
    const page = document.getElementById("settings-page");
    const trigger = document.getElementById("settings-button");
    if (header && page && !page.hidden) {
      page.style.setProperty("--ps-settings-header-height", header.getBoundingClientRect().height + "px");
      page.style.setProperty("--ps-settings-header-padding", window.getComputedStyle(header).padding);
      if (trigger) {
        const triggerRect = trigger.getBoundingClientRect();
        page.style.setProperty("--ps-settings-close-top", triggerRect.top + "px");
        page.style.setProperty("--ps-settings-close-right", (window.innerWidth - triggerRect.right) + "px");
      }
    }
  }

  function openSettings() {
    const page = document.getElementById("settings-page");
    const trigger = document.getElementById("settings-button");
    const close = document.getElementById("settings-close");
    if (!page) return;

    returnFocus = document.activeElement;
    updateThemeControls(normalizeTheme(
      document.documentElement.getAttribute("data-theme") || currentTheme()
    ));
    page.hidden = false;
    syncSettingsHeaderHeight();
    if (document.body) document.body.classList.add("ps-settings-open");
    if (trigger) trigger.setAttribute("aria-expanded", "true");
    if (close) close.focus();
    else page.focus();
  }

  function closeSettings(options) {
    const page = document.getElementById("settings-page");
    const trigger = document.getElementById("settings-button");
    if (!page || page.hidden) return;

    page.hidden = true;
    if (document.body) document.body.classList.remove("ps-settings-open");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    if (!options || options.restoreFocus !== false) {
      if (returnFocus && typeof returnFocus.focus === "function") returnFocus.focus();
      else if (trigger) trigger.focus();
    }
  }

  function bindSettings() {
    const page = document.getElementById("settings-page");
    const trigger = document.getElementById("settings-button");
    const close = document.getElementById("settings-close");
    if (!page || !trigger || page.dataset.plotsrvBound === "1") return;

    applyTheme(currentTheme(), {persist: false});
    const header = document.getElementById("site-header");
    if (header && typeof ResizeObserver === "function") {
      new ResizeObserver(syncSettingsHeaderHeight).observe(header);
    } else {
      window.addEventListener("resize", syncSettingsHeaderHeight);
    }
    trigger.addEventListener("click", openSettings);
    if (close) close.addEventListener("click", closeSettings);
    page.querySelectorAll("[data-theme-option]").forEach(function (button) {
      button.addEventListener("click", function () {
        applyTheme(button.getAttribute("data-theme-option"));
      });
    });

    page.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSettings();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = focusableElements(page);
      if (!focusable.length) {
        event.preventDefault();
        page.focus();
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

    page.dataset.plotsrvBound = "1";
  }

  core.normalizeTheme = normalizeTheme;
  core.currentTheme = currentTheme;
  core.applyTheme = applyTheme;
  core.openSettings = openSettings;
  core.closeSettings = closeSettings;
  core.bindSettings = bindSettings;
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

  // Shared by toolbar and future focus/Compare surfaces. No DOM is required
  // to fetch metadata, choose a version, or protect an asynchronous selection.
  const navigation = state.snapshotNavigation = {
    metadata: null, viewId: config.activeViewId, loading: false, pending: false, loadingVisible: false, error: "",
    displayed: state.currentSnapshot || null, revision: 0,
  };
  let historyController = null;
  let historyRequest = 0;
  let selectionPromise = null;
  let loadingNoticeTimer = null;
  let bannerSnapshot = null;
  let bannerDismissed = false;

  function clearLoadingNotice() {
    if (loadingNoticeTimer !== null) window.clearTimeout(loadingNoticeTimer);
    loadingNoticeTimer = null;
    navigation.loadingVisible = false;
  }

  const bodyLoads = new Map(); // At most one each: artifact, table, plot.

  function beginSnapshotLoad(kind) {
    const previous = bodyLoads.get(kind);
    if (previous) previous.abort();
    const controller = new AbortController();
    bodyLoads.set(kind, controller);
    const view = config.activeViewId;
    const query = snapshotQuery();
    const revision = navigation.revision;
    const timer = window.setTimeout(() => controller.abort(), 10000);
    return {
      signal: controller.signal,
      current: () => bodyLoads.get(kind) === controller &&
        view === config.activeViewId && query === snapshotQuery() &&
        revision === navigation.revision,
      finish: () => {
        window.clearTimeout(timer);
        if (bodyLoads.get(kind) === controller) bodyLoads.delete(kind);
      },
    };
  }

  function preciseTimestamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || "") :
      (/(Z|\+00:00)$/.test(String(value)) ? String(value) : date.toISOString()) + " (UTC)";
  }

  function snapshotLabel(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || "") : date.toLocaleString([], {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  }

  function announce(message) {
    const notice = document.getElementById("snapshot-navigation-notice");
    if (notice) notice.textContent = message;
  }

  function syncNavigation() {
    const metadata = navigation.metadata;
    const usable = navigation.viewId === config.activeViewId && !!metadata && !!state.snapshotCapability &&
      state.snapshotCapability.enabled === true && config.kind !== "stream";
    for (const direction of ["older", "newer"]) {
      const button = document.getElementById("snapshot-" + direction);
      if (!button) continue;
      button.hidden = !usable;
      const target = metadata && metadata[direction];
      const latest = direction === "newer" && !!state.currentSnapshot;
      button.disabled = navigation.loading || !usable || (!target && !latest);
      button.title = target ? (direction === "older" ? "Older: " : "Newer: ") +
        preciseTimestamp(target.created_at) : latest ? "Return to Latest (current server state)" :
        direction === "older" ? "No older snapshot" : "Already at Latest";
    }
    const exportButton = document.getElementById("export-button");
    if (exportButton) exportButton.disabled = navigation.pending || !!navigation.error;
    if (navigation.pending && core.closeExportMenu) core.closeExportMenu();
    if (core.syncCompare) core.syncCompare();
  }

  function selectionFailed(message) {
    clearLoadingNotice();
    if (!navigation.pending && !state.currentSnapshot) {
      if (core.setStatusMessage) core.setStatusMessage(core.escapeHtml(message));
      return; // Ordinary Live failures remain eligible for a later live update.
    }
    navigation.error = message + " Previous content is retained where available; it is not the selected version. Choose another snapshot or Latest explicitly.";
    announce(navigation.error);
    syncNavigation();
  }

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
    if (!state.currentSnapshot || navigation.viewId !== config.activeViewId) return null;

    for (const item of state.historyItems || []) {
      if (item.snapshot_id === state.currentSnapshot) {
        return item;
      }
    }
    const selected = navigation.metadata && navigation.metadata.selected;
    return selected && selected.snapshot_id === state.currentSnapshot ? selected : null;
  }

  function syncSnapshotModeBanner() {
    const banner = document.getElementById("snapshot-mode-banner");
    if (!banner) return;
    const snapshot = state.currentSnapshot || null;
    if (snapshot !== bannerSnapshot) {
      bannerSnapshot = snapshot;
      bannerDismissed = false;
    }
    banner.hidden = !snapshot || bannerDismissed;
    if (!snapshot) return;
    const meta = currentHistoryMeta();
    const time = document.getElementById("snapshot-mode-banner-time");
    if (time) {
      time.textContent = meta && meta.created_at
        ? snapshotLabel(meta.created_at)
        : "Snapshot " + snapshot;
    }
  }

  function syncHistoryUi() {
    if (core.syncViewExplanation) core.syncViewExplanation();
    syncNavigation();
    const sel = document.getElementById("history-select");
    const isHistory = isHistoryMode();
    const pinned = core.inspectionCapture && core.inspectionCapture();

    if (sel) {
      sel.value = state.currentSnapshot || "";
    }

    const unavailableReturn = document.getElementById("snapshots-return-latest");
    if (unavailableReturn) {
      unavailableReturn.hidden = !isHistory && !pinned && !navigation.error;
    }
    syncSnapshotModeBanner();

    if (typeof core.setHeaderViewState === "function") {
      const meta = currentHistoryMeta();
      core.setHeaderViewState(
        isHistory ? "snapshot" : pinned ? "captured" : "latest",
        isHistory
          ? {
              id: state.currentSnapshot,
              createdAt: meta && meta.created_at ? meta.created_at : null,
            }
          : pinned ? {id: "Latest captured r" + pinned.revision, createdAt: pinned.created_at} : null
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
    const sel = document.getElementById("history-select");
    if (!wrap || !selector || !sel) return;

    const usable = !failed && (!capability || capability.enabled === true);
    const hasSnapshots = usable && snapshots.length > 0;
    const availabilityReason = failed
      ? "Snapshot availability could not be loaded."
      : !usable
        ? String(
            (capability && capability.message) ||
              "Snapshots are unavailable for this view."
          )
        : !hasSnapshots
          ? "No snapshots have been saved for this view yet."
          : "";

    const reason = availabilityReason
      ? "Snapshots let you browse saved versions of this view. " + availabilityReason
      : "Browse saved versions of this view.";

    wrap.dataset.state = failed
      ? "error"
      : hasSnapshots
        ? "enabled"
        : usable
          ? "empty"
          : "unavailable";
    selector.hidden = false;
    wrap.title = reason;
    selector.title = reason;
    sel.title = reason;
    sel.setAttribute("aria-label", reason ? "Snapshots. " + reason : "Snapshots");
    sel.disabled = !hasSnapshots;
  }

  async function loadHistory(before) {
    if (config.kind === "stream") return;
    const sel = document.getElementById("history-select");
    const view = config.activeViewId;
    const selected = state.currentSnapshot;
    const request = ++historyRequest;
    if (historyController) historyController.abort();
    const controller = new AbortController();
    historyController = controller;
    const timer = window.setTimeout(() => controller.abort(), 10000);
    const current = () => request === historyRequest && view === config.activeViewId &&
      selected === state.currentSnapshot;
    navigation.loading = true;
    syncNavigation();
    try {
      const res = await fetch(
        "/history/navigation?limit=50&view=" +
          encodeURIComponent(view) +
          (selected ? "&selected=" + encodeURIComponent(selected) : "") +
          (before ? "&before=" + encodeURIComponent(before) : "") +
          "&_ts=" + Date.now(), {signal: controller.signal}
      );
      if (!res.ok) throw new Error("history fetch failed");

      const data = await res.json();
      if (!current()) return;
      navigation.metadata = data;
      navigation.viewId = view;
      const snapshots = Array.isArray(data.snapshots) ? data.snapshots.slice(0, 50) : [];
      const capability =
        data.capability && typeof data.capability === "object"
          ? data.capability
          : null;
      state.historyItems = snapshots;
      state.snapshotCapability = capability;

      if (!sel) return;
      const parts = [];

      if (snapshots.length === 0) {
        parts.push('<option value="">No snapshots yet</option>');
      } else {
        parts.push('<option value="">Live (latest)</option>');
        for (const snap of snapshots) {
          // Latest follows the server; keep a stored latest entry only when selected.
          if ((snap.is_latest || snap.is_live_equivalent) && snap.snapshot_id !== state.currentSnapshot) continue;
          const ts = snapshotLabel(snap.created_at || snap.snapshot_id);
          const label = (snap.is_latest ? "Newest · " : "") + ts +
            (snap.is_live_equivalent ? " · Same revision as Live" : "");

          const kind = snap.kind ? " · " + core.escapeHtml(snap.kind) : "";
          
          parts.push(
            '<option value="' +
              core.escapeHtml(snap.snapshot_id) +
              '" title="' + core.escapeHtml(preciseTimestamp(snap.created_at || snap.snapshot_id)) + '">' +
              core.escapeHtml(label) +
              kind +
              "</option>"
          );
        }
      }

      sel.innerHTML = parts.join("");
      if (data.selected && !snapshots.some(x => x.snapshot_id === data.selected.snapshot_id)) {
        const option = new Option(snapshotLabel(data.selected.created_at), data.selected.snapshot_id);
        option.title = preciseTimestamp(data.selected.created_at);
        sel.append(option);
      }
      if (data.next_cursor) sel.append(new Option("Older snapshots…", "__older_page__"));
      if (before) sel.append(new Option("Newest snapshots…", "__newest_page__"));

      if (state.currentSnapshot) {
        const exists = snapshots.some(function (x) {
          return x.snapshot_id === state.currentSnapshot;
        });
        if (!exists && !data.selected) {
          const missingSnapshot = state.currentSnapshot;
          sel.append(new Option("Unavailable snapshot · " + missingSnapshot, missingSnapshot));
          state.pendingSnapshotNotice =
            '<span class="badge">SNAPSHOT DELETED</span> ' +
            "Selected snapshot " +
            core.escapeHtml(missingSnapshot) +
            " is no longer available. Choose Latest explicitly to return to live data.";
        }
      }

      setSnapshotControlState(capability, snapshots, false);
      sel.value = state.currentSnapshot || "";
      syncHistoryUi();
    } catch (e) {
      if (!current()) return;
      navigation.metadata = null;
      if (sel) sel.innerHTML = '<option value="">Snapshots unavailable</option>';
      state.historyItems = [];
      state.snapshotCapability = null;
      setSnapshotControlState(null, [], true);
      syncHistoryUi();
      announce("Snapshot availability could not be loaded. It may exceed the metadata read budget. Choose Latest explicitly or retry.");
    } finally {
      window.clearTimeout(timer);
      if (request === historyRequest) { navigation.loading = false; syncNavigation(); }
      if (historyController === controller) historyController = null;
    }
  }

  async function handleMissingSnapshot(kindLabel) {
    selectionFailed("Selected " + kindLabel + " snapshot is unavailable or unreadable.");
    syncHistoryUi();

    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage(
        '<span class="badge">SNAPSHOT DELETED</span> ' +
          "Selected " +
          core.escapeHtml(kindLabel) +
          " snapshot is no longer available. Choose Latest explicitly to return to live data."
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

  function selectSnapshot(value) {
    if (config.kind === "stream") return Promise.resolve(false);
    const selected = value ? String(value) : null;
    state.currentSnapshot = selected;
    navigation.revision += 1;
    navigation.pending = true;
    navigation.error = "";
    state.pendingSnapshotNotice = null;
    for (const controller of bodyLoads.values()) controller.abort();
    writeSnapshotToUrl(selected);
    syncHistoryUi();
    clearLoadingNotice();
    announce("");
    const noticeRevision = navigation.revision;
    const noticeView = config.activeViewId;
    loadingNoticeTimer = window.setTimeout(function () {
      loadingNoticeTimer = null;
      if (!navigation.pending || navigation.error || noticeRevision !== navigation.revision ||
          noticeView !== config.activeViewId) return;
      navigation.loadingVisible = true;
      announce("Loading selected version. Previous content may still be visible.");
      syncNavigation();
    }, 500);
    // Metadata work is coalesced with the body selection below.
    navigation.loading = true;
    syncNavigation();
    if (selectionPromise) return selectionPromise;
    selectionPromise = (async function () {
      while (navigation.pending) {
        const revision = navigation.revision;
        const view = config.activeViewId;
        try {
          // Existing auto-refresh may already be rendering. Finish that single
          // job before rendering the most recent selection, including Tabulator.
          if (state.reloadCurrentViewPromise) {
            await Promise.resolve(state.reloadCurrentViewPromise).catch(function () {});
          }
          if (revision !== navigation.revision) continue;
          if (view !== config.activeViewId) {
            selectionFailed("Source changed before the selected version loaded.");
            break;
          }
          if (core.prepareComparedSelection) await core.prepareComparedSelection();
          if (revision !== navigation.revision) continue;
          if (!state.compareActive && !state.currentSnapshot) state.compareCapture = null;
          loadHistory();
          const applied = core.reloadCurrentView ? await core.reloadCurrentView() : true;
          if (revision !== navigation.revision) continue;
          if (view !== config.activeViewId) {
            selectionFailed("Source changed before the selected version loaded.");
            break;
          }
          if (applied === false && !navigation.error) selectionFailed("Selected version could not be loaded.");
          if (!navigation.error) {
            if (core.completeComparedSelection) core.completeComparedSelection();
            navigation.displayed = state.currentSnapshot;
            announce("");
            if (!state.currentSnapshot && !state.compareCapture && core.markBrowserViewApplied) core.markBrowserViewApplied();
          }
        } catch (error) {
          if (revision !== navigation.revision) continue;
          if (view !== config.activeViewId) {
            selectionFailed("Source changed before the selected version loaded.");
            break;
          }
          selectionFailed(error.message || "Selected version could not be loaded.");
        }
        navigation.pending = false;
      }
    })().finally(function () {
      clearLoadingNotice();
      navigation.pending = false;
      selectionPromise = null;
      state.compareCandidate = null;
      if (!historyController) navigation.loading = false;
      syncHistoryUi();
      if (!state.currentSnapshot && core.restoreAutoRefreshState) core.restoreAutoRefreshState();
    });
    return selectionPromise;
  }

  function returnToLive() { return selectSnapshot(null); }

  function moveSnapshot(direction) {
    const data = navigation.metadata;
    if (!data || navigation.viewId !== config.activeViewId || navigation.loading || !state.snapshotCapability ||
        state.snapshotCapability.enabled !== true || config.kind === "stream") return;
    const target = data[direction];
    if (target) return selectSnapshot(target.snapshot_id);
    if (direction === "newer" && state.currentSnapshot) return returnToLive();
  }

  function bindHistoryControls() {
    const sel = document.getElementById("history-select");
    if (sel && !sel.dataset.navigationBound) {
      sel.dataset.navigationBound = "1";
      sel.addEventListener("change", function () {
        if (sel.value === "__older_page__") loadHistory(navigation.metadata.next_cursor);
        else if (sel.value === "__newest_page__") loadHistory();
        else selectSnapshot(sel.value);
      });
    }
    for (const direction of ["older", "newer"]) {
      const button = document.getElementById("snapshot-" + direction);
      if (button && !button.dataset.navigationBound) {
        button.dataset.navigationBound = "1";
        button.addEventListener("click", () => moveSnapshot(direction));
      }
    }
    const latest = document.getElementById("snapshots-return-latest");
    if (latest && !latest.dataset.navigationBound) {
      latest.dataset.navigationBound = "1";
      latest.addEventListener("click", returnToLive);
    }
    const bannerLatest = document.getElementById("snapshot-mode-return-latest");
    if (bannerLatest && !bannerLatest.dataset.navigationBound) {
      bannerLatest.dataset.navigationBound = "1";
      bannerLatest.addEventListener("click", returnToLive);
    }
    const dismiss = document.getElementById("snapshot-mode-dismiss");
    if (dismiss && !dismiss.dataset.navigationBound) {
      dismiss.dataset.navigationBound = "1";
      dismiss.addEventListener("click", function () {
        bannerDismissed = true;
        syncSnapshotModeBanner();
      });
    }
  }

  function showPendingSnapshotNotice() {
    if (!state.pendingSnapshotNotice) return;
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage(state.pendingSnapshotNotice);
    }
    state.pendingSnapshotNotice = null;
  }

  core.snapshotNavigation = {state: navigation, select: selectSnapshot,
    move: moveSnapshot, loadMetadata: loadHistory};
  core.beginSnapshotLoad = beginSnapshotLoad;
  core.snapshotSelectionFailed = selectionFailed;
  window.addEventListener("pagehide", function () {
    clearLoadingNotice();
    historyRequest += 1;
    if (historyController) historyController.abort();
    for (const controller of bodyLoads.values()) controller.abort();
  });
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
  const STREAM_STATUS_GRACE_MS = 2500;
  const METADATA_TIMEOUT_MS = 10000;
  const metadataRequests = new Map(); // At most one /status and one /views.
  let pageSuspended = false;

  function refreshMetadata(promiseKey, url, apply) {
    if (document.hidden || pageSuspended) return Promise.resolve();
    if (state[promiseKey]) return state[promiseKey];
    const controller = new AbortController();
    const requestedView = config.activeViewId;
    const requestedServerEpoch = state.browserUpdateGeneration;
    metadataRequests.set(promiseKey, controller);
    const timer = window.setTimeout(function () { controller.abort(); }, METADATA_TIMEOUT_MS);
    const request = Promise.resolve().then(function () {
      return fetch(url, {signal: controller.signal});
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (payload) {
      if (payload && !controller.signal.aborted && !pageSuspended &&
          requestedView === config.activeViewId && requestedServerEpoch === state.browserUpdateGeneration) {
        apply(payload);
      }
    }).catch(function () {
      // Retain the last status on failure. The next event or explicit refresh
      // can retry; there is no background metadata polling loop.
    }).finally(function () {
      window.clearTimeout(timer);
      if (metadataRequests.get(promiseKey) === controller) metadataRequests.delete(promiseKey);
      if (state[promiseKey] === request) state[promiseKey] = null;
    });
    state[promiseKey] = request;
    return request;
  }

  function cancelMetadataRequests() {
    for (const [key, controller] of metadataRequests) {
      controller.abort();
      state[key] = null;
    }
    metadataRequests.clear();
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) cancelMetadataRequests();
  });
  if (typeof window.addEventListener === "function") {
    window.addEventListener("pagehide", function () {
      pageSuspended = true;
      cancelMetadataRequests();
    });
    window.addEventListener("pageshow", function () { pageSuspended = false; });
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
      stream: "/static/logo_stream.png",
      image: "/static/logo_image.png",
      markdown: "/static/logo_markdown.png",
      json: "/static/logo_json.png",
      python: "/static/logo_python.png",
      traceback: "/static/logo_exception.png",
      exception: "/static/logo_exception.png",       
      text: "/static/logo_txt.png",
      html: "/static/logo_html.png",
    };
    if (core.uiImageUrl) {
      Object.keys(ICONS).forEach(key => { ICONS[key] = core.uiImageUrl(ICONS[key]); });
    }

    return refreshMetadata("viewMenuRefreshPromise", "/views?_ts=" + Date.now(), function (views) {
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
        if (core.updateViewIcon) core.updateViewIcon(img, meta);
        else if (img && ICONS[iconKey] && img.getAttribute("src") !== ICONS[iconKey]) {
          img.setAttribute("src", ICONS[iconKey]);
        }

        applyFreshnessClass(btn, meta.freshness || null);
      });

      const activeMeta = byId[config.activeViewId];
      if (activeMeta) {
        const iconKey = activeMeta.icon_key || "unknown";
        const img = wrap.querySelector(".ps-viewselect__icon");
        const label = wrap.querySelector(".ps-viewselect__label");
        if (core.updateViewIcon) core.updateViewIcon(img, activeMeta);
        else if (img && ICONS[iconKey] && img.getAttribute("src") !== ICONS[iconKey]) {
          img.setAttribute("src", ICONS[iconKey]);
        }
        if (label) label.textContent = String(activeMeta.label || activeMeta.view_id);
      }
      if (nextRevision !== null) {
        state.viewMenuRevision = nextRevision;
      }
    });
  }

  function elapsedLabel(totalSeconds) {
    const age = formatAgeShort(totalSeconds);
    return age ? age.replace(/ old$/, " ago") : "";
  }

  function streamHeaderStatusKey(value) {
    const stream = value || {};
    return [
      stream.lifecycle || "unknown",
      stream.sourceAvailable === false ? "source-unavailable" : "source-available",
      stream.continuityWarning || "continuous",
    ].join("|");
  }

  function clearHeaderStreamTransition() {
    if (state.headerStreamTransitionTimer != null) {
      window.clearTimeout(state.headerStreamTransitionTimer);
    }
    state.headerStreamTransitionTimer = null;
    state.headerStreamPendingStatus = null;
  }

  function applyHeaderStreamStatus(value) {
    const changed = streamHeaderStatusKey(state.headerStatus.stream) !==
      streamHeaderStatusKey(value);
    state.headerStatus.stream = value;
    if (changed) renderHeaderStatus();
  }

  function deriveHeaderStatus(model) {
    if (model.viewMode === "captured") {
      return {visible: config.showHeaderHistory, tone: "history", label: "Latest captured",
        context: model.browserData === "update_available" ? "New data available" : "Held for inspection",
        title: "Captured Latest; open live source status",
        copy: "Viewing one captured Latest revision. Choose Latest explicitly to capture newer data. Status and checks describe the live source."};
    }
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

    if (config.kind === "stream") {
      const stream = model.stream || {};
      if (stream.historical) {
        return {
          visible: config.showHeaderHistory,
          tone: "history",
          label: "Stored run",
          context: "",
          title: "Stored stream run",
          copy: "Viewing a fixed historical stream run, not the current producer.",
        };
      }

      if (state.streamPaused && model.browserData === "update_available") {
        return {
          visible: config.showHeaderFreshness,
          tone: "new-data",
          label: "New data",
          context: "Live table updates are paused",
          title: "New stream data available",
          copy: "The producer has sent newer data. Resume live table updates to apply it.",
        };
      }

      if (state.streamPaused) {
        return {
          visible: config.showHeaderFreshness,
          tone: "neutral",
          label: "Stream paused",
          context: "Table updates are held",
          title: "Stream table updates paused",
          copy: "The table is fixed at its current state. Resume the stream to apply subsequent data.",
        };
      }

      const lifecycle = String(stream.lifecycle || "unknown").toLowerCase();
      if (stream.continuityWarning) {
        return {
          visible: config.showHeaderFreshness,
          tone: "warn",
          label: "Continuity uncertain",
          context: "Stream needs attention",
          title: "Stream continuity is uncertain",
          copy: stream.continuityWarning,
        };
      }

      const terminalLifecycle = lifecycle === "ended" || lifecycle === "disconnected" ||
        lifecycle === "incomplete";
      if (stream.sourceAvailable === false && !terminalLifecycle) {
        return {
          visible: config.showHeaderFreshness,
          tone: "warn",
          label: "Source unavailable",
          context: "Waiting for the source",
          title: "Stream source unavailable",
          copy: "The active stream source is unavailable; waiting for it to return.",
        };
      }

      const presentations = {
        live: {
          tone: "live",
          label: "Stream active",
          title: "Stream active",
          copy: "Receiving a live producer stream.",
        },
        retrying: {
          tone: "warn",
          label: "Stream retrying",
          title: "Stream delivery is retrying",
          copy: "Recent observations may still be awaiting delivery.",
        },
        disconnected: {
          tone: "error",
          label: "Stream disconnected",
          title: "Stream producer disconnected",
          copy: "Producer heartbeats have stopped; application state is unknown.",
        },
        incomplete: {
          tone: "error",
          label: "Stream incomplete",
          title: "Stream observation is incomplete",
          copy: "Some observations may still be pending.",
        },
        ended: {
          tone: "neutral",
          label: "Stream ended",
          title: "Stream observation ended",
          copy: "The producer explicitly ended this observation.",
        },
      };
      const presentation = presentations[lifecycle] || {
        tone: "neutral",
        label: "Stream connecting",
        title: "Waiting for stream status",
        copy: "The producer state has not yet been observed.",
      };
      return Object.assign(
        { visible: config.showHeaderFreshness, context: "" },
        presentation
      );
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
    if (latest.restored) {
      return {
        visible: config.showHeaderFreshness,
        tone: "restored", label: "Restored", context: "Waiting for a live update",
        title: "Restored from storage",
        copy: "Showing restored data while waiting for the next live update.",
      };
    }
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
        copy: policyLabel + ". This browser will remain on the latest view while waiting for data.",
      };
    }

    return {
      visible: config.showHeaderFreshness,
      tone: "live",
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
    const header = document.getElementById("site-header");
    if (header) {
      const accent = presentation.visible && presentation.tone === "restored" ? "history" : presentation.visible &&
        (presentation.tone === "new-data" || presentation.tone === "history")
        ? presentation.tone
        : null;
      if (accent) header.setAttribute("data-status-accent", accent);
      else header.removeAttribute("data-status-accent");
    }

    if (!presentation.visible && typeof core.closeStatusModal === "function") {
      core.closeStatusModal();
    }

    const label = document.getElementById("header-status-label");
    const context = document.getElementById("header-status-context");
    if (label) label.textContent = presentation.label;
    if (context) {
      context.textContent = presentation.context;
      context.hidden = !presentation.context;
    }
    const button = document.getElementById("header-status-button");
    if (button) button.setAttribute("aria-label", presentation.title);
    if (typeof core.renderCheckAttention === "function") core.renderCheckAttention();
    if (typeof core.renderStatusModal === "function") core.renderStatusModal();
  }

  function setHeaderViewState(viewMode, snapshot) {
    state.headerStatus.viewMode = viewMode === "snapshot" ? "snapshot" : viewMode === "captured" ? "captured" : "latest";
    state.headerStatus.snapshot = state.headerStatus.viewMode !== "latest"
      ? snapshot || { id: state.currentSnapshot, createdAt: null }
      : null;
    renderHeaderStatus();
  }

  // Slice 2 can call this when it detects a newer server version without
  // coupling that mechanism to header DOM details.
  function setHeaderBrowserDataState(browserData) {
    const next = browserData === "update_available"
      ? "update_available"
      : "current";
    if (state.headerStatus.browserData === next) return;
    state.headerStatus.browserData = next;
    renderHeaderStatus();
  }

  function setHeaderLatestStatus(statusPayload) {
    state.latestStatusPayload = statusPayload || null;
    if (typeof core.receiveCheckStatus === "function") core.receiveCheckStatus(statusPayload && statusPayload.checks);
    state.headerStatus.latestData = {
      restored: !!(statusPayload && statusPayload.restored_from_storage),
      lastUpdated: statusPayload && statusPayload.last_updated
        ? statusPayload.last_updated
        : null,
      freshness: statusPayload && statusPayload.freshness
        ? statusPayload.freshness
        : null,
    };
    if (config.kind === "stream" && statusPayload && statusPayload.stream_status) {
      setHeaderStreamStatus(statusPayload.stream_status);
      return;
    }
    renderHeaderStatus();
  }

  function setHeaderStreamStatus(streamPayload) {
    const stream = streamPayload && typeof streamPayload === "object"
      ? streamPayload
      : {};
    const next = Object.assign({}, state.headerStatus.stream, {
      lifecycle: typeof stream.lifecycle === "string" ? stream.lifecycle : null,
      lastHeartbeatAt: stream.last_heartbeat_at || null,
      sourceAvailable: typeof stream.source_available === "boolean"
        ? stream.source_available
        : null,
      continuityWarning: typeof stream.continuity_warning === "string"
        ? stream.continuity_warning
        : null,
    });

    const currentKey = streamHeaderStatusKey(state.headerStatus.stream);
    const nextKey = streamHeaderStatusKey(next);
    const healthy = next.lifecycle === "live" &&
      next.sourceAvailable !== false && !next.continuityWarning;

    // Healthy traffic wins immediately. A less healthy state must remain
    // stable for the grace window before changing the compact header; this
    // prevents transient heartbeat boundaries from making it flicker.
    if (healthy || nextKey === currentKey) {
      clearHeaderStreamTransition();
      applyHeaderStreamStatus(next);
      return;
    }

    const pending = state.headerStreamPendingStatus;
    if (pending && streamHeaderStatusKey(pending) === nextKey) {
      state.headerStreamPendingStatus = next;
      return;
    }

    clearHeaderStreamTransition();
    state.headerStreamPendingStatus = next;
    state.headerStreamTransitionTimer = window.setTimeout(function () {
      const settled = state.headerStreamPendingStatus;
      state.headerStreamPendingStatus = null;
      state.headerStreamTransitionTimer = null;
      if (settled) applyHeaderStreamStatus(settled);
    }, STREAM_STATUS_GRACE_MS);
  }

  function setHeaderStreamSessionState(historical) {
    const nextHistorical = historical === true;
    if (state.headerStatus.stream.historical === nextHistorical) return;
    clearHeaderStreamTransition();
    state.headerStatus.stream = Object.assign({}, state.headerStatus.stream, {
      historical: nextHistorical,
    });
    renderHeaderStatus();
  }

  function notifyHeaderStreamPauseChanged() {
    renderHeaderStatus();
  }

  function refreshLocalFreshness() {
    const latest = state.headerStatus.latestData || {};
    if (latest.restored) {
      return {
        visible: config.showHeaderFreshness,
        tone: "restored", label: "Restored", context: "Waiting for a live update",
        title: "Restored from storage",
        copy: "Showing restored data while waiting for the next live update.",
      };
    }
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
    if (config.kind !== "stream" && state.headerFreshnessTimer == null) {
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

    return refreshMetadata("statusRefreshPromise",
      "/status?view=" + encodeURIComponent(config.activeViewId) + "&_ts=" + Date.now(), function (s) {
      const errWrap = document.getElementById("status-error-wrap");
      const err = document.getElementById("status-error");

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

      // Catalogue work has its own coalescing/deadline; it cannot hold status
      // or modal updates open while its response is slow.
      refreshViewIcons(s.view_menu_revision);
      if (typeof core.renderStatusModal === "function") {
        core.renderStatusModal();
      }
    });
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
  core.setHeaderStreamStatus = setHeaderStreamStatus;
  core.setHeaderStreamSessionState = setHeaderStreamSessionState;
  core.notifyHeaderStreamPauseChanged = notifyHeaderStreamPauseChanged;
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
  const STREAM_RANGE_MIN_TOLERANCE_MS = 10000;
  const STREAM_RANGE_MAX_TOLERANCE_MS = 120000;

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function setAttribute(id, name, value) {
    const element = document.getElementById(id);
    if (element) element.setAttribute(name, value);
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
      return date.toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit",
        ...(rangeMilliseconds < 60000 ? { second: "2-digit" } : {}),
      });
    }
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function renderArrivalAxis(start, end, track) {
    const first = document.getElementById("status-modal-range-start");
    const last = document.getElementById("status-modal-range-end");
    const axis = first && first.parentElement;
    if (!axis || !last) return;
    axis.querySelectorAll(".ps-arrival-chart__tick").forEach(function (tick) { tick.remove(); });
    const span = end - start;
    const width = track.getBoundingClientRect().width;
    const spacing = span > 86400000 ? 84 : 70;
    const slots = Math.max(1, Math.min(12, Math.floor(width / spacing)));
    const intervals = [1, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
      3600, 7200, 10800, 14400, 21600, 43200, 86400, 172800, 604800];
    const step = (intervals.find(function (seconds) { return seconds * 1000 >= span / slots; }) ||
      Math.ceil(span / slots / 604800000) * 604800) * 1000;
    // Align hours to local wall time, while positioning by elapsed time (including DST).
    const offset = new Date(start).getTimezoneOffset() * 60000;
    const origin = Math.ceil((start - offset) / step) * step + offset;
    first.textContent = formatAxisTime(start, span);
    last.textContent = formatAxisTime(end, span);
    first.title = new Date(start).toLocaleString();
    last.title = new Date(end).toLocaleString();
    // End labels are edge-aligned; reserve their full width plus half a tick
    // label so 12-hour timestamps do not collide on narrow screens.
    const startClearance = Math.max(spacing, first.getBoundingClientRect().width + spacing / 2);
    const endClearance = Math.max(spacing, last.getBoundingClientRect().width + spacing / 2);
    for (let time = origin, count = 0; time < end && count < 14; time += step, count += 1) {
      const position = (time - start) / span;
      if (position * width < startClearance || (1 - position) * width < endClearance) continue;
      const tick = document.createElement("span");
      tick.className = "ps-arrival-chart__tick";
      tick.style.left = position * 100 + "%";
      tick.textContent = formatAxisTime(time, span);
      tick.title = new Date(time).toLocaleString();
      axis.appendChild(tick);
    }
  }

  function streamRangeTolerance(events) {
    const gaps = [];
    for (let index = 1; index < events.length; index += 1) {
      const gap = events[index].time - events[index - 1].time;
      if (Number.isFinite(gap) && gap > 0) gaps.push(gap);
    }
    if (!gaps.length) return STREAM_RANGE_MIN_TOLERANCE_MS;
    gaps.sort(function (left, right) { return left - right; });
    const middle = Math.floor(gaps.length / 2);
    const median = gaps.length % 2
      ? gaps[middle]
      : (gaps[middle - 1] + gaps[middle]) / 2;
    return Math.max(
      STREAM_RANGE_MIN_TOLERANCE_MS,
      Math.min(STREAM_RANGE_MAX_TOLERANCE_MS, median * 3)
    );
  }

  function streamActivityRanges(events) {
    if (!events.length) return [];
    const tolerance = streamRangeTolerance(events);
    const ranges = [];
    let current = null;
    events.forEach(function (event) {
      if (!current || event.time - current.end > tolerance) {
        current = {
          start: event.time,
          end: event.time,
          startReceivedAt: event.receivedAt,
          endReceivedAt: event.receivedAt,
          batches: 1,
          count: event.count,
        };
        ranges.push(current);
        return;
      }
      current.end = event.time;
      current.endReceivedAt = event.receivedAt;
      current.batches += 1;
      current.count += event.count;
    });
    return ranges;
  }

  function streamRangeLabel(range) {
    const records = range.count + " accepted stream record" +
      (range.count === 1 ? "" : "s");
    const batches = range.batches + " batch" + (range.batches === 1 ? "" : "es");
    return records + " across " + batches + " · " +
      core.fmtLocalTime(range.startReceivedAt) + " – " +
      core.fmtLocalTime(range.endReceivedAt);
  }

  function renderArrivalTimeline(payload) {
    const track = document.getElementById("status-modal-activity-dots");
    const empty = document.getElementById("status-modal-activity-empty");
    const detail = document.getElementById("status-modal-activity-hover");
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
    const streamRanges = config.kind === "stream" ? streamActivityRanges(visible) : [];
    if (config.kind === "stream") {
      streamRanges.forEach(function (range) {
        const segment = document.createElement("span");
        const startPosition = Math.max(0, Math.min(100, ((range.start - start) / (now - start)) * 100));
        const endPosition = Math.max(0, Math.min(100, ((range.end - start) / (now - start)) * 100));
        const width = Math.max(0.9, endPosition - startPosition);
        const label = streamRangeLabel(range);
        segment.className = "ps-arrival-chart__range";
        segment.style.left = Math.min(100 - width, startPosition) + "%";
        segment.style.width = width + "%";
        segment.title = label;
        segment.tabIndex = 0;
        segment.setAttribute("aria-label", label);
        if (detail) {
          const showDetail = function () { detail.textContent = label; };
          segment.addEventListener("mouseenter", showDetail);
          segment.addEventListener("focus", showDetail);
        }
        track.appendChild(segment);
      });
      if (detail) {
        detail.hidden = streamRanges.length === 0;
        detail.textContent = streamRanges.length
          ? "Hover over or focus an activity range for its start and end time."
          : "";
      }
    } else {
      visible.forEach(function (event, index) {
        const dot = document.createElement("span");
        const position = Math.max(1.5, Math.min(98.5, ((event.time - start) / (now - start)) * 100));
        const size = Math.min(13, 6 + Math.log2(event.count));
        dot.className = "ps-arrival-chart__dot";
        dot.style.left = position + "%";
        dot.style.width = size + "px";
        dot.style.height = size + "px";
        dot.style.bottom = 13 + (index % 3) * 9 + "px";
        dot.title = "Published update · " + core.fmtLocalTime(event.receivedAt);
        dot.setAttribute("aria-hidden", "true");
        track.appendChild(dot);
      });
      if (detail) {
        detail.hidden = true;
        detail.textContent = "";
      }
    }

    empty.hidden = visible.length !== 0;
    renderArrivalAxis(start, now, track);
    if (chart) {
      const visibleItems = config.kind === "stream" ? streamRanges.length : visible.length;
      const itemName = config.kind === "stream" ? "stream activity range" : "data arrival event";
      chart.setAttribute(
        "aria-label",
        visibleItems + " " + itemName + (visibleItems === 1 ? "" : "s") +
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

  function renderStreamStatus(payload, historical) {
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

    if (historical) {
      setText("status-modal-freshness", "Stored session");
      setText(
        "status-modal-freshness-detail",
        "This fixed session does not represent the current producer state."
      );
      return;
    }

    const summaryLabels = {
      live: "Active",
      retrying: "Retrying",
      disconnected: "Disconnected",
      incomplete: "Incomplete",
      ended: "Ended",
    };
    setText("status-modal-freshness", summaryLabels[lifecycle] || "Connecting");
    setText(
      "status-modal-freshness-detail",
      stream && stream.last_heartbeat_at
        ? "Last producer heartbeat " + relativeTime(stream.last_heartbeat_at) + "."
        : "Waiting for the first producer heartbeat."
    );
  }

  function renderStatusModal() {
    const modal = document.getElementById("status-modal");
    if (!modal || !state.statusModalOpen) return;
    if (typeof core.renderCheckContext === "function") core.renderCheckContext();
    const payload = state.latestStatusPayload || {};
    const snapshot = state.currentSnapshot;
    const historicalStream = state.streamHistoricalSessionId;
    const historical = !!snapshot || !!historicalStream;
    const snapshotMeta = typeof core.currentHistoryMeta === "function"
      ? core.currentHistoryMeta()
      : null;
    const streamView = config.kind === "stream";
    const policy = document.getElementById("status-modal-policy");

    setAttribute("status-modal", "aria-label", streamView ? "Stream status" : "Live data status");
    const presentation = core.deriveHeaderStatus ? core.deriveHeaderStatus(state.headerStatus) : null;
    if (presentation) {
      setAttribute("status-modal-health", "data-status-tone", presentation.tone);
      setText("status-modal-health-label", presentation.label === "Live" ? "Live and up to date" : presentation.label);
      setText("status-modal-health-copy", presentation.label === "Live"
        ? "Latest data is within its freshness policy." : presentation.copy);
    }
    setAttribute(
      "status-modal-close-icon",
      "aria-label",
      streamView ? "Close stream status" : "Close live data status"
    );
    setText("status-modal-viewing-label", streamView ? "Session" : "Viewing");
    setText(
      "status-modal-received-label",
      streamView ? "Last records received" : "Last data received"
    );
    setText("status-modal-browser-label", streamView ? "Browser stream" : "Browser view");
    setText("status-modal-freshness-label", streamView ? "Producer state" : "Freshness");
    setText(
      "status-modal-activity-title",
      streamView ? "Recent stream activity" : "Recent updates"
    );
    if (policy) policy.hidden = streamView;

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
    } else if (streamView) {
      setText("status-modal-viewing", "Current stream");
      setText("status-modal-viewing-detail", "This browser follows the active observation.");
    } else {
      setText("status-modal-viewing", payload.restored_from_storage ? "Restored data" : "Latest data");
      setText("status-modal-viewing-detail", payload.restored_from_storage
        ? "Restored from storage. Waiting for the next live update." +
          (payload.restored_at ? " Restored at " + core.fmtLocalTime(payload.restored_at) + "." : "")
        : "");
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
          : state.streamPaused
            ? "Live table updates are paused. Resume them to apply the newest stream data."
            : "The server has newer data that this browser has not applied."
        : state.browserLastAppliedAt
          ? "Last applied " + relativeTime(state.browserLastAppliedAt) + "."
          : "The application time is not yet known."
    );

    const freshness = payload.freshness || state.headerStatus.latestData.freshness;
    if (!streamView) {
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
    }
    renderStreamStatus(payload, historical);

    const activity = payload.data_activity || {};
    setText(
      "status-modal-activity-copy",
      config.kind === "stream"
        ? "Nearby accepted record batches are combined into activity ranges; brief quiet gaps are tolerated and heartbeats are excluded."
        : "Each dot represents a published update received."
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
    const actions = document.getElementById("status-modal-actions");
    if (actions) actions.hidden = !historical && (!waiting || state.streamPaused);
    if (updateNow) updateNow.hidden = !waiting || historical || state.streamPaused;
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
      return !element.closest("[hidden]") && element.getClientRects().length > 0;
    });
  }

  function openStatusModal() {
    const backdrop = document.getElementById("status-modal-backdrop");
    const close = document.getElementById("status-modal-close-icon");
    const button = document.getElementById("header-status-button");
    if (!backdrop) return;
    state.statusModalReturnFocus = document.activeElement;
    state.statusModalOpen = true;
    window.addEventListener("resize", renderStatusModal);
    backdrop.hidden = false;
    if (document.body) document.body.classList.add("ps-status-modal-open");
    if (button) button.setAttribute("aria-expanded", "true");
    renderStatusModal();
    if (typeof core.openCheckStatus === "function") core.openCheckStatus();
    const watched = state.latestStatusPayload && state.latestStatusPayload.watched_file;
    if ((config.kind === "stream" || (watched && watched.materialization === "remote")) &&
        typeof core.refreshStatus === "function") {
      core.refreshStatus();
    }
    if (close) close.focus();
  }

  function closeStatusModal(options) {
    const backdrop = document.getElementById("status-modal-backdrop");
    const button = document.getElementById("header-status-button");
    if (!backdrop || backdrop.hidden) return;
    backdrop.hidden = true;
    state.statusModalOpen = false;
    window.removeEventListener("resize", renderStatusModal);
    if (typeof core.closeCheckStatus === "function") core.closeCheckStatus();
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

/* plotsrv source: js/core/check_status.js */
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
    const hasChecks = !!(shown && shown.states.length);
    context.hidden = !hasChecks;
    const personal = el("status-checks-personal");
    if (personal) personal.hidden = !hasChecks;
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

  const bar = state.bottomBar = {collapsed: false};
  const barKey = "plotsrv:bottom-bar:" + encodeURIComponent(window.PLOTSRV.config.dashboardName || "default") + ":" + location.pathname;
  let geometryFrame = null, barBound = false;
  function geometry() {
    if (geometryFrame !== null) return;
    geometryFrame = requestAnimationFrame(() => {
      geometryFrame = null; syncDockClearance();
      for (const table of new Set([state.tabulatorInstance, state.streamTabulatorInstance])) {
        if (!table || !table.initialized || !table.element || !table.element.isConnected) continue;
        if (state.compareActive) {
          const clearance = parseFloat(getComputedStyle(document.body).getPropertyValue("--ps-bottom-dock-clearance")) || 0;
          table.element.style.setProperty("--ps-table-available", Math.max(100, innerHeight - clearance - Math.max(0, table.element.getBoundingClientRect().top) - 12) + "px");
        }
        const holder = table.element.querySelector(".tabulator-tableholder");
        const pos = holder && [holder.scrollLeft, holder.scrollTop];
        table.redraw(false);
        if (holder && pos) {holder.scrollLeft = pos[0]; holder.scrollTop = pos[1];}
      }
    });
  }
  function presentBar() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock) return;
    const expanded = state.expandedView && state.expandedView.active;
    dock.hidden = bar.collapsed || !!expanded;
    document.getElementById("bottom-restore").hidden = !bar.collapsed || !!expanded;
    document.body.classList.toggle("ps-bar-collapsed", bar.collapsed);
    if (barBound) {try {sessionStorage.setItem(barKey, JSON.stringify(bar));} catch (_) {}}
    geometry();
  }
  function setCollapsed(value) {
    if (core.closeExportMenu) core.closeExportMenu();
    bar.collapsed = !!value; presentBar();
    document.getElementById(value ? "bottom-restore" : "bottom-collapse").focus({preventScroll: true});
  }
  core.bottomBar = {state: bar, setCollapsed, present: presentBar};

  function syncDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || !document.body) return;
    const rect = dock.getBoundingClientRect();
    const height = Math.ceil(rect.height);
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const clearance = dock.hidden ? 0 : Math.ceil(Math.max(height, viewportHeight - rect.top));
    document.body.style.setProperty("--ps-bottom-dock-height", height + "px");
    document.body.style.setProperty("--ps-bottom-dock-clearance", clearance + "px");
  }

  function bindDockClearance() {
    const dock = document.querySelector(".ps-bottom-dock");
    if (!dock || dock.dataset.plotsrvClearanceBound === "1") return;
    syncDockClearance();
    window.addEventListener("resize", geometry);
    if (typeof window.ResizeObserver === "function") {
      state.bottomDockResizeObserver = new window.ResizeObserver(geometry);
      state.bottomDockResizeObserver.observe(dock);
    }
    window.addEventListener("pagehide", () => {
      if (state.bottomDockResizeObserver) state.bottomDockResizeObserver.disconnect();
      if (geometryFrame !== null) cancelAnimationFrame(geometryFrame);
      geometryFrame = null;
    });
    window.addEventListener("pageshow", () => {
      if (state.bottomDockResizeObserver) state.bottomDockResizeObserver.observe(dock);
      geometry();
    });
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
    const navigation = state.snapshotNavigation;
    if (navigation && (navigation.pending || navigation.error)) return;
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
    } else if (action === "plot-svg" || action === "plot-png") {
      if (typeof core.exportTablePlot === "function") {
        result = core.exportTablePlot(action === "plot-svg" ? "svg" : "png");
      }
    }

    if (result === false) showExportFailure();
  }

  function configureBottomBar() {
    if (core.syncViewExplanation) core.syncViewExplanation();
    if (core.syncExpandedView) core.syncExpandedView();
    if (core.syncCompare) core.syncCompare();
    const complete = document.querySelector('[data-export-scope="complete"]');
    if (complete) {
      const sourceDownload =
        state.tableLastPayload &&
        state.tableLastPayload.meta &&
        state.tableLastPayload.meta.source_download_url;
      const isHistory =
        typeof core.isHistoryMode === "function" ? core.isHistoryMode() : false;
      complete.textContent = core.inspectionCapture && core.inspectionCapture() ? "Captured table preview" :
        !isHistory && typeof sourceDownload === "string" && sourceDownload
          ? "Complete source CSV file"
          : (!isHistory && state.tableLastPayload && state.tableLastPayload.meta &&
              state.tableLastPayload.meta.materialization === "remote"
            ? "Hosted table preview" : "Complete published table");
    }
    const plotItems = document.getElementById("plot-export-items");
    if (plotItems) {
      const plotMode = state.tablePlotMode === "plot";
      const available = plotMode && state.tablePlotLastResult && state.tablePlotLastResult.ok === true;
      plotItems.hidden = !plotMode;
      Array.from(plotItems.querySelectorAll("[data-export-scope]")).forEach(function (item) {
        item.disabled = !available;
        item.title = available ? "" : "Render a plot before exporting it.";
      });
    }
  }

  function bindBottomBar() {
    bindDockClearance();
    const collapse = document.getElementById("bottom-collapse");
    if (collapse && !collapse.dataset.bound) {
      collapse.dataset.bound = "1"; barBound = true;
      try {const raw = sessionStorage.getItem(barKey); const saved = raw && raw.length < 128 ? JSON.parse(raw) : {};
        bar.collapsed = saved.collapsed === true;} catch (_) {}
      collapse.addEventListener("click", () => setCollapsed(true));
      document.getElementById("bottom-restore").addEventListener("click", () => setCollapsed(false));
      presentBar();
    }
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
  core.closeExportMenu = closeExportMenu;
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
  const STREAM_UPDATE_RETRY_MIN_MS = 1500;
  const STREAM_UPDATE_RETRY_MAX_MS = 15000;
  // The server emits an observable heartbeat every 20 seconds. Waiting for
  // more than two missed heartbeats avoids churn during brief suspension while
  // still recovering a silently wedged proxy/browser connection.
  const UPDATE_SOURCE_STALE_MS = 55000;
  const UPDATE_SOURCE_WATCHDOG_MS = 20000;
  const UPDATE_SOURCE_RECONNECT_MIN_MS = 2000;
  const UPDATE_SOURCE_RECONNECT_MAX_MS = 30000;
  let notificationsBound = false;
  let pageSuspended = false;

  function initialLoadSettled() {
    return state.initialViewLoadComplete || state.initialViewLoadAttempted;
  }

  function clearStreamUpdateRetry() {
    if (state.browserUpdateRetryTimer != null) {
      window.clearTimeout(state.browserUpdateRetryTimer);
    }
    state.browserUpdateRetryTimer = null;
    state.browserUpdateRetryAttempt = 0;
  }

  function scheduleStreamUpdateRetry() {
    if (config.kind !== "stream" || state.browserUpdateRetryTimer != null ||
        document.hidden || pageSuspended || !state.pendingBrowserUpdate) return;
    const attempt = Number.isSafeInteger(state.browserUpdateRetryAttempt)
      ? state.browserUpdateRetryAttempt
      : 0;
    const delay = Math.min(
      STREAM_UPDATE_RETRY_MAX_MS,
      STREAM_UPDATE_RETRY_MIN_MS * Math.pow(2, Math.min(attempt, 4))
    );
    state.browserUpdateRetryAttempt = Math.min(attempt + 1, 5);
    state.browserUpdateRetryTimer = window.setTimeout(function () {
      state.browserUpdateRetryTimer = null;
      applyPendingUpdate();
    }, delay);
  }

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
    if (state.compareActive || state.compareCapture) blockers.push("compare_inspection");
    if (document.hidden) blockers.push("hidden_tab");
    if (state.snapshotNavigation && (state.snapshotNavigation.pending || state.snapshotNavigation.error)) blockers.push("snapshot_navigation");
    if (typeof core.isHistoryMode === "function" && core.isHistoryMode()) {
      blockers.push("snapshot");
    }
    if (state.streamHistoricalSessionId) blockers.push("historical_stream_session");
    if (config.kind === "stream" && state.streamPaused) blockers.push("stream_paused");

    // A live stream mutates Tabulator incrementally. Its sort, filter,
    // grouping, column and plot state survive addData/replaceData, so the
    // interaction blockers needed for wholesale ordinary-table replacement
    // would only freeze the stream. Hidden tabs and history remain bounded.
    if (config.kind === "stream") return blockers;

    const ui = state.tableUiState || {};
    if (String(ui.searchQuery || "").trim()) blockers.push("table_search");
    if (Array.isArray(ui.filters) && ui.filters.some(filter => completeFilter(filter) && !(
      state.observationProfile && filter.field === "surface" && filter.op === "eq" && filter.value === "Fields"
    ))) {
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
    return blocker === "compare_inspection" || blocker === "snapshot" || blocker === "historical_stream_session" ||
      blocker === "stream_paused";
  }

  function canApplyPendingUpdate(options) {
    const force = !!(options && options.force);
    const blockers = getAutomaticUpdateBlockers();
    if (blockers.includes("snapshot_navigation") || blockers.some(historicalBlocker)) return false;
    return force || blockers.length === 0;
  }

  function showPendingUpdate() {
    // A queued live-stream revision is normal burst coalescing, not a
    // user-actionable stale state. Showing it in the header causes rapid
    // green/yellow flicker when records arrive faster than a fetch completes.
    if (config.kind === "stream" && !state.streamPaused) return;
    if (typeof core.setHeaderBrowserDataState === "function") {
      core.setHeaderBrowserDataState("update_available");
    }
  }

  function finishAppliedUpdate(revision) {
    clearStreamUpdateRetry();
    state.initialViewLoadComplete = true;
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
    const force = !!(options && options.force);
    // While an endpoint is failing, incoming stream notices only replace the
    // pending revision. They must not bypass the bounded retry backoff and
    // turn a busy producer into a tight loop of failing HTTP requests.
    if (config.kind === "stream" && state.browserUpdateRetryTimer != null && !force) {
      return Promise.resolve(false);
    }
    if (!initialLoadSettled() || pageSuspended || !canApplyPendingUpdate(options)) {
      showPendingUpdate();
      return Promise.resolve(false);
    }

    if (pending.kind && pending.kind !== config.kind) {
      window.location.reload();
      return Promise.resolve(true);
    }

    state.browserUpdateApplying = true;
    const revision = pending.revision;
    const generation = state.browserUpdateGeneration;
    let retryImmediatelyWhenSettled = false;
    let reloadResult;
    try {
      reloadResult = core.reloadCurrentView();
    } catch (error) {
      reloadResult = Promise.reject(error);
    }
    return Promise.resolve(reloadResult)
      .then(function (applied) {
        if (generation !== state.browserUpdateGeneration) {
          retryImmediatelyWhenSettled = true;
          return false;
        }
        // A pause can invalidate a stream fetch after it starts. Do not
        // acknowledge that revision merely because cancellation was clean.
        if (applied === false || (config.kind === "stream" && state.streamPaused)) {
          showPendingUpdate();
          // Ordinary fetch failure waits for another notice or explicit update.
          // A failed snapshot selection must never become a hot Live retry loop.
          retryImmediatelyWhenSettled = config.kind === "stream";
          return false;
        }
        finishAppliedUpdate(revision);
        // A notice can arrive between this acknowledgement and the final
        // promise callback below. Drain it after releasing the in-flight flag.
        retryImmediatelyWhenSettled = true;
        return true;
      })
      .catch(function () {
        showPendingUpdate();
        scheduleStreamUpdateRetry();
        return false;
      })
      .then(function (result) {
        state.browserUpdateApplying = false;
        if (retryImmediatelyWhenSettled && state.pendingBrowserUpdate &&
            canApplyPendingUpdate()) {
          window.setTimeout(function () { applyPendingUpdate(); }, 0);
        }
        return result;
      });
  }

  function refreshCheckStatus() {
    state.checkStatusDirty = true;
    if (state.checkStatusRequest || typeof core.refreshStatus !== "function") return;
    state.checkStatusDirty = false;
    state.checkStatusRequest = Promise.resolve().then(function () {
      return core.refreshStatus();
    }).catch(function () {}).finally(function () {
      state.checkStatusRequest = null;
      if (state.checkStatusDirty) refreshCheckStatus();
    });
  }

  function receiveBrowserUpdate(payload) {
    if (!payload || typeof payload !== "object") return;
    const revision = Number(payload.revision);
    if (!Number.isSafeInteger(revision) || revision < 0) return;
    const instanceId = payload.server_instance_id;
    if (typeof instanceId === "string" && instanceId &&
        instanceId !== state.browserUpdateInstanceId) {
      if (state.browserUpdateInstanceId && config.kind === "stream" &&
          !state.streamHistoricalSessionId) {
        state.streamAwaitingReceiverSession = true;
      }
      state.browserUpdateInstanceId = instanceId;
      state.browserUpdateGeneration = (state.browserUpdateGeneration || 0) + 1;
      state.observedUpdateRevision = -1;
      state.appliedUpdateRevision = -1;
      state.pendingBrowserUpdate = null;
      clearStreamUpdateRetry();
    }
    if (payload.change_type === "reconnect" &&
        (!payload.view_id || payload.view_id === config.activeViewId)) refreshCheckStatus();
    if (revision <= state.observedUpdateRevision) return;
    state.observedUpdateRevision = revision;

    if (payload.change_type === "reconnect" &&
        typeof core.refreshViewIcons === "function") core.refreshViewIcons(null);
    if (payload.change_type === "catalogue") {
      if (typeof core.refreshViewIcons === "function") core.refreshViewIcons(null);
      return;
    }
    if (payload.view_id && payload.view_id !== config.activeViewId) return;
    if (payload.change_type === "checks") {
      refreshCheckStatus();
      return;
    }
    if (payload.change_type === "stream_history" ||
        (payload.change_type === "reconnect" && config.kind === "stream") ||
        payload.history_catalogue_changed === true) {
      if (typeof core.scheduleStreamHistoryCatalogueRefresh === "function") {
        core.scheduleStreamHistoryCatalogueRefresh();
      }
      if (payload.change_type === "stream_history") return;
    }

    // A single assignment coalesces any burst while a fetch is in flight.
    state.pendingBrowserUpdate = payload;
    if (!initialLoadSettled() || !canApplyPendingUpdate()) {
      showPendingUpdate();
      return;
    }
    applyPendingUpdate();
  }

  function noteUpdateSourceActivity(source) {
    if (state.browserUpdateSource !== source) return;
    state.browserUpdateLastEventAt = Date.now();
    state.browserUpdateReconnectAttempt = 0;
  }

  function clearUpdateSourceReconnect() {
    if (state.browserUpdateReconnectTimer != null) {
      window.clearTimeout(state.browserUpdateReconnectTimer);
    }
    state.browserUpdateReconnectTimer = null;
  }

  function connectUpdateSource() {
    if (!notificationsBound || !initialLoadSettled() || document.hidden || pageSuspended ||
        state.browserUpdateSource || state.browserUpdateReconnectTimer != null ||
        typeof window.EventSource !== "function") return;
    const url = "/updates?view=" + encodeURIComponent(config.activeViewId) +
      "&since=" + encodeURIComponent(Math.max(0, state.observedUpdateRevision));
    let source;
    try {
      source = new window.EventSource(url);
    } catch (e) {
      scheduleUpdateSourceReconnect();
      return;
    }
    state.browserUpdateSource = source;
    state.browserUpdateLastEventAt = Date.now();
    source.addEventListener("open", function () {
      if (state.browserUpdateSource !== source) return;
      state.browserUpdateLastEventAt = Date.now();
      clearUpdateSourceReconnect();
    });
    source.addEventListener("keepalive", function () {
      noteUpdateSourceActivity(source);
    });
    source.addEventListener("update", function (event) {
      if (state.browserUpdateSource !== source) return;
      noteUpdateSourceActivity(source);
      try {
        receiveBrowserUpdate(JSON.parse(event.data));
      } catch (e) {
        // A malformed notice is safely ignored; EventSource still reconnects.
      }
    });
    source.addEventListener("error", function () {
      if (state.browserUpdateSource !== source) return;
      // Own retries so an unavailable server backs off, including terminal
      // EventSource errors. Hidden pages never reconnect in the background.
      scheduleUpdateSourceReconnect();
    });
    scheduleUpdateSourceWatchdog();
  }

  function disconnectUpdateSource() {
    const source = state.browserUpdateSource;
    state.browserUpdateSource = null;
    if (source && typeof source.close === "function") source.close();
    if (state.browserUpdateWatchdogTimer != null) {
      window.clearTimeout(state.browserUpdateWatchdogTimer);
      state.browserUpdateWatchdogTimer = null;
    }
  }

  function reconnectUpdateSource() {
    clearUpdateSourceReconnect();
    disconnectUpdateSource();
    connectUpdateSource();
  }

  function scheduleUpdateSourceReconnect() {
    disconnectUpdateSource();
    if (state.browserUpdateReconnectTimer != null || document.hidden || pageSuspended) return;
    const attempt = state.browserUpdateReconnectAttempt || 0;
    const delay = Math.min(UPDATE_SOURCE_RECONNECT_MAX_MS,
      UPDATE_SOURCE_RECONNECT_MIN_MS * Math.pow(2, Math.min(attempt, 4)));
    state.browserUpdateReconnectAttempt = Math.min(attempt + 1, 5);
    state.browserUpdateReconnectTimer = window.setTimeout(
      reconnectUpdateSource,
      delay
    );
  }

  function checkUpdateSourceLiveness() {
    state.browserUpdateWatchdogTimer = null;
    if (!document.hidden && !pageSuspended && state.browserUpdateSource) {
      const lastEventAt = Number(state.browserUpdateLastEventAt);
      if (!Number.isFinite(lastEventAt) || Date.now() - lastEventAt > UPDATE_SOURCE_STALE_MS) {
        reconnectUpdateSource();
      }
    }
    scheduleUpdateSourceWatchdog();
  }

  function scheduleUpdateSourceWatchdog() {
    if (document.hidden || pageSuspended || !state.browserUpdateSource ||
        state.browserUpdateWatchdogTimer != null ||
        typeof window.setTimeout !== "function") return;
    state.browserUpdateWatchdogTimer = window.setTimeout(
      checkUpdateSourceLiveness,
      UPDATE_SOURCE_WATCHDOG_MS
    );
  }

  function bindUpdateNotifications() {
    notificationsBound = true;
    connectUpdateSource();
  }

  function markInitialViewLoaded() {
    state.initialViewLoadComplete = true;
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  function notifyUpdateEligibilityChanged() {
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  function suspendNotifications() {
    clearUpdateSourceReconnect();
    disconnectUpdateSource();
    clearStreamUpdateRetry();
    state.browserUpdateReconnectAttempt = 0;
  }

  function resumeNotifications() {
    if (!notificationsBound || document.hidden || pageSuspended) return;
    if (!state.initialViewLoadComplete && core.ensureInitialViewLoaded) {
      core.ensureInitialViewLoaded();
    } else {
      connectUpdateSource();
      notifyUpdateEligibilityChanged();
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) suspendNotifications();
    else resumeNotifications();
  });
  if (typeof window.addEventListener === "function") {
    window.addEventListener("pagehide", function () {
      pageSuspended = true;
      suspendNotifications();
    });
    window.addEventListener("pageshow", function () {
      pageSuspended = false;
      resumeNotifications();
    });
  }

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
  const ICONS = {
    unknown: "/static/logo_unknown.png",
    plot: "/static/logo_plot.png",
    table: "/static/logo_table.png",
    stream: "/static/logo_stream.png",
    image: "/static/logo_image.png",
    markdown: "/static/logo_markdown.png",
    json: "/static/logo_json.png",
    python: "/static/logo_python.png",
    traceback: "/static/logo_python_traceback.png",
    exception: "/static/logo_exception.png",
    text: "/static/logo_txt.png",
    html: "/static/logo_html.png",
  };
  if (core.uiImageUrl) {
    Object.keys(ICONS).forEach(key => { ICONS[key] = core.uiImageUrl(ICONS[key]); });
  }
  const CODE_LABELS = {python:"PY", r:"R", sql:"SQL", bash:"SH", javascript:"JS",
    typescript:"TS", css:"CSS", c:"C", cpp:"C++", go:"GO", rust:"RS"};

  function makeViewIcon(view, className) {
    let icon;
    if (view.icon_key === "code") {
      icon = element("span", className + " ps-code-view-icon");
      icon.setAttribute("aria-hidden", "true");
      icon.appendChild(element("span", "ps-code-view-icon__glyph"));
      icon.appendChild(element("span", "ps-code-view-icon__language",
        Object.prototype.hasOwnProperty.call(CODE_LABELS, view.code_language) ? CODE_LABELS[view.code_language] : "CODE"));
    } else {
      icon = element("img", className);
      icon.src = iconUrl(view);
      icon.alt = "";
    }
    icon.dataset.iconSignature = JSON.stringify([view.icon_key, view.code_language || ""]);
    return icon;
  }
  core.makeViewIcon = makeViewIcon;
  core.updateViewIcon = function (icon, view) {
    if (!icon || icon.dataset.iconSignature === JSON.stringify([view.icon_key, view.code_language || ""])) return;
    const className = icon.classList.contains("ps-viewselect__itemicon")
      ? "ps-viewselect__itemicon" : "ps-viewselect__icon";
    icon.replaceWith(makeViewIcon(view, className));
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
        code_language: cleanText(raw.code_language, "").toLowerCase(),
        description: typeof raw.description === "string" ? raw.description.slice(0, 512) : "",
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
      code: "Code" + (view.code_language ? " · " + view.code_language : ""),
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
        caption: cleanText(raw.caption, view.description).slice(0, 512),
        thumbnail_url: safePresentationUrl(raw.thumbnail_url || raw.thumbnail),
      });
    }
    return resolved;
  }

  function resolveCompactViews(views, rawCompact) {
    const catalogue = normalizeViewCatalogue(views);
    const byId = new Map(catalogue.map(function (view) {
      return [view.view_id, view];
    }));
    const resolved = [];
    const seen = new Set();
    if (!Array.isArray(rawCompact)) return resolved;
    for (const raw of rawCompact) {
      const values = typeof raw === "string" ? {view_id: raw} : raw;
      if (!values || typeof values !== "object") continue;
      const viewId = cleanText(values.view_id || values.view, "");
      const view = byId.get(viewId);
      if (!view || seen.has(viewId)) continue;
      seen.add(viewId);
      resolved.push({
        view: view,
        title: cleanText(values.title, view.label),
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
    if (stored === "grouped" || stored === "az" || stored === "my") return stored;
    return "grouped";
  }

  function pinnedStorageKey() {
    return storageKey("viewSelectorPinned", "plotsrv:v1:view_selector_pinned");
  }

  function loadPinnedViews(catalogue) {
    const valid = new Set(catalogue.map(function (view) { return view.view_id; }));
    try {
      const parsed = JSON.parse(localStorage.getItem(pinnedStorageKey()) || "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map(String)
        .filter(function (viewId, index, items) {
          return valid.has(viewId) && items.indexOf(viewId) === index;
        });
    } catch (e) {
      return [];
    }
  }

  function savePinnedViews(viewIds) {
    try {
      localStorage.setItem(pinnedStorageKey(), JSON.stringify(viewIds));
    } catch (e) {
      // ignore
    }
  }

  function togglePinnedView(viewId, catalogue) {
    const current = loadPinnedViews(catalogue);
    const existing = current.indexOf(viewId);
    if (existing >= 0) current.splice(existing, 1);
    else if (catalogue.some(function (view) { return view.view_id === viewId; })) {
      current.unshift(viewId);
    }
    savePinnedViews(current);
    return current;
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
    button.setAttribute("data-selected", selected ? "true" : "false");
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }

  function applyFreshness(button, view) {
    if (typeof core.applyViewFreshness === "function") {
      core.applyViewFreshness(button, view.freshness || null);
    }
  }

  function makePinButton(view, pinned) {
    const button = element(
      "button",
      "ps-viewselect__pin" + (pinned ? " ps-viewselect__pin--active" : ""),
      pinned ? "★" : "☆"
    );
    const action = pinned ? "Unpin" : "Pin";
    button.type = "button";
    button.setAttribute("data-pin-view", view.view_id);
    button.setAttribute("aria-pressed", pinned ? "true" : "false");
    button.setAttribute("aria-label", action + " " + view.label);
    button.title = action + " " + view.label;
    return button;
  }

  function wrapViewEntry(button, view, pinned, feature, compact) {
    const entry = element(
      "div",
      "ps-viewselect__entry" +
        (feature ? " ps-viewselect__entry--feature" : "") +
        (compact ? " ps-viewselect__entry--compact" : "")
    );
    entry.appendChild(button);
    entry.appendChild(makePinButton(view, pinned));
    entry.setAttribute("role", "listitem");
    return entry;
  }

  function makeViewItem(view, includeSection, pinned, compact) {
    const button = element(
      "button",
      "ps-viewselect__item" + (compact ? " ps-viewselect__item--compact" : "")
    );
    button.type = "button";
    button.setAttribute("data-plotsrv-view", view.view_id);
    button.setAttribute("data-view-section", view.section);
    button.setAttribute("data-view-kind", view.kind);
    button.setAttribute("data-view-icon", view.icon_key);
    applySelection(button, view);

    const freshness = element("span", "ps-viewselect__freshness");
    freshness.hidden = true;
    freshness.setAttribute("aria-hidden", "true");
    freshness.setAttribute("data-plotsrv-view-freshness", view.view_id);

    const copy = element("span", "ps-viewselect__itemcopy");
    copy.appendChild(
      element("span", "ps-viewselect__itemlabel", compact ? compact.title : view.label)
    );
    const meta = includeSection
      ? view.section + " · " + viewTypeLabel(view)
      : viewTypeLabel(view);
    copy.appendChild(element("span", "ps-viewselect__itemmeta", meta));
    if (view.description) copy.appendChild(element("span", "ps-viewselect__description", view.description));

    button.appendChild(freshness);
    if (!compact) {
      button.appendChild(makeViewIcon(view, "ps-viewselect__itemicon"));
    }
    button.appendChild(copy);
    const check = element("span", "ps-viewselect__check", "✓");
    check.setAttribute("aria-hidden", "true");
    button.appendChild(check);
    applyFreshness(button, view);
    return wrapViewEntry(button, view, pinned, false, !!compact);
  }

  function makeFeatureFallback(view) {
    const fallback = element("span", "ps-viewselect__feature-fallback");
    fallback.appendChild(makeViewIcon(view, "ps-viewselect__itemicon"));
    return fallback;
  }

  function makeFeatureItem(feature, pinned) {
    const view = feature.view;
    const button = element("button", "ps-viewselect__feature");
    button.type = "button";
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
    return wrapViewEntry(button, view, pinned, true, false);
  }

  function appendGroup(
    fragment,
    label,
    views,
    includeSection,
    pinnedIds,
    compactById
  ) {
    if (!views.length) return;
    const group = element("section", "ps-viewselect__group");
    group.setAttribute("aria-label", label);
    group.appendChild(element("h3", "ps-viewselect__group-label", label));
    const items = element("div", "ps-viewselect__group-items");
    items.setAttribute("role", "list");
    for (const view of views) {
      items.appendChild(
        makeViewItem(
          view,
          includeSection,
          pinnedIds.has(view.view_id),
          compactById ? compactById.get(view.view_id) : null
        )
      );
    }
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
      pinned: [],
      renderFrame: null,
    };
    controller.mode = initialViewSelectorMode();
    controller.pinned = loadPinnedViews(controller.catalogue);
    savePinnedViews(controller.pinned);

    function availableFeatures() {
      return resolveFeaturedViews(controller.catalogue, config.featuredViews);
    }

    function renderTabs() {
      const modes = [["grouped", "Grouped"], ["az", "A–Z"], ["my", "My views"]];
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
      const featuredIds = new Set(features.map(function (feature) {
        return feature.view.view_id;
      }));
      const compactById = new Map(
        resolveCompactViews(controller.catalogue, config.compactViews)
          .filter(function (item) { return !featuredIds.has(item.view.view_id); })
          .map(function (item) { return [item.view.view_id, item]; })
      );
      renderTabs();
      const fragment = document.createDocumentFragment();
      const query = controller.query.trim();
      const pinnedIds = new Set(controller.pinned);

      if (controller.mode === "my") {
        const loaded = core.viewSpec ? core.viewSpec.read() : {items:[], error:null};
        const matching = loaded.items.filter(item => (item.spec.name + " " + item.spec.caption + " " + item.spec.sourceId).toLowerCase().includes(query.toLowerCase()));
        const known = new Map(controller.catalogue.map(view => [view.view_id, view]));
        if (loaded.error || !matching.length) fragment.appendChild(element("p", "ps-viewselect__empty", loaded.error || (query ? "No matching saved views." : "Change table or plot settings, then choose Save view to save a presentation on this browser. Ordinary sources remain in Grouped and A–Z.")));
        matching.forEach(item => {
          const row = element("div", "ps-viewselect__entry");
          const open = element("button", "ps-viewselect__item"); open.type = "button";
          open.setAttribute("data-plotsrv-view", item.spec.sourceId); open.setAttribute("data-personal-view", item.id);
          const current = new URL(window.location.href).searchParams.get("my_view") === item.id;
          open.setAttribute("data-selected", current ? "true" : "false");
          if (current) open.setAttribute("aria-current", "page");
          open.disabled = !known.has(item.spec.sourceId);
          open.appendChild(makeViewIcon(known.get(item.spec.sourceId) || {icon_key: "unknown"}, "ps-viewselect__itemicon"));
          const copy = element("span", "ps-viewselect__itemcopy");
          copy.appendChild(element("span", "ps-viewselect__itemlabel", item.spec.name));
          copy.appendChild(element("span", "ps-viewselect__itemmeta", (known.has(item.spec.sourceId) ? item.spec.caption || known.get(item.spec.sourceId).description || item.spec.sourceId : "Source unavailable — " + item.spec.sourceId)));
          open.appendChild(copy);
          const check = element("span", "ps-viewselect__check", "✓"); check.setAttribute("aria-hidden", "true"); open.appendChild(check);
          row.appendChild(open);
          const remove = element("button", "ps-viewselect__delete", "×"); remove.type = "button";
          remove.setAttribute("data-personal-delete", item.id); remove.setAttribute("aria-label", "Delete saved view " + item.spec.name);
          row.appendChild(remove); fragment.appendChild(row);
        });
      } else if (query) {
        appendGroup(
          fragment,
          "Search results",
          filterViewCatalogue(controller.catalogue, query).sort(compareViews),
          true,
          pinnedIds,
          compactById
        );
      } else if (controller.mode === "az") {
        appendGroup(
          fragment,
          "All views",
          controller.catalogue.slice().sort(compareViews),
          true,
          pinnedIds,
          compactById
        );
      } else {
        if (features.length) {
          const featuredGroup = element(
            "section",
            "ps-viewselect__group ps-viewselect__group--featured"
          );
          featuredGroup.setAttribute("aria-label", "Featured");
          featuredGroup.appendChild(
            element("h3", "ps-viewselect__group-label", "Featured")
          );
          const featureList = element("div", "ps-viewselect__features");
          featureList.setAttribute("role", "list");
          for (const feature of features) {
            featureList.appendChild(
              makeFeatureItem(feature, pinnedIds.has(feature.view.view_id))
            );
          }
          featuredGroup.appendChild(featureList);
          fragment.appendChild(featuredGroup);
        }

        const byId = new Map(controller.catalogue.map(function (view) {
          return [view.view_id, view];
        }));
        const pinned = controller.pinned
          .map(function (viewId) { return byId.get(viewId); })
          .filter(Boolean);
        appendGroup(fragment, "Pinned views", pinned, true, pinnedIds, compactById);

        const groups = new Map();
        for (const view of controller.catalogue) {
          if (featuredIds.has(view.view_id) || pinnedIds.has(view.view_id)) continue;
          if (!groups.has(view.section)) groups.set(view.section, []);
          groups.get(view.section).push(view);
        }
        groups.forEach(function (views, section) {
          appendGroup(fragment, section, views, false, pinnedIds, compactById);
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
        return item.getAttribute("aria-current") === "page";
      }) || items[0];
      items.forEach(function (item) { item.tabIndex = item === roving ? 0 : -1; });
    }

    function scheduleRender() {
      if (controller.renderFrame !== null) cancelAnimationFrame(controller.renderFrame);
      controller.renderFrame = requestAnimationFrame(render);
    }

    function setMode(mode, focusTab) {
      if (mode !== "grouped" && mode !== "az" && mode !== "my") return;
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
      if (core.syncViewExplanation) core.syncViewExplanation();
      controller.pinned = loadPinnedViews(controller.catalogue);
      savePinnedViews(controller.pinned);
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
    window.addEventListener("plotsrv-my-views-changed", scheduleRender);
    results.addEventListener("click", async function (event) {
      const personal = event.target.closest && event.target.closest("[data-personal-view], [data-personal-delete]");
      if (personal) {
        event.preventDefault(); event.stopPropagation();
        const deleting = personal.hasAttribute("data-personal-delete");
        const id = personal.getAttribute(deleting ? "data-personal-delete" : "data-personal-view");
        const item = core.viewSpec.read().items.find(value => value.id === id);
        if (!item) { render(); return; }
        if (deleting) {
          if (await core.deletePersonalView(item)) {
            if (controller.renderFrame !== null) cancelAnimationFrame(controller.renderFrame);
            render();
            const next = results.querySelector("[data-personal-delete]") || search;
            if (next) next.focus();
          }
        } else window.location.href = core.personalViewUrl(item);
        return;
      }
      const pin = event.target.closest && event.target.closest("[data-pin-view]");
      if (pin) {
        event.preventDefault();
        event.stopPropagation();
        const pinnedViewId = pin.getAttribute("data-pin-view");
        controller.pinned = togglePinnedView(
          pinnedViewId,
          controller.catalogue
        );
        render();
        const pinButtons = Array.from(results.querySelectorAll("[data-pin-view]"));
        const nextPin = pinButtons.find(function (button) {
          return button.getAttribute("data-pin-view") === pinnedViewId;
        });
        if (nextPin) nextPin.focus();
        return;
      }
      const item = event.target.closest && event.target.closest("[data-plotsrv-view]");
      if (!item) return;
      const viewId = item.getAttribute("data-plotsrv-view");
      if (!viewId) return;
      window.location.href = window.location.pathname + "?view=" + encodeURIComponent(viewId);
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
    else if (core.syncViewExplanation) core.syncViewExplanation();
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
  core.resolveCompactViews = resolveCompactViews;
  core.initialViewSelectorMode = initialViewSelectorMode;
  core.saveViewSelectorMode = saveViewSelectorMode;
  core.loadPinnedViews = loadPinnedViews;
  core.togglePinnedView = togglePinnedView;
  core.updateViewSelectorCatalogue = updateViewSelectorCatalogue;
  core.bindViewDropdown = bindViewDropdown;
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

  function decodePlot(url, signal) {
    const image = new Image();
    return new Promise(function (resolve, reject) {
      function cleanup() {
        image.onload = image.onerror = null;
        if (signal) signal.removeEventListener("abort", abort);
      }
      function done() { cleanup(); resolve(image); }
      function failed(error) { cleanup(); image.src = ""; reject(error); }
      function abort() { failed(new DOMException("Plot load cancelled", "AbortError")); }
      if (signal && signal.aborted) { abort(); return; }
      if (signal) signal.addEventListener("abort", abort, {once: true});
      image.src = url;
      if (typeof image.decode === "function") image.decode().then(done, failed);
      else {
        image.onload = done;
        image.onerror = () => failed(new Error("Plot image could not be decoded"));
        if (image.complete) {
          if (image.naturalWidth) done();
          else failed(new Error("Plot image could not be decoded"));
        }
      }
    });
  }

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

    const load = core.beginSnapshotLoad ? core.beginSnapshotLoad("plot") :
      {current: () => true, finish: () => {}, signal: undefined};
    let candidateUrl = null;
    try {
      const res = await (core.fetchView || fetch)(url, {signal: load.signal});
      if (!load.current()) return false;
      if (!res.ok) {
        if (
          res.status === 404 && !!snapshotQuery &&
          typeof core.handleMissingSnapshot === "function"
        ) {
          await core.handleMissingSnapshot("plot");
          return false;
        }
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage("Failed to load plot snapshot (" + res.status + ").");
        }
        return false;
      }

      const blob = await res.blob();
      if (!load.current() || (load.signal && load.signal.aborted)) return false;
      candidateUrl = URL.createObjectURL(blob);
      await decodePlot(candidateUrl, load.signal);
      if (!load.current() || (load.signal && load.signal.aborted)) return false;
      const previousUrl = state.plotObjectUrl;
      img.src = candidateUrl;
      img.hidden = false;
      state.plotObjectUrl = candidateUrl;
      candidateUrl = null;
      if (previousUrl) URL.revokeObjectURL(previousUrl);

      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("");
      }

      if (typeof core.refreshStatus === "function") {
        core.refreshStatus();
      }
      return true;
    } catch (e) {
      if (!load.current()) return false;
      if (typeof core.setStatusMessage === "function") {
        core.setStatusMessage("Failed to load plot snapshot (network error or timeout).");
      }
      return false;
    } finally {
      if (candidateUrl) URL.revokeObjectURL(candidateUrl);
      load.finish();
    }
  }

  function exportImage() {
    if (core.inspectionCapture && core.inspectionCapture()) {
      const a = document.createElement("a"); a.href = state.plotObjectUrl;
      a.download = "plotsrv-captured-plot.png"; a.click(); return true;
    }
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

/* plotsrv source: js/core/expanded_view.js */
(function () {
  "use strict";
  const {core, state, config} = window.PLOTSRV;
  const layout = state.expandedView = {active: false, revealed: false};
  const key = "plotsrv:expanded:" + encodeURIComponent(config.dashboardName || "default") + ":" + window.location.pathname;
  const transfers = [];
  let bound = false;
  let frame = null;
  let opener = null;
  let resizeObserver = null;
  let previousHeaderHidden = false;
  let previousDockHidden = false;
  let escapeHadOverlay = false;

  function visible(node) {
    return !!node && !node.closest("[hidden]") && node.getClientRects().length > 0;
  }

  function overlayOpen() {
    return Array.from(document.querySelectorAll(
      'dialog[open], [role="dialog"], [role="menu"], [role="listbox"], [aria-haspopup][aria-expanded="true"]'
    )).some(visible);
  }

  function persist() {
    try {
      if (layout.active) window.sessionStorage.setItem(key, "1");
      else window.sessionStorage.removeItem(key);
    } catch (error) { /* Storage denial leaves a working page-local layout. */ }
  }

  function restoreTransfer(item) {
    if (item.anchor.isConnected) item.anchor.replaceWith(item.node);
    else item.node.remove();
  }

  function transfer(selector, parent, content) {
    const node = document.querySelector(selector);
    if (!node || transfers.some(item => item.node === node)) return false;
    const anchor = document.createComment("expanded control position");
    node.before(anchor);
    parent.append(node);
    transfers.push({node, anchor, content});
    return true;
  }

  // Return renderer-owned controls before its containing DOM is replaced.
  // Static header/snapshot controls keep their original listeners throughout.
  function restoreContentControls() {
    for (let i = transfers.length - 1; i >= 0; i--) {
      if (!transfers[i].content) continue;
      if (layout.active && transfers[i].node.contains(document.activeElement)) {
        document.getElementById("expanded-reveal").focus({preventScroll: true});
      }
      restoreTransfer(transfers[i]);
      transfers.splice(i, 1);
    }
  }

  function scheduleGeometry() {
    if (frame !== null) return;
    frame = window.requestAnimationFrame(function () {
      frame = null;
      const panel = document.getElementById("expanded-controls");
      const top = layout.active && layout.revealed && panel ? Math.ceil(panel.getBoundingClientRect().bottom) + 8 : 52;
      document.body.style.setProperty("--ps-expanded-top", top + "px");
      // CSS sizes plots without rebuilding SVG/zoom state. Tabulator only
      // redraws its existing virtual window; never reload rows for a resize.
      for (const table of new Set([state.tabulatorInstance, state.streamTabulatorInstance])) {
        if (!table || !table.element || !table.element.isConnected || !table.initialized) continue;
        const holder = table.element.querySelector(".tabulator-tableholder");
        const scroll = holder ? [holder.scrollLeft, holder.scrollTop] : null;
        if (typeof table.redraw === "function") table.redraw(false);
        if (holder && scroll) { holder.scrollLeft = scroll[0]; holder.scrollTop = scroll[1]; }
      }
      if (core.syncDockClearance) core.syncDockClearance();
    });
  }

  function sync() {
    if (!layout.active) return;
    const panel = document.getElementById("expanded-controls");
    if (!panel) return;
    for (let i = transfers.length - 1; i >= 0; i--) {
      if (transfers[i].anchor.isConnected) continue;
      transfers[i].node.remove();
      transfers.splice(i, 1);
    }
    let changed = false;
    for (const selector of [".ps-table-mode-switch", "#stream-history-picker", "#stream-pause-button"]) {
      changed = transfer(selector, panel, true) || changed;
    }
    if (changed) scheduleGeometry();
  }

  function reveal(value, options) {
    if (!layout.active) return false;
    const panel = document.getElementById("expanded-controls");
    const button = document.getElementById("expanded-reveal");
    if (!value && overlayOpen()) return false;
    layout.revealed = !!value;
    if (!value && panel.contains(document.activeElement)) button.focus();
    panel.hidden = !value;
    button.setAttribute("aria-expanded", String(!!value));
    button.setAttribute("aria-label", value ? "Hide view controls" : "Show view controls");
    button.title = value ? "Hide view controls" : "Show view controls";
    if (value && !(options && options.keepFocus)) {
      const target = panel.querySelector('.ps-viewselect__btn, #header-status-button, button:not([disabled])');
      if (target) target.focus({preventScroll: true});
    }
    scheduleGeometry();
    return true;
  }

  function setExpanded(active, options) {
    if (!bound || !!active === layout.active) return layout.active;
    // Prompt 17 can call prepareForCompare() before opening its dock, and
    // holds this flag while open. No nested presentation/dock controllers.
    if (active && (state.compareActive || overlayOpen())) return false;
    const header = document.getElementById("site-header");
    const dock = document.querySelector(".ps-bottom-dock");
    const panel = document.getElementById("expanded-controls");
    const handle = document.getElementById("expanded-handle");
    const scroll = [window.scrollX, window.scrollY];
    layout.active = !!active;
    document.body.classList.toggle("ps-expanded", layout.active);
    if (active) {
      opener = document.activeElement;
      previousHeaderHidden = header.hidden;
      previousDockHidden = dock ? dock.hidden : false;
      transfer("#site-header .header-right", panel, false);
      transfer("#snapshots-control", panel, false);
      sync();
      header.hidden = true;
      if (dock) dock.hidden = true;
      handle.hidden = false;
      reveal(false);
      document.getElementById("expanded-reveal").focus({preventScroll: true});
      if (typeof ResizeObserver === "function") {
        resizeObserver = new ResizeObserver(scheduleGeometry);
        resizeObserver.observe(panel);
      }
      window.addEventListener("resize", scheduleGeometry);
    } else {
      if (resizeObserver) resizeObserver.disconnect();
      resizeObserver = null;
      window.removeEventListener("resize", scheduleGeometry);
      for (let i = transfers.length - 1; i >= 0; i--) restoreTransfer(transfers[i]);
      transfers.length = 0;
      header.hidden = previousHeaderHidden;
      if (dock) dock.hidden = previousDockHidden;
      handle.hidden = panel.hidden = true;
      layout.revealed = false;
      if (!(options && options.restoreFocus === false)) {
        const target = visible(opener) ? opener : document.getElementById("expand-view");
        if (target) target.focus({preventScroll: true});
      }
      scheduleGeometry();
    }
    if (core.bottomBar) core.bottomBar.present();
    persist();
    window.scrollTo(scroll[0], scroll[1]);
    return layout.active;
  }

  function bind() {
    if (bound || !document.getElementById("expand-view")) return;
    bound = true;
    document.getElementById("expand-view").addEventListener("click", function () {
      if (state.compareActive && core.compare) {core.compare.exit(); this.focus();}
      setExpanded(true);
    });
    document.getElementById("expanded-exit").addEventListener("click", () => setExpanded(false));
    document.getElementById("expanded-reveal").addEventListener("click", () => reveal(!layout.revealed, {keepFocus: true}));
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") escapeHadOverlay = overlayOpen();
    }, true);
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !layout.active || event.defaultPrevented || escapeHadOverlay) return;
      event.preventDefault();
      setExpanded(false);
    });
    window.addEventListener("pagehide", function () {
      if (resizeObserver) resizeObserver.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
      frame = null;
    });
    window.addEventListener("pageshow", function () {
      if (layout.active) {
        if (resizeObserver) resizeObserver.observe(document.getElementById("expanded-controls"));
        scheduleGeometry();
      }
    });
    try { if (window.sessionStorage.getItem(key) === "1") setExpanded(true); }
    catch (error) { /* No storage requirement. */ }
  }

  core.expandedView = {
    state: layout, set: setExpanded, reveal,
    prepareForCompare: () => setExpanded(false, {restoreFocus: false}),
  };
  core.bindExpandedView = bind;
  core.syncExpandedView = sync;
  core.restoreExpandedContentControls = restoreContentControls;
})();

/* plotsrv source: js/core/compare.js */
(function () {
  "use strict";
  const {core, state, config} = window.PLOTSRV;
  const ui = state.compare = {mode: "timeline", day: new Date().toISOString().slice(0, 10), month: "", rows: [], days: {}, next: null, count: 0, loading: false, error: ""};
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
  function capture() { return !state.currentSnapshot && (state.compareCandidate || state.compareCapture); }
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
    el("compare-enter").title = el("compare-enter").disabled ? "History becomes available when stored snapshots exist." : "Browse stored snapshots using Timeline or List";
    if (!state.compareActive) return;
    const pinned = capture(), selected = core.currentHistoryMeta();
    label("compare-selected", state.currentSnapshot
      ? selected && selected.created_at ? stamp(selected.created_at) : "Loading snapshot…"
      : pinned ? "Latest · " + stamp(pinned.created_at) : "Latest — waiting for capture");
    el("compare-selected").title = el("compare-selected").textContent + (pinned ? " · " + pinned.scope : "");
    for (const dir of ["older", "newer"]) {
      const source = el("snapshot-" + dir), target = el("compare-" + dir);
      target.disabled = !source || source.disabled;
      target.title = source ? source.title : "Unavailable";
    }
    const message = nav.error || ui.error || (nav.loadingVisible ? "Loading selected version…" : ui.loading ? "Loading stored metadata…" : state.currentSnapshot && selected && selected.created_at.slice(0, 10) !== ui.day ? "Selected version is outside this displayed day." : pinned ? pinned.scope + ". Held for inspection; choose Latest again to capture current data." : "");
    label("compare-message", message);
    el("compare-message").title = message;
    label("compare-day", dayLabel(ui.day));
    for (const mode of ["timeline", "list"]) {
      el("compare-" + mode + "-tab").setAttribute("aria-pressed", String(ui.mode === mode));
      el("compare-" + mode).hidden = ui.mode !== mode;
    }
    el("compare-more").hidden = !ui.next;
    el("compare-more").disabled = ui.loading;
    label("compare-count", ui.count + (ui.count === 1 ? " snapshot" : " snapshots") + " · " + ui.rows.length + " shown · UTC");
    for (const button of el("compare-results").querySelectorAll("[data-snapshot]")) button.setAttribute("aria-pressed", String(button.dataset.snapshot === state.currentSnapshot));
  }
  function renderRows() {
    const list = el("compare-list"), timeline = el("compare-points");
    list.replaceChildren(); timeline.replaceChildren();
    const [start, end] = bounds(ui.day), span = Date.parse(end) - Date.parse(start);
    for (const row of ui.rows) {
      const button = document.createElement("button"); button.type = "button";
      button.dataset.snapshot = row.snapshot_id;
      button.textContent = stamp(row.created_at) + (row.kind ? " · " + row.kind : "");
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
    if (!state.currentSnapshot) core.snapshotNavigation.select(null);
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
    el("compare-latest").addEventListener("click", () => core.snapshotNavigation.select(null));
    for (const mode of ["timeline", "list"]) el("compare-" + mode + "-tab").addEventListener("click", () => {ui.mode = mode; sync();});
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
  const config = window.PLOTSRV.config;

  let pendingContentLoads = 0;
  let loadingTimer = null;
  function beginContentLoading() {
    const content = document.getElementById("view-content");
    const indicator = document.getElementById("content-loading");
    if (!content || !indicator || config.kind === "none" ||
        (config.kind === "table" && !document.getElementById("table-grid")) ||
        (config.kind === "stream" && content.dataset.contentReady === "true")) return function () {};
    pendingContentLoads += 1;
    if (pendingContentLoads === 1) {
      content.setAttribute("aria-busy", "true");
      loadingTimer = window.setTimeout(function () { indicator.hidden = false; }, 180);
    }
    let finished = false;
    return function (applied) {
      if (finished) return;
      finished = true;
      pendingContentLoads -= 1;
      if (pendingContentLoads) return;
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
      indicator.hidden = true;
      content.setAttribute("aria-busy", "false");
      if (applied) content.dataset.contentReady = "true";
    };
  }

  function waitForContentImage() {
    const image = document.getElementById("plot");
    if (!image || image.complete) return Promise.resolve();
    return new Promise(function (resolve) {
      const timer = window.setTimeout(done, 10000);
      function done() {
        window.clearTimeout(timer);
        image.removeEventListener("load", done);
        image.removeEventListener("error", done);
        resolve();
      }
      image.addEventListener("load", done);
      image.addEventListener("error", done);
      if (image.complete) done();
    });
  }

  function refreshChromeAfterLoad() {
    if (core.checkPersonalViewSurface) core.checkPersonalViewSurface();
    if (typeof core.configureBottomBar === "function") {
      core.configureBottomBar();
    }
    if (typeof core.refreshStatus === "function") {
      // Stream updates can arrive many times per second. Their data response
      // already carries lifecycle state, so do not mirror every event with a
      // second /status request. The first load and opening the detail modal
      // still fetch a complete status snapshot.
      if (config.kind === "stream" && state.latestStatusPayload) {
        return Promise.resolve();
      }
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
        return core.loadArtifact();
      }
      return Promise.resolve();
    }

    if (document.getElementById("stream-grid")) {
      if (typeof core.loadStream === "function") {
        return core.loadStream();
      }
      return Promise.resolve();
    }

    if (document.getElementById("table-grid") || document.getElementById("simple-table-root")) {
      if (typeof core.loadTable === "function") {
        return core.loadTable();
      }
      return Promise.resolve();
    }

    if (document.getElementById("plot")) {
      if (typeof core.refreshPlot === "function") {
        return core.refreshPlot();
      }
      return Promise.resolve();
    }

    return Promise.resolve();
  }

  core.reloadCurrentView = function () {
    if (state.reloadCurrentViewPromise) {
      return state.reloadCurrentViewPromise;
    }

    if (document.hidden) {
      return Promise.resolve(false);
    }

    const finishLoading = beginContentLoading();
    const refreshPromise = Promise.resolve().then(reloadCurrentViewNow).then(function (result) {
      return waitForContentImage().then(function () { return result; });
    });
    state.reloadCurrentViewPromise = refreshPromise;

    function clearInFlight(applied) {
      if (applied !== false) state.initialViewLoadComplete = true;
      finishLoading(applied !== false);
      if (state.reloadCurrentViewPromise === refreshPromise) {
        state.reloadCurrentViewPromise = null;
      }
    }

    refreshPromise.then(clearInFlight, function () { clearInFlight(false); });
    // Content is ready as soon as its renderer finishes. Status/catalogue
    // requests must not hold the loading indicator or the next reload open.
    refreshPromise.then(refreshChromeAfterLoad, refreshChromeAfterLoad).catch(function () {});
    return refreshPromise;
  };

  core.ensureInitialViewLoaded = function () {
    if (state.initialViewLoadComplete || document.hidden) return Promise.resolve(false);
    if (state.initialViewLoadPromise) return state.initialViewLoadPromise;

    const initialPromise = core.reloadCurrentView().then(function (applied) {
      if (applied !== false) {
        if (core.markInitialViewLoaded) core.markInitialViewLoaded();
        if (!(core.isHistoryMode && core.isHistoryMode()) && core.markBrowserViewApplied) {
          core.markBrowserViewApplied();
        }
      }
      if (core.showPendingSnapshotNotice) core.showPendingSnapshotNotice();
      return applied;
    }).catch(function () { return false; }).then(function (applied) {
      state.initialViewLoadPromise = null;
      // A failed first request is not successful content, but later update
      // notices must be allowed to recover it. A hidden/skipped startup never
      // reaches this point and is retried when the page becomes visible.
      state.initialViewLoadAttempted = true;
      if (core.bindUpdateNotifications) core.bindUpdateNotifications();
      return applied;
    });
    state.initialViewLoadPromise = initialPromise;
    return initialPromise;
  };

  core.bootstrap = function () {
    if (core.bindViewExplanation) core.bindViewExplanation();
    if (core.bindExpandedView) core.bindExpandedView();
    if (typeof core.bindSettings === "function") {
      core.bindSettings();
    }

    if (typeof core.bindStreamInsights === "function") {
      core.bindStreamInsights();
    }

    if (typeof core.bindStreamPauseControl === "function") {
      core.bindStreamPauseControl();
    }

    if (typeof core.bindStreamControlsDisclosure === "function") {
      core.bindStreamControlsDisclosure();
    }

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

    if (core.bindCompare) core.bindCompare();
    const loadHistoryPromise =
      typeof core.loadHistory === "function"
        ? core.loadHistory()
        : Promise.resolve();

    // Metadata is independent of the selected content URL. Do not make a
    // slow history directory hold up Latest or an explicitly selected version.
    Promise.resolve(loadHistoryPromise).then(function () {
      if (core.syncHistoryUi) core.syncHistoryUi();
      if (core.showPendingSnapshotNotice) core.showPendingSnapshotNotice();
    }).catch(function () {});
    if (core.syncHistoryUi) core.syncHistoryUi();
    core.ensureInitialViewLoaded();
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof core.bootstrap === "function") {
      core.bootstrap();
    }
  });
})();

