from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv.app import app
from plotsrv import config, store


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    store.reset()
    config.set_table_view_mode("simple")
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    monkeypatch.setattr(config, "get_status_local_only", lambda: False)
    monkeypatch.setattr(config, "get_history_local_only", lambda: False)
    monkeypatch.setattr(config, "get_views_local_only", lambda: False)
    yield
    store.reset()
    config.set_table_view_mode("simple")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _make_medium_df(rows: int = 1000, cols: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        {f"col_{j}": [f"value_{i}_{j}" for i in range(rows)] for j in range(cols)}
    )


def test_benchmark_status_route(client: TestClient, benchmark) -> None:
    resp = benchmark(lambda: client.get("/status"))
    assert resp.status_code == 200


def test_benchmark_views_route(client: TestClient, benchmark) -> None:
    for i in range(100):
        store.register_view(section="sec", label=f"label_{i}", kind="none")

    resp = benchmark(lambda: client.get("/views"))
    assert resp.status_code == 200


def test_benchmark_table_data_route(client: TestClient, benchmark) -> None:
    df = _make_medium_df(rows=1000, cols=12)
    store.set_table(df, html_simple="<table>dummy</table>")

    resp = benchmark(lambda: client.get("/table/data?limit=500"))
    assert resp.status_code == 200


def test_benchmark_artifact_route_json(client: TestClient, benchmark) -> None:
    payload = {
        "items": [
            {"id": i, "name": f"name_{i}", "values": list(range(10))}
            for i in range(400)
        ]
    }
    store.set_artifact(obj=payload, kind="json")

    resp = benchmark(lambda: client.get("/artifact"))
    assert resp.status_code == 200


def test_benchmark_artifact_route_markdown(client: TestClient, benchmark) -> None:
    payload = "\n".join(
        f"## Section {i}\n\nSome text here.\n\n- a\n- b\n- c" for i in range(250)
    )
    store.set_artifact(obj=payload, kind="markdown")

    resp = benchmark(lambda: client.get("/artifact"))
    assert resp.status_code == 200
