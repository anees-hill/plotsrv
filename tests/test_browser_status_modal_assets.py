from __future__ import annotations

from pathlib import Path


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


def test_stream_modal_distinguishes_records_heartbeats_and_continuity() -> None:
    source = _read("js/core/status_modal.js")

    assert '"Each dot is an accepted record batch; heartbeats are excluded."' in source
    assert "status-modal-stream-lifecycle" in source
    assert "stream.last_heartbeat_at" in source
    assert "stream.continuity_warning" in source
    assert '"No known continuity gap"' in source
    assert "not the application’s full state" in (
        ROOT / "src" / "plotsrv" / "html.py"
    ).read_text(encoding="utf-8")


def test_hidden_modal_does_no_timeline_dom_work() -> None:
    source = _read("js/core/status_modal.js")
    render_start = source.split("function renderStatusModal()", 1)[1].split(
        "function focusableElements", 1
    )[0]

    assert "if (!modal || !state.statusModalOpen) return" in render_start
