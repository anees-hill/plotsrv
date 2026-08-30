from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


_STATIC_JS = Path(__file__).parents[1] / "src" / "plotsrv" / "static" / "js"


def _read(relative_path: str) -> str:
    return (_STATIC_JS / relative_path).read_text(encoding="utf-8")


def test_updates_are_event_driven_coalesced_and_visibility_aware() -> None:
    source = _read("core/auto_refresh.js")

    assert "setInterval" not in source
    assert "new window.EventSource" in source
    assert "state.pendingBrowserUpdate = payload" in source
    assert "getAutomaticUpdateBlockers" in source
    assert 'document.addEventListener("visibilitychange"' in source
    assert "document.hidden" in source
    assert "table_search" in source
    assert "table_filters" in source
    assert "historical_stream_session" in source
    assert "stream_paused" in source
    assert 'source.addEventListener("keepalive"' in source
    assert "STREAM_UPDATE_STALE_MS" in source
    assert "scheduleUpdateSourceWatchdog" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_stream_update_connection_replaces_only_after_missed_heartbeats() -> None:
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
let now = 0;
let nextTimer = 1;
const timers = [];
const sources = [];
class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.listeners = {};
    this.closed = false;
    sources.push(this);
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  close() { this.closed = true; this.readyState = 2; }
}
const state = {
  observedUpdateRevision: 7,
  browserUpdateSource: null,
  browserUpdateLastEventAt: null,
  browserUpdateWatchdogTimer: null,
  browserUpdateReconnectTimer: null,
};
const context = {
  Promise,
  Date: {now: () => now},
  window: {
    EventSource: FakeEventSource,
    setTimeout: (callback, delay) => {
      const timer = {id: nextTimer++, callback, delay};
      timers.push(timer);
      return timer.id;
    },
    clearTimeout: () => {},
    PLOTSRV: {
      core: {}, renderers: {}, state,
      config: {activeViewId: "logs", kind: "stream"},
    },
  },
  document: {
    hidden: false,
    activeElement: null,
    addEventListener: () => {},
    querySelector: () => null,
  },
};
vm.runInNewContext(source, context, {filename: "auto_refresh.js"});
context.window.PLOTSRV.core.bindUpdateNotifications();
if (sources.length !== 1 || timers.length !== 1 || timers[0].delay !== 20000) {
  throw new Error("the stream did not start one low-frequency liveness watchdog");
}
const first = sources[0];
now = 30000;
first.listeners.keepalive();
now = 70000;
timers.shift().callback();
if (sources.length !== 1) {
  throw new Error("a current heartbeat caused an unnecessary reconnect");
}
now = 90001;
timers.shift().callback();
if (sources.length !== 2 || !first.closed || !sources[1].url.includes("since=7")) {
  throw new Error("a silently stale stream connection was not resumed from its revision");
}
'''
    subprocess.run(
        ["node", "-e", script, str(_STATIC_JS / "core" / "auto_refresh.js")],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_stream_history_notice_refreshes_only_the_run_catalogue() -> None:
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
let catalogueRefreshes = 0;
let tableReloads = 0;
const state = {
  observedUpdateRevision: 0,
  appliedUpdateRevision: 0,
  pendingBrowserUpdate: null,
  browserUpdateApplying: false,
  initialViewLoadComplete: true,
};
const context = {
  Promise,
  window: {
    setTimeout,
    clearTimeout,
    PLOTSRV: {
      core: {
        scheduleStreamHistoryCatalogueRefresh: () => { catalogueRefreshes += 1; },
        reloadCurrentView: () => { tableReloads += 1; return Promise.resolve(true); },
      },
      renderers: {}, state,
      config: {activeViewId: "logs", kind: "stream"},
    },
  },
  document: {
    hidden: false,
    activeElement: null,
    addEventListener: () => {},
    querySelector: () => null,
  },
};
vm.runInNewContext(source, context, {filename: "auto_refresh.js"});
context.window.PLOTSRV.core.receiveBrowserUpdate({
  revision: 1,
  view_id: "logs",
  kind: "stream",
  change_type: "stream_history",
  history_catalogue_changed: true,
});
if (catalogueRefreshes !== 1 || tableReloads !== 0 || state.pendingBrowserUpdate !== null) {
  throw new Error("stored-run history notice unnecessarily reloaded live stream data");
}
'''
    subprocess.run(
        ["node", "-e", script, str(_STATIC_JS / "core" / "auto_refresh.js")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_live_stream_updates_do_not_inherit_ordinary_table_interaction_blockers() -> None:
    source = _read("core/auto_refresh.js")
    stream_boundary = source.index('if (config.kind === "stream") return blockers;')

    assert source.index('blockers.push("historical_stream_session")') < stream_boundary
    assert stream_boundary < source.index('blockers.push("table_search")')
    assert stream_boundary < source.index('blockers.push("table_sorting")')
    assert stream_boundary < source.index('blockers.push("plot_mode")')
    assert 'if (config.kind === "stream" && !state.streamPaused) return;' in source


def test_paused_stream_updates_are_retained_until_resume() -> None:
    state_source = _read("core/state.js")
    refresh_source = _read("core/auto_refresh.js")
    stream_source = _read("renderers/stream.js")
    status_source = _read("core/status.js")

    assert "state.streamPaused = false" in state_source
    assert 'blockers.push("stream_paused")' in refresh_source
    assert 'blocker === "stream_paused"' in refresh_source
    assert 'setStreamPaused(state.streamPaused !== true)' in stream_source
    pause_body = stream_source.split("function setStreamPaused(paused)", 1)[1].split(
        "function bindStreamPauseControl", 1
    )[0]
    assert "invalidateStreamLoads();" in pause_body
    assert 'core.setHeaderBrowserDataState("update_available")' in pause_body
    assert 'label: "New data"' in status_source
    assert 'context: "Live table updates are paused"' in status_source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_pause_blocks_even_forced_stream_updates_and_resume_applies_latest() -> None:
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
let reloads = 0;
const headerStates = [];
const state = {
  observedUpdateRevision: 0,
  appliedUpdateRevision: 0,
  pendingBrowserUpdate: null,
  browserUpdateApplying: false,
  browserUpdateRetryTimer: null,
  initialViewLoadComplete: true,
  streamHistoricalSessionId: null,
  streamPaused: true,
};
const context = {
  Promise,
  window: {
    setTimeout,
    clearTimeout,
    PLOTSRV: {
      core: {
        isHistoryMode: () => false,
        reloadCurrentView: () => { reloads += 1; return Promise.resolve(true); },
        setHeaderBrowserDataState: (value) => { headerStates.push(value); },
        markBrowserViewApplied: () => {},
      },
      renderers: {}, state, config: {activeViewId: "stream", kind: "stream"},
    },
  },
  document: {
    hidden: false,
    activeElement: null,
    addEventListener: () => {},
    querySelector: () => null,
  },
};
vm.runInNewContext(source, context, {filename: "auto_refresh.js"});
const core = context.window.PLOTSRV.core;
core.receiveBrowserUpdate({revision: 4, view_id: "stream", kind: "stream", change_type: "stream"});
Promise.resolve(core.applyPendingUpdate({force: true})).then(async () => {
  if (reloads !== 0 || !state.pendingBrowserUpdate || state.pendingBrowserUpdate.revision !== 4) {
    throw new Error("pause did not retain the newest stream revision");
  }
  if (!headerStates.includes("update_available")) {
    throw new Error("pause did not expose the waiting-data header state");
  }
  state.streamPaused = false;
  core.notifyUpdateEligibilityChanged();
  await Promise.resolve();
  await Promise.resolve();
  if (reloads !== 1 || state.pendingBrowserUpdate !== null || state.appliedUpdateRevision !== 4) {
    throw new Error("resume did not apply the retained stream revision");
  }
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
'''
    subprocess.run(
        ["node", "-e", script, str(_STATIC_JS / "core" / "auto_refresh.js")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_stream_session_switch_invalidates_outstanding_data_loads() -> None:
    state_source = _read("core/state.js")
    stream_source = _read("renderers/stream.js")
    reset_body = stream_source.split(
        "async function resetStreamSessionPresentation()", 1
    )[1].split("function syncSessionControl", 1)[0]
    load_body = stream_source.split("async function loadStream()", 1)[1]

    assert "state.streamLoadGeneration = 0" in state_source
    assert "state.streamLoadController = null" in state_source
    assert "state.streamTableMutationPromise = null" in state_source
    assert "invalidateStreamLoads();" in reset_body
    assert "const load = beginStreamLoad(historicalSessionId);" in load_body
    assert "streamLoadIsCurrent(load)" in load_body
    assert "controller.abort()" in stream_source
    assert "queueStreamTableMutation" in stream_source
    assert "STREAM_DATA_REQUEST_TIMEOUT_MS" in stream_source
    assert "load.timedOut = true" in stream_source
    assert 'throw new Error("stream data request timed out")' in stream_source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_hung_stream_data_request_is_aborted_and_rejected() -> None:
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const timers = [];
let rejectFetch = null;
let controller = null;
class FakeAbortController {
  constructor() { this.signal = {}; controller = this; }
  abort() {
    this.aborted = true;
    if (rejectFetch) {
      const reject = rejectFetch;
      rejectFetch = null;
      const error = new Error("aborted");
      error.name = "AbortError";
      reject(error);
    }
  }
}
const state = {
  streamLoadGeneration: 0,
  streamLoadController: null,
  streamLoadTimeoutTimer: null,
  streamHistoricalSessionId: null,
  streamCursor: null,
  streamSessionId: null,
};
const context = {
  Promise,
  fetch: () => new Promise((resolve, reject) => { rejectFetch = reject; }),
  window: {
    AbortController: FakeAbortController,
    setTimeout: (callback, delay) => { timers.push({callback, delay}); return timers.length; },
    clearTimeout: () => {},
    PLOTSRV: {
      core: {}, renderers: {}, state,
      config: {activeViewId: "logs", kind: "stream"},
    },
  },
  document: {
    getElementById: (id) => id === "stream-grid" ? {} : null,
    querySelectorAll: () => [],
    activeElement: null,
    createElement: () => ({}),
  },
};
vm.runInNewContext(source, context, {filename: "stream.js"});
const pending = context.window.PLOTSRV.core.loadStream().then(
  () => { throw new Error("the timed-out stream request unexpectedly succeeded"); },
  (error) => error
);
if (timers.length !== 1 || timers[0].delay !== 15000) {
  throw new Error("the stream request did not receive its bounded timeout");
}
timers[0].callback();
pending.then((error) => {
  if (!controller || !controller.aborted || error.message !== "stream data request timed out") {
    throw new Error("the hung stream request did not abort cleanly");
  }
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
'''
    subprocess.run(
        ["node", "-e", script, str(_STATIC_JS / "renderers" / "stream.js")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_stream_summary_loader_tracks_scope_and_newest_desired_revision() -> None:
    state_source = _read("core/state.js")
    stream_source = _read("renderers/stream.js")

    assert "state.streamSummaryScopeKey = null" in state_source
    assert "state.streamSummaryGeneration = 0" in state_source
    assert "state.streamSummaryDesired = null" in state_source
    assert "function invalidateStreamSummaryLoads()" in stream_source
    assert "while (state.streamSummaryDesired" in stream_source
    assert "payloadRevision < latest.revision" in stream_source
    assert "latest.scope.key !== desired.scope.key" in stream_source


def test_stream_http_failures_reject_the_update_transaction() -> None:
    stream_source = _read("renderers/stream.js")
    refresh_source = _read("core/auto_refresh.js")
    load_body = stream_source.split("async function loadStream()", 1)[1]

    assert 'throw new Error("stream data request failed with status "' in load_body
    assert 'throw new Error("stream data response is invalid")' in load_body
    assert 'throw new Error("Tabulator is not available")' in load_body
    assert "scheduleStreamUpdateRetry();" in refresh_source
    assert "state.browserUpdateRetryTimer" in refresh_source


def test_refresh_paths_share_in_flight_promises_and_gate_view_metadata() -> None:
    app_source = _read("core/app.js")
    status_source = _read("core/status.js")

    assert "state.reloadCurrentViewPromise" in app_source
    assert "state.statusRefreshPromise" in status_source
    assert "state.viewMenuRefreshPromise" in status_source
    assert "core.updateViewSelectorCatalogue(views)" in status_source
    assert "view_menu_revision" in status_source
    assert "await refreshViewIcons(s.view_menu_revision)" in status_source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_reload_current_view_can_load_an_artifact() -> None:
    """Exercise the browser entry point that starts initial artifact rendering."""
    script = """
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
let artifactLoads = 0;
const context = {
  Promise,
  window: {
    PLOTSRV: {
      core: {
        loadArtifact: () => {
          artifactLoads += 1;
          return Promise.resolve();
        },
        refreshStatus: () => Promise.resolve(),
      },
      renderers: {},
      state: {},
      config: {},
    },
  },
  document: {
    hidden: false,
    getElementById: (id) => (id === "artifact-root" ? {} : null),
    addEventListener: () => {},
  },
};
vm.runInNewContext(source, context, { filename: "app.js" });
context.window.PLOTSRV.core.reloadCurrentView().then(() => {
  if (artifactLoads !== 1) {
    throw new Error("artifact loader was not called");
  }
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
"""

    subprocess.run(
        ["node", "-e", script, str(_STATIC_JS / "core" / "app.js")],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_update_policy_coalesces_and_never_applies_to_a_snapshot() -> None:
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
let reloads = 0;
let historical = false;
const state = {
  observedUpdateRevision: 0,
  appliedUpdateRevision: 0,
  pendingBrowserUpdate: null,
  browserUpdateApplying: false,
  initialViewLoadComplete: true,
  tableUiState: {searchQuery: "needle", filters: []},
};
const context = {
  Promise,
  setTimeout,
  window: {
    setTimeout,
    PLOTSRV: {
      core: {
        isHistoryMode: () => historical,
        reloadCurrentView: () => { reloads += 1; return Promise.resolve(); },
        setHeaderBrowserDataState: () => {},
      },
      renderers: {}, state, config: {activeViewId: "view", kind: "table"},
    },
  },
  document: {
    hidden: false,
    activeElement: null,
    addEventListener: () => {},
    querySelector: () => ({contains: () => false}),
  },
};
vm.runInNewContext(source, context, {filename: "auto_refresh.js"});
const core = context.window.PLOTSRV.core;
core.receiveBrowserUpdate({revision: 1, view_id: "view", kind: "table", change_type: "ordinary"});
core.receiveBrowserUpdate({revision: 2, view_id: "view", kind: "table", change_type: "ordinary"});
if (reloads !== 0 || state.pendingBrowserUpdate.revision !== 2) {
  throw new Error("filtered notifications were not coalesced without mutation");
}
state.tableUiState.searchQuery = "";
core.notifyUpdateEligibilityChanged();
Promise.resolve().then(() => Promise.resolve()).then(async () => {
  if (reloads !== 1 || state.pendingBrowserUpdate !== null || state.appliedUpdateRevision !== 2) {
    throw new Error("the coalesced safe update was not applied exactly once");
  }
  historical = true;
  core.receiveBrowserUpdate({revision: 3, view_id: "view", kind: "table", change_type: "ordinary"});
  await core.applyPendingUpdate({force: true});
  if (reloads !== 1 || state.pendingBrowserUpdate.revision !== 3) {
    throw new Error("explicit application changed a historical snapshot");
  }
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
'''
    subprocess.run(
        ["node", "-e", script, str(_STATIC_JS / "core" / "auto_refresh.js")],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_failed_stream_update_is_retained_and_retried() -> None:
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const timers = [];
let reloads = 0;
const state = {
  observedUpdateRevision: 0,
  appliedUpdateRevision: 0,
  pendingBrowserUpdate: null,
  browserUpdateApplying: false,
  browserUpdateRetryTimer: null,
  initialViewLoadComplete: true,
  streamHistoricalSessionId: null,
};
const context = {
  Promise,
  window: {
    setTimeout: (callback) => { timers.push(callback); return timers.length; },
    clearTimeout: () => {},
    PLOTSRV: {
      core: {
        isHistoryMode: () => false,
        reloadCurrentView: () => {
          reloads += 1;
          return reloads === 1
            ? Promise.reject(new Error("temporary failure"))
            : Promise.resolve();
        },
        setHeaderBrowserDataState: () => {},
        markBrowserViewApplied: () => {},
      },
      renderers: {}, state, config: {activeViewId: "stream", kind: "stream"},
    },
  },
  document: {
    hidden: false,
    activeElement: null,
    addEventListener: () => {},
    querySelector: () => null,
  },
};
vm.runInNewContext(source, context, {filename: "auto_refresh.js"});
const core = context.window.PLOTSRV.core;
core.receiveBrowserUpdate({revision: 1, view_id: "stream", kind: "stream", change_type: "stream"});
Promise.resolve().then(() => Promise.resolve()).then(async () => {
  if (reloads !== 1 || state.appliedUpdateRevision !== 0 ||
      !state.pendingBrowserUpdate || state.pendingBrowserUpdate.revision !== 1) {
    throw new Error("the failed stream revision was acknowledged or discarded");
  }
  if (timers.length !== 1) throw new Error("the failed stream update was not scheduled for retry");
  core.receiveBrowserUpdate({revision: 2, view_id: "stream", kind: "stream", change_type: "stream"});
  await Promise.resolve();
  if (reloads !== 1 || !state.pendingBrowserUpdate || state.pendingBrowserUpdate.revision !== 2) {
    throw new Error("incoming data bypassed the failure backoff instead of being coalesced");
  }
  timers.shift()();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  if (reloads !== 2 || state.appliedUpdateRevision !== 2 || state.pendingBrowserUpdate !== null) {
    throw new Error("the retained stream revision was not applied by the retry");
  }
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
'''
    subprocess.run(
        ["node", "-e", script, str(_STATIC_JS / "core" / "auto_refresh.js")],
        check=True,
        capture_output=True,
        text=True,
    )
