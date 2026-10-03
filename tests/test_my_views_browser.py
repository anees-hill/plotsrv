"""Exercise personal settings through the existing real table/plot controllers."""

import pytest
from tests.test_plot_controls_browser import page, STATIC


@pytest.fixture
def personal(page):
    page.click("#table-mode-table-btn")
    for name in ("core/storage", "core/view_spec", "core/my_views"):
        page.add_script_tag(path=str(STATIC / ("js/" + name + ".js")))
    page.evaluate("PLOTSRV.core.mountPersonalViews()")
    return page


def save(page, name="My grouped table"):
    page.click("#table-save-view-btn")
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_label("Caption", exact=True).fill("A <safe> caption")
    page.get_by_role("dialog").get_by_role("button", name="Save view", exact=True).click()
    page.wait_for_function("PLOTSRV.core.viewSpec.read().items.length > 0")


def test_dirty_create_cancel_update_save_as_and_round_trip(personal):
    page = personal
    assert page.locator("#table-save-view-btn").is_disabled()
    page.select_option("#table-group-by-select", "pot")
    page.wait_for_function("!document.querySelector('#table-save-view-btn').disabled")
    save(page)
    assert page.locator("#table-save-view-btn").is_disabled()
    saved = page.evaluate("PLOTSRV.core.viewSpec.read().items[0]")
    assert saved["spec"]["presentation"]["group"] == "pot"
    assert "rows" not in saved["spec"]
    page.select_option("#table-group-by-select", "")
    page.click("#table-save-view-btn")
    page.get_by_label("Name", exact=True).fill("Cancelled")
    page.get_by_role("button", name="Cancel", exact=True).click()
    assert page.evaluate("PLOTSRV.core.viewSpec.read().items[0]") == saved
    page.evaluate(
        "PLOTSRV.core.applyPersonalView(PLOTSRV.core.viewSpec.read().items[0])"
    )
    assert page.locator("#table-group-by-select").input_value() == "pot"
    assert page.locator(".tabulator-group").count() == 2
    page.select_option("#table-group-by-select", "")
    page.click("#table-save-view-btn")
    page.get_by_role("button", name="Update", exact=True).click()
    assert (
        page.evaluate("PLOTSRV.core.viewSpec.read().items[0].spec.presentation.group")
        == ""
    )
    page.select_option("#table-group-by-select", "pot")
    page.click("#table-save-view-btn")
    page.get_by_label("Name", exact=True).fill("Second")
    page.get_by_role("button", name="Save as new", exact=True).click()
    assert page.evaluate("PLOTSRV.core.viewSpec.read().items.length") == 2


@pytest.mark.parametrize("surface", ["ordinary", "embedded", "stream"])
def test_filter_sort_columns_and_plot_round_trip_on_shared_surfaces(personal, surface):
    page = personal
    page.evaluate(
        """surface => {
      const c = PLOTSRV.core, s = PLOTSRV.state;
      if (surface === 'stream') c.configureTableExplorer({table:s.tabulatorInstance,
        fields:fixtureData.columns, rows:fixtureData.rows, plotCapabilities:{sources:['table','summary'],liveUpdates:true}});
      else if (surface === 'ordinary') c.configureTableExplorer({table:s.tabulatorInstance,fields:fixtureData.columns,rows:fixtureData.rows});
      // 'embedded' is the actual rectangular JSON/embedded-table fixture path.
      const spec = c.captureViewSpec('Filtered plot', 'latest presentation');
      spec.presentation.filters = [{field:'pot', op:'eq', value:'A', valueTo:''}];
      spec.presentation.sort = [{field:'value',dir:'desc'}];
      spec.presentation.columns = ['value','pot','timestamp'];
      spec.presentation.hidden = ['timestamp'];
      spec.presentation.mode = 'plot+data';
      spec.presentation.plot = Object.assign(spec.presentation.plot, {type:'bar',categoryField:'pot',aggregation:'sum',valueField:'value'});
      return c.applyPersonalView({id:'fixture',spec});
    }""",
        surface,
    )
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 1
    )
    assert page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getColumns().map(c => c.getField())"
    ) == ["value", "pot", "timestamp"]
    assert not page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getColumn('timestamp').isVisible()"
    )
    spec = page.evaluate(
        "PLOTSRV.core.captureViewSpec('Filtered plot', 'latest presentation')"
    )
    assert spec["presentation"]["mode"] == "plot+data"
    assert spec["presentation"]["filters"][0]["value"] == "A"
    assert spec["presentation"]["sort"] == [{"field": "value", "dir": "desc"}]
    assert page.locator(".ps-table-plot__svg").count() == 1


def test_schema_drift_pauses_filter_until_explicit_repair(personal):
    page = personal
    page.evaluate("""async () => {
      const c = PLOTSRV.core;
      const spec = c.captureViewSpec('Only A');
      spec.presentation.filters = [{field:'pot',op:'eq',value:'A',valueTo:''}];
      c.viewSpec.write({id:'filtered',spec},false);
      await c.applyPersonalView({id:'filtered',spec});
      delete PLOTSRV.state.tableFieldTypes.pot;
      c.checkPersonalViewSchema();
      await c.applyTablePresentation(spec.presentation);
    }""")
    assert page.evaluate("PLOTSRV.state.myViewBlocked")
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 0
    )
    assert "Filter on “pot”" in page.locator("#my-view-notice").inner_text()
    before = page.evaluate("PLOTSRV.core.viewSpec.read().items[0]")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Repair presentation").click()
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 2
    )
    assert page.evaluate("PLOTSRV.core.viewSpec.read().items[0]") == before
    assert "my_view" not in page.url


def test_storage_bounds_corruption_quota_and_base_path(personal):
    page = personal
    first = page.evaluate("PLOTSRV.core.viewSpec.namespace()")
    page.evaluate("history.replaceState(null,'','/another/?view=test:layout')")
    assert page.evaluate("PLOTSRV.core.viewSpec.namespace()") != first
    page.evaluate(
        "localStorage.setItem(PLOTSRV.core.viewSpec.namespace(), 'x'.repeat(262145))"
    )
    assert "safety limit" in page.evaluate("PLOTSRV.core.viewSpec.read().error")
    page.evaluate(
        "() => { localStorage.clear(); Storage.prototype.setItem = () => {throw new DOMException('Quota','QuotaExceededError')}; }"
    )
    page.select_option("#table-group-by-select", "pot")
    page.click("#table-save-view-btn")
    page.get_by_label("Name", exact=True).fill("Cannot save")
    page.get_by_role("dialog").get_by_role("button", name="Save view", exact=True).click()
    assert "disabled or full" in page.get_by_role("alert").inner_text()
    assert page.locator("dialog").is_visible()


def add_selector(page):
    from tests.test_browser_bottom_bar_assets import _render

    page.evaluate(
        """markup => {
      const t = document.createElement('template'); t.innerHTML = markup;
      document.body.prepend(t.content.querySelector('[data-plotsrv-viewselect]'));
      PLOTSRV.config.viewCatalogue = [{view_id:'test:layout',label:'Source',section:'Tables',kind:'table',icon_key:'table'}];
    }""",
        _render("table"),
    )
    page.add_script_tag(path=str(STATIC / "js/core/view_selector.js"))
    page.evaluate("PLOTSRV.core.bindViewDropdown()")
    page.locator(".ps-viewselect__btn").click()


@pytest.mark.parametrize("width", [1366, 390])
def test_selector_exact_tabs_empty_state_delete_cancel_and_focus(personal, width):
    page = personal
    page.set_viewport_size({"width": width, "height": 900})
    add_selector(page)
    assert page.get_by_role("tab").all_text_contents() == ["Grouped", "A–Z", "My views"]
    page.get_by_role("tab", name="My views", exact=True).click()
    assert (
        "Change table or plot settings"
        in page.locator(".ps-viewselect__empty").inner_text()
    )
    page.keyboard.press("Escape")
    assert page.locator(".ps-viewselect__btn").evaluate(
        "e => e === document.activeElement"
    )
    page.select_option("#table-group-by-select", "pot")
    save(page, "<img src=x onerror=alert(1)>")
    page.locator(".ps-viewselect__btn").click()
    page.get_by_role("tab", name="My views", exact=True).click()
    assert page.locator("[data-personal-view] img").count() == 1
    assert page.locator("[data-personal-view] img").get_attribute("src").endswith("/logo_table.png")
    assert page.locator("[data-personal-view] .ps-viewselect__itemlabel").inner_text() == "<img src=x onerror=alert(1)>"
    before = page.url
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("[data-personal-delete]").click()
    assert page.evaluate("PLOTSRV.core.viewSpec.read().items.length") == 1
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("[data-personal-delete]").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("PLOTSRV.core.viewSpec.read().items.length === 0")
    assert "view=" not in page.url or page.url.split("?")[0] == before.split("?")[0]
    assert page.locator(".ps-viewselect__search").evaluate(
        "e => e === document.activeElement"
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= innerWidth"
    ), page.evaluate(
        "[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth).slice(0,8).map(e=>[e.className,e.getBoundingClientRect().right])"
    )


def test_missing_source_and_cross_tab_conflict_preserve_settings(personal):
    page = personal
    page.select_option("#table-group-by-select", "pot")
    save(page)
    # A real storage event from another same-origin tab must not overwrite work.
    other = page.context.new_page()
    other.route(
        "http://plotsrv.test/**", lambda route: route.fulfill(body="<html></html>")
    )
    other.goto("http://plotsrv.test/")
    key = page.evaluate("PLOTSRV.core.viewSpec.namespace()")
    other.evaluate(
        """key => {
      const data = JSON.parse(localStorage.getItem(key)); data.items[0].spec.name = 'Other tab';
      localStorage.setItem(key, JSON.stringify(data));
    }""",
        key,
    )
    page.wait_for_function(
        "document.querySelector('#my-view-notice').textContent.includes('another tab')"
    )
    page.select_option("#table-group-by-select", "")
    page.click("#table-save-view-btn")
    page.get_by_role("button", name="Update", exact=True).click()
    assert "another tab" in page.get_by_role("alert").inner_text()
    page.get_by_role("button", name="Cancel", exact=True).click()
    add_selector(page)
    page.evaluate("PLOTSRV.core.updateViewSelectorCatalogue([])")
    page.get_by_role("tab", name="My views", exact=True).click()
    assert "Source unavailable" in page.locator("[data-personal-view]").inner_text()
    assert page.locator("[data-personal-view]").is_disabled()
    assert page.locator("[data-personal-delete]").is_enabled()
    other.close()


def test_saved_plot_field_type_change_requires_repair_and_extra_columns_do_not(
    personal,
):
    page = personal
    page.evaluate("""async () => {
      const c = PLOTSRV.core, spec = c.captureViewSpec('Plot');
      spec.presentation.mode = 'plot'; spec.presentation.plot.type = 'scatter';
      spec.presentation.plot.xField = 'timestamp'; spec.presentation.plot.yField = 'value';
      await c.applyPersonalView({id:'plot',spec});
      PLOTSRV.state.tableFieldTypes.extra = 'text'; c.checkPersonalViewSchema();
    }""")
    assert not page.evaluate("PLOTSRV.state.myViewBlocked")
    page.evaluate("""() => {
      PLOTSRV.state.tableFieldTypes.value = 'text';
      PLOTSRV.core.checkPersonalViewSchema();
      PLOTSRV.core.refreshTablePlotImmediately();
    }""")
    assert page.evaluate("PLOTSRV.state.myViewBlocked")
    assert "plot source or fields" in page.locator("#my-view-notice").inner_text()
    assert page.locator(".ps-table-plot__svg").count() == 0


def test_reset_saved_changes_and_historical_save_tracks_latest(personal):
    page = personal
    page.select_option("#table-group-by-select", "pot")
    save(page)
    page.select_option("#table-group-by-select", "")
    page.click("#table-reset-btn")
    # Reset applies table settings asynchronously, then refreshes the Save button
    # on an animation frame. The group value can change before that frame runs.
    page.wait_for_function(
        "PLOTSRV.state.tableUiState.groupBy === 'pot' && "
        "document.querySelector('#table-save-view-btn').disabled"
    )
    page.evaluate(
        "history.replaceState(null,'','/?view=test:layout&snapshot=old&session=secret-cursor')"
    )
    page.select_option("#table-group-by-select", "")
    page.click("#table-save-view-btn")
    assert (
        "does not save data, a historical snapshot or a stream session"
        in page.locator("dialog").inner_text()
    )
    page.get_by_role("button", name="Save as new", exact=True).click()
    saved = page.evaluate("PLOTSRV.core.viewSpec.read().items.at(-1)")
    assert "secret-cursor" not in str(saved)
    url = page.evaluate("item => PLOTSRV.core.personalViewUrl(item)", saved)
    assert "snapshot" not in url and "session" not in url


def test_invalid_numeric_plot_axes_are_not_silently_replaced(personal):
    page = personal
    page.evaluate("""async () => {
      const c = PLOTSRV.core, spec = c.captureViewSpec('Bad scatter');
      spec.presentation.mode = 'plot'; spec.presentation.plot.type = 'scatter';
      spec.presentation.plot.xField = 'pot'; spec.presentation.plot.yField = 'value';
      await c.applyPersonalView({id:'invalid-plot',spec});
    }""")
    assert page.evaluate("PLOTSRV.state.myViewBlocked")
    assert page.locator(".ps-table-plot__svg").count() == 0
    assert page.get_by_role("button", name="Repair presentation").is_visible()


def test_remount_keeps_saved_sort_column_order_and_draft_filters(personal):
    page = personal
    page.evaluate("""async () => {
      const c = PLOTSRV.core, spec = c.captureViewSpec('Persistent');
      spec.presentation.sort = [{field:'value',dir:'desc'}];
      spec.presentation.columns = ['value','pot','timestamp'];
      spec.presentation.filters = [{field:'pot',op:'eq',value:'A',valueTo:''}];
      await c.applyPersonalView({id:'remount',spec});
      c.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'),data:fixtureData});
    }""")
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.initialized")
    page.wait_for_function("PLOTSRV.core.extractTablePresentation().sort.length === 1")
    assert page.evaluate("PLOTSRV.core.extractTablePresentation().sort") == [
        {"field": "value", "dir": "desc"}
    ]
    assert page.evaluate("PLOTSRV.core.extractTablePresentation().columns") == [
        "value",
        "pot",
        "timestamp",
    ]
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 1
    )


def test_blocked_filter_survives_remount_and_transient_spec_saves_normally(personal):
    page = personal
    page.evaluate("""async () => {
      const c = PLOTSRV.core, spec = c.captureViewSpec('Transient presentation');
      spec.presentation.filters = [{field:'pot',op:'eq',value:'A',valueTo:''}];
      await c.applyViewSpec(spec);
      c.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'),
        data:{columns:['timestamp','value'],rows:[{timestamp:1,value:2}]}});
    }""")
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.initialized && PLOTSRV.state.myViewBlocked"
    )
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 0
    )
    page.evaluate(
        """() => PLOTSRV.core.initializeEmbeddedTableExplorer({
      grid:document.querySelector('#table-grid'), data:{columns:['timestamp','value'],rows:[{timestamp:2,value:3}]}})"""
    )
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.initialized")
    assert page.evaluate("PLOTSRV.state.myViewBlocked")
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 0
    )
    page.evaluate(
        "PLOTSRV.core.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'),data:fixtureData})"
    )
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.initialized && !PLOTSRV.state.myViewBlocked"
    )
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 1
    )
    save(page, "Saved transient")
    assert (
        page.evaluate("PLOTSRV.core.viewSpec.read().items[0].spec.name")
        == "Saved transient"
    )
