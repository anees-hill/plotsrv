from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


_STATIC_JS = Path(__file__).parents[1] / "src" / "plotsrv" / "static" / "js"


def _read(relative_path: str) -> str:
    return (_STATIC_JS / relative_path).read_text(encoding="utf-8")


def test_auto_refresh_is_completion_scheduled_and_visibility_aware() -> None:
    source = _read("core/auto_refresh.js")

    assert "setInterval" not in source
    assert "window.setTimeout" in source
    assert "state.autoRefreshGeneration" in source
    assert 'document.addEventListener("visibilitychange"' in source
    assert "document.hidden" in source


def test_refresh_paths_share_in_flight_promises_and_gate_view_metadata() -> None:
    app_source = _read("core/app.js")
    status_source = _read("core/status.js")

    assert "state.reloadCurrentViewPromise" in app_source
    assert "state.statusRefreshPromise" in status_source
    assert "state.viewMenuRefreshPromise" in status_source
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
