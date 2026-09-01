from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def test_text_styling_popover_and_tokens_use_theme_palette() -> None:
    css = (STATIC / "css" / "renderers" / "text.css").read_text("utf-8")
    renderer = (STATIC / "js" / "renderers" / "text.js").read_text("utf-8")

    assert ".ps-text-style-menu" in css
    assert "var(--ps-surface-raised)" in css
    assert "var(--ps-danger-text)" in css
    assert "var(--ps-history-text)" in css
    assert "var(--ps-token-string)" in css
    assert "MAX_CLASSIFY_CHARS = 16000" in renderer
    assert "MAX_CLASSIFY_LINES = 80" in renderer
    assert "MAX_COLOURIZE_CHARS = 300000" in renderer


def test_text_and_markdown_scroll_navigation_clears_the_bottom_dock() -> None:
    controls = (STATIC / "css" / "controls.css").read_text("utf-8")
    artifact = (STATIC / "js" / "renderers" / "artifact.js").read_text("utf-8")
    enhancements = (STATIC / "js" / "renderers" / "json.js").read_text("utf-8")

    scroll_nav = controls.split(".ps-scroll-nav {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in scroll_nav
    assert "--ps-bottom-dock-clearance" in scroll_nav
    assert "data-plotsrv-scroll-edge=\"top\"" in artifact
    assert "data-plotsrv-scroll-edge=\"bottom\"" in artifact
    assert ".plotsrv-markdown--sanitized" in artifact
    assert "core.initArtifactScrollNav(root)" in enhancements
    assert "ps-text-jump-bottom" not in controls

    dock_logic = (STATIC / "js" / "core" / "bottom_bar.js").read_text("utf-8")
    assert 'setProperty("--ps-bottom-dock-clearance"' in dock_logic


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_text_classifier_and_highlighter_cover_representative_formats() -> None:
    source = STATIC / "js" / "renderers" / "text.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const escapeHtml = (value) => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");
const context = {
  window: {PLOTSRV: {core: {escapeHtml}, renderers: {}, state: {}, config: {}}},
};
vm.runInNewContext(source, context, {filename: "text.js"});
const api = context.window.PLOTSRV.renderers;

const cases = [
  ["http", '127.0.0.1 - - [04/Sep/2026] "GET /health HTTP/1.1" 200 12'],
  ["application", "INFO service started\nWARNING queue filling\nERROR request failed"],
  ["traceback", 'Traceback (most recent call last):\n  File "worker.py", line 12, in run\nValueError: bad value'],
  ["syslog", "Sep  4 12:13:14 api-01 sshd[812]: Accepted publickey"],
  ["container", "2026-09-04T12:13:14.123Z stdout F worker ready"],
  ["test", "tests/test_api.py::test_health PASSED\ntests/test_api.py::test_error FAILED"],
  ["keyvalue", "host=localhost port=8998\ndebug: true\nworkers=2"],
  ["plain", "A short paragraph about a quiet afternoon.\nNothing here resembles structured output."],
];
for (const [expected, sample] of cases) {
  const actual = api.classifyTextStyle(sample);
  if (actual !== expected) throw new Error(`${expected} classified as ${actual}`);
}

const ambiguous = "This information is useful.\nWarnings in prose are not necessarily logs.";
if (api.classifyTextStyle(ambiguous) !== "plain") throw new Error("ambiguous prose was over-classified");
const beyondBound = "x".repeat(16001) + '\nGET /secret HTTP/1.1 500';
if (api.classifyTextStyle(beyondBound) !== "plain") throw new Error("classification exceeded its sample bound");

const http = api.highlightText('GET /items?q=<script> 503', "http");
if (!http.includes("ps-log-token--method")) throw new Error("HTTP method was not highlighted");
if (!http.includes("ps-log-token--error")) throw new Error("HTTP 5xx was not highlighted");
if (http.includes("<script>")) throw new Error("highlighting did not escape source text");
const traceback = api.highlightText('File "worker.py", line 12\nValueError: bad', "traceback");
if (!traceback.includes("ps-log-token--file") || !traceback.includes("ps-log-token--error")) {
  throw new Error("traceback cues were not highlighted");
}
const plain = api.highlightText("<b>unchanged</b>", "plain");
if (plain !== "&lt;b&gt;unchanged&lt;/b&gt;") throw new Error("plain text was modified or not escaped");
'''
    subprocess.run(["node", "-e", script, str(source)], check=True, cwd=ROOT)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_text_style_preferences_are_isolated_and_migrate_old_toggle() -> None:
    source = STATIC / "js" / "core" / "storage.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const values = new Map();
const localStorage = {
  getItem: (key) => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
};
const context = {
  localStorage,
  window: {PLOTSRV: {core: {}, renderers: {}, state: {}, config: {}}},
};
vm.runInNewContext(source, context, {filename: "storage.js"});
const core = context.window.PLOTSRV.core;

core.saveTextPrefs("view-a", {wrap_enabled: true, reverse_enabled: false, style_preset: "http"});
core.saveTextPrefs("view-b", {wrap_enabled: false, reverse_enabled: true, style_preset: "plain"});
const a = core.loadTextPrefs("view-a");
const b = core.loadTextPrefs("view-b");
if (a.style_preset !== "http" || !a.wrap_enabled) throw new Error("view A preference was not retained");
if (b.style_preset !== "plain" || !b.reverse_enabled) throw new Error("view B preference was not retained");
if (core.loadTextPrefs("view-new").style_preset !== "auto") throw new Error("new views did not default to Auto");

values.set(core.getTextPrefsKey("legacy-off"), JSON.stringify({colour_enabled: false}));
values.set(core.getTextPrefsKey("legacy-on"), JSON.stringify({colour_enabled: true}));
if (core.loadTextPrefs("legacy-off").style_preset !== "plain") throw new Error("old off toggle did not migrate");
if (core.loadTextPrefs("legacy-on").style_preset !== "auto") throw new Error("old on toggle did not migrate");

core.saveTextPrefs("view-a", {...a, style_preset: "auto"});
if (core.loadTextPrefs("view-a").style_preset !== "auto") throw new Error("explicit Auto was not persisted");
if (core.loadTextPrefs("view-b").style_preset !== "plain") throw new Error("saving view A altered view B");
'''
    subprocess.run(["node", "-e", script, str(source)], check=True, cwd=ROOT)
