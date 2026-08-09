from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv import config, store
from plotsrv.app import app
from plotsrv.runtime import WatchConfig, register_watch_views, start_watch_threads


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    store.reset()
    config.set_table_view_mode("simple")
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    monkeypatch.setattr(config, "get_internal_read_local_only", lambda: False)
    monkeypatch.setattr(config, "get_views_local_only", lambda: False)
    yield
    store.reset()
    config.set_table_view_mode("simple")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_file_backed_watch_registration_stores_metadata_not_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.log"
    p.write_text("x" * 100_000, encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    registered = register_watch_views(
        [
            WatchConfig(
                path=p,
                label="large",
                section="logs",
                read_mode="tail",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    assert registered[0].materialization == "file"
    assert registered[0].view_id == "logs:large"

    assert store.has_watched_file_meta(view_id="logs:large") is True
    assert store.has_artifact(view_id="logs:large") is False
    assert store.has_table(view_id="logs:large") is False

    meta = store.get_watched_file_meta(view_id="logs:large")
    assert meta.path == str(p.resolve())
    assert meta.materialization == "file"
    assert meta.size_bytes == p.stat().st_size
    assert meta.max_bytes == 100


def test_file_backed_artifact_route_reads_bounded_preview_only(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.log"
    p.write_text(
        "START\n" + ("x" * 100_000) + "\nEND\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="large",
                section="logs",
                read_mode="tail",
                max_bytes=20,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/artifact?view=logs:large")

    assert resp.status_code == 200
    data = resp.json()

    assert data["kind"] == "text"
    assert data["meta"]["file_backed"] is True
    assert data["meta"]["preview_bytes"] <= 20
    assert "END" in data["html"]
    assert "START" not in data["html"]

    assert store.has_artifact(view_id="logs:large") is False
    assert store.has_table(view_id="logs:large") is False


def test_file_backed_csv_table_data_reads_preview_without_store_table(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.csv"
    p.write_text(
        "a,b\n" + "\n".join(f"{i},value-{i}" for i in range(1000)) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 5)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 2)

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="large",
                section="csv",
                read_mode="head",
                max_bytes=200,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/table/data?view=csv:large")

    assert resp.status_code == 200
    data = resp.json()

    assert data["columns"] == ["a", "b"]
    assert len(data["rows"]) == 5
    assert data["meta"]["file_backed"] is True
    assert data["meta"]["preview_bytes"] <= 200
    assert data["meta"]["truncated"] is True

    assert store.has_table(view_id="csv:large") is False
    assert store.has_artifact(view_id="csv:large") is False


def test_file_backed_watch_thread_records_metadata_without_reading_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.log"
    p.write_text("x" * 100_000, encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    read_calls = {"n": 0}
    publish_calls = {"n": 0}
    sleep_calls = {"n": 0}

    def fake_read_watch_file_bytes(*args: Any, **kwargs: Any) -> bytes:
        read_calls["n"] += 1
        raise AssertionError("file-backed watch thread must not read file contents")

    def fake_publish_prepared_watch_payload(*args: Any, **kwargs: Any) -> bool:
        publish_calls["n"] += 1
        raise AssertionError("file-backed watch thread must not publish payloads")

    def fake_sleep(seconds: float) -> None:
        sleep_calls["n"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "plotsrv.runtime.read_watch_file_bytes",
        fake_read_watch_file_bytes,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.publish_prepared_watch_payload",
        fake_publish_prepared_watch_payload,
    )
    monkeypatch.setattr("plotsrv.runtime.time.sleep", fake_sleep)

    class ImmediateThread:
        def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self) -> None:
            try:
                self.target()
            except KeyboardInterrupt:
                pass

    monkeypatch.setattr("plotsrv.runtime.threading.Thread", ImmediateThread)

    start_watch_threads(
        [
            WatchConfig(
                path=p,
                label="large",
                section="logs",
                read_mode="tail",
                max_bytes=100,
            )
        ],
        host="127.0.0.1",
        port=8000,
        register_views=True,
    )

    assert read_calls["n"] == 0
    assert publish_calls["n"] == 0
    assert sleep_calls["n"] == 1

    assert store.has_watched_file_meta(view_id="logs:large") is True
    assert store.has_artifact(view_id="logs:large") is False
    assert store.has_table(view_id="logs:large") is False

    status = store.get_status(view_id="logs:large")
    assert status["last_error"] is None


def test_memory_backed_watch_thread_still_reads_and_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "small.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "memory",
    )

    read_calls = {"n": 0}
    publish_calls = {"n": 0}
    sleep_calls = {"n": 0}

    def fake_read_watch_file_bytes(*args: Any, **kwargs: Any) -> bytes:
        read_calls["n"] += 1
        return b"hello\n"

    def fake_publish_prepared_watch_payload(*args: Any, **kwargs: Any) -> bool:
        publish_calls["n"] += 1
        return True

    def fake_sleep(seconds: float) -> None:
        sleep_calls["n"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "plotsrv.runtime.read_watch_file_bytes",
        fake_read_watch_file_bytes,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.publish_prepared_watch_payload",
        fake_publish_prepared_watch_payload,
    )
    monkeypatch.setattr("plotsrv.runtime.time.sleep", fake_sleep)

    class ImmediateThread:
        def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self) -> None:
            try:
                self.target()
            except KeyboardInterrupt:
                pass

    monkeypatch.setattr("plotsrv.runtime.threading.Thread", ImmediateThread)

    start_watch_threads(
        [
            WatchConfig(
                path=p,
                label="small",
                section="logs",
                read_mode="tail",
                max_bytes=100,
            )
        ],
        host="127.0.0.1",
        port=8000,
        register_views=True,
    )

    assert read_calls["n"] == 1
    assert publish_calls["n"] == 1
    assert sleep_calls["n"] == 1

    meta = store.get_watched_file_meta(view_id="logs:small")
    assert meta.materialization == "memory"


def test_file_backed_csv_contract_streams_source_and_skips_storage(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plotsrv.storage.worker as worker_mod

    p = tmp_path / "large.csv"
    p.write_text("a\n1\n2\n3\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="large",
                section="csv",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    data_resp = client.get("/table/data?view=csv:large")
    assert data_resp.status_code == 200
    assert data_resp.json()["meta"]["file_backed"] is True

    export_resp = client.get("/table/export?view=csv:large")
    assert export_resp.status_code == 200
    assert export_resp.content == p.read_bytes()

    latest_calls: list[dict[str, Any]] = []
    snapshot_calls: list[dict[str, Any]] = []

    class FakeLatestBackend:
        def __init__(self, **kwargs: Any) -> None:
            latest_calls.append(kwargs)

        def write_latest(self, **kwargs: Any) -> object:
            latest_calls.append(kwargs)
            return object()

    monkeypatch.setattr(worker_mod.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_mod.config, "get_storage_latest_enabled", lambda: True)
    monkeypatch.setattr(worker_mod, "FileLatestStateBackend", FakeLatestBackend)
    monkeypatch.setattr(worker_mod, "list_snapshots", lambda **kwargs: [])
    monkeypatch.setattr(
        worker_mod,
        "write_snapshot_and_prune",
        lambda **kwargs: snapshot_calls.append(kwargs),
    )

    w = worker_mod.StorageWorker()
    w._process_task(
        worker_mod.StorageTask(
            view_id="csv:large",
            kind="table",
            obj=pd.DataFrame({"a": [1]}),
            section="csv",
            label="large",
            source="watch",
            extra={
                "file_backed": True,
                "materialization": "file",
            },
        )
    )

    assert latest_calls == []
    assert snapshot_calls == []
