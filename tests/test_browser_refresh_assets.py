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
