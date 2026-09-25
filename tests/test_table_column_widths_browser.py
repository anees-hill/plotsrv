"""The shared Columns action restores Tabulator's initial width layout."""

import pytest

from tests.test_plot_controls_browser import page
from tests.test_stream_schema_browser import mount_stream


@pytest.mark.parametrize("kind", ["table", "stream"])
def test_reset_column_widths_preserves_table_state(page, kind):
    page.click("#table-mode-table-btn")
    if kind == "stream":
        mount_stream(page)
        page.click("#table-columns-toggle-btn")
        page.click("#table-columns-show-all-btn")
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.initialized")
    before = page.evaluate("""() => {
      const table = PLOTSRV.state.tabulatorInstance;
      const columns = table.getColumns();
      const first = columns[0];
      table.setSort(first.getField(), 'desc');
      table.setFilter(first.getField(), '!=', 'missing-value');
      table.hideColumn(columns[1].getField());
      const result = {
        widths: columns.map(column => column.getWidth()),
        data: JSON.stringify(table.getData()),
        sorters: table.getSorters().map(sorter => [sorter.field, sorter.dir]),
        filters: JSON.stringify(table.getFilters()),
        fields: columns.map(column => column.getField()),
        visible: columns.map(column => column.isVisible()),
      };
      first.setWidth(3000);
      return {...result, stretched: first.getWidth()};
    }""")
    assert before["stretched"] == 3000

    if page.locator("#table-columns-panel").is_hidden():
        page.click("#table-columns-toggle-btn")
    page.click("#table-columns-reset-widths-btn")
    after = page.evaluate("""() => {
      const table = PLOTSRV.state.tabulatorInstance;
      return {
        widths: table.getColumns().map(column => column.getWidth()),
        data: JSON.stringify(table.getData()),
        sorters: table.getSorters().map(sorter => [sorter.field, sorter.dir]),
        filters: JSON.stringify(table.getFilters()),
        fields: table.getColumns().map(column => column.getField()),
        visible: table.getColumns().map(column => column.isVisible()),
      };
    }""")
    assert after["widths"][0] < 500
    assert after["widths"][0] < before["stretched"] / 3
    assert after["widths"][-1] > 500
    if kind == "table":
        assert abs(after["widths"][0] - before["widths"][0]) < 20
    assert after["fields"] == before["fields"]
    assert after["visible"] == before["visible"]
    assert after["data"] == before["data"]
    assert after["sorters"] == before["sorters"]
    assert after["filters"] == before["filters"]
