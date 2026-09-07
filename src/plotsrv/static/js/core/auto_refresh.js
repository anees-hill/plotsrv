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
  const STREAM_UPDATE_STALE_MS = 55000;
  const STREAM_UPDATE_WATCHDOG_MS = 20000;
  const STREAM_UPDATE_RECONNECT_MS = 2000;

  function clearStreamUpdateRetry() {
    if (state.browserUpdateRetryTimer != null) {
      window.clearTimeout(state.browserUpdateRetryTimer);
    }
    state.browserUpdateRetryTimer = null;
    state.browserUpdateRetryAttempt = 0;
  }

  function scheduleStreamUpdateRetry() {
    if (config.kind !== "stream" || state.browserUpdateRetryTimer != null ||
        !state.pendingBrowserUpdate) return;
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
    if (document.hidden) blockers.push("hidden_tab");
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
    return blocker === "snapshot" || blocker === "historical_stream_session" ||
      blocker === "stream_paused";
  }

  function canApplyPendingUpdate(options) {
    const force = !!(options && options.force);
    const blockers = getAutomaticUpdateBlockers();
    if (blockers.some(historicalBlocker)) return false;
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
          retryImmediatelyWhenSettled = true;
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
    if (revision <= state.observedUpdateRevision) return;
    state.observedUpdateRevision = revision;

    if (payload.change_type === "reconnect" &&
        typeof core.refreshViewIcons === "function") core.refreshViewIcons(null);
    if (payload.change_type === "catalogue") {
      if (typeof core.refreshViewIcons === "function") core.refreshViewIcons(null);
      return;
    }
    if (payload.view_id && payload.view_id !== config.activeViewId) return;
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
    if (!state.initialViewLoadComplete || !canApplyPendingUpdate()) {
      showPendingUpdate();
      return;
    }
    applyPendingUpdate();
  }

  function noteUpdateSourceActivity(source) {
    if (state.browserUpdateSource !== source) return;
    state.browserUpdateLastEventAt = Date.now();
  }

  function clearUpdateSourceReconnect() {
    if (state.browserUpdateReconnectTimer != null) {
      window.clearTimeout(state.browserUpdateReconnectTimer);
    }
    state.browserUpdateReconnectTimer = null;
  }

  function connectUpdateSource() {
    if (state.browserUpdateSource || typeof window.EventSource !== "function") return;
    const url = "/updates?view=" + encodeURIComponent(config.activeViewId) +
      "&since=" + encodeURIComponent(state.observedUpdateRevision);
    const source = new window.EventSource(url);
    state.browserUpdateSource = source;
    state.browserUpdateLastEventAt = Date.now();
    source.addEventListener("open", function () {
      noteUpdateSourceActivity(source);
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
      if (state.browserUpdateSource !== source || config.kind !== "stream") return;
      // EventSource normally reconnects itself. A CLOSED source cannot do so,
      // therefore replace only that terminal case; the watchdog handles a
      // connection which remains CONNECTING or silently stalls.
      if (source.readyState === 2) scheduleUpdateSourceReconnect();
    });
  }

  function reconnectUpdateSource() {
    clearUpdateSourceReconnect();
    if (document.hidden || config.kind !== "stream") return;
    const source = state.browserUpdateSource;
    state.browserUpdateSource = null;
    if (source && typeof source.close === "function") source.close();
    connectUpdateSource();
  }

  function scheduleUpdateSourceReconnect() {
    if (state.browserUpdateReconnectTimer != null || document.hidden ||
        config.kind !== "stream") return;
    state.browserUpdateReconnectTimer = window.setTimeout(
      reconnectUpdateSource,
      STREAM_UPDATE_RECONNECT_MS
    );
  }

  function checkUpdateSourceLiveness() {
    state.browserUpdateWatchdogTimer = null;
    if (!document.hidden && config.kind === "stream" && state.browserUpdateSource) {
      const lastEventAt = Number(state.browserUpdateLastEventAt);
      if (!Number.isFinite(lastEventAt) || Date.now() - lastEventAt > STREAM_UPDATE_STALE_MS) {
        reconnectUpdateSource();
      }
    }
    scheduleUpdateSourceWatchdog();
  }

  function scheduleUpdateSourceWatchdog() {
    if (config.kind !== "stream" || state.browserUpdateWatchdogTimer != null ||
        typeof window.setTimeout !== "function") return;
    state.browserUpdateWatchdogTimer = window.setTimeout(
      checkUpdateSourceLiveness,
      STREAM_UPDATE_WATCHDOG_MS
    );
  }

  function bindUpdateNotifications() {
    connectUpdateSource();
    scheduleUpdateSourceWatchdog();
  }

  function markInitialViewLoaded() {
    state.initialViewLoadComplete = true;
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  function notifyUpdateEligibilityChanged() {
    if (state.pendingBrowserUpdate) applyPendingUpdate();
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) return;
    const lastEventAt = Number(state.browserUpdateLastEventAt);
    if (config.kind === "stream" && state.browserUpdateSource &&
        (!Number.isFinite(lastEventAt) || Date.now() - lastEventAt > STREAM_UPDATE_STALE_MS)) {
      reconnectUpdateSource();
    }
    notifyUpdateEligibilityChanged();
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
