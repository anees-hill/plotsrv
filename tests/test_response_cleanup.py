from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import pytest

from plotsrv import config, store
from plotsrv.app import app
from plotsrv.browser_updates import browser_update_hub
from plotsrv.file_backed_loads import _FILE_BACKED_LOADS


@pytest.mark.parametrize("path", ["/table/data", "/updates"])
@pytest.mark.parametrize("stage", ["before_body", "during_body"])
@pytest.mark.parametrize("spec", ["2.3", "2.4"])
def test_disconnect_releases_response_resources(tmp_path, monkeypatch, path, stage, spec):
    store.reset()
    _FILE_BACKED_LOADS.reset_for_tests()
    monkeypatch.setattr(config, "get_watch_active_load_max_concurrent", lambda: 2)
    source = tmp_path / "tiny.csv"
    source.write_text("x,y\n1,2\n")
    store.set_watched_file_meta(store.WatchedFileMeta(
        view_id="cleanup", path=str(source), file_kind="csv", read_mode="head",
        encoding="utf-8", materialization="file", max_bytes=64,
    ))
    baseline = browser_update_hub.subscriber_count()

    async def scenario():
        disconnect = asyncio.Event()

        async def receive():
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            target = "http.response.start" if stage == "before_body" else "http.response.body"
            if message["type"] == target:
                if spec == "2.4":
                    raise OSError("disconnected test client")
                disconnect.set()
                # Model backpressure while the disconnect listener cancels us.
                await asyncio.Event().wait()

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": spec},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": path, "raw_path": path.encode(), "root_path": "",
            "query_string": urlencode({"view": "cleanup"}).encode(),
            "headers": [(b"host", b"testserver")],
            "client": ("198.51.100.10", 1234), "server": ("testserver", 80),
        }
        try:
            await asyncio.wait_for(app(scope, receive, send), timeout=2)
        except Exception as error:
            from starlette.requests import ClientDisconnect
            if spec != "2.4" or not isinstance(error, ClientDisconnect):
                raise

    try:
        asyncio.run(scenario())
        assert _FILE_BACKED_LOADS.stats()["active"] == 0
        assert browser_update_hub.subscriber_count() == baseline
    finally:
        store.reset()
        _FILE_BACKED_LOADS.reset_for_tests()
