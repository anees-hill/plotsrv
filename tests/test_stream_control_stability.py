"""Browser regression: incoming rows must preserve editable toolbar nodes."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_row_arrivals_do_not_rebuild_toolbar_and_schema_updates_do() -> None:
    source = Path(__file__).parents[1] / "src/plotsrv/static/js/renderers/table.js"
    subprocess.run(["node", "-e", r'''
const fs = require("fs"), vm = require("vm");
let builds = 0;
const input = {dataset: {}, value: "", addEventListener() {}};
const filters = {dataset: {}, addEventListener() {}, contains(el) {return el === editor;}};
Object.defineProperty(filters, "innerHTML", {set() {builds++;}});
const editor = {};
const state = {tableUiState: {searchQuery: "", filters: [], hiddenColumns: []}};
const document = {activeElement: null, getElementById(id) {
  return id === "table-search-input" ? input : id === "table-filter-rows" ? filters : null;
}};
const context = {document, localStorage: {getItem() {}, setItem() {}},
  window: {PLOTSRV: {core: {}, state, config: {}, renderers: {}}}};
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context);
const table = {on() {}, clearFilter() {}, setFilter() {}};
const configure = (fields) => context.window.PLOTSRV.core.configureTableExplorer({
  table, fields, rows: [{value: 1}], payload: {rows: [{value: 1}]}
});
configure(["value"]);
const initial = builds;
if (!initial) throw Error("Toolbar was never initialized");
input.value = "uncommitted draft";
for (let i = 0; i < 10; i++) configure(["value"]);
if (builds !== initial || input.value !== "uncommitted draft") throw Error("Row arrival reset controls");
document.activeElement = editor;
configure(["value", "new_field"]);
if (builds !== initial) throw Error("Schema update replaced focused filter");
document.activeElement = null;
configure(["value", "new_field"]);
if (builds !== initial + 1) throw Error("Deferred schema was not applied");
''', str(source)], check=True, capture_output=True, text=True)
