"""Exercise the real shared plot controls and SVG renderer in Chromium.

Run with: uv run --with playwright pytest tests/test_plot_controls_browser.py
Requires a Playwright Chromium installation.
"""
from pathlib import Path

import pytest

from plotsrv.table_explorer_markup import render_table_explorer
from plotsrv.ui_assets import get_ui_assets

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).parents[1] / "src/plotsrv/static"


@pytest.fixture
def page():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=pw.chromium.executable_path)
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("http://plotsrv.test/**", lambda route: route.fulfill(body="<html><body></body></html>", content_type="text/html"))
        page.goto("http://plotsrv.test/")
        page.set_content(render_table_explorer(grid_html='<div id="table-grid" class="ps-table--rich"></div>', search_placeholder="Search"))
        page.add_style_tag(path=str(STATIC / get_ui_assets().css.removeprefix("/static/")))
        page.evaluate("document.body.style.padding = '16px'")
        for name in ("vendor/tabulator/5.5.0/tabulator.min.js", "js/core/dom.js", "js/renderers/table.js", "js/renderers/table_plot.js", "js/renderers/table_plot_controls.js"):
            page.add_script_tag(path=str(STATIC / name))
        page.evaluate("""() => {
          PLOTSRV.config.activeViewId = 'test:layout';
          window.fixtureData = {columns: ['pot', 'timestamp', 'value'], rows: [
            {pot:'A', timestamp:1, value:2}, {pot:'B', timestamp:2, value:3}
          ], total_rows:2, returned_rows:2};
          PLOTSRV.core.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'), data:fixtureData,
            plotCapabilities:{sources:['table','summary'], liveUpdates:true}});
        }""")
        page.click("#table-mode-plot-btn")
        page.wait_for_selector(".ps-table-plot__svg")
        yield page
        browser.close()
        assert not errors


def preferences(page):
    return page.evaluate("JSON.stringify(PLOTSRV.state.tablePlotPreferences)")


@pytest.mark.parametrize("plot_type", ["bar", "line", "scatter"])
def test_series_recovery_preserves_live_notice_and_table(page, plot_type):
    page.evaluate("""() => {
      window.recoveryRows = Array.from({length:12}, (_, i) => ({pot:'group'+i, timestamp:i, value:i+1}));
      PLOTSRV.core.getCurrentFilteredLoadedRows = () => recoveryRows;
    }""")
    page.select_option("#table-plot-type", plot_type)
    page.select_option("#table-plot-series", "pot")
    assert "Too many series" in page.locator("#table-plot-output").inner_text()
    button = page.get_by_role("button", name="Turn Series off", exact=True)
    button.focus()
    page.evaluate("window.recoveryButton = document.activeElement")
    page.evaluate("PLOTSRV.core.refreshTablePlotImmediately()")
    assert page.evaluate("document.activeElement === recoveryButton && recoveryButton.isConnected")
    page.click("#table-plot-controls-toggle")
    page.get_by_role("button", name="Choose another field", exact=True).click()
    assert page.locator("#table-plot-series").evaluate("e => e === document.activeElement")
    assert page.locator("#table-plot-series").input_value() == "pot"
    button.click()
    assert page.evaluate("PLOTSRV.state.tablePlotLastResult.ok")
    assert page.locator("#table-plot-series").input_value() == ""
    assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData().length") == 2
    assert page.evaluate("JSON.parse(localStorage.getItem('plotsrv:v1:table_plot:test:layout')).seriesField") == ""
    page.evaluate("PLOTSRV.core.refreshTablePlotImmediately()")
    assert page.evaluate("PLOTSRV.state.tablePlotLastResult.ok")


@pytest.mark.parametrize("choice,button_label", [
    ("latest", "Plot latest 5000"), ("first", "Plot first 5000"), ("sample", "Plot even sample"),
])
def test_point_recovery_persists_and_reopens_advanced(page, choice, button_label):
    page.evaluate("""() => {
      window.recoveryRows = Array.from({length:5001}, (_, i) => ({pot:'A', timestamp:i, value:i+1}));
      PLOTSRV.core.getCurrentFilteredLoadedRows = () => recoveryRows;
    }""")
    page.select_option("#table-plot-type", "scatter")
    page.get_by_role("button", name=button_label, exact=True).click()
    assert page.evaluate("PLOTSRV.state.tablePlotLastResult.plottedCount") == 5000
    assert "Showing 5000 of 5001" in page.locator("#table-plot-output").inner_text()
    page.evaluate("recoveryRows.push({pot:'A', timestamp:5002, value:5002}); PLOTSRV.core.refreshTablePlotImmediately()")
    assert page.evaluate("PLOTSRV.state.tablePlotLastResult.sampledFrom") == 5002
    assert page.evaluate("JSON.parse(localStorage.getItem('plotsrv:v1:table_plot:test:layout')).pointSelection") == choice
    page.click("#table-plot-controls-toggle")
    page.get_by_role("button", name="Change point selection", exact=True).click()
    assert page.locator("#table-plot-point-selection").evaluate("e => e === document.activeElement")


def test_source_limit_recovery_and_bounded_series_check(page):
    page.evaluate("""() => {
      PLOTSRV.core.getCurrentFilteredLoadedRows = () => new Array(100001).fill({pot:'A', timestamp:1, value:2});
      PLOTSRV.core.refreshTablePlotImmediately();
    }""")
    assert "Narrow the data" in page.locator("#table-plot-output").inner_text()
    page.get_by_role("button", name="Adjust table filters", exact=True).click()
    assert page.locator("#table-filter-panel").is_visible()
    # No need to inspect every distinct group, nor build any bars, once the cap is exceeded.
    assert page.evaluate("""() => {
      let reads = 0;
      const rows = Array.from({length:100}, (_, i) => ({get pot() { reads++; return 'group'+i; }}));
      const result = PLOTSRV.core.renderTablePlot({container:document.createElement('div'), rows,
        type:'bar', categoryField:'pot', aggregation:'count', seriesField:'pot'});
      return result.reason === 'series_limit' && reads === 9;
    }""")


def test_presentations_preserve_controls_state_and_live_updates(page):
    page.select_option("#table-plot-category", "pot")
    saved = preferences(page)
    page.evaluate("window.originalType = document.querySelector('#table-plot-type')")
    page.click("#table-plot-controls-toggle")
    assert not page.locator("#table-plot-type").is_visible()
    assert "Count by pot" in page.locator("#table-plot-controls-summary").inner_text()
    assert page.evaluate("localStorage.getItem('plotsrv:v1:plot_controls:test:layout')") == "collapsed"
    page.click("#table-plot-edit")
    assert preferences(page) == saved
    assert not page.locator("#table-plot-layout").is_visible()
    page.click("#table-plot-controls-pin")
    assert page.locator("#table-plot-layout").is_visible()
    for layout in ("sidebar", "toolbar"):
        page.select_option("#table-plot-layout", layout)
        assert preferences(page) == saved
        assert page.evaluate("originalType === document.querySelector('#table-plot-type')")
        page.select_option("#table-plot-sort", "value-asc")
        assert page.evaluate("PLOTSRV.state.tablePlotPreferences.sort") == "value-asc"
        page.select_option("#table-plot-sort", "value-desc")
        assert preferences(page) == saved
        page.click("#table-plot-controls-toggle")
        assert page.locator("#table-plot-controls").bounding_box()["height"] < 180
        page.click("#table-plot-edit")
        assert preferences(page) == saved
        page.locator("#table-plot-advanced > summary").click()
        assert page.locator("#table-plot-source").is_visible()
        page.fill("#table-plot-title", "My plot")
        page.locator("#table-plot-title").dispatch_event("change")
        assert "My plot" in page.locator("#table-plot-output").inner_text()
        page.fill("#table-plot-title", "")
        page.locator("#table-plot-title").dispatch_event("change")
        page.locator("#table-plot-advanced > summary").click()
        assert not page.locator("#table-plot-source").is_visible()
        assert preferences(page) == saved
    page.click("#table-plot-controls-pin")
    assert not page.locator("#table-plot-layout").is_visible()
    assert preferences(page) == saved
    page.click("#table-plot-controls-pin")
    page.select_option("#table-plot-layout", "sidebar")
    # Simulate a new stream batch through the existing shared controller.
    page.evaluate("""() => {
      fixtureData.rows.push({pot:'C', timestamp:3, value:4});
      PLOTSRV.core.configureTableExplorer({table:PLOTSRV.state.tabulatorInstance,
        fields:fixtureData.columns, rows:fixtureData.rows, payload:fixtureData,
        plotCapabilities:{sources:['table','summary'], liveUpdates:true}});
    }""")
    page.wait_for_function("PLOTSRV.state.tablePlotLastResult.rowCount === 3")
    assert preferences(page) == saved


@pytest.mark.parametrize("width", [1920, 1366, 900, 600])
def test_responsive_toolbar_and_sidebar(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    panel = page.locator("#table-plot-controls")
    if width >= 1366:
        assert panel.bounding_box()["height"] < 180
    for layout in ("toolbar", "sidebar"):
        if not page.locator("#table-plot-layout").is_visible():
            page.click("#table-plot-controls-pin")
        page.select_option("#table-plot-layout", layout)
        controls = panel.bounding_box()
        plot = page.locator("#table-plot-output").bounding_box()
        if layout == "sidebar" and width >= 900:
            assert 240 <= controls["width"] <= 300
            assert plot["x"] >= controls["x"] + controls["width"]
        else:
            assert plot["y"] >= controls["y"] + controls["height"]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.select_option("#table-plot-type", "histogram")
        assert page.locator("#table-plot-bins").is_visible()
        assert not page.locator("#table-plot-category").is_visible()
        assert not page.locator("#table-plot-series").is_visible()
        page.select_option("#table-plot-bins", "5")
        assert page.evaluate("PLOTSRV.state.tablePlotLastResult.type") == "histogram"
        page.select_option("#table-plot-type", "scatter")
        assert page.locator("#table-plot-x").is_visible()
        assert not page.locator("#table-plot-bins").is_visible()
        page.select_option("#table-plot-type", "bar")
