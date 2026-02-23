from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from plotsrv.app import app
from plotsrv import store, config


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
