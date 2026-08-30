from __future__ import annotations

from pathlib import Path

from plotsrv import html as html_mod
from plotsrv.json_model import build_json_document
from plotsrv.renderers.json_tree import JsonTreeRenderer

ROOT = Path(__file__).parents[1]
STATIC_JS = ROOT / "src" / "plotsrv" / "static" / "js"

SHARED_EXPLORER_IDS = (
    "table-search-input",
    "table-group-by-select",
    "table-mode-table-btn",
    "table-mode-plot-btn",
    "table-filter-panel",
    "table-columns-panel",
    "table-plot-controls",
    "table-plot-output",
    "table-supporting-data",
    "table-supporting-data-toggle",
)


def _render_index(kind: str) -> str:
    return html_mod.render_index(
        kind=kind,  # type: ignore[arg-type]
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        active_view_id=f"test:{kind}",
    )


def test_rich_table_stream_and_rectangular_json_share_the_explorer_contract() -> None:
    ordinary = _render_index("table")
    stream = _render_index("stream")
    document = build_json_document(
        [{"time": 1, "value": 2}, {"time": 2, "value": 4}],
        source_format="json_file",
    )
    rectangular_json = JsonTreeRenderer().render(document, view_id="json:data").html

    for markup in (ordinary, stream, rectangular_json):
        for element_id in SHARED_EXPLORER_IDS:
            assert markup.count(f'id="{element_id}"') == 1

    assert 'id="table-grid"' in ordinary
    assert 'id="stream-grid"' in stream
    assert 'data-json-table-grid="1"' in rectangular_json


def test_explorer_markup_has_one_python_owner() -> None:
    helper = (ROOT / "src" / "plotsrv" / "table_explorer_markup.py").read_text(
        encoding="utf-8"
    )
    html_source = (ROOT / "src" / "plotsrv" / "html.py").read_text(encoding="utf-8")
    json_source = (ROOT / "src" / "plotsrv" / "renderers" / "json_tree.py").read_text(
        encoding="utf-8"
    )

    assert helper.count('id="table-search-input"') == 1
    assert 'id="table-search-input"' not in html_source
    assert 'id="table-search-input"' not in json_source
    assert "render_table_explorer(" in html_source
    assert "render_table_explorer(" in json_source


def test_plot_mode_is_explicitly_plot_plus_data_and_orders_plot_before_table() -> None:
    ordinary = _render_index("table")
    helper = (ROOT / "src" / "plotsrv" / "table_explorer_markup.py").read_text(
        encoding="utf-8"
    )
    controls = (STATIC_JS / "renderers" / "table_plot_controls.js").read_text(
        encoding="utf-8"
    )

    assert "Plot + data" in ordinary
    assert 'aria-label="Data view mode"' in ordinary
    assert ordinary.index('id="table-plot-controls"') < ordinary.index(
        'id="table-plot-output"'
    )
    assert ordinary.index('id="table-plot-output"') < ordinary.index(
        'id="table-supporting-data"'
    )
    assert ordinary.index('id="table-supporting-data-header"') < ordinary.index(
        'id="table-data-surface"'
    )
    assert "Supporting table" in helper
    assert 'surface.hidden = collapsed' in controls
    assert 'header.hidden = !isPlot' in controls
    assert 'toggle.textContent = collapsed ? "Show table" : "Hide table"' in controls
    assert 'window.matchMedia("(max-width: 640px)").matches' in controls
    assert 'localStorage.setItem(' in controls


def test_plot_controls_attach_to_plot_and_supporting_table_is_separate() -> None:
    css = (
        ROOT
        / "src"
        / "plotsrv"
        / "static"
        / "css"
        / "renderers"
        / "table_plot_controls.css"
    ).read_text(encoding="utf-8")

    assert ".ps-table-plot-controls:not([hidden])" in css
    assert "margin-bottom: -0.5rem" in css
    assert ".ps-table-plot-controls + .ps-table-plot-root > .ps-table-plot" in css
    assert ".ps-table-supporting-data__header" in css
    assert ".ps-table-supporting-data.is-plot-support #table-data-surface" in css


def test_plot_controls_have_a_matching_remembered_disclosure() -> None:
    rendered = _render_index("table")
    controls = (STATIC_JS / "renderers" / "table_plot_controls.js").read_text(
        encoding="utf-8"
    )
    css = (
        ROOT
        / "src"
        / "plotsrv"
        / "static"
        / "css"
        / "renderers"
        / "table_plot_controls.css"
    ).read_text(encoding="utf-8")

    assert 'id="table-plot-controls-title">Plot controls</h2>' in rendered
    assert 'id="table-plot-controls-content"' in rendered
    assert 'id="table-plot-controls-toggle"' in rendered
    assert 'aria-label="Collapse Plot controls"' in rendered
    assert 'document.getElementById("table-plot-controls-toggle")' in controls
    assert 'toggle.textContent = collapsed ? "+" : "−"' in controls
    assert 'localStorage.setItem(' in controls
    assert ".ps-table-plot-controls.is-collapsed" in css


def test_plot_sources_are_capabilities_not_renderer_kind_branches() -> None:
    controls = (STATIC_JS / "renderers" / "table_plot_controls.js").read_text(
        encoding="utf-8"
    )
    table = (STATIC_JS / "renderers" / "table.js").read_text(encoding="utf-8")
    stream = (STATIC_JS / "renderers" / "stream.js").read_text(encoding="utf-8")
    json_renderer = (STATIC_JS / "renderers" / "json.js").read_text(encoding="utf-8")

    assert 'config.kind === "stream"' not in controls
    assert "setTablePlotCapabilities" in controls
    assert 'plotCapabilities: { sources: ["table"] }' in table
    assert 'sources: ["table", "summary"]' in stream
    assert 'plotCapabilities: { sources: ["table"] }' in json_renderer
    assert "raw-table filters do not apply" in controls


def test_rectangular_json_restores_table_and_plot_modes_across_updates() -> None:
    source = (STATIC_JS / "renderers" / "json.js").read_text(encoding="utf-8")

    assert (
        'const allowed = new Set(["json", "simple", "text", "table", "plot"])' in source
    )
    assert "!hasTableExplorer(jsonRoot)" in source
    assert "prefs.mode = nextMode" in source
    assert '["json", "simple", "text", "table", "plot"].includes(' in source
    assert 'core.setTablePlotMode("table", { redraw: false })' in source


def test_shared_plot_failures_remain_readable() -> None:
    renderer = (STATIC_JS / "renderers" / "table_plot.js").read_text(encoding="utf-8")
    controls = (STATIC_JS / "renderers" / "table_plot_controls.js").read_text(
        encoding="utf-8"
    )

    assert '"No loaded rows pass the current filters.' in renderer
    assert '"No derived summary windows are currently loaded.' in renderer
    assert '"Choose numeric x and y fields' in renderer
    assert '"point_limit"' in renderer
    assert '"category_limit"' in renderer
    assert 'notice.dataset.plotState = "error"' in controls
    assert 'reason: "renderer_error"' in controls
