from __future__ import annotations

import time

import matplotlib.pyplot as plt
import pandas as pd
import pytest
import requests
import seaborn as sns

from plotsrv import (
    start_server,
    stop_server,
    refresh_view,
    set_table_view_mode,
)


def _wait_for_status_ok(url: str, timeout: float = 10.0) -> None:
    """
    Poll the given URL until it responds (200/404) or we hit timeout.
    This avoids race conditions on uvicorn startup in CI.
    """
    start = time.time()
    while True:
        try:
            resp = requests.get(url, timeout=0.5)
            if resp.status_code in (200, 404):
                return
        except Exception:
            pass

        if time.time() - start > timeout:
            raise TimeoutError(f"Server did not respond in {timeout} seconds")
        time.sleep(0.1)


@pytest.mark.integration
def test_plots_and_tables_served_end_to_end() -> None:
    port = 8765
    base_url = f"http://127.0.0.1:{port}"
    plot_url = f"{base_url}/plot"
    index_url = f"{base_url}/"
    table_url = f"{base_url}/table/data"

    plotnine = pytest.importorskip("plotnine")
    ggplot = plotnine.ggplot
    aes = plotnine.aes
    geom_point = plotnine.geom_point

    df = pd.DataFrame(
        {
            "age": [10, 20, 30, 40, 50],
            "fare": [5.0, 10.5, 3.2, 7.7, 12.0],
        }
    )

    try:
        # Start server once
        start_server(host="127.0.0.1", port=port, auto_on_show=False, quiet=True)
        _wait_for_status_ok(index_url)

        # --- PART 1: matplotlib / seaborn plot ---
        sns.scatterplot(data=df, x="age", y="fare")
        plt.title("CI test scatterplot")

        refresh_view()  # use current figure

        resp = requests.get(plot_url, timeout=3.0)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")
        assert len(resp.content) > 100

        # --- PART 2: plotnine plot ---
        p = ggplot(df, aes("age", "fare")) + geom_point()
        refresh_view(p)

        resp2 = requests.get(plot_url, timeout=3.0)
        assert resp2.status_code == 200
        assert resp2.headers["content-type"].startswith("image/")
        assert len(resp2.content) > 100

        # --- PART 3: simple table mode ---
        set_table_view_mode("simple")
        refresh_view(df)

        html = requests.get(index_url, timeout=3.0).text
        assert "<table" in html
        assert "age" in html and "fare" in html

        # --- PART 4: rich table mode ---
        set_table_view_mode("rich")
        refresh_view(df)

        html_rich = requests.get(index_url, timeout=3.0).text
        assert 'id="table-grid"' in html_rich

        json_rich = requests.get(table_url, timeout=3.0).json()
        assert json_rich["columns"] == ["age", "fare"]
        assert json_rich["total_rows"] == len(df)

    finally:
        stop_server(join=True)
