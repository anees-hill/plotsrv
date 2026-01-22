from __future__ import annotations

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
    store.set_plot(b"\x89PNGfake")  # looks like PNG header

    resp = client.get("/plot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")


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
