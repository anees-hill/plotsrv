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

import plotsrv.ui_assets as ui_assets_module
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


def test_asset_manifest_rotation_is_visible_to_a_running_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = tmp_path / "static"
    dist = static / "dist"
    vendor = static / "vendor" / "tabulator" / "5.5.0"
    dist.mkdir(parents=True)
    vendor.mkdir(parents=True)
    tabulator = vendor / "tabulator.min.js"
    tabulator.write_text("tabulator", encoding="utf-8")

    def publish(version: str) -> None:
        (dist / f"plotsrv-ui.{version}.css").write_text(version, encoding="utf-8")
        (dist / f"plotsrv-ui.{version}.js").write_text(version, encoding="utf-8")
        (dist / "manifest.json").write_text(
            json.dumps(
                {
                    "css": f"/static/dist/plotsrv-ui.{version}.css",
                    "js": f"/static/dist/plotsrv-ui.{version}.js",
                    "tabulator_js": "/static/vendor/tabulator/5.5.0/tabulator.min.js",
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(ui_assets_module, "_STATIC_DIR", static)
    monkeypatch.setattr(ui_assets_module, "_MANIFEST_PATH", dist / "manifest.json")
    publish("first")
    assert get_ui_assets().css.endswith("plotsrv-ui.first.css")

    publish("second")
    (dist / "plotsrv-ui.first.css").unlink()
    (dist / "plotsrv-ui.first.js").unlink()
    assert get_ui_assets().css.endswith("plotsrv-ui.second.css")
    assert get_ui_assets().js.endswith("plotsrv-ui.second.js")


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
    assert 'label: "Other"' in renderer
    assert "maxSeries" in renderer
    assert "no points were sampled or plotted" in renderer
    assert "Raw-table filters do not apply" in renderer
    assert 'settings.scopeKind === "summary"' in renderer
    assert "PLOT_PREFERENCE_PREFIX" in controls
    assert 'state.tablePlotMode = "table"' in controls
    assert "setTablePlotSummaryRows" in controls
    assert "setTablePlotCapabilities" in controls
    assert 'config.kind === "stream"' not in controls
    assert 'reason: "renderer_error"' in controls
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
    getElementById: (id) => id === "table-grid" ? {} : null,
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
  if (mount.options.paginationSize !== 100 ||
      !mount.options.paginationSizeSelector.includes(100)) {
    throw new Error(contextLabel + " did not use the 100-row ordinary-table default");
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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_table_status_counts_canonical_rows_across_filter_and_reset() -> None:
    """Tabulator may report no active rows briefly while its mount settles."""
    table_source = _STATIC / "js" / "renderers" / "table.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const status = {innerHTML: ""};
const inline = {innerHTML: ""};
const state = {
  tableUiState: {
    searchQuery: "",
    filtersOpen: false,
    filters: [],
    columnsOpen: false,
    hiddenColumns: [],
    groupBy: null,
  },
};
const context = {
  Date,
  Promise,
  localStorage: {getItem: () => null, setItem: () => {}},
  window: {
    PLOTSRV: {core: {}, renderers: {}, state, config: {activeViewId: "table:count"}},
  },
  document: {
    getElementById: (id) => id === "status" ? status :
      (id === "table-status-inline" ? inline : null),
  },
};
const table = {
  // Reproduce the transient result that previously produced "Showing 0".
  getData: () => [],
  on: () => {},
  clearFilter: () => {},
  setFilter: () => {},
};
const payload = {
  columns: ["value"],
  rows: [{value: 1}, {value: 2}, {value: 3}],
  total_rows: 3,
  returned_rows: 3,
  loaded_rows: 3,
  total_rows_known: true,
};

vm.runInNewContext(source, context, {filename: "table.js"});
const core = context.window.PLOTSRV.core;
function configure() {
  core.configureTableExplorer({
    table,
    payload,
    rows: payload.rows,
    fields: payload.columns,
    columnDefs: [],
  });
}

configure();
if (status.innerHTML !== "Showing 3 rows.") {
  throw new Error("unfiltered status was incorrect: " + status.innerHTML);
}

state.tableUiState.filters = [{
  id: "f_1", field: "value", op: "gt", value: "1", valueTo: "",
}];
configure();
if (status.innerHTML !== "Showing 2 filtered rows of 3 loaded.") {
  throw new Error("filtered status was incorrect: " + status.innerHTML);
}
if (core.getCurrentFilteredLoadedRows().length !== 2) {
  throw new Error("filtered row source disagreed with the status");
}

state.tableUiState.filters = [];
configure();
if (status.innerHTML !== "Showing 3 rows.") {
  throw new Error("cleared-filter status was incorrect: " + status.innerHTML);
}
'''

    subprocess.run(
        ["node", "-e", script, str(table_source)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_rich_table_lines_are_shared_and_empty_surface_is_theme_aware() -> None:
    table_css = (_STATIC / "css" / "renderers" / "table.css").read_text("utf-8")
    layout_css = (_STATIC / "css" / "layout.css").read_text("utf-8")
    themes_css = (_STATIC / "css" / "themes.css").read_text("utf-8")
    stream_js = (_STATIC / "js" / "renderers" / "stream.js").read_text("utf-8")

    assert ".ps-table--rich.tabulator," in table_css
    rich_rows = table_css.split(".ps-table--rich .tabulator-row {", 1)[1].split(
        "}", 1
    )[0]
    assert "border-bottom: 0" in rich_rows
    assert ".ps-table--rich.tabulator," in themes_css
    assert ".plot-frame.empty" in layout_css
    assert "background: var(--ps-surface-soft, #fcfcfc)" in layout_css
    assert "--ps-surface-soft: #f8f9fa" in themes_css
    assert "--ps-surface-soft: #141b21" in themes_css
    assert "pagination:" not in stream_js


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
    assert re.search(
        r'<(?:script|link)\b[^>]*(?:src|href)="https?://', response.text
    ) is None


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
    assert ".ps-bottom-alert--error" in status_css
    assert "overflow-wrap: anywhere" in status_css
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
