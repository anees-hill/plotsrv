from __future__ import annotations

from pathlib import Path


_STATIC = Path(__file__).parents[1] / "src" / "plotsrv" / "static"
_STATIC_JS = _STATIC / "js"


def _read(relative_path: str) -> str:
    return (_STATIC_JS / relative_path).read_text(encoding="utf-8")


def test_header_status_model_keeps_view_freshness_and_browser_state_separate() -> None:
    state_source = _read("core/state.js")
    status_source = _read("core/status.js")

    assert 'viewMode: state.currentSnapshot ? "snapshot" : "latest"' in state_source
    assert "latestData:" in state_source
    assert 'browserData: "current"' in state_source
    assert 'model.viewMode === "snapshot"' in status_source
    assert 'model.browserData === "update_available"' in status_source
    assert "latest.freshness" in status_source


def test_snapshot_presentation_overrides_age_and_new_data_presentation() -> None:
    status_source = _read("core/status.js")

    snapshot_branch = status_source.index('model.viewMode === "snapshot"')
    new_data_branch = status_source.index('model.browserData === "update_available"')
    freshness_branch = status_source.index("const freshness = latest.freshness")

    assert snapshot_branch < new_data_branch < freshness_branch
    assert 'label: "Snapshot"' in status_source
    assert "Freshness applies only to the latest data" in status_source
    assert 'label: "New data available"' in status_source


def test_stream_header_uses_a_stable_lifecycle_presentation_and_slow_pulse() -> None:
    state_source = _read("core/state.js")
    status_source = _read("core/status.js")
    app_source = _read("core/app.js")
    stream_source = _read("renderers/stream.js")
    status_css = (_STATIC / "css" / "status.css").read_text(encoding="utf-8")

    assert "stream:" in state_source
    assert 'config.kind === "stream"' in status_source
    assert 'label: "Stream active"' in status_source
    assert 'label: "Stream retrying"' in status_source
    assert 'label: "Stream disconnected"' in status_source
    assert 'label: "Stream incomplete"' in status_source
    assert 'label: "Stream ended"' in status_source
    assert 'label: "Stream paused"' in status_source
    assert 'label: "Continuity uncertain"' in status_source
    assert 'label: "Source unavailable"' in status_source
    assert 'label: "Stored run"' in status_source
    assert "setHeaderStreamStatus" in stream_source
    assert "setHeaderStreamSessionState" in stream_source
    assert "notifyHeaderStreamPauseChanged" in status_source
    assert "core.notifyHeaderStreamPauseChanged()" in stream_source
    assert 'config.kind !== "stream" && state.headerFreshnessTimer == null' in status_source
    assert 'config.kind === "stream" && state.latestStatusPayload' in app_source
    assert "STREAM_STATUS_GRACE_MS = 2500" in status_source
    assert "state.headerStreamPendingStatus" in status_source
    assert "window.clearTimeout(state.headerStreamTransitionTimer)" in status_source
    status_key = status_source.split("function streamHeaderStatusKey(value)", 1)[1].split(
        "function clearHeaderStreamTransition", 1
    )[0]
    assert "lastHeartbeat" not in status_key
    assert "ps-stream-active-pulse 4s" in status_css
    assert "prefers-reduced-motion: reduce" in status_css


def test_ordinary_latest_status_uses_the_green_live_tone() -> None:
    status_source = _read("core/status.js")
    latest_branch = status_source.split(
        'if (freshnessState === "unknown")', 1
    )[1].split("function renderHeaderStatus", 1)[0]

    assert 'tone: "live"' in latest_branch


def test_new_data_and_history_tones_add_matching_header_accents() -> None:
    status_source = _read("core/status.js")
    layout_css = (_STATIC / "css" / "layout.css").read_text(encoding="utf-8")
    status_css = (_STATIC / "css" / "status.css").read_text(encoding="utf-8")

    assert 'document.getElementById("site-header")' in status_source
    assert 'header.setAttribute("data-status-accent", accent)' in status_source
    assert 'presentation.tone === "new-data"' in status_source
    assert 'presentation.tone === "history"' in status_source
    assert '.ps-header[data-status-accent]::after' in layout_css
    assert '.ps-header[data-status-accent="new-data"]' in layout_css
    assert '.ps-header[data-status-accent="history"]' in layout_css
    assert "--ps-header-status-accent: #f2c200" in layout_css
    assert "--ps-header-status-accent: #8b72b8" in layout_css
    assert "var(--ps-header-status-accent, #f2c200)" in status_css
    assert "var(--ps-header-status-accent, #8b72b8)" in status_css


def test_header_status_opens_the_shared_accessible_modal() -> None:
    status_source = _read("core/status.js")
    modal_source = _read("core/status_modal.js")
    app_source = _read("core/app.js")

    assert 'button.addEventListener("click"' in status_source
    assert "core.openStatusModal()" in status_source
    assert 'event.key === "Escape"' in modal_source
    assert 'event.key !== "Tab"' in modal_source
    assert "state.statusModalReturnFocus" in modal_source
    assert "core.returnToLive()" in modal_source
    assert "core.bindHeaderStatus()" in app_source
    assert "core.bindStatusModal()" in app_source


def test_view_selector_and_status_use_the_same_header_control_treatment() -> None:
    status_css = (_STATIC / "css" / "status.css").read_text(encoding="utf-8")
    controls_css = (_STATIC / "css" / "controls.css").read_text(encoding="utf-8")
    html_source = (
        Path(__file__).parents[1] / "src" / "plotsrv" / "html.py"
    ).read_text(encoding="utf-8")

    shared = status_css.split(".ps-header-status__button,", 1)[1].split("}", 1)[0]
    assert ".ps-viewselect__btn" in shared
    for declaration in (
        "min-height: 36px",
        "padding: 0.38rem 0.65rem",
        "border: 1px solid #dedede",
        "border-radius: 12px",
        "box-shadow: 0 1px 3px rgba(0, 0, 0, 0.07)",
    ):
        assert declaration in shared

    assert ".ps-header-status__button:hover,\n.ps-viewselect__btn:hover" in status_css
    assert ".ps-header-status__button:focus-visible,\n.ps-viewselect__btn:focus-visible" in status_css
    assert "grid-template-columns: auto minmax(0, auto) auto" in controls_css
    assert 'class="ps-viewselect__chev" aria-hidden="true">⌄</span>' in html_source
