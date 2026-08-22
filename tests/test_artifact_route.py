from __future__ import annotations

import importlib

import pandas as pd
from fastapi.testclient import TestClient

from plotsrv import config, store
from plotsrv.app import app
from plotsrv.runtime import WatchConfig, register_watch_views


def test_artifact_404_when_none() -> None:
    store.reset()
    config.set_table_view_mode("simple")
    client = TestClient(app)
    r = client.get("/artifact")
    assert r.status_code == 404


def test_artifact_plot_returns_html() -> None:
    store.reset()
    client = TestClient(app)

    store.set_plot(b"\x89PNGfake")
    r = client.get("/artifact")
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "plot"
    assert "<img" in data["html"]
    assert "/plot?view=" in data["html"]


def test_artifact_table_returns_html() -> None:
    store.reset()
    client = TestClient(app)

    store.set_table(pd.DataFrame({"a": [1]}), html_simple="<table>hi</table>")
    r = client.get("/artifact")
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "table"
    assert "table-grid" in data["html"]


def test_artifact_route_caches_current_render_and_invalidates_on_publish(
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)
    app_module = importlib.import_module("plotsrv.app")
    original_render_any = app_module.render_any
    calls = 0

    def counting_render_any(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_render_any(*args, **kwargs)

    monkeypatch.setattr(app_module, "render_any", counting_render_any)

    view_id = "report:current"
    store.set_artifact(
        view_id=view_id,
        kind="markdown",
        obj="# First report\n\nUnchanged content.",
    )

    first = client.get(f"/artifact?view={view_id}")
    second = client.get(f"/artifact?view={view_id}")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert calls == 1

    store.set_artifact(
        view_id=view_id,
        kind="markdown",
        obj="# Updated report\n\nNew content.",
    )

    refreshed = client.get(f"/artifact?view={view_id}")

    assert refreshed.status_code == 200
    assert "Updated report" in refreshed.json()["html"]
    assert calls == 2


def test_artifact_route_caches_representative_large_json_render(
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)
    app_module = importlib.import_module("plotsrv.app")
    original_render_any = app_module.render_any
    calls = 0

    def counting_render_any(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_render_any(*args, **kwargs)

    monkeypatch.setattr(app_module, "render_any", counting_render_any)

    store.set_artifact(
        kind="json",
        obj={
            "items": [
                {
                    "id": index,
                    "name": f"name_{index}",
                    "values": list(range(10)),
                }
                for index in range(400)
            ]
        },
    )

    first = client.get("/artifact")
    second = client.get("/artifact")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1


def test_file_backed_artifacts_are_not_cached_between_requests(
    tmp_path,
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)
    app_module = importlib.import_module("plotsrv.app")
    original_render_any = app_module.render_any
    calls = 0

    def counting_render_any(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_render_any(*args, **kwargs)

    monkeypatch.setattr(app_module, "render_any", counting_render_any)

    path = tmp_path / "report.md"
    path.write_text("# First", encoding="utf-8")
    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    register_watch_views(
        [
            WatchConfig(
                path=path,
                label="report",
                section="docs",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    first = client.get("/artifact?view=docs:report")
    path.write_text("# Updated", encoding="utf-8")
    second = client.get("/artifact?view=docs:report")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "First" in first.json()["html"]
    assert "Updated" in second.json()["html"]
    assert calls == 2


def test_artifact_route_serves_file_backed_text_watch(
    tmp_path,
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)

    p = tmp_path / "app.log"
    p.write_text("first\nsecond\nthird\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="api",
                section="logs",
                read_mode="tail",
                max_bytes=12,
            )
        ],
        activate_first_if_none=True,
    )

    r = client.get("/artifact?view=logs:api")

    assert r.status_code == 200
    data = r.json()

    assert data["view_id"] == "logs:api"
    assert data["kind"] == "text"
    assert "third" in data["html"]
    assert "first\nsecond" not in data["html"]
    assert data["meta"]["file_backed"] is True
    assert data["meta"]["watch"] is True
    assert data["meta"]["materialization"] == "file"
    assert data["meta"]["read_mode"] == "tail"
    assert data["meta"]["preview_bytes"] == len(b"third\n")


def test_artifact_route_serves_file_backed_markdown_watch(
    tmp_path,
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)

    p = tmp_path / "README.md"
    p.write_text("# Hello\n\nWorld", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="readme",
                section="docs",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    r = client.get("/artifact?view=docs:readme")

    assert r.status_code == 200
    data = r.json()

    assert data["view_id"] == "docs:readme"
    assert data["kind"] == "markdown"
    assert "Hello" in data["html"]
    assert data["meta"]["file_backed"] is True
    assert data["meta"]["file_kind"] == "markdown"


def test_artifact_route_file_backed_missing_file_returns_visible_watch_error(
    tmp_path,
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)

    p = tmp_path / "missing.log"

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="missing",
                section="logs",
                read_mode="tail",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    r = client.get("/artifact?view=logs:missing")

    assert r.status_code == 200
    data = r.json()

    assert data["kind"] == "watch_error"
    assert data["status_code"] == 404
    assert data["meta"]["error"] is True
    assert data["meta"]["file_backed"] is True
    assert "file-backed artifact read failed" in data["html"]
    assert "FileNotFoundError" in data["html"]
    assert str(p.resolve()) in data["html"]

    status = store.get_status(view_id="logs:missing")
    assert status["last_error"]


def test_artifact_route_file_backed_csv_does_not_render_as_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)

    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    r = client.get("/artifact?view=watch:data")

    assert r.status_code == 404
    assert "No artifact has been published yet" in r.json()["detail"]


def test_file_backed_artifact_error_is_not_truncated(
    tmp_path,
    monkeypatch,
) -> None:
    store.reset()
    client = TestClient(app)

    p = tmp_path / "missing.log"

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    monkeypatch.setattr(
        config,
        "get_truncation_max_chars",
        lambda kind, view_id=None: 20,
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="missing",
                section="logs",
                read_mode="tail",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    r = client.get("/artifact?view=logs:missing")

    assert r.status_code == 200
    data = r.json()

    assert data["kind"] == "watch_error"
    assert data["truncation"]["truncated"] is False
    assert "Config keys to check" in data["html"]
    assert "limits.watched_files.max_mb" in data["html"]
