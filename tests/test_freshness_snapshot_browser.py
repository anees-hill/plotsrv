"""Freshness markers use the same stored-snapshot selection as History."""

import pytest

from tests.test_expanded_view_browser import mount, page


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_retained_point_is_accessible_and_opens_its_snapshot(page, theme):
    mount(page)
    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
    page.evaluate("""() => {
      const now = Date.now();
      const events = [90, 70, 50, 30, 10].map((seconds, index) => ({
        received_at: new Date(now - seconds * 1000).toISOString(),
        count: 1,
        ...(index === 2 ? {snapshot_id: '2'} : {}),
      }));
      PLOTSRV.core.setHeaderLatestStatus({
        last_updated: events[4].received_at,
        last_data_arrival_at: events[4].received_at,
        data_activity: {events, limit: 256},
      });
      PLOTSRV.core.openStatusModal();
    }""")

    markers = page.locator("#status-modal-activity-dots .ps-arrival-chart__dot")
    assert markers.count() == 5
    assert page.locator("#status-modal-activity-dots button").count() == 1
    assert page.locator("#status-modal-snapshot-legend").is_visible()
    marker = page.get_by_role("button", name="Snapshot available — click to open")
    assert marker.get_attribute("title").startswith("Snapshot available — click to open")
    assert marker.evaluate("e => e.getBoundingClientRect().width") >= 28
    assert marker.evaluate("e => getComputedStyle(e, '::before').outlineColor") != marker.evaluate(
        "e => getComputedStyle(e.parentElement).backgroundColor"
    )
    marker.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("PLOTSRV.state.currentSnapshot === '2'")
    assert page.locator("#status-modal-backdrop").is_hidden()
    assert "snapshot=2" in page.url


def test_activity_without_retained_snapshot_has_no_open_action(page):
    mount(page)
    page.evaluate("""() => {
      const now = new Date().toISOString();
      PLOTSRV.core.setHeaderLatestStatus({
        last_updated: now, last_data_arrival_at: now,
        data_activity: {events: [{received_at: now, count: 1}], limit: 256},
      });
      PLOTSRV.core.openStatusModal();
    }""")
    assert page.locator("#status-modal-activity-dots .ps-arrival-chart__dot").count() == 1
    assert page.locator("#status-modal-activity-dots button").count() == 0
    assert page.locator("#status-modal-snapshot-legend").is_hidden()
