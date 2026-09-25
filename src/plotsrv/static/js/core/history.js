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
