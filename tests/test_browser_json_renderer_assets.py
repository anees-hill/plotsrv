from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from plotsrv.renderers.json_tree import JsonTreeRenderer


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def test_json_mode_selector_is_anchored_without_a_fixed_position() -> None:
    css = (STATIC / "css" / "renderers" / "json.css").read_text("utf-8")

    view_group = css.split(
        '.ps-json-toolbar-group[data-json-toolbar-group="view"] {', 1
    )[1].split("}", 1)[0]
    assert "margin-left: auto" in view_group
    assert "flex: 0 0 auto" in view_group
    assert "position:" not in view_group

    responsive = css.split("@media (max-width: 900px)", 1)[1]
    responsive_view_group = responsive.split(
        '.ps-json-toolbar-group[data-json-toolbar-group="view"] {', 1
    )[1].split("}", 1)[0]
    assert "margin-left: 0" in responsive_view_group


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_json_levels_are_one_indexed_and_collapse_is_deterministic() -> None:
    source = STATIC / "js" / "renderers" / "json.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const details = [0, 1, 2, 3].map((depth) => ({
  open: true,
  getAttribute: (name) => name === "data-json-depth" ? String(depth) : "",
}));
let changeLevel = null;
let toolbarClick = null;
let prefs = {mode: "json", level_limit: "2", find_query: "", pinned_values: []};

const classNames = new Set(["is-active"]);
const modeButton = {
  classList: {
    toggle(name, enabled) { enabled ? classNames.add(name) : classNames.delete(name); },
  },
  getAttribute(name) { return name === "data-json-mode" ? "json" : ""; },
  setAttribute() {},
};
const select = {
  value: "2",
  addEventListener(type, listener) {
    if (type === "change") changeLevel = listener;
  },
};
const toolbar = {
  bound: "",
  getAttribute(name) { return name === "data-plotsrv-bound" ? this.bound : ""; },
  setAttribute(name, value) { if (name === "data-plotsrv-bound") this.bound = value; },
  addEventListener(type, listener) { if (type === "click") toolbarClick = listener; },
};
const jsonRoot = {
  querySelector(selector) {
    if (selector === "[data-json-text-view='1']") return null;
    if (selector === "[data-json-table-data='1']") return null;
    if (selector === "[data-json-table-grid='1']") return null;
    return null;
  },
  querySelectorAll(selector) {
    if (selector.includes("details[data-json-depth]")) return details;
    if (selector === "[data-json-panel]") return [];
    if (selector === "[data-json-pin-toggle]") return [];
    return [];
  },
  addEventListener() {},
};
const root = {
  querySelector(selector) {
    if (selector === '[data-plotsrv-toolbar="json"]') return toolbar;
    if (selector === '[data-plotsrv-json="1"]') return jsonRoot;
    if (selector === "[data-json-mode].is-active") return modeButton;
    if (selector === "[data-json-level-limit='1']") return select;
    return null;
  },
  querySelectorAll(selector) {
    return selector === "[data-json-mode]" ? [modeButton] : [];
  },
};
const context = {
  window: {
    PLOTSRV: {
      core: {
        loadJsonPrefs: () => ({...prefs}),
        saveJsonPrefs: (_view, next) => { prefs = {...next}; },
      },
      renderers: {},
      state: {},
      config: {activeViewId: "json:depth"},
    },
  },
};

vm.runInNewContext(source, context, {filename: "json.js"});
context.window.PLOTSRV.renderers.initJsonToolbar(root);

function assertOpen(expected, label) {
  const actual = details.map((node) => node.open);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(label + ": " + JSON.stringify(actual));
  }
}

assertOpen([true, false, false, false], "Level 2 did not show root and children");
select.value = "1";
changeLevel();
assertOpen([false, false, false, false], "Level 1 did not show root only");
select.value = "3";
changeLevel();
assertOpen([true, true, false, false], "Level 3 did not add one nested layer");
select.value = "all";
changeLevel();
assertOpen([true, true, true, true], "All did not expand every container");

const collapseButton = {
  closest: () => collapseButton,
  getAttribute(name) {
    return name === "data-plotsrv-action" ? "collapse-all" : "";
  },
};
toolbarClick({target: collapseButton});
assertOpen([false, false, false, false], "Collapse all left descendants visible");
if (select.value !== "1" || prefs.level_limit !== "1") {
  throw new Error("Collapse all did not align the saved selector level");
}
'''

    subprocess.run(
        ["node", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"servers": {"web": {"status": "ok"}}, "clusters": {"primary": {"nodes": 3}}},
        [{"servers": ["web"]}],
        {},
        [],
    ],
)
def test_json_roots_use_zero_based_model_depth(payload: object) -> None:
    rendered = JsonTreeRenderer().render(payload, view_id="json:depth")

    assert 'data-json-depth="0"' in rendered.html
    if payload:
        assert 'data-json-depth="1"' in rendered.html

