# tests/test_app_more.py
from __future__ import annotations

import base64
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv.app import app
from plotsrv import store, config


@pytest.fixture(autouse=True)
def reset_state() -> None:
    store.reset()
    config.set_table_view_mode("simple")
    yield
    store.reset()
    config.set_table_view_mode("simple")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_views_returns_registered_views(client: TestClient) -> None:
    vid = store.register_view(section="etl", label="metrics", kind="none")
    store.set_active_view(vid)

    resp = client.get("/views")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(v["view_id"] == vid for v in data)


def test_table_export_400_for_non_csv(client: TestClient) -> None:
    store.set_table(pd.DataFrame({"a": [1, 2]}), html_simple="<table/>")
    r = client.get("/table/export?format=xlsx")
    assert r.status_code == 400
    assert "Only format=csv" in r.text


def test_table_export_csv_returns_attachment(client: TestClient) -> None:
    store.set_table(pd.DataFrame({"a": [1, 2]}), html_simple="<table/>")
    r = client.get("/table/export?format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd.lower()
    assert "plotsrv_table.csv" in cd


def test_artifact_404_when_none(client: TestClient) -> None:
    r = client.get("/artifact")
    assert r.status_code == 404


def test_publish_artifact_then_artifact_endpoint_renders(client: TestClient) -> None:
    payload = {
        "kind": "artifact",
        "section": "ops",
        "label": "log",
        "artifact_kind": "text",
        "artifact": "hello <b>world</b>",
        "force": True,
    }
    r = client.post("/publish", json=payload)
    assert r.status_code == 200

    vid = store.normalize_view_id(None, section="ops", label="log")
    r2 = client.get(f"/artifact?view={vid}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["view_id"] == vid
    # Should render as text (not html) by default renderer ordering
    assert data["kind"] == "text"
    assert "<pre" in data["html"]
    assert "&lt;b&gt;" in data["html"]


def test_publish_rejects_unknown_kind(client: TestClient) -> None:
    r = client.post("/publish", json={"kind": "nope"})
    assert r.status_code == 422
    assert "kind must be" in r.text


def test_publish_plot_requires_plot_png_b64(client: TestClient) -> None:
    r = client.post("/publish", json={"kind": "plot", "label": "x", "section": "s"})
    assert r.status_code == 422
    assert "plot_png_b64 is required" in r.text


def test_publish_plot_rejects_bad_base64(client: TestClient) -> None:
    r = client.post(
        "/publish",
        json={
            "kind": "plot",
            "label": "x",
            "section": "s",
            "plot_png_b64": "!!!notb64!!!",
        },
    )
    assert r.status_code == 422
    assert "not valid base64" in r.text


def test_publish_table_requires_table_dict(client: TestClient) -> None:
    r = client.post("/publish", json={"kind": "table", "label": "x", "section": "s"})
    assert r.status_code == 422
    assert "table dict is required" in r.text


def test_publish_table_requires_columns_and_rows_lists(client: TestClient) -> None:
    r = client.post(
        "/publish",
        json={
            "kind": "table",
            "label": "x",
            "section": "s",
            "table": {"columns": "nope", "rows": {}},
        },
    )
    assert r.status_code == 422
    assert "columns(list) and rows(list)" in r.text


def test_table_data_falls_back_when_counts_missing(client: TestClient) -> None:
    # Store a table without counts; endpoint should fall back to len(df)/len(rows)
    vid = store.register_view(section="etl", label="import", kind="none")
    store.set_active_view(vid)

    df = pd.DataFrame({"a": [1, 2, 3]})
    store.set_table(
        df, html_simple="<table/>", view_id=vid, total_rows=None, returned_rows=None
    )

    r = client.get(f"/table/data?view={vid}&limit=2")
    assert r.status_code == 200
    data = r.json()
    assert data["total_rows"] == 3
    assert data["returned_rows"] == 2
