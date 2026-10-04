from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import threading

import pandas as pd
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from plotsrv import config, store
from plotsrv.app import app, _get_table_data_uncached
from plotsrv.http_security import require_snapshot_read
from plotsrv.table_cache import TABLE_RESPONSES, TableResponseCache, TableResponseKey


@pytest.fixture(autouse=True)
def reset():
    store.reset()
    yield
    store.reset()
    app.dependency_overrides.clear()


def publish(client, rows=None, view="cache:table", **table):
    response = client.post("/publish", json={
        "view_id": view, "kind": "table", "force": True,
        "table": {"columns": ["a"], "rows": [{"a": 1}, {"a": 2}] if rows is None else rows, **table},
    })
    assert response.status_code == 200, response.text
    return view


@pytest.mark.parametrize("df", [
    pd.DataFrame(), pd.DataFrame({"a": []}),
    pd.DataFrame({"a": [1, None, 3], "unicode": ["café", "你好", "<>&"]}),
    pd.DataFrame({"date": [datetime(2026, 1, 1)], "nested": [{"list": [1, None]}]}),
    pd.DataFrame({"number": [float("nan"), float("inf"), -float("inf")]}),
])
def test_wire_bytes_match_original_framework_path(df):
    # A reference route retains the original synchronous framework serialization.
    reference = FastAPI()
    @reference.get("/table/data")
    def original() -> dict[str, object]:
        return _get_table_data_uncached(limit=None, view="test", snapshot=None)
    store.set_table(df, None, view_id="test", receiver_owned=True)
    with TestClient(reference) as old, TestClient(app, client=("127.0.0.1", 50000)) as new:
        expected = old.get("/table/data")
        for _ in range(2):
            actual = new.get("/table/data?view=test")
            assert actual.status_code == expected.status_code
            assert actual.content == expected.content
            assert actual.headers["content-type"] == expected.headers["content-type"]
            assert actual.headers["content-length"] == expected.headers["content-length"]


def test_errors_are_not_cached():
    store.set_table(pd.DataFrame({"a": [object()]}), None, view_id="bad", receiver_owned=True)
    with TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False) as client:
        assert client.get("/table/data?view=bad").status_code == 500
        assert client.get("/table/data?view=bad").status_code == 500
    assert TABLE_RESPONSES.stats() == dict(entries=0, bytes=0, builds=0, waiters=0)


def test_http_hits_limits_counts_views_and_dependencies(monkeypatch):
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        publish(client, total_rows=10, returned_rows=2)
        publish(client, rows=[{"a": 9}], view="other")
        calls = []
        original = pd.DataFrame.to_dict
        def tracked(df, *args, **kwargs):
            calls.append(len(df))
            return original(df, *args, **kwargs)
        monkeypatch.setattr(pd.DataFrame, "to_dict", tracked)
        for _ in range(2):
            data = client.get("/table/data?view=cache:table&limit=1").json()
            assert data["rows"] == [{"a": 1}]
            assert data["total_rows"] == 10 and data["returned_rows"] == 2
        assert calls == [1]
        assert client.get("/table/data?view=other").json()["rows"] == [{"a": 9}]
        store.set_active_view("cache:table")
        assert len(client.get("/table/data").json()["rows"]) == 2
        assert client.get("/table/data?limit=0").status_code == 422
        def reject():
            raise HTTPException(403, "denied")
        app.dependency_overrides[require_snapshot_read] = reject
        assert client.get("/table/data?view=cache:table&limit=1").status_code == 403


def test_config_limits_are_part_of_key(monkeypatch):
    store.set_table(pd.DataFrame({"a": [1, 2], "b": [3, 4]}), None,
                    view_id="test", receiver_owned=True)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 1)
        monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 1)
        assert client.get("/table/data?view=test").json()["rows"] == [{"a": 1}]
        monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 2)
        monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 2)
        assert client.get("/table/data?view=test").json()["rows"] == [{"a": 1, "b": 3}, {"a": 2, "b": 4}]


def test_local_mutation_remains_visible_and_replacement_invalidates():
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        publish(client)
        client.get("/table/data?view=cache:table")
        assert TABLE_RESPONSES.stats()["entries"] == 1
        df = pd.DataFrame({"a": [3]})
        store.set_table(df, None, view_id="cache:table")
        assert TABLE_RESPONSES.stats()["entries"] == 0
        assert client.get("/table/data?view=cache:table").json()["rows"] == [{"a": 3}]
        df.loc[0, "a"] = 4
        assert client.get("/table/data?view=cache:table").json()["rows"] == [{"a": 4}]
        assert TABLE_RESPONSES.stats()["entries"] == 0


@pytest.mark.parametrize("replacement", ["republish", "reset", "artifact"])
def test_publication_race_never_retains_old_build(monkeypatch, replacement):
    # Import through importlib: plotsrv's public app symbol can be lazy.
    import importlib
    app_module = importlib.import_module("plotsrv.app")
    entered, release = threading.Event(), threading.Event()
    original = app_module._table_data_response_from_df
    def blocked(df, **kwargs):
        if df.iloc[0, 0] == 1:
            entered.set()
            assert release.wait(5)
        return original(df, **kwargs)
    with TestClient(app, client=("127.0.0.1", 50000)) as client, ThreadPoolExecutor() as pool:
        publish(client)
        monkeypatch.setattr(app_module, "_table_data_response_from_df", blocked)
        pending = pool.submit(client.get, "/table/data?view=cache:table")
        assert entered.wait(5)
        try:
            if replacement == "republish":
                publish(client, rows=[{"a": 8}], total_rows=11, returned_rows=1)
            elif replacement == "reset":
                store.reset()
            else:
                store.set_artifact(obj="hello", kind="text", view_id="cache:table")
        finally:
            release.set()
        assert pending.result(5).json()["rows"] == [{"a": 1}, {"a": 2}]
        assert TABLE_RESPONSES.stats()["entries"] == 0
        if replacement == "republish":
            data = client.get("/table/data?view=cache:table").json()
            assert data["rows"] == [{"a": 8}] and data["total_rows"] == 11
        elif replacement == "reset":
            assert not store.list_views()


def test_remote_metadata_bypasses_even_an_existing_entry(monkeypatch):
    from plotsrv import remote_watch
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        publish(client)
        client.get("/table/data?view=cache:table")
        monkeypatch.setattr(remote_watch, "public_meta", lambda vid: {
            "complete": False, "status": "disconnected", "limitation": "preview",
        })
        response = client.get("/table/data?view=cache:table").json()
        assert response["meta"]["status"] == "disconnected"
        assert response["total_rows_known"] is False


def test_cache_lru_and_byte_bounds():
    cache = TableResponseCache(max_entries=2, max_bytes=5, max_entry_bytes=4)
    keys = [TableResponseKey(str(i), 1, None, None) for i in range(4)]
    cache.put(keys[0], b"aa")
    cache.put(keys[1], b"bb")
    async def scenario():
        assert await cache.get_or_build(keys[0], lambda: pytest.fail("cache hit rebuilt")) == b"aa"
    asyncio.run(scenario())
    cache.put(keys[2], b"ccc")
    assert set(cache._entries) == {keys[0], keys[2]}
    cache.put(keys[3], b"12345")
    assert cache.stats()["bytes"] == 5
    cache.invalidate("0")
    assert cache.stats()["bytes"] == 3
    cache.invalidate()
    assert cache.stats()["entries"] == 0


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.mark.parametrize("fail", [False, True])
def test_single_build_followers_cancellation_failure_and_retry(fail):
    cache = TableResponseCache()
    key = TableResponseKey("view", 1, None, None)
    release = threading.Event()
    builds = []
    def build():
        builds.append(1)
        assert release.wait(5)
        if fail:
            raise ValueError("failed build")
        return b"result"
    async def scenario():
        readers = [asyncio.create_task(cache.get_or_build(key, build)) for _ in range(20)]
        try:
            await wait_until(lambda: cache.stats()["waiters"] == 20)
            readers[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await readers[0]
        finally:
            release.set()
        results = await asyncio.gather(*readers[1:], return_exceptions=True)
        assert len(builds) == 1
        assert all(isinstance(r, ValueError) if fail else r == b"result" for r in results)
        await wait_until(lambda: cache.stats()["builds"] == 0)
        assert cache.stats()["waiters"] == 0
        assert await cache.get_or_build(key, lambda: b"retry") == b"retry"
    asyncio.run(scenario())


def test_coordination_capacity_falls_back_without_rejection():
    cache = TableResponseCache(max_builds=1, max_waiters=1)
    key = TableResponseKey("view", 1, None, None)
    release = threading.Event()
    async def scenario():
        first = asyncio.create_task(cache.get_or_build(key, lambda: (release.wait(5), b"first")[1]))
        try:
            await wait_until(lambda: cache.stats()["waiters"] == 1)
            assert await cache.get_or_build(key, lambda: b"fallback") == b"fallback"
            assert cache.stats()["builds"] == 1
        finally:
            release.set()
        assert await first == b"first"
    asyncio.run(scenario())


def test_twenty_http_readers_share_one_encoding(monkeypatch):
    import importlib
    import time
    module = importlib.import_module("plotsrv.app")
    entered, release = threading.Event(), threading.Event()
    builds = []
    original = module._table_data_response_from_df
    def blocked(*args, **kwargs):
        builds.append(1)
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    with TestClient(app, client=("127.0.0.1", 50000)) as client, ThreadPoolExecutor(max_workers=20) as pool:
        publish(client)
        monkeypatch.setattr(module, "_table_data_response_from_df", blocked)
        pending = [pool.submit(client.get, "/table/data?view=cache:table") for _ in range(20)]
        try:
            assert entered.wait(5)
            deadline = time.monotonic() + 5
            while TABLE_RESPONSES.stats()["waiters"] < 20 and time.monotonic() < deadline:
                time.sleep(.001)
            assert TABLE_RESPONSES.stats()["waiters"] == 20
        finally:
            release.set()
        responses = [p.result(5) for p in pending]
        assert all(r.status_code == 200 and r.content == responses[0].content for r in responses)
        assert client.get("/table/data?view=cache:table").content == responses[0].content
        assert builds == [1]


def test_oversized_build_is_shared_but_not_retained():
    cache = TableResponseCache(max_entry_bytes=1)
    key = TableResponseKey("view", 1, None, None)
    release = threading.Event()
    builds = []
    def build():
        builds.append(1)
        assert release.wait(5)
        cache.put(key, b"oversized")
        return b"oversized"
    async def scenario():
        readers = [asyncio.create_task(cache.get_or_build(key, build)) for _ in range(5)]
        try:
            await wait_until(lambda: cache.stats()["waiters"] == 5)
        finally:
            release.set()
        assert await asyncio.gather(*readers) == [b"oversized"] * 5
        assert builds == [1] and cache.stats()["entries"] == 0
    asyncio.run(scenario())


def test_memory_watch_bypasses_and_invalidates_cached_table(tmp_path):
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        publish(client)
        client.get("/table/data?view=cache:table")
        store.set_watched_file_meta(store.WatchedFileMeta(
            view_id="cache:table", path=str(tmp_path / "watch.csv"), file_kind="csv",
            read_mode="head", encoding="utf-8", materialization="memory",
        ))
        assert TABLE_RESPONSES.stats()["entries"] == 0
        first = client.get("/table/data?view=cache:table").json()
        assert "meta" in first
        store.get_table_df(view_id="cache:table").loc[0, "a"] = 7
        assert client.get("/table/data?view=cache:table").json()["rows"][0]["a"] == 7
        assert TABLE_RESPONSES.stats()["entries"] == 0


def test_republish_columns_and_historical_reads_do_not_reuse_current_bytes(monkeypatch):
    import importlib
    from types import SimpleNamespace
    module = importlib.import_module("plotsrv.app")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        publish(client)
        assert client.get("/table/data?view=cache:table").json()["columns"] == ["a"]
        publish(client, rows=[{"b": 5}], columns=["b"], total_rows=30, returned_rows=1)
        current = client.get("/table/data?view=cache:table").json()
        assert current["columns"] == ["b"] and current["rows"] == [{"b": 5}]
        monkeypatch.setattr(module, "_load_snapshot_or_404", lambda **kw: SimpleNamespace(
            obj=pd.DataFrame({"a": [9]}), meta=SimpleNamespace(kind="table", extra={}),
        ))
        historical = client.get("/table/data?view=cache:table&snapshot=old").json()
        assert historical["rows"] == [{"a": 9}] and historical["snapshot_id"] == "old"
        assert client.get("/table/data?view=cache:table").json() == current
