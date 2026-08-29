from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv import config, store
from plotsrv.app import app
from plotsrv.ui_assets import get_ui_assets

_ROOT = Path(__file__).parents[1]
_STATIC = _ROOT / "src" / "plotsrv" / "static"


def _static_requests(html: str) -> list[str]:
    return re.findall(r'(?:src|href)="(/static/[^"]+)"', html)


def test_manifest_only_exposes_existing_local_assets() -> None:
    raw = json.loads((_STATIC / "dist" / "manifest.json").read_text("utf-8"))
    assets = get_ui_assets()

    assert raw["tabulator_version"] == "5.5.0"
    assert assets.css.startswith("/static/dist/plotsrv-ui.")
    assert assets.js.startswith("/static/dist/plotsrv-ui.")
    assert assets.tabulator_js == "/static/vendor/tabulator/5.5.0/tabulator.min.js"
    for url in (assets.css, assets.js, assets.tabulator_js):
        assert (_STATIC / url.removeprefix("/static/")).is_file()


def test_committed_bundles_match_ui_sources() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_ui_assets.py", "--check"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_table_plot_renderer_is_local_and_has_explicit_limits() -> None:
    renderer = (
        _STATIC / "js" / "renderers" / "table_plot.js"
    ).read_text("utf-8")
    controls = (
        _STATIC / "js" / "renderers" / "table_plot_controls.js"
    ).read_text("utf-8")
    bundle = (_STATIC / get_ui_assets().js.removeprefix("/static/")).read_text("utf-8")

    assert "core.renderTablePlot = renderTablePlot" in renderer
    assert "core.getCurrentFilteredLoadedRows" in renderer
    assert "maxSourceRows" in renderer
    assert "maxPoints" in renderer
    assert "maxCategories" in renderer
    assert "no categories were collapsed or sampled" in renderer
    assert "no points were sampled or plotted" in renderer
    assert "retained recent raw observation window" in renderer
    assert 'settings.scopeKind === "summary"' in renderer
    assert "PLOT_PREFERENCE_PREFIX" in controls
    assert 'state.tablePlotMode = "table"' in controls
    assert "setTablePlotSummaryRows" in controls
    assert "raw-table filters do not apply" in controls
    assert "plotsrv source: js/renderers/table_plot.js" in bundle
    assert "plotsrv source: js/renderers/table_plot_controls.js" in bundle
    assert "core.configureTablePlotSurface" in bundle
    assert "plotsrv source: css/renderers/table_plot.css" in (
        _STATIC / get_ui_assets().css.removeprefix("/static/")
    ).read_text("utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_shared_table_renderer_mounts_flat_data_controlled_columns_safely() -> None:
    """Exercise static and embedded Table mounts with hostile and dotted keys."""
    table_source = _STATIC / "js" / "renderers" / "table.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const unsafeName = '<img src=x onerror="window.__header_xss = 1">';
const payload = {
  columns: [unsafeName, "http.status"],
  rows: [{[unsafeName]: "label", "http.status": 200}],
  total_rows: 1,
  returned_rows: 1,
  loaded_rows: 1,
  total_rows_known: true,
};
const mounts = [];
const context = {
  Date,
  Promise,
  encodeURIComponent,
  localStorage: {getItem: () => null, setItem: () => {}},
  window: {
    PLOTSRV: {core: {}, renderers: {}, state: {}, config: {activeViewId: "json:unsafe"}},
  },
  document: {
    createElement: (tagName) => ({tagName, textContent: ""}),
    getElementById: () => null,
  },
  fetch: async () => ({ok: true, status: 200, json: async () => payload}),
  Tabulator: function (target, options) {
    mounts.push({target, options});
    this.on = () => {};
    this.getData = () => options.data;
    this.clearFilter = () => {};
    this.destroy = () => {};
  },
};

function assertSafeFlatColumns(mount, contextLabel) {
  if (!mount || mount.options.nestedFieldSeparator !== false) {
    throw new Error(contextLabel + " did not keep dotted keys flat");
  }
  if (mount.options.data[0]["http.status"] !== 200) {
    throw new Error(contextLabel + " did not retain a dotted key");
  }
  const column = mount.options.columns[0];
  if (column.title !== "") {
    throw new Error(contextLabel + " passed a data-controlled string title");
  }
  const title = column.titleFormatter();
  if (title.textContent !== unsafeName) {
    throw new Error(contextLabel + " did not render its title through textContent");
  }
}

vm.runInNewContext(source, context, {filename: "table.js"});
const core = context.window.PLOTSRV.core;
if (!core.initializeEmbeddedTableExplorer({grid: {}, data: payload})) {
  throw new Error("embedded table explorer did not mount");
}
assertSafeFlatColumns(mounts[0], "embedded table");
core.disposeEmbeddedTableExplorer();
core.loadTable().then(() => {
  assertSafeFlatColumns(mounts[1], "static table");
}).catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
'''

    subprocess.run(
        ["node", "-e", script, str(table_source)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_standard_page_uses_two_bundles_and_no_remote_assets() -> None:
    store.reset()
    config.set_table_view_mode("simple")
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "https://unpkg.com" not in response.text
    loaded = _static_requests(response.text)
    assert get_ui_assets().css in loaded
    assert get_ui_assets().js in loaded
    assert get_ui_assets().tabulator_js not in loaded


def test_rich_table_loads_local_tabulator_before_plotsrv_bundle() -> None:
    store.reset()
    config.set_table_view_mode("rich")
    store.set_table(pd.DataFrame({"value": [1]}), html_simple=None)
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assets = get_ui_assets()
    loaded = _static_requests(response.text)
    assert assets.tabulator_js in loaded
    assert response.text.index(assets.tabulator_js) < response.text.index(assets.js)
    assert "http://" not in response.text
    assert "https://" not in response.text


def test_built_assets_are_served_by_the_application() -> None:
    client = TestClient(app)
    assets = get_ui_assets()

    css = client.get(assets.css)
    js = client.get(assets.js)
    tabulator = client.get(assets.tabulator_js)

    assert css.status_code == 200
    assert js.status_code == 200
    assert tabulator.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert "javascript" in js.headers["content-type"]
    assert "window.PLOTSRV" in js.text
    assert "Tabulator" in tabulator.text


def test_watch_errors_have_a_compact_status_presentation() -> None:
    status_js = (_STATIC / "js" / "core" / "status.js").read_text("utf-8")
    status_css = (_STATIC / "css" / "status.css").read_text("utf-8")
    text_css = (_STATIC / "css" / "renderers" / "text.css").read_text("utf-8")

    assert "errWrap.hidden = false" in status_js
    assert "errWrap.hidden = true" in status_js
    assert "flex-basis: 100%" in status_css
    assert ".ps-watch-error" in text_css


def test_public_module_compatibility_imports_remain_available() -> None:
    import plotsrv.app as app_module
    import plotsrv.cli as cli_module
    import plotsrv.runtime as runtime_module
    import plotsrv.server as server_module

    assert callable(cli_module.build_parser)
    assert callable(app_module.require_local_request)
    assert callable(runtime_module.file_backed_load_slot)
    assert callable(server_module.refresh_view)
