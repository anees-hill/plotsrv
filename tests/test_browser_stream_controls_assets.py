from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

import plotsrv.html as html_mod


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def _render(kind: html_mod.ViewKind) -> str:
    return html_mod.render_index(
        kind=kind,
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        views=[],
        active_view_id=f"demo:{kind}",
    )


def test_stream_controls_precede_shared_table_controls_and_grouping() -> None:
    rendered = _render("stream")
    stream_controls = rendered.index('class="ps-stream-controls"')
    table_controls = rendered.index('class="ps-table-topbar"')

    assert stream_controls < table_controls
    assert rendered.count('id="table-group-by-select"') == 1
    stream_panel = rendered[stream_controls:table_controls]
    assert 'id="table-group-by-select"' not in stream_panel
    assert rendered.index('id="table-search-input"') < rendered.index(
        'id="table-group-by-select"'
    ) < rendered.index('id="table-mode-table-btn"')
    assert '>Run</span>' in rendered
    assert 'id="stream-history-session-select"' in rendered
    assert 'id="stream-history-info"' not in rendered
    assert '>Current run</option>' in rendered
    assert 'id="stream-insights-button"' in rendered
    assert 'id="stream-pause-button"' in rendered
    assert 'id="stream-pause-label">Pause stream</span>' in rendered
    assert 'class="ps-stream-controls__actions"' in rendered
    assert 'id="stream-controls-content"' in rendered
    assert 'id="stream-controls-toggle"' in rendered
    assert 'aria-label="Collapse Stream controls"' in rendered
    assert rendered.index('id="stream-pause-button"') < rendered.index(
        'id="stream-insights-button"'
    )
    assert 'id="stream-lifecycle-badge"' not in rendered


def test_stream_controls_and_insights_do_not_leak_into_ordinary_tables() -> None:
    rendered = _render("table")

    assert 'class="ps-stream-controls"' not in rendered
    assert 'id="stream-insights-button"' not in rendered
    assert 'id="stream-pause-button"' not in rendered
    assert 'id="stream-insights-drawer"' not in rendered
    assert rendered.count('id="table-group-by-select"') == 1
    assert 'class="ps-table-toolbar__grouping"' in rendered


def test_insight_sections_are_tabs_in_a_closed_non_modal_companion_drawer() -> None:
    rendered = _render("stream")
    drawer_start = rendered.rfind("<aside", 0, rendered.index('id="stream-insights-drawer"'))
    drawer_tag_end = rendered.index(">", drawer_start)
    drawer_tag = rendered[drawer_start:drawer_tag_end]
    drawer = rendered[drawer_start:]

    assert " hidden" in drawer_tag
    assert 'role="dialog"' in drawer
    assert 'aria-modal="false"' in drawer
    assert 'aria-labelledby="stream-insights-title"' in drawer
    assert 'id="stream-insights-close"' in drawer
    assert 'role="tablist" aria-label="Stream insight sections"' in drawer
    assert drawer.count('role="tab"') == 3
    assert drawer.count('role="tabpanel"') == 3
    assert 'data-stream-insights-panel="since"' in drawer
    assert 'data-stream-insights-panel="noteworthy"' in drawer
    assert 'data-stream-insights-panel="history"' in drawer

    # The established renderer targets retain their identities after moving.
    for element_id in (
        "stream-status-inline",
        "stream-health-inline",
        "stream-since-visit-status",
        "stream-since-visit-details",
        "stream-noteworthy-status",
        "stream-noteworthy-items",
        "stream-summary-status",
        "stream-summary-windows",
    ):
        assert rendered.count(f'id="{element_id}"') == 1

    assert rendered.index('id="stream-pause-button"') < rendered.index(
        'class="ps-table-topbar"'
    )
    assert drawer.index('id="stream-status-inline"') < drawer.index(
        'role="tablist"'
    )


def test_run_control_has_truthful_disabled_empty_and_stored_states() -> None:
    source = (STATIC / "js" / "renderers" / "stream.js").read_text(
        encoding="utf-8"
    )

    assert 'current.textContent = "Current run"' in source
    assert 'picker.dataset.state = enabled ?' in source
    assert 'select.disabled = !enabled' in source
    assert 'document.getElementById("stream-history-info")' not in source
    assert "plotsrv disk storage is disabled in configuration" in source
    assert "No past runs have been saved yet." in source
    assert 'return "Past run — " + updated + incomplete' in source
    assert 'select.disabled = true' in source
    assert 'select.disabled = false' in source


def test_compact_only_stored_run_has_a_truthful_raw_table_notice() -> None:
    rendered = _render("stream")
    source = (STATIC / "js" / "renderers" / "stream.js").read_text(
        encoding="utf-8"
    )

    assert 'id="stream-raw-history-notice"' in rendered
    assert "No original log rows are available for this stored run." in source
    assert "compact summaries and noteworthy history remain available" in source


def test_drawer_css_is_substantial_without_a_blocking_backdrop_and_mobile_safe() -> None:
    source = (STATIC / "css" / "renderers" / "stream.css").read_text(
        encoding="utf-8"
    )
    drawer = source.split(".ps-stream-insights {", 1)[1].split("}", 1)[0]

    assert "position: fixed" in drawer
    assert "right: 0" in drawer
    assert "width: min(52vw, 780px)" in drawer
    assert "height: 100dvh" in drawer
    assert "overflow: auto" in source
    assert ".ps-stream-insights-backdrop" not in source
    mobile = source.split("@media (max-width: 640px)", 1)[1]
    assert "width: 100vw" in mobile


def test_stream_and_table_controls_form_one_attached_stack() -> None:
    source = (STATIC / "css" / "renderers" / "stream.css").read_text(
        encoding="utf-8"
    )
    controls = source.split(".ps-stream-controls {", 1)[1].split("}", 1)[0]
    attached = source.split(
        ".ps-stream-controls + .ps-table-topbar {", 1
    )[1].split("}", 1)[0]

    assert "margin-bottom: -0.5rem" in controls
    assert "border-radius: 8px 8px 0 0" in controls
    assert "border-top: 0" in attached
    assert "border-radius: 0 0 8px 8px" in attached


def test_pause_and_insights_form_a_compact_horizontal_action_pair() -> None:
    source = (STATIC / "css" / "renderers" / "stream.css").read_text(
        encoding="utf-8"
    )
    actions = source.split(".ps-stream-controls__actions {", 1)[1].split(
        "}", 1
    )[0]
    buttons = source.split(".ps-stream-controls__actions .ps-btn {", 1)[1].split(
        "}", 1
    )[0]

    assert "grid-area: actions" in actions
    assert "display: flex" in actions
    assert "height: 32px" in buttons
    assert "min-height: 32px" in buttons
    assert source.index(".ps-stream-pause-button") < source.index(
        ".ps-stream-insights-button"
    )
    assert ".ps-stream-badge" not in source


def test_stream_controls_use_a_remembered_accessible_disclosure() -> None:
    source = (STATIC / "js" / "renderers" / "stream.js").read_text(
        encoding="utf-8"
    )
    app = (STATIC / "js" / "core" / "app.js").read_text(encoding="utf-8")

    assert 'document.getElementById("stream-controls-toggle")' in source
    assert 'document.getElementById("stream-controls-content")' in source
    assert 'toggle.textContent = collapsed ? "+" : "−"' in source
    assert 'toggle.setAttribute("aria-expanded"' in source
    assert 'localStorage.setItem(' in source
    assert "core.bindStreamControlsDisclosure = bindStreamControlsDisclosure" in source
    assert "core.bindStreamControlsDisclosure()" in app


def test_stream_disclosure_floats_above_the_right_aligned_actions() -> None:
    source = (STATIC / "css" / "renderers" / "stream.css").read_text(
        encoding="utf-8"
    )
    disclosure = source.split(
        ".ps-stream-controls > .ps-pane-disclosure {", 1
    )[1].split("}", 1)[0]
    content = source.split(".ps-stream-controls__content {", 1)[1].split(
        "}", 1
    )[0]

    assert "position: absolute" in disclosure
    assert "right:" in disclosure
    assert 'grid-template-areas: "session . actions"' in content
    assert "minmax(260px, 360px)" in content


def test_control_panes_share_a_neutral_theme_safe_grey_surface() -> None:
    themes = (STATIC / "css" / "themes.css").read_text(encoding="utf-8")
    shared = themes.split(".ps-stream-controls,", 1)[1].split("}", 1)[0]

    assert ".ps-table-plot-controls" in shared
    assert "border-color: var(--ps-border)" in shared
    assert "background: var(--ps-surface-soft)" in shared


def test_drawer_source_restores_focus_and_supports_keyboard_tabs() -> None:
    source = (STATIC / "js" / "renderers" / "stream.js").read_text(
        encoding="utf-8"
    )

    assert "state.streamInsightsReturnFocus = document.activeElement" in source
    assert 'trigger.setAttribute("aria-expanded", "true")' in source
    assert 'trigger.setAttribute("aria-expanded", "false")' in source
    assert 'event.key === "ArrowRight"' in source
    assert 'event.key === "ArrowLeft"' in source
    assert 'event.key === "Home"' in source
    assert 'event.key === "End"' in source
    assert 'event.key !== "Escape"' in source
    assert "core.bindStreamInsights = bindStreamInsights" in source
    assert "core.bindStreamInsights()" in (
        STATIC / "js" / "core" / "app.js"
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_drawer_open_close_and_tab_selection_behaviour() -> None:
    source = STATIC / "js" / "renderers" / "stream.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");

function element(attributes = {}) {
  const listeners = {};
  return {
    hidden: false,
    dataset: {},
    tabIndex: 0,
    attributes: Object.assign({}, attributes),
    addEventListener(name, callback) { listeners[name] = callback; },
    dispatch(name, event = {}) { listeners[name](Object.assign({preventDefault() {}}, event)); },
    getAttribute(name) { return this.attributes[name] || null; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    focus() { document.activeElement = this; },
  };
}

const trigger = element({"aria-expanded": "false"});
const close = element();
const tabs = ["since", "noteworthy", "history"].map((name) =>
  element({"data-stream-insights-tab": name})
);
const panels = ["since", "noteworthy", "history"].map((name) =>
  element({"data-stream-insights-panel": name})
);
const drawer = element();
drawer.hidden = true;
drawer.querySelectorAll = (selector) => selector.includes("tab]") ? tabs : [];

const elements = {
  "stream-insights-button": trigger,
  "stream-insights-close": close,
  "stream-insights-drawer": drawer,
};
const document = {
  activeElement: trigger,
  getElementById: (id) => elements[id] || null,
  querySelectorAll: (selector) => selector.includes("tab]") ? tabs : panels,
};
const context = {
  window: {PLOTSRV: {core: {}, renderers: {}, state: {}, config: {}}},
  document,
};

vm.runInNewContext(source, context, {filename: "stream.js"});
const core = context.window.PLOTSRV.core;
core.bindStreamInsights();
trigger.dispatch("click");
if (drawer.hidden || trigger.attributes["aria-expanded"] !== "true") {
  throw new Error("Insights did not open");
}
if (document.activeElement !== close) throw new Error("focus did not enter drawer");

tabs[1].dispatch("click");
if (!panels[0].hidden || panels[1].hidden || !panels[2].hidden) {
  throw new Error("Noteworthy tab did not select its panel exclusively");
}
tabs[1].dispatch("keydown", {key: "ArrowRight"});
if (document.activeElement !== tabs[2] || panels[2].hidden) {
  throw new Error("arrow navigation did not select and focus History");
}

drawer.dispatch("keydown", {key: "Escape"});
if (!drawer.hidden || trigger.attributes["aria-expanded"] !== "false") {
  throw new Error("Insights did not close");
}
if (document.activeElement !== trigger) throw new Error("focus was not restored");
'''
    subprocess.run(
        ["node", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
