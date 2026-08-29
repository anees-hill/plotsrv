from __future__ import annotations

from pathlib import Path


_STATIC_JS = Path(__file__).parents[1] / "src" / "plotsrv" / "static" / "js"


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
