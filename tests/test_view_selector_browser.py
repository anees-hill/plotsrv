"""Browser coverage for the view selector's layout and navigation controls."""

import re

import pytest

from plotsrv.html import render_index
from plotsrv.store import ViewMeta
from tests.test_browser_settings_assets import _ui
from tests.test_plot_controls_browser import STATIC, page


def open_dashboard(page, count=12, active=0, sections=None):
    page.route(
        "http://plotsrv.test/static/**",
        lambda route: route.fulfill(path=str(STATIC / route.request.url.split("/static/", 1)[1]))
        if (STATIC / route.request.url.split("/static/", 1)[1]).is_file() else route.abort(),
    )
    views = [
        ViewMeta(f"reports:v{i}", "artifact", f"View {i:02d}", sections[i] if sections else ("Reports" if i < 9 else "Live"))
        for i in range(count)
    ]
    markup = render_index(
        kind="artifact", table_view_mode="rich", table_html_simple=None,
        max_table_rows_simple=200, max_table_rows_rich=1000,
        ui_settings=_ui(), views=views, active_view_id=views[active].view_id,
    )
    page.set_content(re.sub(r"<script\b[^>]*>.*?</script>", "", markup, flags=re.S))
    page.add_script_tag(path=str(STATIC / "js/core/storage.js"))
    page.add_script_tag(path=str(STATIC / "js/core/view_selector.js"))
    page.evaluate("""data => {
      const views = data.views;
      PLOTSRV.config.viewCatalogue = views;
      PLOTSRV.config.activeViewId = views[data.active].view_id;
      PLOTSRV.core.bindViewDropdown();
    }""", {"views": [dict(view_id=v.view_id, kind=v.kind, label=v.label, section=v.section, icon_key="html") for v in views], "active": active})
    return views


def test_compact_menu_uses_two_columns_and_one_on_mobile(page):
    open_dashboard(page)
    page.locator(".ps-viewselect__btn").click()
    page.locator('[data-view-layout="compact"]').click()
    assert page.evaluate("localStorage.getItem('plotsrv:v1:view_selector_layout')") == "compact"
    menu = page.locator(".ps-viewselect__menu")
    assert menu.get_attribute("class").find("--compact") >= 0
    assert menu.bounding_box()["width"] > 800
    assert page.locator(".ps-viewselect__column").count() == 2
    assert page.locator(".ps-viewselect__column [data-plotsrv-view]").count() == 12
    assert page.locator(".ps-viewselect__column:nth-child(2) .ps-viewselect__group-label").count() >= 1
    assert page.locator(".ps-viewselect__item").first.bounding_box()["height"] < 40
    page.set_viewport_size({"width": 390, "height": 850})
    page.locator(".ps-viewselect__search").press("Escape")
    page.locator(".ps-viewselect__btn").click()
    assert page.locator(".ps-viewselect__menu").evaluate("node => node.getBoundingClientRect().right <= innerWidth")
    assert page.locator(".ps-viewselect__results").evaluate("node => getComputedStyle(node).gridTemplateColumns.split(' ').length === 1")
    page.locator('[data-view-layout="standard"]').click()
    assert page.locator('[data-view-layout="standard"]').get_attribute("aria-pressed") == "true"


def test_compact_menu_keeps_short_sections_together(page):
    open_dashboard(page, sections=["First"] * 4 + ["Second"] * 4 + ["Third"] * 4)
    page.locator(".ps-viewselect__btn").click()
    page.locator('[data-view-layout="compact"]').click()
    assert page.locator(".ps-viewselect__group-label").count() == 3
    assert page.locator(".ps-viewselect__column").nth(0).locator(".ps-viewselect__group-label").all_text_contents() == ["First"]


def test_view_menu_restores_scroll_after_navigation(page):
    open_dashboard(page, count=70)
    page.locator(".ps-viewselect__btn").click()
    results = page.locator(".ps-viewselect__results")
    results.evaluate("node => node.scrollTop = 420")
    assert results.evaluate("node => node.scrollTop") == 420
    page.locator("[data-plotsrv-view='reports:v15']").evaluate("node => node.click()")
    page.wait_for_url("**/?view=reports%3Av15")
    open_dashboard(page, count=70)
    page.locator(".ps-viewselect__btn").click()
    assert page.locator(".ps-viewselect__results").evaluate("node => node.scrollTop") == 420


def test_menu_icons_use_full_asset_contrast(page):
    open_dashboard(page)
    page.locator(".ps-viewselect__btn").click()
    assert page.locator(".ps-viewselect__itemicon").first.evaluate(
        "node => getComputedStyle(node).opacity"
    ) == "1"


def test_view_navigation_wraps_and_settings_can_hide_it(page):
    open_dashboard(page, count=4)
    assert page.locator(".ps-viewselect__nav button").count() == 2
    page.locator('[data-view-step="-1"]').click()
    page.wait_for_url("**/?view=reports%3Av3")
    open_dashboard(page, count=4, active=3)
    page.locator('[data-view-step="1"]').click()
    page.wait_for_url("**/?view=reports%3Av0")
    open_dashboard(page, count=4)
    page.add_script_tag(path=str(STATIC / "js/core/settings.js"))
    page.evaluate("PLOTSRV.core.continuousUpdatesEnabled = () => false; PLOTSRV.core.bindSettings()")
    page.locator("#settings-button").click()
    page.locator("#settings-view-navigation").uncheck()
    assert page.locator(".ps-viewselect").get_attribute("data-nav-hidden") == "true"
    assert page.evaluate("localStorage.getItem('plotsrv:v1:view_selector_navigation')") == "0"
    open_dashboard(page, count=4)
    assert page.locator(".ps-viewselect").get_attribute("data-nav-hidden") == "true"
    page.add_script_tag(path=str(STATIC / "js/core/settings.js"))
    page.evaluate("PLOTSRV.core.continuousUpdatesEnabled = () => false; PLOTSRV.core.bindSettings()")
    page.locator("#settings-button").click()
    page.locator("#settings-view-navigation").check()
    assert page.locator(".ps-viewselect").get_attribute("data-nav-hidden") == "false"


def test_view_navigation_follows_my_views_tab(page):
    open_dashboard(page, count=3)
    page.evaluate("""() => {
      PLOTSRV.core.viewSpec = {read: () => ({items: [
        {id: 'saved-1', spec: {sourceId: 'reports:v1', name: 'First saved', caption: ''}},
        {id: 'saved-2', spec: {sourceId: 'reports:v2', name: 'Second saved', caption: ''}}
      ]})};
      PLOTSRV.core.personalViewUrl = item => '/?view=' + encodeURIComponent(item.spec.sourceId) + '&my_view=' + item.id;
    }""")
    page.locator(".ps-viewselect__btn").click()
    page.locator('[data-view-mode="my"]').click()
    page.locator('[data-view-step="1"]').click()
    page.wait_for_url("**/?view=reports%3Av1&my_view=saved-1")


def test_view_navigation_skips_duplicate_pinned_source(page):
    open_dashboard(page, count=4)
    page.locator(".ps-viewselect__btn").click()
    page.locator('[data-pin-view="reports:v2"]').first.click()
    page.locator(".ps-viewselect__search").press("Escape")
    page.locator('[data-view-step="-1"]').click()
    page.wait_for_url("**/?view=reports%3Av2")


def test_view_catalogue_refresh_stops_after_access_denied(page):
    open_dashboard(page)
    page.add_script_tag(path=str(STATIC / "js/core/status.js"))
    calls = []

    def reject_views(route):
        calls.append(route.request.url)
        route.fulfill(status=403, content_type="application/json", body='{"detail":"Local access only"}')

    page.route("http://plotsrv.test/views?*", reject_views)
    page.evaluate("""async () => {
      PLOTSRV.state.viewMenuRevision = 0;
      PLOTSRV.config.viewMenuRefreshAllowed = false;
      await PLOTSRV.core.refreshViewIcons(1);
      await PLOTSRV.core.refreshViewIcons(2);
    }""")
    assert calls == []
    page.evaluate("""async () => {
      PLOTSRV.config.viewMenuRefreshAllowed = true;
      await PLOTSRV.core.refreshViewIcons(1);
      await PLOTSRV.core.refreshViewIcons(2);
    }""")
    assert len(calls) == 1


@pytest.mark.parametrize("width", [390, 1280])
def test_escape_closes_picker_before_deferred_focus(page, width):
    page.set_viewport_size({"width": width, "height": 850})
    open_dashboard(page)
    result = page.evaluate("""() => {
      const trigger = document.querySelector('.ps-viewselect__btn');
      const menu = document.querySelector('.ps-viewselect__menu');
      const requestFrame = window.requestAnimationFrame;
      const pending = [];
      window.requestAnimationFrame = callback => { pending.push(callback); return pending.length; };
      try {
        trigger.focus();
        trigger.click();
        const opened = !menu.hidden;
        trigger.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        const closedBeforeFrame = menu.hidden;
        pending.forEach(callback => callback(performance.now()));
        return {opened, closedBeforeFrame, closedAfterFrame: menu.hidden,
                focusRestored: document.activeElement === trigger};
      } finally {
        window.requestAnimationFrame = requestFrame;
      }
    }""")
    assert result == {
        "opened": True, "closedBeforeFrame": True,
        "closedAfterFrame": True, "focusRestored": True,
    }
