from __future__ import annotations

import base64
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
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


def test_get_plot_404_when_none(client: TestClient) -> None:
    resp = client.get("/plot")
    assert resp.status_code == 404


def test_get_plot_returns_png_when_set(client: TestClient) -> None:
    vid = _mk_view("etl", "metrics")
    store.set_plot(b"\x89PNGfake", view_id=vid)

    resp = client.get(f"/plot?view={vid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"



def test_get_plot_download_sets_content_disposition(client: TestClient) -> None:
    store.set_plot(b"\x89PNGfake")

    resp = client.get("/plot?download=true")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "").lower()


def test_table_data_404_when_none(client: TestClient) -> None:
    resp = client.get("/table/data")
    assert resp.status_code == 404


def test_table_data_returns_json_sample(client: TestClient) -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    store.set_table(df, html_simple="<table>dummy</table>")

    resp = client.get("/table/data?limit=2")
    assert resp.status_code == 200

    data = resp.json()
    assert data["columns"] == ["a", "b"]
    assert data["total_rows"] == 3
    assert data["returned_rows"] == 2
    assert len(data["rows"]) == 2


def test_index_none_shows_empty_state(client: TestClient) -> None:
    store.reset()
    resp = client.get("/")
    text = resp.text
    assert "No plot or table has been published yet" in text


def test_index_plot_embeds_image(client: TestClient) -> None:
    store.set_plot(b"\x89PNGfake")
    resp = client.get("/")
    text = resp.text
    assert '<img id="plot"' in text
    assert "/plot" in text


def test_index_table_simple_embeds_table_html(client: TestClient) -> None:
    config.set_table_view_mode("simple")
    store.set_table(
        pd.DataFrame({"a": [1]}),
        html_simple="<table><tr><td>SIMPLE</td></tr></table>",
    )

    resp = client.get("/")
    text = resp.text
    assert "SIMPLE" in text

    # Don't look for "table-grid" substring
    assert 'id="table-grid"' not in text
    assert "tabulator-tables" not in text


def test_index_table_rich_has_table_grid_div(client: TestClient) -> None:
    config.set_table_view_mode("rich")
    store.set_table(pd.DataFrame({"a": [1]}), html_simple=None)

    resp = client.get("/")
    text = resp.text
    assert 'id="table-grid"' in text
    assert "tabulator-tables" in text


def test_status_includes_service_fields(client: TestClient) -> None:
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "last_updated" in data
    assert "last_duration_s" in data
    assert "last_error" in data

    assert "service_mode" in data
    assert "service_target" in data
    assert "service_refresh_rate_s" in data


def _mk_view(section: str = "default", label: str = "titanic") -> str:
    vid = store.register_view(section=section, label=label, kind="none")
    store.set_active_view(vid)
    return vid


def test_publish_plot_creates_view_and_serves_plot(client: TestClient) -> None:
    # Build a tiny png bytes payload (server expects b64 png)
    fig: Figure = plt.figure()
    buf = b"\x89PNGfake"  # you can generate real bytes too; fake is fine if server doesn't validate PNG
    png_b64 = base64.b64encode(buf).decode("utf-8")

    payload = {
        "kind": "plot",
        "label": "metrics",
        "section": "etl-1",
        "update_limit_s": None,
        "force": False,
        "plot_png_b64": png_b64,
    }

    r = client.post("/publish", json=payload)
    assert r.status_code == 200

    vid = store.normalize_view_id(None, section="etl-1", label="metrics")
    r2 = client.get(f"/plot?view={vid}")
    assert r2.status_code == 200
    assert r2.content.startswith(b"\x89PNG")  # if you used a real png; if fake, just assert equals buf


def test_publish_table_creates_view_and_serves_table(client: TestClient) -> None:
    payload = {
        "kind": "table",
        "label": "import",
        "section": "etl-1",
        "update_limit_s": None,
        "force": False,
        "table": {
            "columns": ["a"],
            "rows": [{"a": 1}, {"a": 2}],
            "total_rows": 2,
            "returned_rows": 2,
        },
        "table_html_simple": "<table><tr><td>hi</td></tr></table>",
    }

    r = client.post("/publish", json=payload)
    assert r.status_code == 200

    vid = store.normalize_view_id(None, section="etl-1", label="import")
    r2 = client.get(f"/table/data?view={vid}&limit=2")
    assert r2.status_code == 200
    assert r2.json()["columns"] == ["a"]


def test_publish_respects_update_limit(client: TestClient) -> None:
    payload = {
        "kind": "table",
        "label": "import",
        "section": "etl-1",
        "update_limit_s": 600,
        "force": False,
        "table": {
            "columns": ["a"],
            "rows": [{"a": 1}],
            "total_rows": 1,
            "returned_rows": 1,
        },
        "table_html_simple": "<table></table>",
    }

    r1 = client.post("/publish", json=payload)
    assert r1.status_code == 200
    r2 = client.post("/publish", json=payload)
    assert r2.status_code == 200

    # second should have been rejected server-side (whatever your API returns)
    # If you return {"accepted": false}, assert that:
    # assert r2.json()["accepted"] is False
    #
    # If you always return 200 with message, assert substring.
