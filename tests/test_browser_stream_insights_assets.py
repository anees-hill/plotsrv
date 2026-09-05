from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def _read(relative_path: str) -> str:
    return (STATIC / relative_path).read_text(encoding="utf-8")


def test_since_last_visit_is_default_plain_language_and_keeps_exactness_details() -> None:
    html = (ROOT / "src" / "plotsrv" / "html.py").read_text(encoding="utf-8")
    stream = _read("js/renderers/stream.js")
    state = _read("js/core/state.js")

    assert 'id="stream-insights-tab-since"' in html
    assert 'aria-selected="true"' in html.split(
        'id="stream-insights-tab-since"', 1
    )[1].split("</button>", 1)[0]
    assert 'state.streamInsightsTab = "since"' in state
    assert '"No new records observed"' in stream
    assert '"new record", "new records"' in stream
    assert '"Some activity may be missing"' in stream
    assert '"A new stream session is active"' in stream
    assert '"Comparison starts with this visit"' in stream
    assert '"Since last visit does not apply"' in stream
    assert "an unavailable comparison is not the same as no change" in stream
    assert 'summary.textContent = "Technical details"' in stream
    assert '["Checkpoint stream instance"' in stream
    assert '["Counter schema"' in stream

    # The presentation slice must not alter the fixed browser-local baseline.
    assert 'STREAM_CHECKPOINT_SCHEMA_VERSION = 3' in state
    assert 'STREAM_CHECKPOINT_STORAGE_PREFIX = "plotsrv:v1:stream_checkpoint:"' in state
    assert "state.streamVisitCheckpoint" in state
    assert "state.streamVisitCheckpoint = compareCheckpoint" not in state


def test_noteworthy_uses_deterministic_human_names_and_safe_disclosures() -> None:
    stream = _read("js/renderers/stream.js")

    for title in (
        'severity + " · source"',
        'title: "New " + field + " appeared"',
        "A new low value was observed",
        "A new high value was observed",
        "Continuity may have been interrupted",
        "Data structure changed",
        "Some source records were skipped",
    ):
        assert title in stream

    assert 'reason === "structured_severity"' in stream
    assert 'reason === "first_low_cardinality_value"' in stream
    assert 'reason === "numeric_minimum"' in stream
    assert 'reason === "numeric_maximum"' in stream
    assert 'event === "stream_schema_changed"' in stream
    assert "recognizedStructuredSeverity(item.data) !== item.severity" in stream
    assert 'raw.textContent = stableJson(rawValue)' in stream
    assert 'article.dataset.noteworthyKind = "unknown"' in stream
    assert '"Earlier items have aged out"' in stream
    assert '"Noteworthy activity could not be loaded."' in stream
    assert 'details.className = "ps-stream-technical"' in stream
    assert ".innerHTML" not in stream


def test_history_is_plain_language_while_raw_aggregate_shape_stays_available() -> None:
    html = (ROOT / "src" / "plotsrv" / "html.py").read_text(encoding="utf-8")
    stream = _read("js/renderers/stream.js")

    assert '>History</h3>' in html
    assert "Older observations may be summarised" in html
    assert "not original rows" in html
    assert "do not use the table’s filters" in html
    assert '"No older history yet"' in stream
    assert '"Older history is available"' in stream
    assert '"History for this stored session"' in stream
    assert '"Older records represented"' in stream
    assert '"1-minute summaries"' not in stream  # Derived from payload resolution.
    assert 'return minutes + "-minute summaries"' in stream
    assert '"Oldest available period"' in stream
    assert '"Earlier activity"' in stream
    assert '"Recent older activity"' in stream
    assert '["Internal tier", summaryTierLabel(window)]' in stream
    assert '["First browser sequence", window.first_browser_sequence]' in stream
    assert '["Untracked field observations"' in stream
    assert "appendTechnicalDetails(article" in stream
    assert "], window);" in stream


def test_history_storage_and_continuity_caveats_are_truthful_but_proportionate() -> None:
    stream = _read("js/renderers/stream.js")

    assert 'durable.state === "incomplete"' in stream
    assert "Some persisted history for this stored session is incomplete." in stream
    assert "Live observation continues, but some history could not be saved." in stream
    assert "Some field-level detail was omitted to keep this history bounded." in stream
    assert '["Persistent history state", durable && durable.state]' in stream

    render_summary = stream.split("function renderSummary(payload, data)", 1)[1].split(
        "function showSummaryError", 1
    )[0]
    assert 'durable.state === "disabled"' not in render_summary


def test_shared_insight_cards_and_technical_disclosures_are_mobile_safe() -> None:
    css = _read("css/renderers/stream.css")

    assert ".ps-stream-insight-empty" in css
    assert ".ps-stream-summary__overview" in css
    assert ".ps-stream-technical > summary" in css
    assert ".ps-stream-technical__raw" in css
    mobile = css.split("@media (max-width: 640px)", 1)[1]
    assert ".ps-stream-summary__overview-facts div" in mobile
    assert ".ps-stream-technical__facts div" in mobile
    assert "grid-template-columns: 1fr" in mobile


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_stream_insight_renderers_cover_plain_language_states_and_safe_details() -> None:
    stream_source = STATIC / "js" / "renderers" / "stream.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");

function element() {
  return {
    textContent: "",
    className: "",
    dataset: {},
    children: [],
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
  };
}

const elements = {
  "stream-since-visit-status": element(),
  "stream-since-visit-details": element(),
  "stream-noteworthy-status": element(),
  "stream-noteworthy-items": element(),
  "stream-summary-status": element(),
  "stream-summary-windows": element(),
};
const context = {
  window: {
    PLOTSRV: {
      core: {fmtLocalTime: (value) => "local:" + value},
      renderers: {},
      state: {},
      config: {activeViewId: "logs:test"},
    },
  },
  document: {
    createElement: () => element(),
    getElementById: (id) => elements[id] || null,
  },
};
vm.runInNewContext(source, context, {filename: "stream.js"});
const core = context.window.PLOTSRV.core;

function deltas(total, noteworthy = "0") {
  return {
    total_records: total,
    recognized_severity_records: "0",
    recognized_severity_counts: {
      warning: "0", emergency: "0", alert: "0", critical: "0",
      fatal: "0", error: "0",
    },
    rejected_source_records: "0",
    continuity_events: "0",
    noteworthy_items: noteworthy,
    noteworthy_source_records: noteworthy,
    system_notices: "0",
    latest_server_sequence: total,
  };
}
const identity = {
  session_id: "session-a", stream_instance_id: "instance-a",
  counter_schema_version: 2,
};
const streamData = {
  cumulative: {
    first_observed_at: "2026-01-01T00:00:00Z",
    last_observed_at: "2026-01-01T00:01:00Z",
  },
};
core.renderStreamVisitComparison({
  status: "available", exact_deltas: true, deltas: deltas("3", "1"),
  continuity: {status: "no_known_gap"},
  checkpoint_identity: identity, current_identity: identity,
}, streamData);
if (elements["stream-since-visit-status"].textContent !== "3 new records") {
  throw new Error("exact visit delta did not get a plain-language primary summary");
}
let visitCard = elements["stream-since-visit-details"].children[0];
if (visitCard.dataset.comparisonStatus !== "available" ||
    !visitCard.children.some((child) => child.className === "ps-stream-technical")) {
  throw new Error("exact visit details were not retained behind disclosure");
}
core.renderStreamVisitComparison({
  status: "available", exact_deltas: true, deltas: deltas("0"),
  continuity: {status: "no_known_gap"},
  checkpoint_identity: identity, current_identity: identity,
}, streamData);
if (elements["stream-since-visit-status"].textContent !== "No new records observed") {
  throw new Error("exact zero was not distinguished from unavailable comparison");
}
core.renderStreamVisitComparison({
  status: "incomplete", exact_deltas: false, deltas: null,
  unavailable_reason: "continuity_uncertain",
  continuity: {status: "continuity_uncertain"},
  checkpoint_identity: identity, current_identity: identity,
}, streamData);
if (elements["stream-since-visit-status"].textContent !== "Some activity may be missing") {
  throw new Error("continuity uncertainty was not shown neutrally");
}
core.renderStreamVisitComparison({
  status: "unavailable", exact_deltas: false, deltas: null,
  unavailable_reason: "session_changed",
  checkpoint_identity: identity,
  current_identity: Object.assign({}, identity, {session_id: "session-b"}),
}, streamData);
if (elements["stream-since-visit-status"].textContent !== "A new stream session is active") {
  throw new Error("session change was not distinguished from exact zero");
}
core.renderHistoricalStreamVisitNotice({
  session_id: "stored-a", historical_updated_at: "2026-01-02T00:00:00Z",
  lifecycle: "ended",
});
if (elements["stream-since-visit-details"].children[0].dataset.comparisonStatus !== "historical") {
  throw new Error("stored session did not suppress live-visit comparison");
}

const unsafeField = "<img src=x onerror=alert(1)>";
const noteworthy = {
  object_type: "stream_noteworthy_collection",
  max_retained_items: 16,
  retained_item_count: 9,
  items: [
    {object_type: "stream_noteworthy_source_record", kind: "source_record",
      noteworthy_reason: "structured_severity", severity: "warning",
      observed_at: "2026-01-01T00:00:00Z", source_browser_sequence: "1",
      data: {severity: "warning"}},
    {object_type: "stream_noteworthy_source_record", kind: "source_record",
      noteworthy_reason: "first_low_cardinality_value", field_name: unsafeField,
      field_value: "new", observed_at: "2026-01-01T00:00:01Z",
      source_browser_sequence: "2", data: {[unsafeField]: "new"}},
    {object_type: "stream_noteworthy_source_record", kind: "source_record",
      noteworthy_reason: "numeric_minimum", field_name: "latency", field_value: 2,
      observed_at: "2026-01-01T00:00:02Z", source_browser_sequence: "3", data: {latency: 2}},
    {object_type: "stream_noteworthy_source_record", kind: "source_record",
      noteworthy_reason: "numeric_maximum", field_name: "latency", field_value: 9,
      observed_at: "2026-01-01T00:00:03Z", source_browser_sequence: "4", data: {latency: 9}},
    {object_type: "stream_system_notice", kind: "system_notice",
      event: "stream_schema_changed", observed_at: "2026-01-01T00:00:04Z", schema_revision: 2},
    {object_type: "stream_system_notice", kind: "system_notice",
      event: "source_continuity_uncertain", observed_at: "2026-01-01T00:00:05Z"},
    {object_type: "stream_system_notice", kind: "system_notice",
      event: "source_record_rejection_reported", observed_at: "2026-01-01T00:00:06Z",
      rejected_record_count: "2"},
    {object_type: "future_noteworthy_item", kind: "future_kind",
      observed_at: "2026-01-01T00:00:07Z", arbitrary: "<b>safe text</b>"},
    {object_type: "stream_noteworthy_source_record", kind: "source_record",
      noteworthy_reason: "structured_severity", severity: "error", data: {message: "error"}},
  ],
};
core.renderStreamNoteworthy(noteworthy, {noteworthy_items: "9"});
const cards = elements["stream-noteworthy-items"].children.filter(
  (child) => child.dataset && child.dataset.noteworthyKind
);
const titles = cards.map((card) => card.children.find(child => child.className === "ps-stream-noteworthy__item-title").textContent);
for (const title of [
  "Warning · source", "New " + unsafeField + " appeared",
  "A new low value was observed", "A new high value was observed",
  "Data structure changed", "Continuity may have been interrupted",
  "Some source records were skipped", "Noteworthy stream item",
]) {
  if (!titles.includes(title)) throw new Error("missing noteworthy title: " + title);
}
if (!cards.every((card) => card.children.some(
  (child) => child.className === "ps-stream-technical"
))) {
  throw new Error("noteworthy technical disclosures were missing");
}
core.renderStreamNoteworthy({
  object_type: "stream_noteworthy_collection", retained_item_count: 0, items: [],
}, {noteworthy_items: "5"});
if (elements["stream-noteworthy-status"].textContent !== "No recent noteworthy items") {
  throw new Error("aged-out noteworthy state was not distinguished from never observed");
}

function summaryWindow(tier, seconds, count, field) {
  return {
    object_type: "derived_stream_summary_window", derived: true, tier,
    observation_window: {from: "2026-01-01T00:00:00Z", until: "2026-01-01T01:00:00Z"},
    resolution: seconds === null ? {kind: "cumulative"} : {kind: "fixed_seconds", seconds},
    record_count: count, record_bytes: "100", first_browser_sequence: "1",
    last_browser_sequence: count, field_observation_count: count,
    truncation: {max_fields: 8, untracked_field_observations: tier === "coarse" ? "1" : "0"},
    fields: [{field, observed_count: count, numeric: {
      included_finite_count: count,
      mean: {numerator: "5", denominator: "2"},
      minimum: {numerator: "1", denominator: "1"},
      maximum: {numerator: "4", denominator: "1"},
    }}],
  };
}
const history = {
  object_type: "derived_stream_summary_collection", derived: true,
  session_id: "session-a", historical: false, summary_revision: 3,
  summary_window_count: 3,
  summary_retention: {max_fine_windows: 4, max_coarse_windows: 4, max_retained_windows: 9},
  windows: [
    summaryWindow("cumulative", null, "2", "load"),
    summaryWindow("coarse", 3600, "3", "load"),
    summaryWindow("fine", 60, "4", "load"),
  ],
};
core.renderStreamSummary(history, {historical: false, durable_history: {state: "disabled"}});
if (elements["stream-summary-status"].textContent !== "3 older summaries available") {
  throw new Error("current-session history status was not approachable");
}
const historyChildren = elements["stream-summary-windows"].children;
if (historyChildren[0].dataset.sessionMode !== "current" ||
    historyChildren[1].children[0].textContent !== "Oldest available period" ||
    historyChildren[2].children[0].textContent !== "Earlier activity" ||
    historyChildren[3].children[0].textContent !== "Recent older activity") {
  throw new Error("history tiers were not translated into plain-language cards");
}
if (!historyChildren.slice(1).every((card) => card.children.some(
  (child) => child.className === "ps-stream-technical"
))) {
  throw new Error("raw aggregate details were not disclosed per history window");
}
history.historical = true;
core.renderStreamSummary(history, {
  historical: true, durable_history: {state: "incomplete", last_error: "gap"},
});
if (elements["stream-summary-windows"].children[0].dataset.sessionMode !== "stored") {
  throw new Error("stored-session history was not identified");
}
core.renderStreamSummary(Object.assign({}, history, {windows: [], summary_window_count: 0}), {
  historical: false, durable_history: {state: "disabled"},
});
if (elements["stream-summary-status"].textContent !== "No older history yet") {
  throw new Error("storage-disabled empty compact history looked broken");
}
'''
    subprocess.run(
        ["node", "-e", script, str(stream_source)],
        check=True,
        capture_output=True,
        text=True,
    )
