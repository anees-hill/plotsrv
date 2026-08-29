from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
from starlette.requests import Request

from plotsrv import store
from plotsrv.app import browser_updates
from plotsrv.browser_updates import (
    BrowserUpdateCapacityError,
    BrowserUpdateHub,
    browser_update_hub,
)


def test_subscriber_queue_coalesces_to_the_latest_change_and_cleans_up() -> None:
    async def scenario() -> None:
        hub = BrowserUpdateHub()
        subscription = hub.subscribe(
            view_id="reports:daily", since=0, loop=asyncio.get_running_loop()
        )
        hub.publish(view_id="reports:daily", change_type="ordinary", metadata={"n": 1})
        latest = hub.publish(
            view_id="reports:daily", change_type="ordinary", metadata={"n": 2}
        )
        await asyncio.sleep(0)

        assert subscription.queue.qsize() == 1
        assert subscription.queue.get_nowait() == latest
        hub.unsubscribe(subscription)
        assert hub.subscriber_count() == 0

    asyncio.run(scenario())


def test_reconnect_gets_current_view_state_but_not_other_view_changes() -> None:
    async def scenario() -> None:
        hub = BrowserUpdateHub()
        first = hub.publish(
            view_id="wanted", change_type="ordinary", metadata={"render_revision": 7}
        )
        hub.publish(view_id="other", change_type="ordinary")
        assert first is not None

        subscription = hub.subscribe(
            view_id="wanted", since=0, loop=asyncio.get_running_loop()
        )
        event = subscription.queue.get_nowait()
        assert event.change_type == "reconnect"
        assert event.revision == first.revision
        assert event.metadata == {"render_revision": 7}
        hub.unsubscribe(subscription)

    asyncio.run(scenario())


def test_duplicate_fingerprints_are_suppressed_and_subscribers_are_bounded() -> None:
    async def scenario() -> None:
        hub = BrowserUpdateHub(max_subscribers=1)
        assert hub.publish(view_id="stream", change_type="stream", fingerprint="same")
        assert hub.publish(
            view_id="stream", change_type="stream", fingerprint="same"
        ) is None
        subscription = hub.subscribe(
            view_id="stream", since=hub.current_revision("stream"),
            loop=asyncio.get_running_loop(),
        )
        try:
            hub.subscribe(view_id="other", since=0, loop=asyncio.get_running_loop())
        except BrowserUpdateCapacityError:
            pass
        else:
            raise AssertionError("subscriber cap was not enforced")
        hub.unsubscribe(subscription)

    asyncio.run(scenario())


def test_ordinary_render_revision_advances_browser_update_token() -> None:
    store.reset()
    before = browser_update_hub.current_revision("reports:daily")
    store.set_table(pd.DataFrame([{"value": 1}]), None, view_id="reports:daily")
    after = browser_update_hub.current_revision("reports:daily")

    assert after > before
    assert store.get_render_revision(view_id="reports:daily") > 0


def test_sse_serializes_an_event_id_and_releases_its_subscription() -> None:
    async def scenario() -> None:
        store.reset()
        baseline = browser_update_hub.subscriber_count()
        initial_revision = browser_update_hub.current_revision("events")
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/updates",
                "raw_path": b"/updates",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
            }
        )
        response = await browser_updates(
            request=request, view="events", since=initial_revision
        )
        iterator = response.body_iterator
        assert await anext(iterator) == "retry: 2000\n\n"
        event = browser_update_hub.publish(
            view_id="events", change_type="ordinary", metadata={"kind": "table"}
        )
        assert event is not None
        chunk = await asyncio.wait_for(anext(iterator), timeout=1)
        assert f"id: {event.revision}\n" in chunk
        assert 'event: update\ndata: {"revision":' in chunk
        await iterator.aclose()
        assert browser_update_hub.subscriber_count() == baseline

    asyncio.run(scenario())


def test_browser_policy_keeps_history_filters_and_stream_cursor_contract() -> None:
    root = Path(__file__).parents[1] / "src" / "plotsrv" / "static" / "js"
    updates = (root / "core" / "auto_refresh.js").read_text("utf-8")
    stream = (root / "renderers" / "stream.js").read_text("utf-8")

    assert 'blockers.push("snapshot")' in updates
    assert 'blockers.push("table_search")' in updates
    assert 'blockers.push("table_filters")' in updates
    assert 'blockers.push("table_sorting")' in updates
    assert 'blockers.push("plot_mode")' in updates
    assert "state.pendingBrowserUpdate = payload" in updates
    assert 'url += "&after="' in stream
    assert "await appendTableData(table, merged.additions)" in stream
    assert "setInterval" not in stream
