"""Description precedence and accessible disclosure using the actual bundle."""

import pytest
from tests.test_expanded_view_browser import page, mount as base_mount
from tests.test_my_views_browser import save


def mount(page, description="Source purpose"):
    reads = base_mount(page)
    page.evaluate(
        """description => {
      PLOTSRV.core.updateViewSelectorCatalogue(PLOTSRV.config.viewCatalogue.map(v=>({...v,description:v.view_id===PLOTSRV.config.activeViewId?description:null})));
    }""",
        description,
    )
    return reads


def test_description_disclosure_keyboard_escape_and_safe_text(page):
    mount(page, '<img src=x onerror="window.injected=1"> & totals')
    summary = page.locator("#view-about > summary")
    summary.focus()
    page.keyboard.press("Enter")
    assert (
        page.locator("#view-about-text").inner_text()
        == '<img src=x onerror="window.injected=1"> & totals'
    )
    assert page.locator("#view-about-text img").count() == 0
    assert page.evaluate("window.injected") is None
    page.keyboard.press("Escape")
    assert not page.locator("#view-about").evaluate("e=>e.open")
    assert summary.evaluate("e=>e===document.activeElement")
    page.click(".ps-viewselect__btn")
    assert (
        page.locator("#view-selector-results .ps-viewselect__description")
        .first.inner_text()
        .startswith("<img")
    )


def test_saved_and_suggested_captions_override_source_and_empty_falls_back(page):
    mount(page)
    page.select_option("#table-group-by-select", "group")
    save(page, "Regional totals")
    page.locator("#view-about > summary").click()
    assert page.locator("#view-about-text").inner_text() == "A <safe> caption"
    assert "My view" in page.locator("#view-about-scope").inner_text()
    page.evaluate("""() => {
      PLOTSRV.config.featuredViews=[{view_id:'tables:main',caption:'Featured purpose'}];
      PLOTSRV.core.updateViewSelectorCatalogue(PLOTSRV.config.viewCatalogue.map(v=>({...v,description:'Changed source description'})));
    }""")
    assert page.locator("#view-about-text").inner_text() == "A <safe> caption"
    page.evaluate(
        """() => {const spec=structuredClone(PLOTSRV.core.viewSpec.read().items[0].spec); spec.caption='Suggested scope'; return PLOTSRV.core.applyViewSpec(spec);}"""
    )
    assert page.locator("#view-about-text").inner_text() == "Suggested scope"
    page.evaluate(
        """() => {const spec=structuredClone(PLOTSRV.core.viewSpec.read().items[0].spec); spec.caption=''; return PLOTSRV.core.applyViewSpec(spec);}"""
    )
    assert page.locator("#view-about-text").inner_text() == "Changed source description"


def test_featured_source_and_historical_scope(page):
    mount(page)
    page.evaluate(
        "() => {PLOTSRV.config.featuredViews=[{view_id:'tables:main',caption:'Featured purpose'}]; PLOTSRV.core.syncViewExplanation();}"
    )
    page.locator("#view-about > summary").click()
    assert page.locator("#view-about-text").inner_text() == "Featured purpose"
    page.evaluate("PLOTSRV.core.snapshotNavigation.select('2')")
    assert "not stored" in page.locator("#view-about-scope").inner_text()
    page.evaluate("PLOTSRV.core.snapshotNavigation.select(null)")
    assert page.locator("#view-about-scope").inner_text() == "Featured presentation"


def test_empty_description_hides_disclosure_and_metadata_update_preserves_body(page):
    reads = mount(page, "")
    assert page.locator("#view-about").is_hidden()
    page.evaluate("window.originalTable=PLOTSRV.state.tabulatorInstance")
    before = list(reads)
    page.evaluate(
        "PLOTSRV.core.updateViewSelectorCatalogue(PLOTSRV.config.viewCatalogue.map(v=>({...v,description:'New description'})))"
    )
    assert page.locator("#view-about").is_visible()
    assert page.evaluate("PLOTSRV.state.tabulatorInstance===originalTable")
    assert reads == before
    page.locator("#view-about > summary").click()
    page.evaluate(
        "PLOTSRV.core.updateViewSelectorCatalogue(PLOTSRV.config.viewCatalogue.map(v=>({...v,description:''})))"
    )
    assert page.locator("#view-about").is_hidden()
    assert page.locator(".ps-viewselect__btn").evaluate("e=>e===document.activeElement")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_and_expanded_description_disclosure(page, theme):
    mount(page, "A bounded explanation of the business totals. " * 10)
    page.set_viewport_size({"width": 375, "height": 667})
    page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
    page.click("#expand-view")
    page.click("#expanded-reveal")
    page.locator("#view-about > summary").click()
    box = page.locator(".ps-view-about__panel").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    assert box["y"] + box["height"] <= 667
    page.keyboard.press("Escape")
    assert page.evaluate("PLOTSRV.state.expandedView.active")
    assert not page.locator("#view-about").evaluate("e=>e.open")
    page.keyboard.press("Escape")
    assert not page.evaluate("PLOTSRV.state.expandedView.active")
