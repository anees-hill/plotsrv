from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def _read(relative_path: str) -> str:
    return (STATIC / relative_path).read_text(encoding="utf-8")


def test_modal_markup_is_labelled_scrollable_and_shared_by_all_status_states() -> None:
    html_source = (ROOT / "src" / "plotsrv" / "html.py").read_text(encoding="utf-8")
    css_source = _read("css/status.css")

    assert 'role="dialog"' in html_source
    assert 'aria-modal="true"' in html_source
    assert 'aria-labelledby="status-modal-title"' in html_source
    assert 'aria-describedby="status-modal-intro"' in html_source
    assert 'id="status-modal-update-now"' in html_source
    assert 'id="status-modal-return-latest"' in html_source
    assert 'id="status-modal-range"' in html_source
    assert "max-height: calc(100vh - 3rem)" in css_source
    assert ".ps-status-modal__body" in css_source
    assert "overflow: auto" in css_source


def test_modal_interaction_traps_focus_restores_focus_and_dismisses_with_escape() -> None:
    source = _read("js/core/status_modal.js")

    assert "state.statusModalReturnFocus = document.activeElement" in source
    assert "focusableElements(modal)" in source
    assert 'event.key !== "Tab"' in source
    assert 'event.key === "Escape"' in source
    assert "target.focus()" in source
    assert "event.target === backdrop" in source
    assert 'document.body.classList.add("ps-status-modal-open")' in source


def test_modal_keeps_snapshot_browser_and_freshness_axes_separate() -> None:
    source = _read("js/core/status_modal.js")

    assert 'setText("status-modal-viewing", "Snapshot")' in source
    assert 'setText("status-modal-viewing", "Latest data")' in source
    assert 'state.headerStatus.browserData === "update_available"' in source
    assert '"Newer update waiting"' in source
    assert 'core.applyPendingUpdate({ force: true })' in source
    assert '"Not evaluated for history"' in source
    assert 'freshness.enabled === false' in source
    assert '"Freshness monitoring is disabled for this view."' in source
    assert "freshness.expected_every_s" in source
    assert "freshness.warn_after_s" in source
    assert "freshness.overdue_after_s" in source


def test_timeline_is_client_rendered_bounded_and_has_basic_ranges() -> None:
    source = _read("js/core/status_modal.js")

    open_body = source.split("function openStatusModal()", 1)[1].split(
        "function closeStatusModal", 1
    )[0]
    assert "fetch(" not in open_body
    assert "validActivityEvents(payload)" in source
    assert "AUTO_RANGES" in source
    assert "status-modal-range" in source
    assert 'document.createElement("span")' in source
    assert 'dot.className = "ps-arrival-chart__dot"' in source
    assert "activity.limit || 256" in source
    assert "does not survive restart" in (
        ROOT / "src" / "plotsrv" / "html.py"
    ).read_text(encoding="utf-8")


def test_stream_timeline_combines_nearby_batches_into_accessible_ranges() -> None:
    source = _read("js/core/status_modal.js")
    css_source = _read("css/status.css")
    html_source = (ROOT / "src" / "plotsrv" / "html.py").read_text(
        encoding="utf-8"
    )

    assert "function streamRangeTolerance(events)" in source
    assert "STREAM_RANGE_MIN_TOLERANCE_MS = 10000" in source
    assert "STREAM_RANGE_MAX_TOLERANCE_MS = 120000" in source
    assert "Math.min(STREAM_RANGE_MAX_TOLERANCE_MS, median * 3)" in source
    assert "function streamActivityRanges(events)" in source
    assert "event.time - current.end > tolerance" in source
    assert 'segment.className = "ps-arrival-chart__range"' in source
    assert 'segment.addEventListener("mouseenter", showDetail)' in source
    assert 'segment.addEventListener("focus", showDetail)' in source
    assert 'segment.setAttribute("aria-label", label)' in source
    assert 'id="status-modal-activity-hover"' in html_source
    assert 'role="group"' in html_source
    assert ".ps-arrival-chart__range" in css_source
    assert '.ps-arrival-chart__range:focus-visible' in css_source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_stream_timeline_range_tolerance_groups_short_gaps() -> None:
    source = STATIC / "js" / "core" / "status_modal.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");

function element(id) {
  const listeners = {};
  return {
    id,
    hidden: false,
    value: id === "status-modal-range" ? "auto" : "",
    style: {},
    children: [],
    attributes: {},
    textContent: "",
    addEventListener(name, callback) { listeners[name] = callback; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
    closest(selector) { return id === "status-modal-activity-dots" ? chart : null; },
    querySelectorAll() { return []; },
    focus() {},
  };
}

const chart = element("activity-chart");
const elements = {};
const get = (id) => elements[id] || (elements[id] = element(id));
const now = Date.now();
const times = [now - 40000, now - 39000, now - 35000, now - 5000];
const state = {
  statusModalOpen: true,
  latestStatusPayload: {
    data_activity: {
      events: times.map((time) => ({received_at: new Date(time).toISOString(), count: 1})),
      event_count: 4,
      represented_item_count: 4,
    },
    stream_status: {lifecycle: "live", source_available: true},
  },
  currentSnapshot: null,
  streamHistoricalSessionId: null,
  headerStatus: {browserData: "current", latestData: {}},
  browserLastAppliedAt: null,
  streamPaused: false,
};
const document = {
  getElementById: get,
  createElement: (tag) => element(tag),
  activeElement: null,
  body: {classList: {add() {}, remove() {}}},
};
const context = {
  window: {
    PLOTSRV: {
      core: {
        fmtLocalTime: (value) => String(value),
        fmtAgo: (value) => String(value),
        formatAgeShort: (value) => String(value),
      },
      renderers: {}, state, config: {kind: "stream", activeViewId: "stream"},
    },
  },
  document,
};
vm.runInNewContext(source, context, {filename: "status_modal.js"});
context.window.PLOTSRV.core.renderStatusModal();
const ranges = get("status-modal-activity-dots").children;
if (ranges.length !== 2) throw new Error("expected one bridged range and one post-gap range");
if (ranges.some((range) => range.className !== "ps-arrival-chart__range")) {
  throw new Error("stream activity rendered a non-range marker");
}
if (!ranges[0].title.includes(new Date(times[0]).toISOString()) ||
    !ranges[0].title.includes(new Date(times[2]).toISOString())) {
  throw new Error("range hover detail does not contain its start and end");
}
'''
    subprocess.run(
        ["node", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_stream_modal_distinguishes_records_heartbeats_and_continuity() -> None:
    source = _read("js/core/status_modal.js")
    html_source = (ROOT / "src" / "plotsrv" / "html.py").read_text(encoding="utf-8")

    assert '"Nearby accepted record batches are combined into activity ranges;' in source
    assert 'brief quiet gaps are tolerated and heartbeats are excluded."' in source
    assert 'streamView ? "Stream status" : "Live data status"' in source
    assert 'streamView ? "Producer state" : "Freshness"' in source
    assert 'streamView ? "Records received over time" : "Data received over time"' in source
    assert "if (policy) policy.hidden = streamView" in source
    assert 'id="status-modal-policy"' in html_source
    assert "status-modal-stream-lifecycle" in source
    assert "stream.last_heartbeat_at" in source
    assert "stream.continuity_warning" in source
    assert '"No known continuity gap"' in source
    assert "not the application’s full state" in html_source


def test_hidden_modal_does_no_timeline_dom_work() -> None:
    source = _read("js/core/status_modal.js")
    render_start = source.split("function renderStatusModal()", 1)[1].split(
        "function focusableElements", 1
    )[0]

    assert "if (!modal || !state.statusModalOpen) return" in render_start


def test_complete_status_refresh_can_update_an_open_stream_modal_during_header_grace() -> None:
    status_source = _read("js/core/status.js")
    refresh = status_source.split("function refreshStatus()", 1)[1].split(
        "core.fmtLocalTime", 1
    )[0]

    assert 'typeof core.renderStatusModal === "function"' in refresh
    assert "core.renderStatusModal()" in refresh
