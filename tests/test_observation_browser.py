"""Real shared Tabulator/plot/personal presentation behaviour for observations."""

import numpy as np
import pandas as pd

from tests.test_plot_controls_browser import page, STATIC
from tests.test_observation_presentation import summary
from plotsrv.observations.history import compact
from plotsrv.observations.rendering import render_observation


def document(source=None, *, prior=False, snapshot=False):
    if source is None:
        source = pd.DataFrame({"value": np.arange(1000), "missing": [None] * 1000})
    value = summary(source, at=2)
    value["view_id"] = "test:layout"
    entries = []
    if prior:
        old = summary({"rows": 100}, at=1)
        old["view_id"] = "test:layout"
        entries = [
            dict(compact(old), received_at=1700000000),
            dict(compact(value), received_at=1700000020),
        ]
    return render_observation(
        value, view_id="test:layout", entries=entries, snapshot=snapshot
    ).html


def mount(page, html):
    page.click("#table-mode-table-btn")
    page.evaluate("PLOTSRV.core.disposeEmbeddedTableExplorer()")
    page.evaluate(
        "html => {document.body.innerHTML = html;}",
        '<main><div id="artifact-root">' + html + "</div></main>",
    )
    for module in (
        "core/storage",
        "core/view_spec",
        "core/my_views",
        "core/http_suggestions",
        "renderers/observation",
        "core/auto_refresh",
    ):
        page.add_script_tag(path=str(STATIC / ("js/" + module + ".js")))
    page.evaluate(
        "PLOTSRV.config.kind='artifact'; PLOTSRV.renderers.initObservation(document.getElementById('artifact-root'))"
    )
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.initialized && PLOTSRV.state.tableUiState.filters.length === 1"
    )
    page.wait_for_function("!PLOTSRV.state.tableUiState.filtersOpen")


def test_overview_default_live_filter_and_keyboard_suggestion_save(page):
    mount(page, document())
    assert page.evaluate("document.body.scrollWidth <= window.innerWidth")
    assert page.get_by_role("heading", name="Observation overview").is_visible()
    assert page.locator("#table-save-view-btn").is_disabled()
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 2
    )
    assert "table_filters" not in page.evaluate(
        "PLOTSRV.core.getAutomaticUpdateBlockers()"
    )
    select = page.get_by_label("Suggested observation views")
    select.focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    select.select_option("1")
    page.wait_for_function(
        "PLOTSRV.state.tablePlotLastResult && PLOTSRV.state.tablePlotLastResult.ok"
    )
    assert page.locator(".ps-table-plot__svg").count() == 1
    assert "plot_mode" in page.evaluate("PLOTSRV.core.getAutomaticUpdateBlockers()")
    page.click("#table-save-view-btn")
    page.get_by_label("Name", exact=True).fill("Missingness")
    page.get_by_role("dialog").get_by_role(
        "button", name="Save view", exact=True
    ).click()
    page.wait_for_function("PLOTSRV.core.viewSpec.read().items.length === 1")
    saved = page.evaluate("PLOTSRV.core.viewSpec.read().items[0]")
    assert saved["spec"]["requirements"]["capability"] == "observation-v1"
    assert saved["spec"]["sourceId"] == "test:layout"
    assert "rows" not in saved["spec"]
    select.select_option("0")
    page.evaluate(
        "PLOTSRV.core.applyPersonalView(PLOTSRV.core.viewSpec.read().items[0])"
    )
    page.wait_for_function("PLOTSRV.state.tablePlotMode === 'plot'")


def test_distribution_and_irregular_scalar_scatter_use_shared_plot(page):
    mount(page, document())
    page.get_by_label("Suggested observation views").select_option("2")
    page.wait_for_function(
        "PLOTSRV.state.tablePlotLastResult && PLOTSRV.state.tablePlotLastResult.ok"
    )
    assert page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getData('active').every(row => row.surface.startsWith('Distribution:'))"
    )
    page.evaluate("PLOTSRV.core.disposeEmbeddedTableExplorer()")
    page.evaluate(
        "html => {document.body.innerHTML = html;}",
        '<main><div id="artifact-root">'
        + document({"rows": 125}, prior=True)
        + "</div></main>",
    )
    page.evaluate(
        "PLOTSRV.renderers.initObservation(document.getElementById('artifact-root'))"
    )
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.initialized")
    # Field overview, missingness, then the available scalar trend.
    page.get_by_label("Suggested observation views").select_option("2")
    page.wait_for_function(
        "PLOTSRV.state.tablePlotLastResult && PLOTSRV.state.tablePlotLastResult.ok && PLOTSRV.state.tablePlotPreferences.type === 'scatter'"
    )
    assert page.evaluate("PLOTSRV.state.tablePlotLastResult.plottedCount") == 2
    assert "irregular" in page.locator("#my-view-notice").inner_text()


def test_user_filter_survives_remount_and_capability_loss_pauses(page):
    mount(page, document())
    page.evaluate("""async () => {
      const spec = PLOTSRV.core.captureViewSpec('Only value', 'Captured field');
      spec.presentation.filters.push({field:'field',op:'eq',value:'value',valueTo:''});
      await PLOTSRV.core.applyViewSpec(spec);
    }""")
    assert "table_filters" in page.evaluate("PLOTSRV.core.getAutomaticUpdateBlockers()")
    page.evaluate("PLOTSRV.core.disposeEmbeddedTableExplorer()")
    page.evaluate(
        "html => {document.body.innerHTML = html;}",
        '<main><div id="artifact-root">'
        + document(pd.DataFrame({"value": [5, 6], "missing": [None, None]}))
        + "</div></main>",
    )
    page.evaluate(
        "PLOTSRV.renderers.initObservation(document.getElementById('artifact-root'))"
    )
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.initialized && PLOTSRV.state.tabulatorInstance.getData('active').length === 1"
    )
    assert page.evaluate(
        "PLOTSRV.state.tableUiState.filters.some(f => f.field === 'field' && f.value === 'value')"
    )
    page.evaluate("""() => {
      PLOTSRV.state.observationProfile=null;
      PLOTSRV.core.checkPersonalViewSchema();
    }""")
    assert page.evaluate("PLOTSRV.state.myViewBlocked")
    assert (
        "no longer provides observation" in page.locator("#my-view-notice").inner_text()
    )


def test_snapshot_no_examples_and_mobile_dark_layout(page):
    page.set_viewport_size({"width": 390, "height": 844})
    mount(page, document(snapshot=True))
    page.evaluate(
        "document.documentElement.dataset.theme='dark'; PLOTSRV.core.isHistoryMode=() => true"
    )
    assert "snapshot" in page.evaluate("PLOTSRV.core.getAutomaticUpdateBlockers()")
    assert "fixed historical evidence" in page.locator("#artifact-root").inner_text()
    assert page.get_by_text("Examples / sample", exact=False).count() == 0
    page.get_by_text("Capture details and provenance", exact=True).focus()
    page.keyboard.press("Enter")
    assert page.locator("details[open]").count() == 1
    assert page.evaluate("document.body.scrollWidth <= window.innerWidth")


def test_distribution_binding_pauses_after_column_rename(page):
    mount(page, document())
    page.get_by_label("Suggested observation views").select_option("2")
    page.wait_for_function(
        "PLOTSRV.state.tablePlotLastResult && PLOTSRV.state.tablePlotLastResult.ok"
    )
    page.evaluate("PLOTSRV.core.disposeEmbeddedTableExplorer()")
    page.evaluate(
        "html => document.getElementById('artifact-root').innerHTML=html",
        document(pd.DataFrame({"renamed": np.arange(1000), "missing": [None] * 1000})),
    )
    page.evaluate(
        "PLOTSRV.renderers.initObservation(document.getElementById('artifact-root'))"
    )
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.initialized && PLOTSRV.state.myViewBlocked"
    )
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 0
    )


def test_missing_snapshot_and_late_live_response_cannot_resume_live(page):
    mount(page, document(snapshot=True))
    page.add_script_tag(path=str(STATIC / "js/core/history.js"))
    page.add_script_tag(path=str(STATIC / "js/renderers/artifact.js"))
    page.evaluate("""async () => {
      const {core, state, renderers} = PLOTSRV;
      core.refreshStatus = () => Promise.resolve();
      renderers.initArtifactEnhancements = () => {};
      document.body.insertAdjacentHTML('beforeend', '<select id="history-select"></select>');
      window.fetch = async () => ({ok:true,json:async()=>({snapshots:[]})});
      state.currentSnapshot = 'deleted';
      await core.loadHistory();
      await core.handleMissingSnapshot('artifact');
    }""")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "deleted"
    assert page.locator("#history-select").input_value() == "deleted"
    page.evaluate("""async () => {
      const {core, state} = PLOTSRV;
      let release;
      window.fetch = () => new Promise(resolve => {release=resolve;});
      state.currentSnapshot = null;
      window.pendingLive = core.loadArtifact();
      window.releaseLive = release;
      state.currentSnapshot = 'fixed';
      window.fetch = async () => ({ok:true,json:async()=>({kind:'json',html:'<p>Fixed snapshot</p>'})});
      await core.loadArtifact();
      release({ok:true,json:async()=>({kind:'json',html:'<p>Stale live data</p>'})});
      await window.pendingLive;
    }""")
    assert page.locator("#artifact-root").inner_text() == "Fixed snapshot"
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "fixed"


def test_missing_artifact_keeps_historical_selection(page):
    mount(page, document(snapshot=True))
    previous = page.locator("#artifact-root").inner_text()
    page.add_script_tag(path=str(STATIC / "js/core/history.js"))
    page.add_script_tag(path=str(STATIC / "js/renderers/artifact.js"))
    page.evaluate("""async () => {
      PLOTSRV.core.refreshStatus = () => Promise.resolve();
      PLOTSRV.state.currentSnapshot = 'deleted';
      window.fetch = async () => ({ok:false,status:404});
      await PLOTSRV.core.loadArtifact();
    }""")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "deleted"
    assert page.locator("#artifact-root").inner_text() == previous
    assert "unavailable or unreadable" in page.evaluate("PLOTSRV.state.snapshotNavigation.error")
