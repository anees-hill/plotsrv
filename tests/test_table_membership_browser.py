"""One-of text filters share semantics across the table and plot."""
import pytest

from tests.test_plot_controls_browser import page


def test_membership_filters_table_plot_and_saved_preferences(page):
    page.evaluate("""() => {
      window.planetData = {columns:['planet','value'], rows:[
        {planet:'Earth',value:1}, {planet:'Mars',value:2}, {planet:'Venus',value:3},
        {planet:'New Earth',value:4}, {planet:'Earth, Mars',value:5}, {planet:null,value:6}
      ]};
      PLOTSRV.core.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'),data:planetData});
    }""")
    page.click("#table-mode-table-btn")
    page.click("#table-filters-toggle-btn")
    page.click("#table-filter-add-btn")
    op = page.locator('[data-filter-part="op"]').first
    op.select_option("in")
    values = page.get_by_role("textbox", name="Values, one per line", exact=True)
    assert values.get_attribute("placeholder") is None
    assert values.input_value() == ""
    assert values.evaluate("e => getComputedStyle(e).resize") == "none"
    assert abs(values.bounding_box()["height"] - op.bounding_box()["height"]) < 3
    values.fill(" Earth \n\nMARS\nEarth")
    assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').map(r=>r.planet)") == ["Earth", "Mars"]
    assert page.locator("#table-active-filters").inner_text().startswith('planet is one of "Earth", "MARS"')
    for theme in ("light", "dark"):
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        assert page.locator(".ps-table-filter-chip").first.evaluate("e => getComputedStyle(e).backgroundColor !== getComputedStyle(e).getPropertyValue('--ps-surface-raised').trim()")
    page.click("#table-mode-plot-btn")
    assert page.evaluate("PLOTSRV.state.tablePlotLastResult.rowCount") == 2
    # Reload the locally saved preferences into a fresh table instance.
    page.evaluate("""() => {
      PLOTSRV.state.tableUiState = null;
      PLOTSRV.core.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'),data:planetData});
    }""")
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.getData('active').length === 2")
    assert values.input_value() == " Earth \n\nMARS\nEarth"
    op.select_option("not_in")
    assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').map(r=>r.planet)") == ["Venus", "New Earth", "Earth, Mars", None]
    # Delimit on lines, never on punctuation within a literal string.
    op.select_option("in")
    values.fill("Earth, Mars")
    assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 1
    values.fill(" \n ")
    assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 6
    values.fill("Earth\nMars")
    page.click("#table-filter-add-btn")
    page.locator('[data-filter-part="field"]').nth(1).select_option("value")
    page.locator('[data-filter-part="op"]').nth(1).select_option("gt")
    page.locator('[data-filter-part="value"]').nth(1).fill("1")
    assert page.evaluate("PLOTSRV.core.getCurrentFilteredLoadedRows().map(r=>r.planet)") == ["Mars"]
    assert page.evaluate("PLOTSRV.state.tablePlotLastResult.rowCount") == 1
    # Numeric columns do not advertise the text-only membership operators.
    assert page.locator('[data-filter-part="op"]').nth(1).locator('option[value="in"]').count() == 0


def test_separate_membership_filters_union_only_within_same_column(page):
    page.evaluate("""() => {
      window.membershipData = {columns:['planet','origin','value'], rows:[
        {planet:'Earth',origin:'A',value:1}, {planet:'Earth',origin:'B',value:2},
        {planet:'Mars',origin:'A',value:3}, {planet:'Venus',origin:'A',value:4}
      ]};
      PLOTSRV.core.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'),data:membershipData});
    }""")
    page.click("#table-filters-toggle-btn")

    def add(field, operator, value):
        page.click("#table-filter-add-btn")
        page.locator('[data-filter-part="field"]').last.select_option(field)
        page.locator('[data-filter-part="op"]').last.select_option(operator)
        page.locator('[data-filter-part="value"]').last.fill(value)

    def assert_count(count):
        assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == count
        assert page.evaluate("PLOTSRV.state.tablePlotLastResult.rowCount") == count

    add("planet", "in", "Earth")
    add("planet", "in", "Mars")
    assert_count(3)
    add("origin", "in", "A")
    assert_count(2)
    add("origin", "in", "B")
    assert_count(3)
    # Empty lists do not broaden the union or suppress complete filters.
    add("planet", "in", " \n ")
    assert_count(3)
    page.evaluate("""() => {
      PLOTSRV.state.tableUiState = null;
      PLOTSRV.core.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'),data:membershipData});
    }""")
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.getData('active').length === 3")
    add("planet", "not_in", "Earth")
    assert_count(1)
    add("planet", "not_in", "Mars")
    assert_count(0)
    page.locator('[data-filter-action="remove"]').last.click()
    assert_count(1)
    page.locator('[data-filter-action="remove"]').last.click()
    assert_count(3)
    # Removing one positive list narrows only that column's union.
    page.locator('[data-filter-action="remove"]').nth(1).click()
    assert_count(2)
