from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from plotsrv.app import app
from plotsrv import store, config
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


def test_artifact_route_file_backed_missing_file_returns_404(
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

    assert r.status_code == 404
    assert "Watched file not found" in r.json()["detail"]


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
