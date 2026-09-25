"""Empty tables stay clear when data changes and under both appearance themes."""

from tests.test_plot_controls_browser import page


def test_rich_table_empty_state_tracks_rows_and_themes(page):
    page.click("#table-mode-table-btn")
    page.evaluate("""() => PLOTSRV.core.initializeEmbeddedTableExplorer({
      grid: document.querySelector('#table-grid'),
      data: {columns: ['value'], rows: []}
    })""")
    empty = page.locator("#table-grid .tabulator-placeholder")
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.initialized")
    assert empty.is_visible()
    assert empty.inner_text() == "No data"
    assert empty.bounding_box()["height"] > 200

    for theme in ("light", "dark"):
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        assert empty.locator(".tabulator-placeholder-contents").evaluate("""element =>
          {
            const probe = document.createElement('span');
            probe.style.color = 'var(--ps-text)';
            document.body.appendChild(probe);
            const matches = getComputedStyle(element).color === getComputedStyle(probe).color;
            probe.remove();
            return matches;
          }
        """)

    page.evaluate("() => PLOTSRV.state.tabulatorInstance.replaceData([{value: 1}])")
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.getData().length === 1")
    assert not empty.is_visible()
    page.evaluate("() => PLOTSRV.state.tabulatorInstance.replaceData([])")
    assert empty.is_visible()


def test_simple_table_refresh_replaces_empty_state(page):
    page.evaluate("""() => {
      PLOTSRV.core.disposeEmbeddedTableExplorer();
      document.querySelector('#table-grid').remove();
      const simple = document.createElement('div');
      simple.id = 'simple-table-root';
      simple.className = 'ps-table--simple';
      document.querySelector('#table-data-surface').appendChild(simple);
      window.tableRows = [];
      window.fetch = async () => ({ok: true, json: async () => ({columns: ['value'], rows: tableRows})});
    }""")
    assert page.evaluate("() => PLOTSRV.core.loadTable()")
    assert page.locator("#simple-table-root .ps-table-empty").inner_text() == "No data"

    page.evaluate("() => { tableRows = [{value: 1}]; }")
    assert page.evaluate("() => PLOTSRV.core.loadTable()")
    assert page.locator("#simple-table-root table tbody tr").count() == 1
    assert page.locator("#simple-table-root .ps-table-empty").count() == 0
