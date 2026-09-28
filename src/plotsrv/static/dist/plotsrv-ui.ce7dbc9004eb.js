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
   viewSelectorLayout: "plotsrv:v1:view_selector_layout",
   featuredDisplay: "plotsrv:v1:featured_display",
   viewSelectorPinned: "plotsrv:v1:view_selector_pinned",
   theme: "plotsrv:v1:theme",
   continuousUpdates: "plotsrv:v1:continuous_updates",
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
    const historical = state.currentSnapshot || state.streamHistoricalSessionId;
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
  const { core, state } = window.PLOTSRV;
  const derived = new WeakMap();
  let profile = null,
    rawColumns = [],
    opening = false,
    selectedName = null;

  function supportsInterpretation() {
    const fields = profile && profile.fields;
    return !!fields && (profile.label
      ? ["time", "level", "logger", "message"].every(role => fields[role])
      : ["time", "method", "path", "status"].every(role => fields[role]));
  }

  function profileLabel() {
    return (profile && profile.label) || "HTTP access log";
  }

  function interpretationModel() {
    const available = supportsInterpretation();
    const manual = available && state.streamInterpretationOverride === "default";
    return {
      available: available,
      mode: manual ? "default" : "auto",
      manual: manual,
      label: manual ? "Default stream" : profileLabel(),
    };
  }

  function closeInterpretationMenu(details) {
    if (details) details.open = false;
  }

  core.mountStreamInterpretationControl = function (target) {
    if (!target) return;
    const host = document.getElementById("stream-interpretation-host") || target;
    const model = interpretationModel();
    const existing = host.querySelector(":scope > .ps-stream-interpretation");
    if (!model.available) {
      if (existing) existing.remove();
      return;
    }
    if (existing && existing.dataset.mode === model.mode) return;

    const wrapper = document.createElement("span");
    wrapper.className = "ps-stream-interpretation";
    wrapper.dataset.mode = model.mode;
    const prefix = document.createElement("span");
    prefix.className = "ps-stream-interpretation__prefix";
    prefix.textContent = model.manual ? "Chosen as" : "Detected as";
    const details = document.createElement("details");
    details.className = "ps-stream-interpretation__menu";
    const summary = document.createElement("summary");
    summary.setAttribute("aria-label", "Stream interpretation: " + model.label);
    summary.innerHTML = model.manual
      ? '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 5h12M6 12h12M6 19h12"></path></svg>'
      : '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8"></circle><path d="M4 12h16M12 4a13 13 0 0 1 0 16M12 4a13 13 0 0 0 0 16"></path></svg>';
    const current = document.createElement("span");
    current.textContent = model.label;
    const chevron = document.createElement("span");
    chevron.className = "ps-stream-interpretation__chevron";
    chevron.setAttribute("aria-hidden", "true");
    summary.append(current, chevron);
    details.appendChild(summary);
    details.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !details.open) return;
      details.open = false;
      summary.focus();
    });
    details.addEventListener("toggle", function () {
      if (!details.open) return;
      window.setTimeout(function () {
        document.addEventListener("pointerdown", function closeOnOutsideClick(event) {
          if (!details.contains(event.target)) details.open = false;
        }, {once: true});
      }, 0);
    });

    const list = document.createElement("span");
    list.className = "ps-stream-interpretation__options";
    list.setAttribute("role", "menu");
    const choices = [
      {mode: "auto", label: (model.manual ? "Return to auto — " : "Auto — ") + profileLabel()},
      {mode: "default", label: "Default stream"},
    ];
    for (const choice of choices) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ps-stream-interpretation__option";
      button.dataset.mode = choice.mode;
      button.setAttribute("role", "menuitemradio");
      button.setAttribute("aria-checked", String(choice.mode === model.mode));
      const label = document.createElement("span");
      label.textContent = choice.label;
      const check = document.createElement("span");
      check.className = "ps-stream-interpretation__check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = choice.mode === model.mode ? "✓" : "";
      button.append(label, check);
      button.addEventListener("click", async function () {
        closeInterpretationMenu(details);
        if (choice.mode === model.mode) return;
        if (typeof core.applyStreamInterpretation === "function") {
          await core.applyStreamInterpretation(choice.mode);
        }
      });
      list.appendChild(button);
    }
    details.appendChild(list);
    wrapper.append(prefix, details);
    if (existing) existing.replaceWith(wrapper);
    else host.appendChild(wrapper);
  };

  core.getStreamInterpretation = interpretationModel;
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
    if (errorMessage && typeof core.setStatusMessage === "function") {
      core.setStatusMessage(errorMessage);
    }
  }
  core.clearHttpSuggestionSelection = function () {
    selectedName = null;
    if (document.getElementById("http-suggestions")) core.mountHttpSuggestions();
  };
  core.prepareHttpSuggestions = function (data) {
    rawColumns = data.columns.slice();
    const http = data.http_profile && data.http_profile.version === 1 &&
      data.http_profile.recipes.length ? data.http_profile : null;
    const log = data.log_profile && data.log_profile.version === 1 &&
      data.log_profile.recipes.length ? data.log_profile : null;
    profile = http || log || (data.http_profile && data.http_profile.version === 1
      ? data.http_profile : null);
    state.httpProfile = profile;
    const projectionKey = profile === log ? "log_projection" : "http_projection";
    const fields = Object.values((profile && profile.fields) || {});
    const allowed = new Set(fields);
    data.columns = rawColumns.concat(fields);
    for (const record of data.records) {
      const projection = record[projectionKey];
      if (!projection || !fields.length) continue;
      const row = Object.assign(Object.create(null), record.data),
        keys = [];
      for (const [role, key] of Object.entries(profile.fields)) {
        if (
          Object.prototype.hasOwnProperty.call(projection, role) &&
          !Object.prototype.hasOwnProperty.call(row, key)
        ) {
          row[key] = projection[role];
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
      const topbar = save.closest(".ps-table-topbar");
      topbar?.classList.add("ps-http-topbar");
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
      area.appendChild(select);
      const filters = document.getElementById("table-filters-toggle-btn");
      const columns = document.getElementById("table-columns-toggle-btn");
      const actions = save.closest(".ps-my-view-actions");
      const row = document.createElement("div");
      row.id = "stream-secondary-controls";
      row.className = "ps-stream-secondary-controls";
      const interpretation = document.createElement("span");
      interpretation.id = "stream-interpretation-host";
      interpretation.className = "ps-stream-interpretation-host";
      row.append(interpretation, area);
      if (filters) row.appendChild(filters);
      if (columns) row.appendChild(columns);
      if (actions) row.appendChild(actions);
      topbar?.appendChild(row);
    }
    const recipes = (profile && profile.recipes) || [];
    const select = area.querySelector("select");
    const signature = JSON.stringify([profileLabel(), ...recipes.map((r) => r.name)]);
    // Keep keyboard focus/open native menus stable across ordinary appends.
    if (select.dataset.signature !== signature) {
      select.replaceChildren(new Option(
        recipes.length ? "✦ Suggested views " + recipes.length : "Suggested views",
        ""
      ));
      select.options[0].disabled = true;
      const group = document.createElement("optgroup");
      group.label = "Based on " + profileLabel();
      recipes.forEach((recipe, index) =>
        group.appendChild(new Option(recipe.name, String(index))),
      );
      if (recipes.length) select.appendChild(group);
      select.dataset.signature = signature;
    }
    area.classList.toggle("is-available", recipes.length > 0);
    // This is the chosen starting presentation, even after manual edits.
    // Match by name because available recipes can change order as data arrives.
    if (!opening) {
      const selected = recipes.findIndex(recipe => recipe.name === selectedName);
      const value = selected < 0 ? "" : String(selected);
      if (select.value !== value) select.value = value;
    }
    select.disabled = opening || !recipes.length;
    select.removeAttribute("title");
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
    const continuousUpdates = document.getElementById("settings-continuous-updates");
    if (continuousUpdates) continuousUpdates.checked = core.continuousUpdatesEnabled();
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
    const continuousUpdates = document.getElementById("settings-continuous-updates");
    if (continuousUpdates) {
      continuousUpdates.checked = core.continuousUpdatesEnabled();
      continuousUpdates.addEventListener("change", function () {
        core.savePref(core.storageKeys.continuousUpdates, continuousUpdates.checked ? "1" : "0");
        if (continuousUpdates.checked && typeof core.notifyUpdateEligibilityChanged === "function") {
          core.notifyUpdateEligibilityChanged();
        }
      });
    }

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

    if (sel) {
      sel.value = state.currentSnapshot || "";
    }

    const unavailableReturn = document.getElementById("snapshots-return-latest");
    if (unavailableReturn) {
      unavailableReturn.hidden = !isHistory && !navigation.error;
    }
    syncSnapshotModeBanner();

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
          loadHistory();
          const applied = core.reloadCurrentView ? await core.reloadCurrentView() : true;
          if (revision !== navigation.revision) continue;
          if (view !== config.activeViewId) {
            selectionFailed("Source changed before the selected version loaded.");
            break;
          }
          if (applied === false && !navigation.error) selectionFailed("Selected version could not be loaded.");
          if (!navigation.error) {
            navigation.displayed = state.currentSnapshot;
            announce("");
            if (!state.currentSnapshot && core.markBrowserViewApplied) core.markBrowserViewApplied();
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
      observe: "/static/logo_observe.png",
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
      if (lifecycle === "held") {
        return {
          visible: config.showHeaderFreshness,
          tone: "error",
          label: "Stream held",
          context: "Remote upload budget reached",
          title: "Stream delivery is held",
          copy: "The publisher paused record delivery after reaching its remote upload budget. The source log continues independently. To resume sooner, change stream-settings.remote_upload_max_mb_per_day in the publisher's plotsrv configuration.",
        };
      }
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
    const updateNow = document.getElementById("header-update-now");
    if (updateNow) {
      updateNow.hidden = presentation.tone !== "new-data" ||
        state.headerStatus.viewMode !== "latest" ||
        (config.kind === "stream" && state.streamPaused);
      wrap.toggleAttribute("data-quick-update", !updateNow.hidden);
    }
    if (typeof core.renderCheckAttention === "function") core.renderCheckAttention();
    if (typeof core.renderStatusModal === "function") core.renderStatusModal();
  }

  function setHeaderViewState(viewMode, snapshot) {
    state.headerStatus.viewMode = viewMode === "snapshot" ? "snapshot" : "latest";
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
    const updateNow = document.getElementById("header-update-now");
    if (updateNow) updateNow.addEventListener("click", function () {
      if (typeof core.applyPendingUpdate !== "function") return;
      updateNow.disabled = true;
      Promise.resolve(core.applyPendingUpdate({force: true})).finally(function () {
        updateNow.disabled = false;
      });
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
          snapshotId: event && typeof event.snapshot_id === "string" ? event.snapshot_id : null,
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
      let snapshotCount = 0;
      visible.forEach(function (event, index) {
        const stored = !!event.snapshotId && typeof core.snapshotNavigation?.select === "function";
        const dot = document.createElement(stored ? "button" : "span");
        const position = Math.max(1.5, Math.min(98.5, ((event.time - start) / (now - start)) * 100));
        const size = Math.min(13, 6 + Math.log2(event.count));
        dot.className = "ps-arrival-chart__dot";
        dot.style.left = stored
          ? "clamp(14px, " + position + "%, calc(100% - 14px))"
          : position + "%";
        dot.style.setProperty("--dot-size", size + "px");
        dot.style.bottom = 13 + (index % 3) * 9 - (stored ? (28 - size) / 2 : 0) + "px";
        if (stored) {
          snapshotCount += 1;
          dot.classList.add("ps-arrival-chart__dot--snapshot");
          dot.type = "button";
          dot.title = "Snapshot available — click to open · " + core.fmtLocalTime(event.receivedAt);
          dot.setAttribute("aria-label", dot.title);
          dot.addEventListener("click", function () {
            core.closeStatusModal();
            core.snapshotNavigation.select(event.snapshotId);
          });
        } else {
          dot.title = "Published update · " + core.fmtLocalTime(event.receivedAt);
          dot.setAttribute("aria-hidden", "true");
        }
        track.appendChild(dot);
      });
      const legend = document.getElementById("status-modal-snapshot-legend");
      if (legend) legend.hidden = snapshotCount === 0;
      if (detail) {
        detail.hidden = true;
        detail.textContent = "";
      }
    }
    if (config.kind === "stream") {
      const legend = document.getElementById("status-modal-snapshot-legend");
      if (legend) legend.hidden = true;
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
      setAttribute("status-modal-overview", "data-status-tone", presentation.tone);
      setAttribute("status-modal-health", "data-status-tone", presentation.tone);
      setText("status-modal-health-label", presentation.label === "Live" ? "Up to date" : presentation.label);
      setText("status-modal-health-copy", presentation.label === "Live"
        ? "The latest data shown in this browser is within its freshness policy." : presentation.copy);
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
      complete.textContent = !isHistory && typeof sourceDownload === "string" && sourceDownload
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

  function continuousUpdatesEnabled() {
    return typeof core.loadPref === "function" &&
      core.loadPref(core.storageKeys.continuousUpdates, "0") === "1";
  }

  // The single policy boundary for every renderer. Explicit application
  // bypasses interaction blockers, but never changes historical selections.
  function getAutomaticUpdateBlockers() {
    const blockers = [];
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

    if (continuousUpdatesEnabled()) return blockers;

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
    return blocker === "snapshot" || blocker === "historical_stream_session" ||
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
  core.continuousUpdatesEnabled = continuousUpdatesEnabled;
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
    observe: "/static/logo_observe.png",
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
      observe: "Observation",
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

  function loadFeaturedDisplay() {
    const key = storageKey("featuredDisplay", "plotsrv:v1:featured_display");
    const stored = typeof core.loadPref === "function"
      ? core.loadPref(key, "expanded")
      : loadLocalPreference(key, "expanded");
    return stored === "compact" ? "compact" : "expanded";
  }

  function loadLocalPreference(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function saveFeaturedDisplay(display) {
    const key = storageKey("featuredDisplay", "plotsrv:v1:featured_display");
    if (typeof core.savePref === "function") {
      core.savePref(key, display);
      return;
    }
    try {
      localStorage.setItem(key, display);
    } catch (e) {
      // Browser storage can be unavailable in private/restricted contexts.
    }
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
    const layouts = wrap.querySelector(".ps-viewselect__layouts");
    const results = wrap.querySelector(".ps-viewselect__results");
    if (!trigger || !menu || !search || !tabs || !results) return null;

    const controller = {
      catalogue: normalizeViewCatalogue(config.viewCatalogue),
      mode: "grouped",
      layout: core.loadPref && core.loadPref(core.storageKeys.viewSelectorLayout, "standard") === "compact" ? "compact" : "standard",
      query: "",
      pinned: [],
      featuredDisplay: loadFeaturedDisplay(),
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

    function arrangeCompactColumns(fragment) {
      const groups = Array.from(fragment.children);
      const count = groups.reduce(function (sum, group) {
        const list = group.querySelector("[role='list']");
        return sum + (list ? list.children.length : 0);
      }, 0);
      if (!count) return;
      const columns = [element("div", "ps-viewselect__column"), element("div", "ps-viewselect__column")];
      const leftTarget = Math.ceil(count / 2);
      let leftCount = 0;
      for (const group of groups) {
        const list = group.querySelector("[role='list']");
        if (!list) { columns[leftCount < leftTarget ? 0 : 1].appendChild(group); continue; }
        const rows = Array.from(list.children);
        const leftTake = Math.max(0, Math.min(rows.length, leftTarget - leftCount));
        if (leftTake === 0) { columns[1].appendChild(group); continue; }
        columns[0].appendChild(group);
        leftCount += leftTake;
        if (leftTake < rows.length) {
          const continuation = group.cloneNode(false);
          const heading = group.querySelector(".ps-viewselect__group-label");
          if (heading) continuation.appendChild(heading.cloneNode(true));
          const remainder = list.cloneNode(false);
          rows.slice(leftTake).forEach(function (row) { remainder.appendChild(row); });
          continuation.appendChild(remainder);
          columns[1].appendChild(continuation);
        }
      }
      fragment.replaceChildren.apply(fragment, columns);
    }

    function scrollStorageKey() {
      return "plotsrv:v1:view_selector_scroll:" + controller.mode + ":" + controller.layout;
    }

    function savedScrollTop() {
      try {
        const value = Number(sessionStorage.getItem(scrollStorageKey()));
        return Number.isFinite(value) && value > 0 ? value : 0;
      } catch (e) {
        return 0;
      }
    }

    function saveScrollTop() {
      if (controller.query || menu.hidden) return;
      try {
        sessionStorage.setItem(scrollStorageKey(), String(results.scrollTop));
      } catch (e) {
        // Session storage can be unavailable in restricted browsers.
      }
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
      if (layouts) layouts.querySelectorAll("[data-view-layout]").forEach(function (button) {
        button.setAttribute("aria-pressed", button.getAttribute("data-view-layout") === controller.layout ? "true" : "false");
      });
      menu.classList.toggle("ps-viewselect__menu--compact", controller.layout === "compact");
      results.classList.toggle("ps-viewselect__results--compact", controller.layout === "compact");
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
          const heading = element("div", "ps-viewselect__group-heading");
          heading.appendChild(element("h3", "ps-viewselect__group-label", "Featured"));
          const toggle = element(
            "button",
            "ps-viewselect__featured-toggle",
            controller.featuredDisplay === "compact" ? "Show cards" : "Show as list"
          );
          toggle.type = "button";
          toggle.setAttribute("data-featured-display-toggle", "");
          toggle.setAttribute("aria-label", controller.featuredDisplay === "compact"
            ? "Show featured views as cards" : "Show featured views as a list");
          heading.appendChild(toggle);
          featuredGroup.appendChild(heading);
          const compact = controller.featuredDisplay === "compact";
          const featureList = element("div", compact
            ? "ps-viewselect__group-items" : "ps-viewselect__features");
          featureList.setAttribute("role", "list");
          for (const feature of features) {
            featureList.appendChild(
              compact
                ? makeViewItem(feature.view, false, pinnedIds.has(feature.view.view_id), null)
                : makeFeatureItem(feature, pinnedIds.has(feature.view.view_id))
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
          if (featuredIds.has(view.view_id)) continue;
          if (!groups.has(view.section)) groups.set(view.section, []);
          groups.get(view.section).push(view);
        }
        groups.forEach(function (views, section) {
          appendGroup(fragment, section, views, false, pinnedIds, compactById);
        });
      }

      if (controller.layout === "compact" && controller.mode === "my") {
        const group = element("section", "ps-viewselect__group");
        group.setAttribute("aria-label", "My views");
        group.appendChild(element("h3", "ps-viewselect__group-label", "My views"));
        const list = element("div", "ps-viewselect__group-items");
        list.setAttribute("role", "list");
        Array.from(fragment.querySelectorAll(".ps-viewselect__entry")).forEach(function (row) { list.appendChild(row); });
        if (list.children.length) { group.appendChild(list); fragment.replaceChildren(group); }
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
      if (controller.layout === "compact") arrangeCompactColumns(fragment);
      results.replaceChildren(fragment);
      results.scrollTop = query ? 0 : savedScrollTop();
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
      saveScrollTop();
      controller.mode = mode;
      saveViewSelectorMode(mode);
      render();
      if (focusTab) {
        const selectedTab = tabs.querySelector('[data-view-mode="' + mode + '"]');
        if (selectedTab) selectedTab.focus();
      }
    }

    function clampMenuToViewport() {
      menu.style.left = "";
      menu.style.right = "0";
      const rect = menu.getBoundingClientRect();
      const pad = 8;
      const desiredLeft = Math.max(pad, Math.min(rect.left, window.innerWidth - pad - rect.width));
      menu.style.right = "auto";
      menu.style.left = (desiredLeft - wrap.getBoundingClientRect().left) + "px";
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
    results.addEventListener("scroll", saveScrollTop);
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
    if (layouts) layouts.addEventListener("click", function (event) {
      const button = event.target.closest && event.target.closest("[data-view-layout]");
      if (!button) return;
      saveScrollTop();
      controller.layout = button.getAttribute("data-view-layout") === "compact" ? "compact" : "standard";
      core.savePref(core.storageKeys.viewSelectorLayout, controller.layout);
      render();
      clampMenuToViewport();
      layouts.querySelector('[data-view-layout="' + controller.layout + '"]').focus();
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
      const displayToggle = event.target.closest && event.target.closest("[data-featured-display-toggle]");
      if (displayToggle) {
        event.preventDefault();
        controller.featuredDisplay = controller.featuredDisplay === "compact" ? "expanded" : "compact";
        saveFeaturedDisplay(controller.featuredDisplay);
        render();
        results.querySelector("[data-featured-display-toggle]").focus();
        return;
      }
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
      saveScrollTop();
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
      { value: "in", label: "is one of" },
      { value: "not_in", label: "is not one of" },
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
          element.textContent = core.tableFieldLabel ? core.tableFieldLabel(name) : name;
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

  function hasSameTableFields(table, columns) {
    if (!table || typeof table.getColumns !== "function") return false;
    const existing = table.getColumns();
    if (existing.length !== columns.length) return false;
    const fields = new Set(columns.map(column => column.field));
    return existing.every(column => fields.has(column.getField()));
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
      hiddenColumns: (state.tableDefaultHidden || []).slice(),
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
    if (core.presentationChanged) core.presentationChanged();

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

  const membershipCache = new WeakMap();
  function membershipValues(filter) {
    const value = String(filter.value || "");
    const cached = membershipCache.get(filter);
    if (cached && cached.value === value) return cached.values;
    const values = new Set(value.split(/\r?\n/).map(function (entry) {
      return entry.trim().toLowerCase();
    }).filter(Boolean));
    membershipCache.set(filter, {value: value, values: values});
    return values;
  }

  function isFilterComplete(filter) {
    if (!filter.field || !filter.op) return false;
    if (!operatorNeedsValue(filter.op)) return true;
    if (filter.op === "in" || filter.op === "not_in") return membershipValues(filter).size > 0;
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

  const fieldLabel = field => core.tableFieldLabel ? core.tableFieldLabel(field) : field;

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
      let datetimeHits = 0;
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
        } else if (
          typeof value === "string" &&
          /^\d{4}-\d{2}-\d{2}(?:[T ][^\s]+)?/.test(value.trim()) &&
          Number.isFinite(Date.parse(value))
        ) {
          datetimeHits += 1;
        } else {
          textHits += 1;
        }
      }

      out[field] =
        numericHits > 0 && datetimeHits === 0 && textHits === 0
          ? "number"
          : datetimeHits > 0 && numericHits === 0 && textHits === 0
            ? "datetime"
            : "text";
    }

    return out;
  }

  function getActiveRowCount() {
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    return rows.filter(rowMatchesCurrentTableFilters).length;
  }

  function hasActiveTableFiltering() {
    return getSearchQuery().trim() !== "" || hasActiveFilters();
  }

  function updateTableStatus(data, activeCount, filtering) {
    const status = document.getElementById("status");
    const inline = document.getElementById("table-status-inline");

    if (config.kind === "stream" && inline &&
        typeof core.renderStreamFeedStatus === "function") {
      core.renderStreamFeedStatus(inline, activeCount, filtering);
      if (status) {
        status.textContent = inline.dataset.statusText || "";
      }
      return;
    }

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
      const hasFilter = filtering && typeof activeCount === "number";

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

    if (data.meta && data.meta.materialization === "remote") {
      html += data.meta.full_download
        ? " Complete source hosted."
        : " Preview available; original file is not hosted here.";
      if (data.meta.status !== "available") {
        html += " Source currently unavailable; showing last received content.";
      }
    }
    for (const el of targetEls) {
      el.innerHTML = html;
    }
  }

  function refreshTableStatus() {
    if (!state.tableLastPayload) return;
    const activeCount = getActiveRowCount();
    const filtering = hasActiveTableFiltering();
    updateTableStatus(
      state.tableLastPayload,
      activeCount,
      filtering
    );
    syncFilteredEmptyState(activeCount, filtering);
  }

  function syncFilteredEmptyState(activeCount, filtering) {
    const empty = document.getElementById("table-filter-empty");
    if (!empty) return;
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    empty.hidden = !(
      rows.length > 0 &&
      filtering &&
      activeCount === 0
    );
  }

  function refreshActiveTablePlot(immediate) {
    if (immediate && typeof core.refreshTablePlotImmediately === "function") {
      core.refreshTablePlotImmediately();
    } else if (typeof core.refreshTablePlot === "function") {
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
      option.textContent = fieldLabel(field);
      select.appendChild(option);
    }

    select.value = selected || "";
    select.disabled = fields.length === 0;
  }

  function applyTableGrouping() {
    const table = state.tabulatorInstance;
    const groupingField = normalizeGroupingField();
    if (!table || table.initialized === false || typeof table.setGroupBy !== "function") return;

    if (state.tableAppliedGrouping === groupingField) return;
    if (!groupingField && state.tableAppliedGrouping == null) return;

    try {
      // Group keys are source data, not markup. Tabulator's default header
      // inserts them with innerHTML even when individual cells are escaped.
      if (typeof table.setGroupHeader === "function") {
        table.setGroupHeader(function (value, count) {
          const heading = document.createElement("span");
          heading.textContent = String(value) + " (" + count + " " +
            (count === 1 ? "item" : "items") + ")";
          return heading;
        });
      }
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
                escapeHtml(fieldLabel(f)) +
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

        const multipleValues = op === "in" || op === "not_in";
        const valueInput = multipleValues
          ? '<textarea class="ps-table-filter-value ps-table-filter-value--list" data-filter-part="value" data-filter-id="' +
            escapeHtml(filter.id) + '" rows="1" aria-label="Values, one per line" title="One exact value per line; case-insensitive. Blank lines and surrounding spaces are ignored.">' +
            escapeHtml(filter.value || "") + '</textarea>'
          :
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
          escapeHtml(fieldLabel(field)) +
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

    if (op === "in" || op === "not_in") {
      return fieldLabel(field) + " " + opLabel + " " + String(value).split(/\r?\n/).map(function (entry) {
        return entry.trim();
      }).filter(Boolean).map(function (entry) { return JSON.stringify(entry); }).join(", ");
    }

    if (operatorNeedsTwoValues(op)) {
      return fieldLabel(field) + " " + opLabel + " " + value + " and " + valueTo;
    }

    if (operatorNeedsValue(op)) {
      return fieldLabel(field) + " " + opLabel + " " + value;
    }

    return fieldLabel(field) + " " + opLabel;
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

    const count = getCompleteFilters().length;
    btn.classList.toggle("is-active", count > 0);
    btn.textContent = count ? "Filters · " + count : "Filters";
    btn.setAttribute(
      "aria-label",
      count ? "Filters, " + count + " active" : "Filters"
    );
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

    if (op === "in") return membershipValues(filter).has(text);
    if (op === "not_in") return !membershipValues(filter).has(text);
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

    // Positive membership lists on a column form a union. Other conditions,
    // including exclusions, still constrain that union with AND.
    let membershipMatches = null;
    for (const filter of filters) {
      if (filter.op === "in" && getFieldType(filter.field) !== "number") {
        if (!membershipMatches) membershipMatches = new Map();
        if (!membershipMatches.get(filter.field)) {
          membershipMatches.set(filter.field, matchesSingleFilter(rowData, filter));
        }
      } else if (!matchesSingleFilter(rowData, filter)) return false;
    }
    if (membershipMatches) {
      for (const matched of membershipMatches.values()) if (!matched) return false;
    }

    return true;
  }

  function getCurrentFilteredLoadedRows() {
    const rows = Array.isArray(state.tableRows) ? state.tableRows : [];
    return state.myViewBlocked ? [] : rows.filter(rowMatchesCurrentTableFilters);
  }

  function applyAllTableFilters(options) {
    const immediatePlot = !!(options && options.immediatePlot);
    if (!state.tabulatorInstance || state.tabulatorInstance.initialized === false) return;

    const searchQuery = getSearchQuery().trim().toLowerCase();
    const filters = getCompleteFilters();
    const fields = Array.isArray(state.tableFields) ? state.tableFields : [];

    if (state.myViewBlocked) {
      state.tabulatorInstance.setFilter(function () { return false; });
      refreshActiveTablePlot(true);
      return;
    }
    if (!searchQuery && !filters.length) {
      state.tabulatorInstance.clearFilter(true);
      refreshTableStatus();
      refreshActiveTablePlot(immediatePlot);
      return;
    }

    state.tabulatorInstance.setFilter(rowMatchesCurrentTableFilters);

    refreshTableStatus();
    refreshActiveTablePlot(immediatePlot);
  }

  function resetTableFilters() {
    const input = document.getElementById("table-search-input");
    setSearchQuery("");
    setFilters([]);
    setFiltersOpen(false);
    if (input) input.value = "";
    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters({ immediatePlot: true });
    refreshTableStatus();
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
    if (!state.tabulatorInstance || state.tabulatorInstance.initialized === false) return;

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
    applyAllTableFilters({ immediatePlot: true });
  }

  function removeFilter(filterId) {
    const filters = getFilters().filter(function (f) {
      return f.id !== filterId;
    });

    setFilters(filters);

    renderFilterRows();
    renderActiveFilters();
    syncFilterPanelUi();
    applyAllTableFilters({ immediatePlot: true });
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
    applyAllTableFilters({ immediatePlot: true });
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

  function resetColumnWidths() {
    const table = state.tabulatorInstance;
    if (!table || table.initialized === false || typeof table.getColumns !== "function") return;

    // Tabulator's true width reset remeasures the header and cells. Columns
    // with an explicit default width (used by stream roles) keep that default.
    // fitDataStretch then fills the remaining space as on first open.
    table.getColumns().forEach(function (column) {
      if (!column || typeof column.setWidth !== "function") return;
      const definition = column.getDefinition();
      column.setWidth(definition && definition.width != null ? definition.width : true);
    });
    // Reapply fitDataStretch after all columns have their natural widths. A
    // per-column reset alone leaves the last column narrow until a later draw.
    table.redraw();
  }

  core.resetTableColumnWidths = resetColumnWidths;

  function bindTableToolbar() {
    const input = document.getElementById("table-search-input");
    const groupBySelect = document.getElementById("table-group-by-select");
    const resetBtn = document.getElementById("table-reset-btn");
    const resetFiltersBtn = document.getElementById("table-reset-filters-btn");
    const filtersToggleBtn = document.getElementById("table-filters-toggle-btn");
    const columnsToggleBtn = document.getElementById("table-columns-toggle-btn");
    const addFilterBtn = document.getElementById("table-filter-add-btn");
    const showAllColumnsBtn = document.getElementById("table-columns-show-all-btn");
    const resetColumnWidthsBtn = document.getElementById("table-columns-reset-widths-btn");
    const filterRows = document.getElementById("table-filter-rows");
    const columnsList = document.getElementById("table-columns-list");
    const activeFilters = document.getElementById("table-active-filters");

    // Row arrivals do not change the toolbar. Replacing its children on every
    // poll closes native selects and discards focused filter inputs.
    const toolbarSignature = JSON.stringify([state.tableFields, state.tableFieldTypes]);
    const toolbarRoot = input || groupBySelect;
    const editingToolbar = document.activeElement &&
      [filterRows, columnsList, groupBySelect].some(function (element) {
        return element && element.contains(document.activeElement);
      });
    const newTable = toolbarRoot && toolbarRoot._plotsrvTable !== state.tabulatorInstance;
    if (!toolbarRoot || newTable || (toolbarRoot._plotsrvSchema !== toolbarSignature && !editingToolbar)) {
      restoreToolbarInputs();
      renderGroupingControl();
      renderFilterRows();
      renderColumnsList();
      renderActiveFilters();
      syncFilterPanelUi();
      syncColumnsPanelUi();
      if (toolbarRoot) {
        toolbarRoot._plotsrvSchema = toolbarSignature;
        toolbarRoot._plotsrvTable = state.tabulatorInstance;
      }
    }

    if (input && !input.dataset.plotsrvBound) {
      let timer = null;

      input.addEventListener("input", function () {
        const q = String(input.value || "");
        setSearchQuery(q);

        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          applyAllTableFilters({ immediatePlot: true });
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
        if (core.resetPersonalView && core.resetPersonalView()) return;
        state.tableUiState = defaultTableUiState();
        saveTableUiState();

        if (input) input.value = "";

        if (state.tabulatorInstance && state.tabulatorInstance.initialized !== false) {
          // Clear grouping before rebuilding columns. Reset only the view:
          // replacing rows here can race with grouping and live arrivals.
          applyTableGrouping();
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
        }

        renderGroupingControl();
        renderFilterRows();
        renderColumnsList();
        renderActiveFilters();
        syncFilterPanelUi();
        syncColumnsPanelUi();
        applyColumnVisibilityState();
        applyTableGrouping();
        applyAllTableFilters({ immediatePlot: true });
      });

      resetBtn.dataset.plotsrvBound = "1";
    }

    if (resetFiltersBtn && !resetFiltersBtn.dataset.plotsrvBound) {
      resetFiltersBtn.addEventListener("click", resetTableFilters);
      resetFiltersBtn.dataset.plotsrvBound = "1";
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

    if (resetColumnWidthsBtn && !resetColumnWidthsBtn.dataset.plotsrvBound) {
      resetColumnWidthsBtn.addEventListener("click", resetColumnWidths);
      resetColumnWidthsBtn.dataset.plotsrvBound = "1";
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
    state.tableDefaultHidden = Array.isArray(settings.defaultHidden) ? settings.defaultHidden : [];

    if (!state.tableUiState) {
      loadTableUiState();
    }
    if (config.kind === "stream" && !state.streamInitialPanelsCollapsed) {
      state.tableUiState.filtersOpen = false;
      state.tableUiState.columnsOpen = false;
      state.streamInitialPanelsCollapsed = true;
    }

    const previousFields = new Set(state.tableFields || []);
    const newlyHidden = state.tableDefaultHidden.filter(field => !previousFields.has(field));
    state.tableUiState.hiddenColumns = [...new Set([
      ...getHiddenColumns().filter(field => fields.includes(field)), ...newlyHidden
    ])];

    // The stream renderer uses the same small controller as a rich static
    // table.  There is only one table surface per page, so this alias lets
    // search, filters, and column controls operate without duplicating their
    // state model or event bindings.
    if (state.tableGroupingOwner !== table) {
      state.tableAppliedGrouping = undefined;
      state.tableGroupingOwner = table;
    }
    state.tabulatorInstance = table;
    state.tableLastPayload = settings.payload || {};
    state.tableRows = rows;
    state.tableFields = fields;
    state.tableFieldTypes = inferFieldTypes(fields, rows);
    for (const field of fields) {
      const type = (settings.fieldTypes || {})[field];
      if (["number", "datetime", "text"].includes(type)) state.tableFieldTypes[field] = type;
    }
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

    if (core.checkPersonalViewSchema) core.checkPersonalViewSchema();
    bindTableToolbar();
    if (core.syncExpandedView) core.syncExpandedView();
    // Tabulator builds asynchronously. Calling setGroupBy before tableBuilt
    // can leave its display pipeline empty even though getData() has rows.
    if (table.initialized === false && typeof table.on === "function") {
      if (!table._plotsrvReadyBound) {
        table._plotsrvReadyBound = true;
        table.on("tableBuilt", function () {
          if (state.tabulatorInstance !== table) return;
          applyColumnVisibilityState();
          applyTableGrouping();
          applyAllTableFilters();
          refreshTableStatus();
          if (typeof core.configureTablePlotSurface === "function") core.configureTablePlotSurface();
          if (core.mountPersonalViews) core.mountPersonalViews();
        });
      }
      return;
    }
    applyTableGrouping();
    applyAllTableFilters();
    refreshTableStatus();
    if (typeof core.configureTablePlotSurface === "function") {
      core.configureTablePlotSurface();
    }
    if (core.mountPersonalViews) core.mountPersonalViews();
  }

  function destroyMountedTable() {
    if (core.capturePersonalBeforeRemount) core.capturePersonalBeforeRemount();
    const table = state.tabulatorInstance;
    state.tabulatorInstance = null;
    state.tableAppliedGrouping = undefined;
    state.tableGroupingOwner = null;

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
    if (!state.tableUiState) loadTableUiState();
    const columns = buildColumnDefs(fields);
    const table = new Tabulator(grid, {
      data: rows,
      columns: columns,
      height: "72vh",
      layout: "fitDataStretch",
      pagination: "local",
      paginationSize: 100,
      paginationSizeSelector: [20, 50, 100, 200],
      movableColumns: true,
      placeholder: "No data",
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
      fieldTypes: settings.fieldTypes,
    });
    state.embeddedTableExplorer = true;
    return true;
  }

  function disposeEmbeddedTableExplorer() {
    if (core.restoreExpandedContentControls) core.restoreExpandedContentControls();
    if (!state.embeddedTableExplorer) return;
    destroyMountedTable();
    state.embeddedTableExplorer = false;
    state.observationProfile = null;
  }

  async function loadTable() {
    const grid = document.getElementById("table-grid");
    const simple = document.getElementById("simple-table-root");
    if (!grid && !simple) return false;

    if (!state.tableUiState) {
      loadTableUiState();
    }

    const snapshotQuery =
      typeof core.snapshotQuery === "function" ? core.snapshotQuery() : "";

    const url =
      "/table/data?view=" +
      encodeURIComponent(config.activeViewId) +
      snapshotQuery +
      (simple ? "&limit=" + (config.maxTableRowsSimple || 200) : "") +
      "&_ts=" +
      Date.now();

    const load = core.beginSnapshotLoad ? core.beginSnapshotLoad("table") :
      {current: () => true, finish: () => {}, signal: undefined};
    try {
      let res = await fetch(url, {signal: load.signal});
      // A file-backed server admits only a bounded number of expensive CSV
      // loads. A short retry keeps normal refreshes smooth without hiding a
      // persistent failure behind an endless client loop.
      for (let attempt = 0; res.status === 503 && attempt < 2; attempt += 1) {
        await new Promise(function (resolve) {
          window.setTimeout(resolve, 250 * (attempt + 1));
        });
        if (!load.current()) return false;
        res = await fetch(url, {signal: load.signal});
      }

      if (!load.current()) return false;
      if (!res.ok) {
        if (
          res.status === 404 &&
          typeof core.isHistoryMode === "function" &&
          core.isHistoryMode() &&
          typeof core.handleMissingSnapshot === "function"
        ) {
          await core.handleMissingSnapshot("table");
          return false;
        }

        console.error("Failed to load table data");
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage("Failed to load table data (" + res.status + ").");
        }
        return false;
      }

      const data = await res.json();
      if (!load.current() || (load.signal && load.signal.aborted)) return false;
      if (simple) {
        const table = document.createElement("table");
        table.className = "dataframe";
        const header = table.createTHead().insertRow();
        const fields = data.columns || [];
        fields.forEach(function (field) {
          const th = document.createElement("th");
          th.textContent = String(field);
          header.append(th);
        });
        const body = table.createTBody();
        (data.rows || []).forEach(function (row) {
          const tr = body.insertRow();
          fields.forEach(function (field) {
            tr.insertCell().textContent = row[field] == null ? "" : String(row[field]);
          });
        });
        if (data.rows && data.rows.length) {
          simple.replaceChildren(table);
        } else {
          const empty = document.createElement("div");
          empty.className = "ps-table-empty";
          empty.textContent = "No data";
          simple.replaceChildren(empty);
        }
        return true;
      }
      let columns = buildColumnDefs(data.columns || []);
      const rows = data.rows || [];

      if (state.tabulatorInstance) {
        const sorters = currentSorters(state.tabulatorInstance);
        columns = preserveColumnOrder(columns, state.tabulatorInstance);
        const schemaChanged = !hasSameTableFields(state.tabulatorInstance, columns);
        if (schemaChanged) {
          state.tableAppliedGrouping = undefined;
          await Promise.resolve(state.tabulatorInstance.setColumns(columns));
        }
        // replaceData preserves existing column widths/order, grouping and sorting.
        // Rebuilding unchanged columns needlessly lays out every visible cell twice.
        await Promise.resolve(state.tabulatorInstance.replaceData(rows));
        if (schemaChanged && sorters.length && typeof state.tabulatorInstance.setSort === "function") {
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
        return true;
      }

      if (typeof Tabulator === "undefined") {
        console.error("Tabulator is not available (did not load).");
        if (typeof core.setStatusMessage === "function") {
          core.setStatusMessage("Failed to start the rich table renderer.");
        }
        return false;
      }

      state.tabulatorInstance = new Tabulator("#table-grid", {
        data: rows,
        columns: columns,
        height: "72vh",
        layout: "fitDataStretch",
        pagination: "local",
        paginationSize: 100,
        paginationSizeSelector: [20, 50, 100, 200],
        movableColumns: true,
        placeholder: "No data",
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
      return true;
    } catch (error) {
      if (load.current() && core.snapshotSelectionFailed) core.snapshotSelectionFailed("Failed to load selected table (network error or timeout).");
      return false;
    } finally {
      load.finish();
    }
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

  core.setTableFiltersOpen = function (open) { setFiltersOpen(open); syncFilterPanelUi(); };

  core.extractTablePresentation = function () {
    const ui = getTableUiState();
    return {
      search: ui.searchQuery || "",
      filters: getCompleteFilters().map(f => ({field:f.field, op:f.op, value:f.value, valueTo:f.valueTo})),
      sort: currentSorters(state.tabulatorInstance).map(s => ({field:s.column, dir:s.dir})),
      group: ui.groupBy || "", columns: state.tabulatorInstance.getColumns().map(c => c.getField()).filter(Boolean), hidden: getHiddenColumns().slice()
    };
  };
  core.applyTablePresentation = function (p) {
    state.tableUiState = Object.assign(defaultTableUiState(), {
      searchQuery:p.search, filters:p.filters.map(normalizeFilter), groupBy:p.group || null,
      hiddenColumns:p.hidden.slice(), filtersOpen:!!p.filters.length
    });
    const table = state.tabulatorInstance;
    const defs = config.kind === "stream" && typeof core.buildStreamColumns === "function"
      ? core.buildStreamColumns(state.tableFields)
      : buildColumnDefs(state.tableFields);
    const ordered = p.columns.map(field => defs.find(d => d.field === field)).filter(Boolean);
    defs.forEach(d => { if (!ordered.includes(d)) ordered.push(d); });
    return Promise.resolve(table.setColumns(ordered)).then(function () {
      if (state.tabulatorInstance !== table) return;
      table.setSort(p.sort.map(s => ({column:s.field,dir:s.dir})));
      const search = document.getElementById("table-search-input");
      if (search) search.value = p.search;
      renderGroupingControl(); renderFilterRows(); renderColumnsList(); renderActiveFilters();
      syncFilterPanelUi(); applyColumnVisibilityState(); applyTableGrouping(); applyAllTableFilters({immediatePlot:true});
    });
  };
  core.loadTable = loadTable;
  core.exportTable = exportTable;
  core.exportFilteredRichTable = exportFilteredRichTable;
  core.exportRetainedRawWindow = exportRetainedRawWindow;
  core.exportCompletePublishedTable = exportCompletePublishedTable;
  core.configureTableExplorer = configureTableExplorer;
  core.disposeEmbeddedTableExplorer = disposeEmbeddedTableExplorer;
  core.initializeEmbeddedTableExplorer = initializeEmbeddedTableExplorer;
  core.getCurrentFilteredLoadedRows = getCurrentFilteredLoadedRows;
  core.hasActiveTableFiltering = hasActiveTableFiltering;
  core.resetTableFilters = resetTableFilters;
  core.getTableGrouping = normalizeGroupingField;
  core.setTableGrouping = setTableGrouping;

  window.exportTable = exportTable;
})();

/* plotsrv source: js/renderers/table_plot.js */
(function () {
  "use strict";
  window.PLOTSRV = window.PLOTSRV || {core: {}, renderers: {}, state: {}, config: {}};
  const core = window.PLOTSRV.core;
  const config = window.PLOTSRV.config;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const configuredPointLimit = Number(config.tablePlotMaxPoints);
  const TABLE_PLOT_LIMITS = {
    maxSourceRows: 100000,
    maxPoints: Number.isSafeInteger(configuredPointLimit)
      ? Math.max(1, Math.min(25000, configuredPointLimit))
      : 5000,
    maxCategories: 40,
    maxSeries: 8,
  };
  const TABLE_PLOT_PALETTES = {
    http: {name:"HTTP status", kind:"discrete", colours:["#2166ac","#15803d","#8c6d00","#c2410c","#b91c1c"], darkColours:["#60a5fa","#6ccf7f","#f5cf65","#fb923c","#f87171"]},
    plotsrv: {name: "plotsrv", kind: "discrete", colours: ["#d55970", "#7a3950", "#e58a5f", "#4e8291", "#8e6aae", "#d4a72c"], darkColours: ["#f07b91", "#d9a0b2", "#f2a47c", "#72b7c7", "#b49ad4", "#e1c15c"]},
    accessible: {name: "Accessible", kind: "discrete", colours: ["#0072b2", "#e69f00", "#009e73", "#cc79a7", "#d55e00", "#56b4e9", "#f0e442", "#000000"], darkColours: ["#56b4e9", "#f0b84f", "#4bc99c", "#e69ac8", "#ef8354", "#8bd3f2", "#f5e96b", "#e7edf2"]},
    ocean: {name: "Ocean", kind: "discrete", colours: ["#2166ac", "#0891b2", "#0f766e", "#60a5fa", "#5ab4ac", "#164e63"], darkColours: ["#60a5fa", "#22d3ee", "#2dd4bf", "#93c5fd", "#7dd3fc", "#5eead4"]},
    forest: {name: "Forest", kind: "discrete", colours: ["#1b7837", "#5aae61", "#8c6d31", "#4d9221", "#7f9f35", "#356859"], darkColours: ["#6ccf7f", "#a3d977", "#d1aa62", "#73c991", "#b4d568", "#83b9a4"]},
    sunset: {name: "Sunset", kind: "discrete", colours: ["#b2182b", "#ef8a62", "#f1a340", "#d6604d", "#9970ab", "#c45d38"], darkColours: ["#f87171", "#fb9a78", "#f7bd65", "#ef7770", "#c4a2df", "#ee9465"]},
    violet: {name: "Violet", kind: "discrete", colours: ["#6a51a3", "#807dba", "#54278f", "#9e6ab0", "#8c6bb1", "#b05c91"], darkColours: ["#a78bfa", "#c4b5fd", "#b89af5", "#d6a3e3", "#c6a9df", "#e19bc5"]},
    neutral: {name: "Neutral", kind: "discrete", colours: ["#374151", "#6b7280", "#78716c", "#4b5563", "#9ca3af", "#57534e"], darkColours: ["#d1d5db", "#9ca3af", "#c4b8ad", "#b8c0cc", "#e5e7eb", "#aaa39d"]},
    viridis: {name: "Viridis", kind: "continuous", colours: ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"], darkColours: ["#7b2f8e", "#6677b5", "#42a1b4", "#40c39d", "#98dc70", "#f5e85c"]},
    plasma: {name: "Plasma", kind: "continuous", colours: ["#0d0887", "#6a00a8", "#b12a90", "#e16462", "#fca636", "#f0f921"], darkColours: ["#5b55c7", "#9b4dcc", "#db68b2", "#f18879", "#fcb95b", "#f3ef64"]},
    blues: {name: "Blues", kind: "continuous", colours: ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c"], darkColours: ["#d7e8f7", "#b9d8ef", "#89bee1", "#58a0cc", "#347eb2", "#8fc7ed"]},
    ember: {name: "Ember", kind: "continuous", colours: ["#fff5eb", "#fdd0a2", "#fdae6b", "#fd8d3c", "#e6550d", "#a63603"], darkColours: ["#ffe0c2", "#ffc489", "#f9a45d", "#ef8240", "#df6230", "#f29a68"]},
  };

  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }
  function html(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function svg(tag, attrs, text) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { if (attrs[key] != null) node.setAttribute(key, String(attrs[key])); });
    if (text != null) node.textContent = text;
    return node;
  }
  function svgText(root, attrs, text) { const node = svg("text", attrs, text); root.appendChild(node); return node; }
  function plural(n, word) { return n === 1 ? word : word + "s"; }
  function formatNumber(value) {
    if (!Number.isFinite(value)) return "";
    if (Math.abs(value) >= 1000000 || (value !== 0 && Math.abs(value) < 0.001)) return value.toExponential(2);
    return new Intl.NumberFormat(undefined, {maximumFractionDigits: 3}).format(value);
  }
  function formatTime(value, span) {
    const opts = span < 86400000 ? {hour: "2-digit", minute: "2-digit", second: "2-digit"} :
      span < 31536000000 ? {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"} :
        {year: "numeric", month: "short", day: "numeric"};
    return new Intl.DateTimeFormat(undefined, opts).format(new Date(value));
  }
  function label(field) { return typeof field === "string" && field ? (core.tableFieldLabel ? core.tableFieldLabel(field) : field) : "selected field"; }
  function missing(value) { return value == null || (typeof value === "string" && value.trim() === ""); }
  function numberValue(value) {
    if (missing(value)) return {kind: "missing"};
    if (typeof value === "boolean" || typeof value === "bigint") return {kind: "invalid"};
    const n = typeof value === "number" ? value : Number(value);
    return Number.isFinite(n) ? {kind: "value", value: n} : {kind: "invalid"};
  }
  function dateValue(value) {
    if (missing(value)) return {kind: "missing"};
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}(?:[T ][^\s]+)?/.test(value.trim())) return {kind: "invalid"};
    const n = Date.parse(value);
    return Number.isFinite(n) ? {kind: "value", value: n} : {kind: "invalid"};
  }
  function categoryValue(value) {
    if (missing(value)) return {kind: "missing"};
    if ((typeof value === "number" && !Number.isFinite(value)) || typeof value === "object" || typeof value === "function" || typeof value === "symbol") return {kind: "invalid"};
    return {kind: "value", key: typeof value + ":" + String(value), label: String(value)};
  }
  function rowsFor(settings) {
    if (Array.isArray(settings.rows)) return settings.rows;
    if (typeof core.getCurrentFilteredLoadedRows === "function") {
      const rows = core.getCurrentFilteredLoadedRows();
      if (Array.isArray(rows)) return rows;
    }
    return [];
  }
  function scopeText(settings, rows, plotted) {
    let text = settings.scopeKind === "summary"
      ? "Plot scope: " + rows + " loaded derived summary " + plural(rows, "window") + "; " + plotted + " " + plural(plotted, "value") + " plotted. These are selected aggregate records, not source log rows."
      : "Plot scope: " + rows + " loaded " + plural(rows, "row") + " passing the current browser filters; " + plotted + " " + plural(plotted, "value") + " plotted.";
    if (typeof settings.scopeDescription === "string" && settings.scopeDescription.trim()) text += " " + settings.scopeDescription.trim();
    return text;
  }
  function skipped(missingCount, invalidCount) {
    const parts = [];
    if (missingCount) parts.push(missingCount + " " + plural(missingCount, "row") + " with missing values");
    if (invalidCount) parts.push(invalidCount + " " + plural(invalidCount, "row") + " with invalid values");
    return parts.length ? "Excluded " + parts.join(" and ") + "." : "";
  }
  function notice(container, reason, detail, settings, rowCount, actions) {
    const titles = {series_limit: "Too many series to display clearly", point_limit: "Choose how to display these points", source_limit: "Narrow the data to build this plot"};
    const availableActions = (actions || []).filter(function (action) { return action && typeof action.onClick === "function"; });
    const signature = JSON.stringify([reason, availableActions.map(function (action) { return action.label; })]);
    const previous = container._plotsrvNotice;
    // Keep focused buttons alive across stream refreshes, but update their callbacks.
    if (previous && previous.root.parentNode === container && previous.signature === signature) {
      previous.detail.textContent = detail;
      previous.scope.textContent = scopeText(settings, rowCount, 0);
      previous.buttons.forEach(function (button, index) { button._plotsrvAction = availableActions[index].onClick; });
      return {ok: false, reason: reason, rowCount: rowCount, plottedCount: 0};
    }
    clear(container);
    const root = html("section", "ps-table-plot__notice" + (reason === "filtered_empty" ? "" : " ps-table-plot__notice--refused"));
    root.dataset.plotState = "refused";
    root.appendChild(html("h2", "ps-table-plot__notice-title", titles[reason] || (reason === "filtered_empty" ? "No matching data" : "Plot not rendered")));
    const detailNode = html("p", "ps-table-plot__notice-detail", detail);
    root.appendChild(detailNode);
    const buttons = [];
    if (availableActions.length) {
      const actionRoot = html("div", "ps-table-plot__notice-actions");
      availableActions.forEach(function (action) {
        if (!action || typeof action.onClick !== "function") return;
        const button = html("button", "ps-btn ps-table-plot__notice-action", action.label);
        button.type = "button";
        button._plotsrvAction = action.onClick;
        button.addEventListener("click", function () { button._plotsrvAction(); });
        buttons.push(button);
        actionRoot.appendChild(button);
      });
      root.appendChild(actionRoot);
    }
    const scopeNode = html("p", "ps-table-plot__scope", scopeText(settings, rowCount, 0));
    root.appendChild(scopeNode);
    container.appendChild(root);
    container._plotsrvNotice = {root: root, signature: signature, detail: detailNode, scope: scopeNode, buttons: buttons};
    return {ok: false, reason: reason, rowCount: rowCount, plottedCount: 0};
  }
  function frame(container, type, automaticTitle, settings) {
    container._plotsrvNotice = null;
    clear(container);
    const figure = html("figure", "ps-table-plot");
    figure.dataset.plotType = type;
    figure.dataset.plotState = "rendered";
    figure.dataset.plotPalette = settings.palette || "plotsrv";
    figure.dataset.plotTitleAlign = settings.titleAlign === "center" ? "center" : "left";
    figure.appendChild(html("h2", "ps-table-plot__title", settings.title || automaticTitle));
    const tip = html("div", "ps-table-plot__tooltip");
    tip.hidden = true;
    tip.setAttribute("role", "tooltip");
    figure.appendChild(tip);
    container.appendChild(figure);
    return figure;
  }
  function summary(figure, detail, scope) {
    if (detail) figure.appendChild(html("p", "ps-table-plot__detail", detail));
    figure.appendChild(html("figcaption", "ps-table-plot__scope", scope));
  }
  function tooltip(mark, figure, text, tabbable) {
    mark.appendChild(svg("title", {}, text));
    if (tabbable) mark.setAttribute("tabindex", "0");
    const tip = figure.querySelector(".ps-table-plot__tooltip");
    if (!tip || typeof mark.addEventListener !== "function") return;
    function show(event) {
      tip.textContent = text;
      tip.hidden = false;
      const box = figure.getBoundingClientRect ? figure.getBoundingClientRect() : {left: 0, top: 0};
      tip.style.left = Math.max(8, (event && Number.isFinite(event.clientX) ? event.clientX - box.left : 18) + 10) + "px";
      tip.style.top = Math.max(42, (event && Number.isFinite(event.clientY) ? event.clientY - box.top : 42) + 10) + "px";
      mark.classList.add("is-highlighted");
    }
    function hide() { tip.hidden = true; mark.classList.remove("is-highlighted"); }
    ["mouseenter", "mousemove", "focus"].forEach(function (name) { mark.addEventListener(name, show); });
    ["mouseleave", "blur"].forEach(function (name) { mark.addEventListener(name, hide); });
  }
  function domain(values, includeZero, logarithmic) {
    let low = Math.min.apply(null, values);
    let high = Math.max.apply(null, values);
    if (includeZero && !logarithmic) { low = Math.min(0, low); high = Math.max(0, high); }
    if (low === high) { if (logarithmic) { low /= 10; high *= 10; } else { const pad = low === 0 ? 1 : Math.abs(low) * 0.1; low -= pad; high += pad; } }
    return {minimum: low, maximum: high};
  }
  function scale(domainValue, start, end, logarithmic) {
    const transform = logarithmic ? Math.log10 : function (v) { return v; };
    const low = transform(domainValue.minimum);
    const span = transform(domainValue.maximum) - low;
    return function (value) { return start + ((transform(value) - low) / span) * (end - start); };
  }
  function darkThemeActive() {
    const theme = document.documentElement && document.documentElement.getAttribute("data-theme");
    return theme === "dark" || (theme === "system" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function paletteFor(settings) {
    const selected = TABLE_PLOT_PALETTES[settings.palette] || TABLE_PLOT_PALETTES.plotsrv;
    return {name: selected.name, kind: selected.kind || "discrete", colours: darkThemeActive() ? selected.darkColours : selected.colours};
  }
  function paletteColour(palette, index, count) {
    if (palette.kind === "continuous" && count > 1) {
      const position = index * (palette.colours.length - 1) / (count - 1);
      const lower = Math.max(0, Math.min(palette.colours.length - 1, Math.floor(position)));
      const upper = Math.min(palette.colours.length - 1, lower + 1);
      const fraction = position - lower;
      const from = palette.colours[lower].slice(1).match(/.{2}/g).map(function (part) { return parseInt(part, 16); });
      const to = palette.colours[upper].slice(1).match(/.{2}/g).map(function (part) { return parseInt(part, 16); });
      const channels = from.map(function (channel, channelIndex) {
        return Math.round(channel + (to[channelIndex] - channel) * fraction).toString(16).padStart(2, "0");
      });
      return "#" + channels.join("");
    }
    return palette.colours[index % palette.colours.length];
  }
  function seriesColour(palette, group, index, count) {
    const match = palette.name === "HTTP status" && /^([1-5])xx /.exec(group.label || "");
    return match ? palette.colours[Number(match[1]) - 1] : paletteColour(palette, index, count);
  }
  function seriesFor(rows, field) {
    if (!field) return [{key: "__all__", label: "All rows"}];
    const found = new Map();
    for (const row of rows) {
      const value = categoryValue(row ? row[field] : null);
      if (value.kind === "value" && !found.has(value.key)) found.set(value.key, value);
      if (found.size > TABLE_PLOT_LIMITS.maxSeries) break;
    }
    return Array.from(found.values());
  }
  function seriesLimitNotice(container, settings, count) {
    const actions = [];
    if (typeof settings.onDisableSeries === "function") actions.push({label: "Turn Series off", onClick: settings.onDisableSeries});
    if (typeof settings.onEditPlotField === "function") actions.push({label: "Choose another field", onClick: function () { settings.onEditPlotField("series"); }});
    return notice(container, "series_limit", "The field “" + label(settings.seriesField) + "” exceeds the limit of " + TABLE_PLOT_LIMITS.maxSeries + " series. Choose how to continue; no series have been dropped or merged." + (settings.type === "line" ? " Turning Series off joins the groups into one line." : ""), settings, count, actions);
  }
  function legend(series, palette, position) {
    if (series.length <= 1) return null;
    const root = html("div", "ps-table-plot__legend ps-table-plot__legend--" + (position || "top"));
    root.setAttribute("aria-label", "Plot series");
    series.forEach(function (item, index) {
      const entry = html("span", "ps-table-plot__legend-item", item.label);
      entry.tabIndex = 0;
      entry.title = item.label;
      const swatch = html("span", "ps-table-plot__legend-swatch");
      swatch.style.backgroundColor = seriesColour(palette, item, index, series.length);
      entry.insertBefore(swatch, entry.firstChild);
      root.appendChild(entry);
    });
    return root;
  }
  function chartBody(figure, drawing, chartLegend) {
    const body = html("div", "ps-table-plot__body" + (chartLegend ? " ps-table-plot__body--legend-" + chartLegend.className.split("--").pop() : ""));
    if (chartLegend && chartLegend.classList.contains("ps-table-plot__legend--top")) body.appendChild(chartLegend);
    body.appendChild(drawing);
    if (chartLegend && !chartLegend.parentNode) body.appendChild(chartLegend);
    figure.appendChild(body);
  }

  function accumulator() { return {count: 0, sum: 0, min: Infinity, max: -Infinity}; }
  function add(acc, value, aggregation) { acc.count += 1; if (aggregation !== "count") { acc.sum += value; acc.min = Math.min(acc.min, value); acc.max = Math.max(acc.max, value); } }
  function aggregate(acc, aggregation) {
    if (!acc || !acc.count) return 0;
    return aggregation === "sum" ? acc.sum : aggregation === "mean" ? acc.sum / acc.count : aggregation === "min" ? acc.min : aggregation === "max" ? acc.max : acc.count;
  }
  function merge(into, from) { into.count += from.count; into.sum += from.sum; into.min = Math.min(into.min, from.min); into.max = Math.max(into.max, from.max); }
  function barData(rows, settings, series) {
    const map = new Map();
    let missingCount = 0;
    let invalidCount = 0;
    rows.forEach(function (row) {
      const category = categoryValue(row ? row[settings.categoryField] : null);
      const group = settings.seriesField ? categoryValue(row ? row[settings.seriesField] : null) : {kind: "value", key: "__all__"};
      const value = settings.aggregation === "count" ? {kind: "value", value: 1} : numberValue(row ? row[settings.valueField] : null);
      if (category.kind === "missing" || group.kind === "missing" || value.kind === "missing") { missingCount += 1; return; }
      if (category.kind !== "value" || group.kind !== "value" || value.kind !== "value") { invalidCount += 1; return; }
      if (!map.has(category.key)) map.set(category.key, {label: category.label, values: new Map()});
      const item = map.get(category.key);
      if (!item.values.has(group.key)) item.values.set(group.key, accumulator());
      add(item.values.get(group.key), value.value, settings.aggregation);
    });
    let categories = Array.from(map.values());
    function score(item) { return series.reduce(function (total, group) { return total + aggregate(item.values.get(group.key), settings.aggregation); }, 0); }
    categories.forEach(function (item) { item.score = score(item); });
    const order = settings.sort || "value-desc";
    function compare(a, b) {
      if (order === "value-asc") return a.score - b.score;
      if (order === "category-asc") return a.label.localeCompare(b.label);
      if (order === "category-desc") return b.label.localeCompare(a.label);
      return b.score - a.score;
    }
    const limit = Math.max(1, Math.min(TABLE_PLOT_LIMITS.maxCategories, Number(settings.categoryLimit) || 10));
    if (categories.length > limit) {
      const ranked = categories.slice().sort(function (a, b) { return b.score - a.score; });
      const selected = ranked.slice(0, limit);
      const remainder = ranked.slice(limit);
      const other = {label: "Other", values: new Map(), score: 0, isOther: true};
      series.forEach(function (group) {
        const combined = accumulator();
        remainder.forEach(function (item) { if (item.values.has(group.key)) merge(combined, item.values.get(group.key)); });
        if (combined.count) other.values.set(group.key, combined);
      });
      other.score = score(other);
      categories = selected.sort(compare).concat([other]);
    } else {
      categories.sort(compare);
    }
    return {categories: categories, missing: missingCount, invalid: invalidCount, plotted: rows.length - missingCount - invalidCount};
  }
  function drawBars(figure, data, series, settings, palette) {
    const rowHeight = Math.max(34, series.length * 18 + 16);
    const d = {width: 860, height: Math.max(240, 92 + data.categories.length * rowHeight), left: 220, right: 72, top: 28, bottom: 46};
    const right = d.width - d.right;
    const bottom = d.height - d.bottom;
    let min = 0, max = 0;
    data.categories.forEach(function (category) {
      const values = series.map(function (group) { return aggregate(category.values.get(group.key), settings.aggregation); });
      if (settings.display === "stacked" && series.length > 1) {
        min = Math.min(min, values.filter(function (v) { return v < 0; }).reduce(function (a, b) { return a + b; }, 0));
        max = Math.max(max, values.filter(function (v) { return v > 0; }).reduce(function (a, b) { return a + b; }, 0));
      } else { min = Math.min.apply(null, [min].concat(values)); max = Math.max.apply(null, [max].concat(values)); }
    });
    if (min === max) max = min + 1;
    const x = scale({minimum: min, maximum: max}, d.left, right, false);
    const zero = x(0);
    const drawing = svg("svg", {viewBox: "0 0 " + d.width + " " + d.height, role: "img", "aria-label": "Bar chart for " + label(settings.categoryField), class: "ps-table-plot__svg ps-table-plot__svg--bar"});
    for (let index = 0; index <= 4; index += 1) {
      const value = min + (max - min) * index / 4;
      const xx = x(value);
      drawing.appendChild(svg("line", {x1: xx, y1: d.top, x2: xx, y2: bottom, class: "ps-table-plot__grid-line"}));
      svgText(drawing, {x: xx, y: bottom + 22, "text-anchor": "middle", class: "ps-table-plot__tick"}, formatNumber(value));
    }
    drawing.appendChild(svg("line", {x1: zero, y1: d.top, x2: zero, y2: bottom, class: "ps-table-plot__axis"}));
    const band = (bottom - d.top) / data.categories.length;
    data.categories.forEach(function (category, categoryIndex) {
      const center = d.top + band * categoryIndex + band / 2;
      svgText(drawing, {x: d.left - 10, y: center, "text-anchor": "end", "dominant-baseline": "middle", class: "ps-table-plot__category"}, category.label);
      let positive = 0, negative = 0;
      series.forEach(function (group, seriesIndex) {
        const values = category.values.get(group.key);
        const value = aggregate(values, settings.aggregation);
        const grouped = settings.display !== "stacked" || series.length === 1;
        const height = grouped ? Math.max(7, Math.min(16, (band - 8) / series.length)) : Math.max(12, Math.min(22, band - 10));
        const y = grouped ? center - series.length * height / 2 + seriesIndex * height : center - height / 2;
        const start = grouped ? 0 : value >= 0 ? positive : negative;
        const end = start + value;
        if (!grouped) { if (value >= 0) positive = end; else negative = end; }
        const x1 = x(start), x2 = x(end);
        const colourIndex = series.length > 1 ? seriesIndex : categoryIndex;
        const colourCount = series.length > 1 ? series.length : data.categories.length;
        const mark = svg("rect", {x: Math.min(x1, x2), y: y, width: Math.max(1, Math.abs(x2 - x1)), height: height - 2, rx: 2, fill: seriesColour(palette, group, colourIndex, colourCount), class: "ps-table-plot__bar"});
        tooltip(mark, figure, category.label + (series.length > 1 ? " · " + group.label : "") + ": " + formatNumber(value) + (settings.aggregation === "count" || !values ? "" : " · " + values.count + " " + plural(values.count, "row")), true);
        drawing.appendChild(mark);
      });
    });
    svgText(drawing, {x: d.left + (right - d.left) / 2, y: d.height - 8, "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.xLabel || (settings.aggregation === "count" ? "Count" : label(settings.valueField)));
    if (settings.yLabel) svgText(drawing, {x: 18, y: d.top + (bottom - d.top) / 2, transform: "rotate(-90 18 " + (d.top + (bottom - d.top) / 2) + ")", "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.yLabel);
    chartBody(figure, drawing, legend(series, palette, settings.legend));
  }

  function pointData(rows, settings, series) {
    const groups = new Map();
    series.forEach(function (group) { groups.set(group.key, {key: group.key, label: group.label, points: []}); });
    let missingCount = 0, invalidCount = 0;
    rows.forEach(function (row, index) {
      const x = settings.xKind === "datetime" ? dateValue(row ? row[settings.xField] : null) : numberValue(row ? row[settings.xField] : null);
      const y = numberValue(row ? row[settings.yField] : null);
      const group = settings.seriesField ? categoryValue(row ? row[settings.seriesField] : null) : {kind: "value", key: "__all__"};
      if (x.kind === "missing" || y.kind === "missing" || group.kind === "missing") { missingCount += 1; return; }
      if (x.kind !== "value" || y.kind !== "value" || group.kind !== "value" || (settings.xScale === "log" && x.value <= 0) || (settings.yScale === "log" && y.value <= 0)) { invalidCount += 1; return; }
      if (groups.has(group.key)) groups.get(group.key).points.push({x: x.value, y: y.value, index: index});
    });
    const list = Array.from(groups.values()).filter(function (group) { return group.points.length > 0; });
    return {groups: list, points: list.flatMap(function (group) { return group.points; }), missing: missingCount, invalid: invalidCount};
  }
  function limitedPointData(data, limit, mode) {
    if (!data || data.points.length <= limit) return data;
    const ordered = data.points.slice().sort(function (a, b) { return a.index - b.index; });
    let selected;
    if (mode === "first") {
      selected = ordered.slice(0, limit);
    } else if (mode === "latest") {
      selected = ordered.slice(-limit);
    } else {
      selected = Array.from({length: limit}, function (_, index) {
        if (limit === 1) return ordered[0];
        return ordered[Math.round(index * (ordered.length - 1) / (limit - 1))];
      });
    }
    const retained = new Set(selected);
    return {
      groups: data.groups.map(function (group) {
        return {
          key: group.key,
          label: group.label,
          points: group.points.filter(function (point) { return retained.has(point); }),
        };
      }).filter(function (group) { return group.points.length > 0; }),
      points: selected,
      missing: data.missing,
      invalid: data.invalid,
      sampledFrom: data.points.length,
      selectionMode: mode,
    };
  }
  function axes(drawing, d, xDomain, yDomain, settings) {
    const right = d.width - d.right, bottom = d.height - d.bottom;
    const x = scale(xDomain, d.left, right, settings.xScale === "log");
    const y = scale(yDomain, bottom, d.top, settings.yScale === "log");
    const span = xDomain.maximum - xDomain.minimum;
    for (let index = 0; index <= 4; index += 1) {
      const fraction = index / 4;
      const xv = settings.xScale === "log" ? Math.pow(10, Math.log10(xDomain.minimum) + (Math.log10(xDomain.maximum) - Math.log10(xDomain.minimum)) * fraction) : xDomain.minimum + span * fraction;
      const yv = settings.yScale === "log" ? Math.pow(10, Math.log10(yDomain.minimum) + (Math.log10(yDomain.maximum) - Math.log10(yDomain.minimum)) * fraction) : yDomain.minimum + (yDomain.maximum - yDomain.minimum) * fraction;
      const xx = x(xv), yy = y(yv);
      drawing.appendChild(svg("line", {x1: xx, y1: d.top, x2: xx, y2: bottom, class: "ps-table-plot__grid-line"}));
      drawing.appendChild(svg("line", {x1: d.left, y1: yy, x2: right, y2: yy, class: "ps-table-plot__grid-line"}));
      svgText(drawing, {x: xx, y: bottom + 22, "text-anchor": "middle", class: "ps-table-plot__tick"}, settings.xKind === "datetime" ? formatTime(xv, span) : formatNumber(xv));
      svgText(drawing, {x: d.left - 10, y: yy + 4, "text-anchor": "end", class: "ps-table-plot__tick"}, formatNumber(yv));
    }
    drawing.appendChild(svg("line", {x1: d.left, y1: d.top, x2: d.left, y2: bottom, class: "ps-table-plot__axis"}));
    drawing.appendChild(svg("line", {x1: d.left, y1: bottom, x2: right, y2: bottom, class: "ps-table-plot__axis"}));
    svgText(drawing, {x: d.left + (right - d.left) / 2, y: d.height - 10, "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.xLabel || label(settings.xField));
    svgText(drawing, {x: 18, y: d.top + (bottom - d.top) / 2, transform: "rotate(-90 18 " + (d.top + (bottom - d.top) / 2) + ")", "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.yLabel || label(settings.yField));
    return {x: x, y: y};
  }
  function drawPoints(figure, type, data, settings, palette) {
    const d = {width: 820, height: 450, left: 82, right: 34, top: 28, bottom: 68};
    const xDomain = domain(data.points.map(function (point) { return point.x; }), settings.zeroBaseline && settings.xKind !== "datetime", settings.xScale === "log");
    const yDomain = domain(data.points.map(function (point) { return point.y; }), settings.zeroBaseline, settings.yScale === "log");
    const drawing = svg("svg", {viewBox: "0 0 " + d.width + " " + d.height, role: "img", "aria-label": (type === "line" ? "Line" : "Scatter") + " plot of " + label(settings.yField) + " by " + label(settings.xField), class: "ps-table-plot__svg ps-table-plot__svg--points"});
    const scales = axes(drawing, d, xDomain, yDomain, settings);
    data.groups.forEach(function (group, index) {
      const points = type === "line" ? group.points.slice().sort(function (a, b) { return a.x - b.x || a.index - b.index; }) : group.points;
      const colour = seriesColour(palette, group, index, data.groups.length);
      if (type === "line" && points.length > 1) drawing.appendChild(svg("polyline", {points: points.map(function (point) { return scales.x(point.x) + "," + scales.y(point.y); }).join(" "), fill: "none", stroke: colour, class: "ps-table-plot__line"}));
      if (type === "scatter" || settings.showPoints !== false) points.forEach(function (point) {
        const mark = svg("circle", {cx: scales.x(point.x), cy: scales.y(point.y), r: type === "line" ? 2.8 : 3.5, fill: type === "line" ? "var(--ps-surface, #fff)" : colour, stroke: colour, class: "ps-table-plot__point"});
        const xText = settings.xKind === "datetime" ? formatTime(point.x, xDomain.maximum - xDomain.minimum) : formatNumber(point.x);
        tooltip(mark, figure, (group.label !== "All rows" ? group.label + " · " : "") + (settings.xLabel || settings.xField) + ": " + xText + " · " + (settings.yLabel || settings.yField) + ": " + formatNumber(point.y), false);
        drawing.appendChild(mark);
      });
    });
    chartBody(figure, drawing, legend(data.groups, palette, settings.legend));
  }

  function histogramData(rows, settings) {
    const values = [];
    let missingCount = 0, invalidCount = 0;
    rows.forEach(function (row) { const value = numberValue(row ? row[settings.histogramField] : null); if (value.kind === "missing") missingCount += 1; else if (value.kind !== "value") invalidCount += 1; else values.push(value.value); });
    if (!values.length) return {values: values, bins: [], missing: missingCount, invalid: invalidCount};
    const min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    const requested = settings.bins === "auto" ? Math.ceil(Math.sqrt(values.length)) : Number(settings.bins);
    const count = min === max ? 1 : Math.max(1, Math.min(40, requested || 10));
    const width = min === max ? 1 : (max - min) / count;
    const start = min === max ? min - 0.5 : min;
    const bins = Array.from({length: count}, function (_, index) { return {start: start + width * index, end: start + width * (index + 1), count: 0}; });
    values.forEach(function (value) { bins[Math.min(count - 1, Math.floor((value - start) / width))].count += 1; });
    return {values: values, bins: bins, missing: missingCount, invalid: invalidCount};
  }
  function drawHistogram(figure, data, settings, palette) {
    const d = {width: 820, height: 420, left: 76, right: 30, top: 26, bottom: 66};
    const bottom = d.height - d.bottom, right = d.width - d.right;
    const max = Math.max.apply(null, data.bins.map(function (bin) { return bin.count; }).concat([1]));
    const x = scale({minimum: 0, maximum: data.bins.length}, d.left, right, false);
    const y = scale({minimum: 0, maximum: max}, bottom, d.top, false);
    const drawing = svg("svg", {viewBox: "0 0 " + d.width + " " + d.height, role: "img", "aria-label": "Histogram of " + label(settings.histogramField), class: "ps-table-plot__svg ps-table-plot__svg--histogram"});
    for (let index = 0; index <= 4; index += 1) { const value = max * index / 4, yy = y(value); drawing.appendChild(svg("line", {x1: d.left, y1: yy, x2: right, y2: yy, class: "ps-table-plot__grid-line"})); svgText(drawing, {x: d.left - 10, y: yy + 4, "text-anchor": "end", class: "ps-table-plot__tick"}, formatNumber(value)); }
    data.bins.forEach(function (bin, index) {
      const left = x(index), next = x(index + 1);
      const mark = svg("rect", {x: left + 1, y: y(bin.count), width: Math.max(1, next - left - 2), height: bottom - y(bin.count), fill: paletteColour(palette, index, data.bins.length), class: "ps-table-plot__bar"});
      tooltip(mark, figure, formatNumber(bin.start) + " to " + formatNumber(bin.end) + ": " + bin.count + " " + plural(bin.count, "row"), true);
      drawing.appendChild(mark);
      if (index === 0 || index === data.bins.length - 1 || index % Math.max(1, Math.floor(data.bins.length / 5)) === 0) svgText(drawing, {x: left, y: bottom + 21, "text-anchor": "middle", class: "ps-table-plot__tick"}, formatNumber(bin.start));
    });
    drawing.appendChild(svg("line", {x1: d.left, y1: bottom, x2: right, y2: bottom, class: "ps-table-plot__axis"}));
    svgText(drawing, {x: d.left + (right - d.left) / 2, y: d.height - 9, "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.xLabel || label(settings.histogramField));
    svgText(drawing, {x: 18, y: d.top + (bottom - d.top) / 2, transform: "rotate(-90 18 " + (d.top + (bottom - d.top) / 2) + ")", "text-anchor": "middle", class: "ps-table-plot__axis-label"}, settings.yLabel || "Count");
    chartBody(figure, drawing, null);
  }

  // Epoch-aligned half-open buckets; no rates, interpolation or summary rehydration.
  function timeCountData(rows, settings) {
    let minimum = Infinity, maximum = -Infinity, missingCount = 0, invalidCount = 0;
    const groups = new Map();
    for (const row of rows) {
      const time = dateValue(row && row[settings.xField]);
      const category = settings.seriesField ? categoryValue(row && row[settings.seriesField]) : {kind:"value", key:"__all__", label:"Retained records"};
      if (time.kind === "missing" || category.kind === "missing") { missingCount++; continue; }
      if (time.kind !== "value" || category.kind !== "value") { invalidCount++; continue; }
      if (!groups.has(category.key)) {
        if (groups.size === TABLE_PLOT_LIMITS.maxSeries) return {overflow:true};
        groups.set(category.key, {key:category.key, label:category.label, points:[], counts:new Map()});
      }
      minimum = Math.min(minimum, time.value); maximum = Math.max(maximum, time.value);
    }
    if (!groups.size) return {groups:[], points:[], missing:missingCount, invalid:invalidCount};
    let width = 1000;
    while (Math.floor(maximum / width) - Math.floor(minimum / width) >= 40) width *= 2;
    for (const row of rows) {
      const time = dateValue(row && row[settings.xField]);
      const category = settings.seriesField ? categoryValue(row && row[settings.seriesField]) : {kind:"value", key:"__all__"};
      if (time.kind !== "value" || category.kind !== "value") continue;
      const group = groups.get(category.key), start = Math.floor(time.value / width) * width;
      group.counts.set(start, (group.counts.get(start) || 0) + 1);
    }
    let index = 0;
    for (const group of groups.values()) {
      // Do not draw continuous lines suggesting evidence between observed buckets.
      group.points = [...group.counts].map(([x,y]) => ({x,y,index:index++}));
      delete group.counts;
    }
    const list = [...groups.values()];
    return {groups:list, points:list.flatMap(g => g.points), missing:missingCount, invalid:invalidCount, width};
  }
  core.bucketTimeCounts = timeCountData;

  function renderTablePlot(options) {
    const settings = options && typeof options === "object" ? options : {};
    if (!["count", "sum", "mean", "min", "max"].includes(settings.aggregation)) settings.aggregation = "count";
    if (!["grouped", "stacked"].includes(settings.display)) settings.display = "grouped";
    if (!["linear", "log"].includes(settings.xScale)) settings.xScale = "linear";
    if (!["linear", "log"].includes(settings.yScale)) settings.yScale = "linear";
    const container = settings.container;
    if (!container || typeof container.appendChild !== "function") return {ok: false, reason: "missing_container", rowCount: 0, plottedCount: 0};
    const rows = rowsFor(settings);
    if (!rows.length) {
      if (settings.scopeKind !== "summary" && settings.loadedRowCount > 0 &&
          typeof settings.onResetFilters === "function") {
        return notice(container, "filtered_empty",
          "Data is available, but no rows match your search or filters. Adjust them or reset filters to show the data.",
          settings, 0, [{label: "Reset filters", onClick: settings.onResetFilters}]);
      }
      const resetActions = settings.scopeKind === "summary" || typeof settings.onResetFilters !== "function"
        ? []
        : [{label: "Reset filters", onClick: settings.onResetFilters}];
      return notice(container, "no_rows", settings.scopeKind === "summary" ? "No derived summary windows are currently loaded. Raw-table filters do not apply to this source." : "No loaded rows pass the current filters.", settings, 0, resetActions);
    }
    if (rows.length > TABLE_PLOT_LIMITS.maxSourceRows) {
      const actions = [];
      if (settings.scopeKind !== "summary" && typeof settings.onNarrowData === "function") actions.push({label: "Adjust table filters", onClick: settings.onNarrowData});
      if (typeof settings.onEditPlotField === "function") actions.push({label: "Review plot options", onClick: function () { settings.onEditPlotField("source"); }});
      return notice(container, "source_limit", "This plot has " + rows.length + " loaded rows (limit " + TABLE_PLOT_LIMITS.maxSourceRows + "). Narrow the source before plotting. Reducing categories or sampling plotted points does not reduce this processing limit. No rows were sampled or plotted." + (settings.scopeKind === "summary" ? " Table filters do not apply to summary windows." : " Table filters also affect the supporting table."), settings, rows.length, actions);
    }
    const type = String(settings.type || "bar").toLowerCase();
    const palette = paletteFor(settings);
    if (type === "bar") {
      if (!settings.categoryField) return notice(container, "missing_category_field", "Choose a categorical field for the bar chart.", settings, rows.length);
      if (settings.aggregation !== "count" && !settings.valueField) return notice(container, "missing_value_field", "Choose a numeric value field for this aggregation.", settings, rows.length);
      const series = seriesFor(rows, settings.seriesField);
      if (series.length > TABLE_PLOT_LIMITS.maxSeries) return seriesLimitNotice(container, settings, rows.length);
      const data = barData(rows, settings, series);
      if (!data.plotted) return notice(container, "no_valid_values", "No usable values were found. " + skipped(data.missing, data.invalid), settings, rows.length);
      const activeSeries = series.filter(function (group) {
        return data.categories.some(function (category) { return category.values.has(group.key); });
      });
      const autoTitle = (settings.aggregation === "count" ? "Count" : settings.aggregation.charAt(0).toUpperCase() + settings.aggregation.slice(1) + " of " + label(settings.valueField)) + " by " + label(settings.categoryField);
      const figure = frame(container, type, autoTitle, settings);
      drawBars(figure, data, activeSeries, settings, palette);
      const scope = scopeText(settings, rows.length, data.plotted);
      summary(figure, skipped(data.missing, data.invalid), scope);
      return {ok: true, type: type, rowCount: rows.length, plottedCount: data.plotted, categoryCount: data.categories.length, seriesCount: activeSeries.length, scope: scope};
    }
    if (type === "time-count") {
      if (settings.xKind !== "datetime" || settings.scopeKind === "summary") return notice(container, "unavailable_time_counts", "Counts over time require retained event timestamps; compact summaries cannot stand in for events.", settings, rows.length);
      const data = timeCountData(rows, settings);
      if (data.overflow) return seriesLimitNotice(container, settings, rows.length);
      if (!data.points.length) return notice(container, "no_valid_points", "No valid timestamps in the filtered evidence window. " + skipped(data.missing, data.invalid), settings, rows.length);
      if (data.points.length > TABLE_PLOT_LIMITS.maxPoints) return notice(container, "point_limit", "This count plot exceeds the configured " + TABLE_PLOT_LIMITS.maxPoints + " mark limit. Narrow the time window or disable Series; no counts were dropped.", settings, rows.length);
      const figure = frame(container, type, "Retained counts over time", settings);
      const counted = Object.assign({}, settings, {xScale:"linear", yScale:"linear", zeroBaseline:true, showPoints:true, yField:"Retained count", yLabel:settings.yLabel || "Retained count"});
      drawPoints(figure, "scatter", data, counted, palette);
      const plotted = rows.length - data.missing - data.invalid;
      summary(figure, "UTC buckets [start, end), " + data.width / 1000 + " seconds wide, at most 40 buckets. Points show bucket starts; missing buckets do not establish absence of real traffic. " + skipped(data.missing, data.invalid), scopeText(settings, rows.length, plotted));
      return {ok:true, type, rowCount:rows.length, plottedCount:plotted, bucketWidthMs:data.width, markCount:data.points.length};
    }
    if (type === "histogram") {
      if (!settings.histogramField) return notice(container, "missing_numeric_field", "Choose a numeric field for the histogram.", settings, rows.length);
      const data = histogramData(rows, settings);
      if (!data.values.length) return notice(container, "no_valid_values", "No usable numeric values were found. " + skipped(data.missing, data.invalid), settings, rows.length);
      const figure = frame(container, type, "Distribution of " + label(settings.histogramField), settings);
      drawHistogram(figure, data, settings, palette);
      const scope = scopeText(settings, rows.length, data.values.length);
      summary(figure, skipped(data.missing, data.invalid), scope);
      return {ok: true, type: type, rowCount: rows.length, plottedCount: data.values.length, binCount: data.bins.length, scope: scope};
    }
    if (type !== "line" && type !== "scatter") return notice(container, "unknown_type", "Choose a bar, line, scatter, or histogram plot.", settings, rows.length);
    if (!settings.xField || !settings.yField) return notice(container, "missing_numeric_field", "Choose numeric or timestamp X and numeric Y fields for the " + type + " plot.", settings, rows.length);
    const series = seriesFor(rows, settings.seriesField);
    if (series.length > TABLE_PLOT_LIMITS.maxSeries) return seriesLimitNotice(container, settings, rows.length);
    let data = pointData(rows, settings, series);
    if (!data.points.length) return notice(container, "no_valid_points", "No usable point pairs were found. Check log-scale values and selected fields. " + skipped(data.missing, data.invalid), settings, rows.length);
    const originalPointCount = data.points.length;
    const pointSelection = ["sample", "first", "latest"].includes(settings.pointSelection)
      ? settings.pointSelection
      : "refuse";
    if (originalPointCount > TABLE_PLOT_LIMITS.maxPoints && pointSelection === "refuse") {
      const actions = typeof settings.onPointLimitChoice === "function"
        ? [
            {label: "Plot even sample", onClick: function () { settings.onPointLimitChoice("sample"); }},
            {label: "Plot first " + TABLE_PLOT_LIMITS.maxPoints, onClick: function () { settings.onPointLimitChoice("first"); }},
            {label: "Plot latest " + TABLE_PLOT_LIMITS.maxPoints, onClick: function () { settings.onPointLimitChoice("latest"); }},
          ]
        : [];
      return notice(container, "point_limit", "This " + type + " plot has " + originalPointCount + " valid points (limit " + TABLE_PLOT_LIMITS.maxPoints + "). Choose a selection for this plot only; the table stays unchanged. Selections use loaded row order, and may omit rare events. Your choice also applies to future updates.", settings, rows.length, actions);
    }
    if (originalPointCount > TABLE_PLOT_LIMITS.maxPoints) {
      data = limitedPointData(data, TABLE_PLOT_LIMITS.maxPoints, pointSelection);
    }
    const figure = frame(container, type, (type === "line" ? "Line" : "Scatter") + " plot: " + label(settings.yField) + " by " + label(settings.xField), settings);
    drawPoints(figure, type, data, settings, palette);
    const scope = scopeText(settings, rows.length, data.points.length);
    const selectionDetail = data.sampledFrom
      ? "Showing " + data.points.length + " of " + data.sampledFrom + " valid points using " + (data.selectionMode === "sample" ? "an even sample" : data.selectionMode === "first" ? "the first values" : "the latest values") + "."
      : "";
    summary(figure, [selectionDetail, skipped(data.missing, data.invalid)].filter(Boolean).join(" "), scope);
    if (selectionDetail && typeof settings.onEditPlotField === "function") {
      const change = html("button", "ps-btn ps-table-plot__notice-action", "Change point selection");
      change.type = "button";
      change.addEventListener("click", function () { settings.onEditPlotField("point-selection"); });
      figure.appendChild(change);
    }
    return {ok: true, type: type, rowCount: rows.length, plottedCount: data.points.length, sampledFrom: data.sampledFrom || null, pointSelection: data.selectionMode || null, seriesCount: data.groups.length, scope: scope};
  }

  core.TABLE_PLOT_LIMITS = TABLE_PLOT_LIMITS;
  core.TABLE_PLOT_PALETTES = TABLE_PLOT_PALETTES;
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
  const SUPPORTING_TABLE_PREFERENCE_PREFIX = "plotsrv:v1:plot_supporting_table:";
  const PLOT_CONTROLS_PREFERENCE_PREFIX = "plotsrv:v1:plot_controls:";
  const PLOT_CONTROLS_PIN_PREFERENCE_PREFIX = "plotsrv:v1:plot_controls_pin:";
  const PLOT_TYPES = ["bar", "line", "scatter", "histogram", "time-count"];
  const AGGREGATIONS = ["count", "sum", "mean", "min", "max"];
  const BAR_SORTS = ["value-desc", "value-asc", "category-asc", "category-desc"];
  const PALETTE_GROUPS = [
    {kind: "discrete", label: "Discrete", keys: ["plotsrv", "accessible", "http", "ocean", "forest", "sunset", "violet", "neutral"]},
    {kind: "continuous", label: "Continuous", keys: ["viridis", "plasma", "blues", "ember"]},
  ];
  const PALETTES = PALETTE_GROUPS.flatMap(function (group) { return group.keys; });
  const STREAM_PLOT_REDRAW_MS = 2000;

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
      liveUpdates: value.liveUpdates === true,
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

  function supportingTablePreferenceKey() {
    return SUPPORTING_TABLE_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function plotControlsPreferenceKey() {
    return PLOT_CONTROLS_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function plotControlsPinPreferenceKey() {
    return PLOT_CONTROLS_PIN_PREFERENCE_PREFIX + String(config.activeViewId || "default");
  }

  function plotControlsPinned() {
    if (typeof state.tablePlotControlsPinned === "boolean") {
      return state.tablePlotControlsPinned;
    }
    let pinned = false;
    try {
      pinned = localStorage.getItem(plotControlsPinPreferenceKey()) === "pinned";
    } catch (e) {
      pinned = false;
    }
    state.tablePlotControlsPinned = pinned;
    return pinned;
  }

  function syncPlotControlsPin() {
    const panel = document.getElementById("table-plot-controls");
    const button = document.getElementById("table-plot-controls-pin");
    if (!panel || !button) return;
    const pinned = plotControlsPinned();
    if (panel.classList && typeof panel.classList.toggle === "function") {
      panel.classList.toggle("is-pinned", pinned);
    }
    button.setAttribute("aria-pressed", pinned ? "true" : "false");
    button.setAttribute("aria-label", (pinned ? "Unpin" : "Pin") + " Plot controls while scrolling");
    button.title = (pinned ? "Unpin" : "Pin") + " Plot controls while scrolling";
    syncPlotControlsLayout();
  }

  function controlsLayout() {
    if (!state.tablePlotControlsLayout) {
      try {
        state.tablePlotControlsLayout = localStorage.getItem(plotControlsPinPreferenceKey() + ":layout") === "sidebar" ? "sidebar" : "toolbar";
      } catch (e) { state.tablePlotControlsLayout = "toolbar"; }
    }
    return state.tablePlotControlsLayout;
  }

  function syncPlotControlsLayout() {
    const panel = document.getElementById("table-plot-controls");
    const workspace = document.getElementById("table-plot-workspace");
    const control = document.getElementById("table-plot-layout-control");
    const select = document.getElementById("table-plot-layout");
    const pinned = plotControlsPinned();
    const sidebar = pinned && controlsLayout() === "sidebar";
    if (control) control.hidden = !pinned;
    if (select) select.value = controlsLayout();
    if (panel) panel.classList.toggle("is-sidebar", sidebar);
    if (workspace) workspace.classList.toggle("is-sidebar", sidebar);
  }

  function syncPlotSummary() {
    const summary = document.getElementById("table-plot-controls-summary");
    if (!summary) return;
    const prefs = preferences();
    const fieldLabel = field => core.tableFieldLabel ? core.tableFieldLabel(field) : field;
    const parts = [prefs.type.charAt(0).toUpperCase() + prefs.type.slice(1)];
    if (prefs.type === "bar") {
      parts.push((prefs.aggregation === "count" ? "Count" : prefs.aggregation + " of " + fieldLabel(prefs.valueField)) + " by " + fieldLabel(prefs.categoryField));
      parts.push("Top " + prefs.categoryLimit);
      parts.push({"value-desc": "High → low", "value-asc": "Low → high", "category-asc": "A → Z", "category-desc": "Z → A"}[prefs.sort]);
      if (prefs.seriesField) parts.push(prefs.display);
    } else if (prefs.type === "histogram") {
      parts.push(fieldLabel(prefs.histogramField), prefs.bins === "auto" ? "Auto bins" : prefs.bins + " bins");
    } else if (prefs.type === "time-count") {
      parts.push("Retained count by " + fieldLabel(prefs.xField));
    } else {
      parts.push(fieldLabel(prefs.yField) + " by " + fieldLabel(prefs.xField));
    }
    if (prefs.seriesField && prefs.type !== "histogram") parts.push("Series: " + fieldLabel(prefs.seriesField));
    parts.push(paletteDefinition(prefs.palette).name + " palette");
    if (prefs.source === "summary") parts.push("Summary windows");
    summary.textContent = parts.filter(Boolean).join(" · ");
    summary.title = summary.textContent;
  }

  function setPlotControlsPinned(pinned) {
    state.tablePlotControlsPinned = pinned === true;
    try {
      localStorage.setItem(
        plotControlsPinPreferenceKey(),
        state.tablePlotControlsPinned ? "pinned" : "unpinned"
      );
    } catch (e) {
      // Sticky controls remain available when local preferences are blocked.
    }
    syncPlotControlsPin();
  }

  function plotControlsCollapsed() {
    if (typeof state.tablePlotControlsCollapsed === "boolean") {
      return state.tablePlotControlsCollapsed;
    }
    let collapsed = false;
    try {
      collapsed = localStorage.getItem(plotControlsPreferenceKey()) === "collapsed";
    } catch (e) {
      collapsed = false;
    }
    state.tablePlotControlsCollapsed = collapsed;
    return collapsed;
  }

  function syncPlotControlsDisclosure() {
    const panel = document.getElementById("table-plot-controls");
    const content = document.getElementById("table-plot-controls-content");
    const toggle = document.getElementById("table-plot-controls-toggle");
    if (!panel || !content || !toggle) return;
    const collapsed = plotControlsCollapsed();
    content.hidden = collapsed;
    const summary = document.getElementById("table-plot-controls-summary");
    const edit = document.getElementById("table-plot-edit");
    if (summary) summary.hidden = !collapsed;
    if (edit) edit.hidden = !collapsed;
    toggle.hidden = collapsed;
    syncPlotSummary();
    if (panel.classList && typeof panel.classList.toggle === "function") {
      panel.classList.toggle("is-collapsed", collapsed);
    }
    toggle.textContent = collapsed ? "+" : "−";
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      (collapsed ? "Expand" : "Collapse") + " Plot controls"
    );
    toggle.title = (collapsed ? "Expand" : "Collapse") + " Plot controls";
  }

  function setPlotControlsCollapsed(collapsed) {
    state.tablePlotControlsCollapsed = collapsed === true;
    try {
      localStorage.setItem(
        plotControlsPreferenceKey(),
        state.tablePlotControlsCollapsed ? "collapsed" : "expanded"
      );
    } catch (e) {
      // The disclosure still works when browser-local preferences are blocked.
    }
    syncPlotControlsDisclosure();
  }

  function loadSupportingTablePreference() {
    let collapsed = null;
    try {
      const stored = localStorage.getItem(supportingTablePreferenceKey());
      if (stored === "collapsed") collapsed = true;
      if (stored === "expanded") collapsed = false;
    } catch (e) {
      collapsed = null;
    }
    if (collapsed === null) {
      collapsed = typeof window.matchMedia === "function" &&
        window.matchMedia("(max-width: 640px)").matches;
    }
    state.tablePlotSupportingCollapsed = collapsed;
    return collapsed;
  }

  function supportingTableCollapsed() {
    if (typeof state.tablePlotSupportingCollapsed !== "boolean") {
      return loadSupportingTablePreference();
    }
    return state.tablePlotSupportingCollapsed;
  }

  function saveSupportingTablePreference() {
    if (core.presentationChanged) core.presentationChanged();
    try {
      localStorage.setItem(
        supportingTablePreferenceKey(),
        supportingTableCollapsed() ? "collapsed" : "expanded"
      );
    } catch (e) {
      // Supporting-table disclosure is optional browser-local convenience.
    }
  }

  function defaultPreferences() {
    return {
      type: "bar",
      source: "table",
      categoryField: "",
      xField: "",
      yField: "",
      aggregation: "count",
      valueField: "",
      histogramField: "",
      bins: "auto",
      seriesField: "",
      palette: "plotsrv",
      sort: "value-desc",
      categoryLimit: 10,
      display: "grouped",
      title: "",
      xLabel: "",
      yLabel: "",
      xScale: "linear",
      yScale: "linear",
      zeroBaseline: false,
      showPoints: true,
      legend: "top",
      titleAlign: "left",
      pointSelection: "refuse",
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
      aggregation:
        parsed && AGGREGATIONS.includes(parsed.aggregation)
          ? parsed.aggregation : defaults.aggregation,
      valueField: parsed && typeof parsed.valueField === "string" ? parsed.valueField : "",
      histogramField: parsed && typeof parsed.histogramField === "string" ? parsed.histogramField : "",
      bins: parsed && ["auto", "5", "10", "20", "40"].includes(String(parsed.bins)) ? String(parsed.bins) : defaults.bins,
      seriesField: parsed && typeof parsed.seriesField === "string" ? parsed.seriesField : "",
      palette: parsed && PALETTES.includes(parsed.palette) ? parsed.palette : defaults.palette,
      sort: parsed && BAR_SORTS.includes(parsed.sort) ? parsed.sort : defaults.sort,
      categoryLimit: parsed && [5, 10, 20, 40].includes(Number(parsed.categoryLimit)) ? Number(parsed.categoryLimit) : defaults.categoryLimit,
      display: parsed && parsed.display === "stacked" ? "stacked" : defaults.display,
      title: parsed && typeof parsed.title === "string" ? parsed.title : "",
      xLabel: parsed && typeof parsed.xLabel === "string" ? parsed.xLabel : "",
      yLabel: parsed && typeof parsed.yLabel === "string" ? parsed.yLabel : "",
      xScale: parsed && parsed.xScale === "log" ? "log" : defaults.xScale,
      yScale: parsed && parsed.yScale === "log" ? "log" : defaults.yScale,
      zeroBaseline: !!(parsed && parsed.zeroBaseline === true),
      showPoints: !parsed || parsed.showPoints !== false,
      legend: parsed && ["top", "right", "bottom"].includes(parsed.legend) ? parsed.legend : defaults.legend,
      titleAlign: parsed && parsed.titleAlign === "center" ? "center" : defaults.titleAlign,
      pointSelection: parsed && ["sample", "first", "latest"].includes(parsed.pointSelection)
        ? parsed.pointSelection
        : defaults.pointSelection,
    };
  }

  function preferences() {
    if (!state.tablePlotPreferences) loadPreferences();
    return state.tablePlotPreferences;
  }

  function savePreferences() {
    if (core.presentationChanged) core.presentationChanged();
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

  function sourceXAxisFields(source) {
    const types = source === "summary"
      ? (state.tablePlotSummaryFieldTypes || {})
      : (state.tableFieldTypes || {});
    return sourceFields(source).filter(function (field) {
      return types[field] === "number" || types[field] === "datetime";
    });
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
    const xCandidates = sourceXAxisFields(source);
    const nextType = PLOT_TYPES.includes(prefs.type) ? prefs.type : "bar";
    const nextCategory = chooseField(prefs.categoryField, allFields);
    const nextX = chooseField(prefs.xField, xCandidates);
    const nextY = chooseField(prefs.yField, numeric, nextX);
    const nextValue = chooseField(prefs.valueField, numeric);
    const nextHistogram = chooseField(prefs.histogramField, numeric);
    const nextSeries = prefs.seriesField && allFields.includes(prefs.seriesField)
      ? prefs.seriesField : "";
    const changed =
      prefs.type !== nextType ||
      prefs.source !== source ||
      prefs.categoryField !== nextCategory ||
      prefs.xField !== nextX ||
      prefs.yField !== nextY ||
      prefs.valueField !== nextValue ||
      prefs.histogramField !== nextHistogram ||
      prefs.seriesField !== nextSeries;

    prefs.type = nextType;
    prefs.source = source;
    prefs.categoryField = nextCategory;
    prefs.xField = nextX;
    prefs.yField = nextY;
    prefs.valueField = nextValue;
    prefs.histogramField = nextHistogram;
    prefs.seriesField = nextSeries;
    const typeMap = source === "summary" ? (state.tablePlotSummaryFieldTypes || {}) : (state.tableFieldTypes || {});
    let advancedChanged = false;
    if (typeMap[prefs.xField] === "datetime" && prefs.xScale !== "linear") {
      prefs.xScale = "linear";
      advancedChanged = true;
    }
    if ((prefs.xScale === "log" || prefs.yScale === "log") && prefs.zeroBaseline) {
      prefs.zeroBaseline = false;
      advancedChanged = true;
    }
    if (changed || advancedChanged) savePreferences();
    return prefs;
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function populateSelect(select, values, selected, placeholder) {
    if (!select || typeof document.createElement !== "function") return;
    const signature = JSON.stringify([values, placeholder]);
    if (select._plotsrvOptions === signature) {
      if (select.value !== (selected || "")) select.value = selected || "";
      return;
    }
    select._plotsrvOptions = signature;
    clearElement(select);

    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    select.appendChild(empty);

    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = core.tableFieldLabel ? core.tableFieldLabel(value) : value;
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

  function fieldTypes(source) {
    return source === "summary"
      ? (state.tablePlotSummaryFieldTypes || {})
      : (state.tableFieldTypes || {});
  }

  function paletteDefinition(key) {
    const palettes = core.TABLE_PLOT_PALETTES || {};
    return palettes[key] || palettes.plotsrv || {
      name: "plotsrv", kind: "discrete", colours: ["#d55970", "#7a3950", "#e58a5f"],
    };
  }

  function appendPalettePreview(target, palette) {
    clearElement(target);
    const theme = document.documentElement && document.documentElement.getAttribute("data-theme");
    const dark = theme === "dark" || (theme === "system" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const colours = dark && Array.isArray(palette.darkColours) ? palette.darkColours : palette.colours;
    colours.slice(0, 3).forEach(function (colour) {
      const swatch = document.createElement("span");
      swatch.className = "ps-table-plot-palette__swatch";
      swatch.style.backgroundColor = colour;
      target.appendChild(swatch);
    });
  }

  function renderPaletteControl(selected) {
    const preview = document.getElementById("table-plot-palette-preview");
    const name = document.getElementById("table-plot-palette-name");
    const menu = document.getElementById("table-plot-palette-menu");
    const palette = paletteDefinition(selected);
    if (preview) appendPalettePreview(preview, palette);
    if (name) name.textContent = palette.name;
    if (!menu) return;
    if (!menu.childNodes.length) {
      PALETTE_GROUPS.forEach(function (paletteGroup) {
        const group = document.createElement("div");
        group.className = "ps-table-plot-palette__group";
        group.dataset.paletteKind = paletteGroup.kind;
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", paletteGroup.label + " palettes");
        const groupLabel = document.createElement("span");
        groupLabel.className = "ps-table-plot-palette__group-label";
        groupLabel.textContent = paletteGroup.label;
        group.appendChild(groupLabel);
        paletteGroup.keys.forEach(function (key) {
          const definition = paletteDefinition(key);
          const option = document.createElement("button");
          option.type = "button";
          option.className = "ps-table-plot-palette__option";
          option.dataset.plotPalette = key;
          option.setAttribute("role", "option");
          const optionPreview = document.createElement("span");
          optionPreview.className = "ps-table-plot-palette__preview";
          appendPalettePreview(optionPreview, definition);
          option.appendChild(optionPreview);
          option.appendChild(document.createTextNode(definition.name));
          group.appendChild(option);
        });
        menu.appendChild(group);
      });
    }
    Array.from(menu.querySelectorAll("[data-plot-palette]")).forEach(function (item) {
      item.setAttribute("aria-selected", item.dataset.plotPalette === selected ? "true" : "false");
    });
  }

  function renderControls() {
    const panel = document.getElementById("table-plot-controls");
    const signature = JSON.stringify([
      preferences(), state.tableFields, state.tableFieldTypes,
      state.tablePlotSummaryFields, state.tablePlotSummaryFieldTypes,
      capabilities(),
      document.documentElement && document.documentElement.getAttribute("data-theme"),
    ]);
    if (panel && panel._plotsrvControlsSignature === signature) return;
    // Keep drafts and native dropdown navigation intact while new schemas
    // arrive. The next render after focus leaves applies any pending changes.
    if (panel && panel._plotsrvControlsSignature &&
        panel.contains(document.activeElement) &&
        panel._plotsrvPreferences === JSON.stringify(preferences())) return;
    const type = document.getElementById("table-plot-type");
    const source = document.getElementById("table-plot-source");
    const category = document.getElementById("table-plot-category");
    const x = document.getElementById("table-plot-x");
    const y = document.getElementById("table-plot-y");
    const aggregation = document.getElementById("table-plot-aggregation");
    const value = document.getElementById("table-plot-value");
    const histogram = document.getElementById("table-plot-histogram");
    const bins = document.getElementById("table-plot-bins");
    const series = document.getElementById("table-plot-series");
    const sort = document.getElementById("table-plot-sort");
    const limit = document.getElementById("table-plot-limit");
    const display = document.getElementById("table-plot-display");
    const categoryControl = document.getElementById("table-plot-category-control");
    const xControl = document.getElementById("table-plot-x-control");
    const yControl = document.getElementById("table-plot-y-control");
    const aggregationControl = document.getElementById("table-plot-aggregation-control");
    const valueControl = document.getElementById("table-plot-value-control");
    const histogramControl = document.getElementById("table-plot-histogram-control");
    const binsControl = document.getElementById("table-plot-bins-control");
    const seriesControl = document.getElementById("table-plot-series-control");
    const sortControl = document.getElementById("table-plot-sort-control");
    const limitControl = document.getElementById("table-plot-limit-control");
    const displayControl = document.getElementById("table-plot-display-control");
    const sourceControl = document.getElementById("table-plot-source-control");
    const xScale = document.getElementById("table-plot-x-scale");
    const yScale = document.getElementById("table-plot-y-scale");
    const zero = document.getElementById("table-plot-zero");
    const points = document.getElementById("table-plot-points");
    const legend = document.getElementById("table-plot-legend");
    const pointsControl = document.getElementById("table-plot-points-control");
    const legendControl = document.getElementById("table-plot-legend-control");
    const xScaleControl = document.getElementById("table-plot-x-scale-control");
    const yScaleControl = document.getElementById("table-plot-y-scale-control");
    const zeroControl = document.getElementById("table-plot-zero-control");
    const title = document.getElementById("table-plot-title");
    const titleAlign = document.getElementById("table-plot-title-align");
    const xLabel = document.getElementById("table-plot-x-label");
    const yLabel = document.getElementById("table-plot-y-label");
    const pointSelection = document.getElementById("table-plot-point-selection");
    const scopeNotice = document.getElementById("table-plot-controls-scope");
    const supportingCopy = document.getElementById("table-supporting-data-copy");
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
    const availableXAxisFields = sourceXAxisFields(prefs.source);
    populateSelect(category, availableFields, prefs.categoryField, "Choose a category");
    populateSelect(x, availableXAxisFields, prefs.xField, "Choose an x field");
    populateSelect(y, availableNumericFields, prefs.yField, "Choose a y field");
    populateSelect(value, availableNumericFields, prefs.valueField, "Choose a value");
    populateSelect(histogram, availableNumericFields, prefs.histogramField, "Choose a field");
    populateSelect(series, availableFields, prefs.seriesField, "No series");

    const isBar = prefs.type === "bar";
    const isHistogram = prefs.type === "histogram";
    const isPoints = prefs.type === "line" || prefs.type === "scatter";
    if (categoryControl) categoryControl.hidden = !isBar;
    if (xControl) xControl.hidden = !isPoints && prefs.type !== "time-count";
    if (yControl) yControl.hidden = !isPoints;
    if (aggregationControl) aggregationControl.hidden = !isBar;
    if (valueControl) valueControl.hidden = !isBar || prefs.aggregation === "count";
    if (histogramControl) histogramControl.hidden = !isHistogram;
    if (binsControl) binsControl.hidden = !isHistogram;
    if (seriesControl) seriesControl.hidden = isHistogram;
    if (sortControl) sortControl.hidden = !isBar;
    if (limitControl) limitControl.hidden = !isBar;
    if (displayControl) displayControl.hidden = !isBar || !prefs.seriesField;
    if (pointsControl) pointsControl.hidden = prefs.type !== "line";
    if (legendControl) legendControl.hidden = isHistogram || !prefs.seriesField;
    if (xScaleControl) xScaleControl.hidden = !isPoints;
    if (yScaleControl) yScaleControl.hidden = !isPoints;
    if (zeroControl) zeroControl.hidden = !isPoints;
    const pointSelectionControl = document.getElementById("table-plot-point-selection-control");
    if (pointSelectionControl) pointSelectionControl.hidden = !isPoints;
    if (aggregation) aggregation.value = prefs.aggregation;
    if (bins) bins.value = prefs.bins;
    if (sort) sort.value = prefs.sort;
    if (limit) limit.value = String(prefs.categoryLimit);
    if (display) display.value = prefs.display;
    if (xScale) {
      xScale.value = prefs.xScale;
      xScale.disabled = fieldTypes(prefs.source)[prefs.xField] === "datetime" || !isPoints;
    }
    if (yScale) { yScale.value = prefs.yScale; yScale.disabled = !isPoints; }
    if (zero) {
      zero.checked = prefs.zeroBaseline;
      zero.disabled = prefs.xScale === "log" || prefs.yScale === "log" || !isPoints;
    }
    if (points) points.checked = prefs.showPoints;
    if (legend) legend.value = prefs.legend;
    if (title) title.value = prefs.title;
    if (titleAlign) titleAlign.value = prefs.titleAlign;
    if (xLabel) xLabel.value = prefs.xLabel;
    if (yLabel) yLabel.value = prefs.yLabel;
    if (pointSelection) pointSelection.value = prefs.pointSelection;
    renderPaletteControl(prefs.palette);
    syncPlotSummary();
    if (scopeNotice) {
      scopeNotice.textContent = prefs.source === "summary"
        ? "Derived summary plots use only the currently loaded aggregate windows; they are not source log rows and raw-table filters do not apply."
        : availableCapabilities.tableScopeDescription ||
          "Plots use only loaded rows that pass the current browser filters.";
    }
    if (supportingCopy) {
      supportingCopy.textContent = prefs.source === "summary"
        ? "Recent source rows for cross-reference; this plot uses derived summary windows."
        : "Filtered rows used by this plot.";
    }
    if (panel) {
      panel._plotsrvControlsSignature = signature;
      panel._plotsrvPreferences = JSON.stringify(preferences());
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
    cancelScheduledTablePlotRefresh();
    const output = document.getElementById("table-plot-output");
    if (!output || typeof core.renderTablePlot !== "function") return null;

    if (state.myViewBlocked) { output.replaceChildren(); return null; }
    renderControls();
    const prefs = normalizePreferences();
    const options = {
      container: output,
      type: prefs.type,
      categoryField: prefs.categoryField,
      xField: prefs.xField,
      yField: prefs.yField,
      xKind: fieldTypes(prefs.source)[prefs.xField] || "number",
      aggregation: prefs.aggregation,
      valueField: prefs.valueField,
      histogramField: prefs.histogramField,
      bins: prefs.bins,
      seriesField: prefs.seriesField,
      palette: prefs.palette,
      sort: prefs.sort,
      categoryLimit: prefs.categoryLimit,
      display: prefs.display,
      title: prefs.title.trim(),
      titleAlign: prefs.titleAlign,
      xLabel: prefs.xLabel.trim(),
      yLabel: prefs.yLabel.trim(),
      xScale: prefs.xScale,
      yScale: prefs.yScale,
      zeroBaseline: prefs.zeroBaseline,
      showPoints: prefs.showPoints,
      legend: prefs.legend,
      pointSelection: prefs.pointSelection,
      onDisableSeries: function () {
        preferences().seriesField = "";
        savePreferences();
        renderControls();
        refreshTablePlot();
      },
      onEditPlotField: function (field) {
        setPlotControlsCollapsed(false);
        const advanced = document.getElementById("table-plot-advanced");
        if (advanced && (field === "source" || field === "point-selection")) advanced.open = true;
        let target = document.getElementById("table-plot-" + field);
        if (!target || !target.getClientRects().length) target = document.getElementById("table-plot-type");
        if (target) { target.focus(); target.scrollIntoView({block: "nearest"}); }
      },
      onNarrowData: function () {
        const toggle = document.getElementById("table-filters-toggle-btn");
        if (!toggle) return;
        if (toggle.getAttribute("aria-expanded") !== "true") toggle.click();
        toggle.focus();
        toggle.scrollIntoView({block: "nearest"});
      },
      loadedRowCount: Array.isArray(state.tableRows) ? state.tableRows.length : 0,
      onResetFilters:
        typeof core.resetTableFilters === "function" &&
        typeof core.hasActiveTableFiltering === "function" &&
        core.hasActiveTableFiltering()
          ? function () { core.resetTableFilters(); }
          : null,
      onPointLimitChoice: function (choice) {
        if (!["sample", "first", "latest"].includes(choice)) return;
        preferences().pointSelection = choice;
        savePreferences();
        renderControls();
        refreshTablePlot();
      },
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
      const result = core.renderTablePlot(options);
      state.tablePlotLastResult = result;
      if (typeof core.configureBottomBar === "function") core.configureBottomBar();
      return result;
    } catch (error) {
      console.error("Unable to render table plot", error);
      renderControllerError(output);
      state.tablePlotLastResult = { ok: false, reason: "renderer_error", rowCount: 0, plottedCount: 0 };
      if (typeof core.configureBottomBar === "function") core.configureBottomBar();
      return state.tablePlotLastResult;
    }
  }

  function cancelScheduledTablePlotRefresh() {
    if (state.tablePlotRefreshTimer) {
      window.clearTimeout(state.tablePlotRefreshTimer);
      state.tablePlotRefreshTimer = null;
    }
  }

  function scheduleTablePlotRefresh() {
    if (currentMode() !== "plot") return null;
    if (!capabilities().liveUpdates) return refreshTablePlot();
    if (state.tablePlotRefreshTimer) return null;
    state.tablePlotRefreshTimer = window.setTimeout(function () {
      state.tablePlotRefreshTimer = null;
      if (currentMode() === "plot") refreshTablePlot();
    }, STREAM_PLOT_REDRAW_MS);
    return null;
  }

  function redrawTable() {
    const table = state.tabulatorInstance || state.streamTabulatorInstance;
    if (!table || table.initialized === false || typeof table.redraw !== "function") return;
    try {
      table.redraw(true);
    } catch (e) {
      // A redraw failure does not prevent switching or expanding modes.
    }
  }

  function syncSupportingTable(isPlot) {
    const section = document.getElementById("table-supporting-data");
    const header = document.getElementById("table-supporting-data-header");
    const toggle = document.getElementById("table-supporting-data-toggle");
    const surface = document.getElementById("table-data-surface");
    if (!surface) return;

    const collapsed = isPlot && supportingTableCollapsed();
    surface.hidden = collapsed;
    if (header) header.hidden = !isPlot;
    if (section && section.classList && typeof section.classList.toggle === "function") {
      section.classList.toggle("is-plot-support", isPlot);
      section.classList.toggle("is-collapsed", collapsed);
    }
    if (toggle) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.textContent = collapsed ? "Show table" : "Hide table";
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
    if (core.presentationChanged) core.presentationChanged();
    if (typeof core.notifyUpdateEligibilityChanged === "function") {
      core.notifyUpdateEligibilityChanged();
    }
    const isPlot = nextMode === "plot";
    if (!isPlot) cancelScheduledTablePlotRefresh();
    controls.hidden = !isPlot;
    output.hidden = !isPlot;
    const workspace = document.getElementById("table-plot-workspace");
    if (workspace) workspace.hidden = !isPlot;
    syncPlotControlsDisclosure();
    syncPlotControlsPin();
    syncSupportingTable(isPlot);
    setButtonState(tableButton, !isPlot);
    setButtonState(plotButton, isPlot);
    if (typeof core.configureBottomBar === "function") core.configureBottomBar();

    if (isPlot) {
      if (options && options.deferPlotRefresh) scheduleTablePlotRefresh();
      else refreshTablePlot();
      if (!surface.hidden) redrawTable();
      return;
    }

    if (!options || options.redraw !== false) {
      redrawTable();
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
    const value = document.getElementById("table-plot-value");
    const histogram = document.getElementById("table-plot-histogram");
    const series = document.getElementById("table-plot-series");
    const paletteButton = document.getElementById("table-plot-palette-button");
    const paletteMenu = document.getElementById("table-plot-palette-menu");
    const reset = document.getElementById("table-plot-reset");
    const supportingToggle = document.getElementById("table-supporting-data-toggle");
    const plotControlsToggle = document.getElementById("table-plot-controls-toggle");
    const plotControlsPin = document.getElementById("table-plot-controls-pin");
    const layoutSelect = document.getElementById("table-plot-layout");
    const editPlot = document.getElementById("table-plot-edit");
    if (layoutSelect && !layoutSelect.dataset.plotsrvBound) {
      layoutSelect.addEventListener("change", function () {
        state.tablePlotControlsLayout = layoutSelect.value === "sidebar" ? "sidebar" : "toolbar";
        try { localStorage.setItem(plotControlsPinPreferenceKey() + ":layout", state.tablePlotControlsLayout); } catch (e) { /* Optional preference. */ }
        syncPlotControlsLayout();
      });
      layoutSelect.dataset.plotsrvBound = "1";
    }
    if (editPlot && !editPlot.dataset.plotsrvBound) {
      editPlot.addEventListener("click", function () {
        setPlotControlsCollapsed(false);
        document.getElementById("table-plot-type").focus();
      });
      editPlot.dataset.plotsrvBound = "1";
    }

    if (!state.tablePlotThemeChangeBound) {
      window.addEventListener("plotsrv:themechange", function () {
        renderPaletteControl(preferences().palette);
        if (currentMode() === "plot") refreshTablePlot();
      });
      state.tablePlotThemeChangeBound = true;
    }

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

    if (supportingToggle && !supportingToggle.dataset.plotsrvBound) {
      supportingToggle.addEventListener("click", function () {
        state.tablePlotSupportingCollapsed = !supportingTableCollapsed();
        saveSupportingTablePreference();
        syncSupportingTable(currentMode() === "plot");
        if (!state.tablePlotSupportingCollapsed) redrawTable();
      });
      supportingToggle.dataset.plotsrvBound = "1";
    }

    if (plotControlsToggle && !plotControlsToggle.dataset.plotsrvBound) {
      plotControlsToggle.addEventListener("click", function () {
        setPlotControlsCollapsed(!plotControlsCollapsed());
        if (plotControlsCollapsed() && editPlot) editPlot.focus();
      });
      plotControlsToggle.dataset.plotsrvBound = "1";
    }

    if (plotControlsPin && !plotControlsPin.dataset.plotsrvBound) {
      plotControlsPin.addEventListener("click", function () {
        setPlotControlsPinned(!plotControlsPinned());
      });
      plotControlsPin.dataset.plotsrvBound = "1";
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
    bindField(value, "valueField");
    bindField(histogram, "histogramField");
    bindField(series, "seriesField");

    function bindChoice(id, preferenceName, normalize) {
      const control = document.getElementById(id);
      if (!control || control.dataset.plotsrvBound) return;
      control.addEventListener("change", function () {
        preferences()[preferenceName] = normalize ? normalize(control) : control.value;
        if ((preferenceName === "xScale" || preferenceName === "yScale") && control.value === "log") {
          preferences().zeroBaseline = false;
        }
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      control.dataset.plotsrvBound = "1";
    }

    bindChoice("table-plot-aggregation", "aggregation");
    bindChoice("table-plot-bins", "bins");
    bindChoice("table-plot-sort", "sort");
    bindChoice("table-plot-limit", "categoryLimit", function (control) { return Number(control.value); });
    bindChoice("table-plot-display", "display");
    bindChoice("table-plot-x-scale", "xScale");
    bindChoice("table-plot-y-scale", "yScale");
    bindChoice("table-plot-legend", "legend");
    bindChoice("table-plot-zero", "zeroBaseline", function (control) { return control.checked; });
    bindChoice("table-plot-points", "showPoints", function (control) { return control.checked; });
    bindChoice("table-plot-title", "title");
    bindChoice("table-plot-title-align", "titleAlign");
    bindChoice("table-plot-x-label", "xLabel");
    bindChoice("table-plot-y-label", "yLabel");
    bindChoice("table-plot-point-selection", "pointSelection");

    function closePaletteMenu(restoreFocus) {
      if (!paletteMenu || !paletteButton) return;
      paletteMenu.hidden = true;
      paletteButton.setAttribute("aria-expanded", "false");
      if (restoreFocus) paletteButton.focus();
    }

    if (paletteButton && paletteMenu && !paletteButton.dataset.plotsrvBound) {
      paletteButton.addEventListener("click", function () {
        paletteMenu.hidden = !paletteMenu.hidden;
        paletteButton.setAttribute("aria-expanded", paletteMenu.hidden ? "false" : "true");
        if (!paletteMenu.hidden) {
          const selected = paletteMenu.querySelector('[aria-selected="true"]');
          if (selected) selected.focus();
        }
      });
      paletteMenu.addEventListener("click", function (event) {
        const option = event.target.closest("[data-plot-palette]");
        if (!option) return;
        preferences().palette = PALETTES.includes(option.dataset.plotPalette)
          ? option.dataset.plotPalette : "plotsrv";
        savePreferences();
        closePaletteMenu(true);
        renderControls();
        refreshTablePlot();
      });
      paletteMenu.addEventListener("keydown", function (event) {
        const options = Array.from(paletteMenu.querySelectorAll("[data-plot-palette]"));
        const index = options.indexOf(document.activeElement);
        if (event.key === "Escape") { event.preventDefault(); closePaletteMenu(true); return; }
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        const next = event.key === "ArrowDown" ? (index + 1) % options.length : (index - 1 + options.length) % options.length;
        options[next].focus();
      });
      document.addEventListener("click", function (event) {
        const root = document.getElementById("table-plot-palette");
        if (root && !root.contains(event.target)) closePaletteMenu(false);
      });
      paletteButton.dataset.plotsrvBound = "1";
    }

    if (reset && !reset.dataset.plotsrvBound) {
      reset.addEventListener("click", function () {
        state.tablePlotPreferences = defaultPreferences();
        normalizePreferences();
        savePreferences();
        renderControls();
        refreshTablePlot();
      });
      reset.dataset.plotsrvBound = "1";
    }
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
    if (core.checkPersonalViewSchema) core.checkPersonalViewSchema();
    if (currentMode() === "plot" && preferences().source === "summary") {
      scheduleTablePlotRefresh();
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
      state.tablePlotSupportingCollapsed = null;
      state.tablePlotControlsCollapsed = null;
      state.tablePlotControlsPinned = null;
      state.tablePlotControlsLayout = null;
      state.tablePlotConfigured = false;
    }

    bindControls();
    renderControls();
    applyMode(currentMode(), {
      redraw: false,
      deferPlotRefresh: capabilities().liveUpdates && state.tablePlotConfigured === true,
    });
    state.tablePlotConfigured = true;
  }

  function plotExportFilename(extension) {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const base = String(config.activeViewId || "plot").replace(/[^\w.-]+/g, "_");
    return base + "-plot-" + stamp + "." + extension;
  }

  function downloadablePlotSvg() {
    const figure = document.querySelector("#table-plot-output .ps-table-plot[data-plot-state='rendered']");
    const source = figure && figure.querySelector("svg");
    if (!figure || !source || typeof XMLSerializer === "undefined") return null;
    const clone = source.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const viewBox = (clone.getAttribute("viewBox") || "0 0 820 450").split(/\s+/).map(Number);
    clone.setAttribute("width", String(viewBox[2] || 820));
    clone.setAttribute("height", String(viewBox[3] || 450));
    const sourceNodes = [source].concat(Array.from(source.querySelectorAll("*")));
    const cloneNodes = [clone].concat(Array.from(clone.querySelectorAll("*")));
    sourceNodes.forEach(function (node, index) {
      const target = cloneNodes[index];
      if (!target || typeof window.getComputedStyle !== "function") return;
      const style = window.getComputedStyle(node);
      ["fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "font-family", "font-size", "font-weight", "opacity"].forEach(function (property) {
        const value = style.getPropertyValue(property);
        if (value) target.style.setProperty(property, value);
      });
      target.removeAttribute("tabindex");
    });
    const titleNode = figure.querySelector(".ps-table-plot__title");
    const legendItems = Array.from(figure.querySelectorAll(".ps-table-plot__legend-item"));
    let legendX = 16;
    let legendY = 48;
    const legendLayout = [];
    legendItems.forEach(function (item) {
      const width = Math.max(72, item.textContent.length * 7 + 30);
      if (legendX + width > (viewBox[2] || 820) - 16) {
        legendX = 16;
        legendY += 22;
      }
      legendLayout.push({item: item, x: legendX, y: legendY});
      legendX += width;
    });
    const headerHeight = legendItems.length ? legendY + 18 : 42;
    const drawing = document.createElementNS("http://www.w3.org/2000/svg", "g");
    drawing.setAttribute("transform", "translate(0 " + headerHeight + ")");
    while (clone.firstChild) drawing.appendChild(clone.firstChild);
    clone.appendChild(drawing);
    clone.setAttribute("viewBox", "0 0 " + (viewBox[2] || 820) + " " + ((viewBox[3] || 450) + headerHeight));
    clone.setAttribute("height", String((viewBox[3] || 450) + headerHeight));
    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    const centredTitle = figure.dataset.plotTitleAlign === "center";
    title.setAttribute("x", centredTitle ? String((viewBox[2] || 820) / 2) : "16");
    title.setAttribute("y", "25");
    if (centredTitle) title.setAttribute("text-anchor", "middle");
    title.setAttribute("font-size", "16");
    title.setAttribute("font-weight", "600");
    title.setAttribute("fill", titleNode && typeof window.getComputedStyle === "function" ? window.getComputedStyle(titleNode).color : "#25282a");
    title.textContent = titleNode ? titleNode.textContent : "plotsrv plot";
    clone.insertBefore(title, drawing);
    legendLayout.forEach(function (entry) {
      const swatch = entry.item.querySelector(".ps-table-plot__legend-swatch");
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", String(entry.x + 6));
      circle.setAttribute("cy", String(entry.y - 4));
      circle.setAttribute("r", "5");
      circle.setAttribute("fill", swatch && typeof window.getComputedStyle === "function" ? window.getComputedStyle(swatch).backgroundColor : "#d55970");
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", String(entry.x + 16));
      text.setAttribute("y", String(entry.y));
      text.setAttribute("font-size", "12");
      text.setAttribute("fill", title.getAttribute("fill"));
      text.textContent = entry.item.textContent;
      clone.insertBefore(circle, drawing);
      clone.insertBefore(text, drawing);
    });
    const background = typeof window.getComputedStyle === "function"
      ? window.getComputedStyle(figure).backgroundColor : "#ffffff";
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", String(viewBox[0] || 0));
    rect.setAttribute("y", String(viewBox[1] || 0));
    rect.setAttribute("width", String(viewBox[2] || 820));
    rect.setAttribute("height", String((viewBox[3] || 450) + headerHeight));
    rect.setAttribute("fill", background || "#ffffff");
    clone.insertBefore(rect, clone.firstChild);
    return {
      text: new XMLSerializer().serializeToString(clone),
      width: viewBox[2] || 820,
      height: (viewBox[3] || 450) + headerHeight,
    };
  }

  function downloadBlob(filename, blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function exportTablePlot(format) {
    const exported = downloadablePlotSvg();
    if (!exported) return false;
    const svgBlob = new Blob([exported.text], {type: "image/svg+xml;charset=utf-8"});
    if (format === "svg") {
      downloadBlob(plotExportFilename("svg"), svgBlob);
      return true;
    }
    if (format !== "png") return false;
    const imageUrl = URL.createObjectURL(svgBlob);
    const image = new Image();
    image.onload = function () {
      const canvas = document.createElement("canvas");
      canvas.width = exported.width * 2;
      canvas.height = exported.height * 2;
      const context = canvas.getContext("2d");
      if (!context) { URL.revokeObjectURL(imageUrl); return; }
      context.scale(2, 2);
      context.drawImage(image, 0, 0, exported.width, exported.height);
      URL.revokeObjectURL(imageUrl);
      canvas.toBlob(function (blob) {
        if (blob) downloadBlob(plotExportFilename("png"), blob);
      }, "image/png");
    };
    image.onerror = function () {
      URL.revokeObjectURL(imageUrl);
      if (typeof core.setStatusMessage === "function") core.setStatusMessage("Unable to export this plot as PNG.");
    };
    image.src = imageUrl;
    return true;
  }

  core.extractPlotPresentation = function () {
    return {mode: currentMode() === "plot" ? (supportingTableCollapsed() ? "plot" : "plot+data") : "table",
      plot: Object.assign({}, preferences())};
  };
  core.applyPlotPresentation = function (p) {
    if (state.myViewBlocked) {
      const output = document.getElementById("table-plot-output");
      if (output) output.replaceChildren();
    }
    state.tablePlotPreferences = Object.assign(defaultPreferences(), p.plot);
    state.tablePlotSupportingCollapsed = p.mode !== "plot+data";
    applyMode(p.mode === "table" ? "table" : "plot");
  };
  core.resetPlotPresentation = function () {
    state.tablePlotPreferences = defaultPreferences();
    applyMode("table");
  };
  core.configureTablePlotSurface = configureTablePlotSurface;
  core.refreshTablePlot = scheduleTablePlotRefresh;
  core.refreshTablePlotImmediately = refreshTablePlot;
  core.cancelScheduledTablePlotRefresh = cancelScheduledTablePlotRefresh;
  core.setTablePlotMode = applyMode;
  core.setTablePlotCapabilities = setTablePlotCapabilities;
  core.setTablePlotSummaryRows = setTablePlotSummaryRows;
  core.setPlotControlsCollapsed = setPlotControlsCollapsed;
  core.exportTablePlot = exportTablePlot;
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
    el("compare-enter").title = el("compare-enter").disabled ? "History becomes available when stored snapshots exist." : "Browse stored snapshots using Timeline or List";
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
    for (const mode of ["timeline", "list"]) el("compare-" + mode + "-tab").addEventListener("click", () => {ui.mode = mode; sync();});
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

