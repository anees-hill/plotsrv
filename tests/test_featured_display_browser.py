"""Featured presentation preference in the real view selector DOM."""

from pathlib import Path

import pytest


playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).parents[1] / "src/plotsrv/static"
SELECTOR = """
<div class="ps-viewselect" data-plotsrv-viewselect="1">
  <button class="ps-viewselect__btn" type="button"></button>
  <div class="ps-viewselect__menu" hidden>
    <input class="ps-viewselect__search" type="search">
    <div class="ps-viewselect__tabs"></div>
    <div class="ps-viewselect__results"></div>
  </div>
</div>
"""


def _mount(page):
    page.set_content(SELECTOR)
    page.evaluate("""() => {
      window.PLOTSRV = {core: {}, renderers: {}, state: {}, config: {
        activeViewId: 'reports:daily',
        viewCatalogue: [
          {view_id: 'reports:daily', label: 'Daily report', section: 'Reports',
           kind: 'table', icon_key: 'table', description: 'Daily source'},
          {view_id: 'ops:health', label: 'Health', section: 'Operations',
           kind: 'plot', icon_key: 'plot'}
        ],
        featuredViews: [{view_id: 'reports:daily', title: 'Overview',
          caption: 'Featured caption', thumbnail_url: '/static/overview.png'}],
        compactViews: []
      }};
    }""")
    page.add_script_tag(path=str(STATIC / "js/core/storage.js"))
    page.add_script_tag(path=str(STATIC / "js/core/view_selector.js"))
    page.evaluate("PLOTSRV.core.bindViewDropdown()")
    page.locator(".ps-viewselect__btn").click()


def test_featured_can_switch_to_regular_entries_and_back_with_saved_preference():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("http://plotsrv.test/**", lambda route: route.fulfill(
            body="<html><body></body></html>", content_type="text/html"))
        page.goto("http://plotsrv.test/")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        _mount(page)
        featured = page.locator(".ps-viewselect__group--featured")
        toggle = featured.locator("[data-featured-display-toggle]")
        assert featured.locator(".ps-viewselect__feature").count() == 1
        assert featured.locator(".ps-viewselect__feature-title").inner_text() == "Overview"
        assert toggle.inner_text() == "Show as list"

        toggle.click()
        assert featured.locator(".ps-viewselect__feature").count() == 0
        assert featured.locator(".ps-viewselect__item").count() == 1
        assert featured.locator(".ps-viewselect__itemlabel").inner_text() == "Daily report"
        assert featured.locator(".ps-viewselect__item[data-selected='true']").count() == 1
        assert featured.locator("[data-pin-view='reports:daily']").count() == 1
        assert featured.locator(".ps-viewselect__feature-thumbnail").count() == 0
        assert toggle.inner_text() == "Show cards"
        assert toggle.evaluate("element => element === document.activeElement")
        assert page.evaluate("localStorage.getItem('plotsrv:v1:featured_display')") == "compact"
        assert page.evaluate("PLOTSRV.config.featuredViews[0].title") == "Overview"

        page.reload()
        _mount(page)
        featured = page.locator(".ps-viewselect__group--featured")
        toggle = featured.locator("[data-featured-display-toggle]")
        assert featured.locator(".ps-viewselect__item").count() == 1
        toggle.click()
        assert featured.locator(".ps-viewselect__feature").count() == 1
        assert toggle.inner_text() == "Show as list"
        assert page.evaluate("localStorage.getItem('plotsrv:v1:featured_display')") == "expanded"
        assert errors == []
        browser.close()


def test_pinned_view_remains_in_its_section_and_unpin_removes_only_shortcut():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("http://plotsrv.test/**", lambda route: route.fulfill(
            body="<html><body></body></html>", content_type="text/html"))
        page.goto("http://plotsrv.test/")
        _mount(page)

        original = page.locator('.ps-viewselect__group[aria-label="Operations"]')
        shortcut = page.locator('.ps-viewselect__group[aria-label="Pinned views"]')
        original_pin = original.locator('[data-pin-view="ops:health"]')
        assert original.locator('[data-plotsrv-view="ops:health"]').count() == 1
        assert shortcut.count() == 0

        original_pin.click()
        assert original.locator('[data-plotsrv-view="ops:health"]').count() == 1
        assert shortcut.locator('[data-plotsrv-view="ops:health"]').count() == 1
        assert page.locator('[data-plotsrv-view="ops:health"]').count() == 2
        assert original_pin.get_attribute("aria-pressed") == "true"
        assert shortcut.locator('[data-pin-view="ops:health"]').get_attribute("aria-pressed") == "true"

        shortcut.locator('[data-pin-view="ops:health"]').click()
        assert shortcut.count() == 0
        assert original.locator('[data-plotsrv-view="ops:health"]').count() == 1
        assert original_pin.get_attribute("aria-pressed") == "false"

        original_pin.click()
        assert shortcut.locator('[data-plotsrv-view="ops:health"]').count() == 1
        assert page.evaluate("JSON.parse(localStorage.getItem('plotsrv:v1:view_selector_pinned'))") == ["ops:health"]
        browser.close()
