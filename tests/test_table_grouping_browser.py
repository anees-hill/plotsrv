"""Regression: persisted grouping must wait for Tabulator's asynchronous build."""
import pytest

from tests.test_plot_controls_browser import page


def test_group_headers_treat_untrusted_values_as_text(page):
    page.click("#table-mode-table-btn")
    payload = '<img src=x onerror="window.groupingXss=true">'
    page.evaluate("""value => {
      window.groupingXss = false;
      return PLOTSRV.state.tabulatorInstance.replaceData([
        {pot:value,timestamp:1,value:2}, {pot:'safe',timestamp:2,value:3}
      ]);
    }""", payload)
    page.select_option("#table-group-by-select", "pot")
    assert page.locator(".tabulator-group img").count() == 0
    assert payload in page.locator(".tabulator-group").first.inner_text()
    assert not page.evaluate("window.groupingXss")
    # Incoming stream-style mutations must use the same safe formatter.
    page.evaluate("""value => PLOTSRV.state.tabulatorInstance.addData([
      {pot:value+' again',timestamp:3,value:4}
    ])""", payload)
    assert page.locator(".tabulator-group img").count() == 0
    assert not page.evaluate("window.groupingXss")


@pytest.mark.parametrize("kind", ["ordinary", "embedded", "stream"])
def test_restored_grouping_and_reset_keep_rows_visible(page, kind):
    warnings = []
    page.on("console", lambda message: warnings.append(message.text) if message.type == "warning" else None)
    page.click("#table-mode-table-btn")
    page.route("**/table/data?**", lambda route: route.fulfill(json={
        "columns": ["pot", "timestamp", "value"],
        "rows": [{"pot": "A", "timestamp": 1, "value": 2}, {"pot": "B", "timestamp": 2, "value": 3}],
    }))
    # Repeat mounting with the same grouping to catch caches leaking between instances.
    for _ in range(2):
        page.evaluate("""async kind => {
          if (PLOTSRV.state.tabulatorInstance) PLOTSRV.state.tabulatorInstance.destroy();
          PLOTSRV.state.tabulatorInstance = null;
          PLOTSRV.state.tableUiState = null;
          localStorage.setItem('plotsrv:v4:table_state:test:layout', JSON.stringify({groupBy:'pot'}));
          if (kind === 'ordinary') await PLOTSRV.core.loadTable();
          else if (kind === 'embedded') PLOTSRV.core.initializeEmbeddedTableExplorer({grid:document.querySelector('#table-grid'), data:fixtureData});
          else {
            const table = new Tabulator('#table-grid', {data:fixtureData.rows,
              columns:fixtureData.columns.map(field => ({field, title:field})), height:'72vh', nestedFieldSeparator:false});
            PLOTSRV.core.configureTableExplorer({table, rows:fixtureData.rows, fields:fixtureData.columns,
              payload:fixtureData, plotCapabilities:{sources:['table'],liveUpdates:true}});
          }
        }""", kind)
        page.wait_for_function("document.querySelectorAll('#table-grid .tabulator-group').length === 2")
        assert page.locator("#table-group-by-select").input_value() == "pot"
        assert page.locator("#table-grid .tabulator-row:not(.tabulator-group)").count() == 2
    # Reset is a UI operation, not a replacement from a possibly stale row snapshot.
    page.evaluate("""() => {
      window.replacements = 0;
      const table = PLOTSRV.state.tabulatorInstance;
      const replace = table.replaceData.bind(table);
      table.replaceData = (...args) => { replacements++; return replace(...args); };
    }""")
    for _ in range(2):
        page.click("#table-reset-btn")
        assert page.locator("#table-group-by-select").input_value() == ""
        assert page.locator("#table-grid .tabulator-row:not(.tabulator-group)").count() == 2
        page.select_option("#table-group-by-select", "pot")
        assert page.locator("#table-grid .tabulator-group").count() == 2
    assert page.evaluate("replacements") == 0
    page.evaluate("PLOTSRV.state.tabulatorInstance.addData([{pot:'C',timestamp:3,value:4}])")
    page.click("#table-reset-btn")
    assert page.locator("#table-grid .tabulator-row:not(.tabulator-group)").count() == 3
    assert page.evaluate("replacements") == 0
    assert not [warning for warning in warnings if "Table Not Initialized" in warning]
