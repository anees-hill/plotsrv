# tests/test_plotsrv_integration.py

import time

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import pandas as pd
import pytest
import requests
import seaborn as sns
from typing import Any

from plotsrv.server import (
    start_plot_server,
    stop_plot_server,
    refresh_plot_server,
)

_ORIGINAL_SHOW = plt.show


def _patched_show(*args: Any, **kwargs: Any) -> None:
    """
    Replacement for plt.show that also updates the plot server
    from the current figure.

    On non-interactive backends like Agg, we skip the original
    show() call to avoid pointless warnings.
    """
    refresh_plot_server()

    backend = matplotlib.get_backend().lower()
    if "agg" not in backend:
        _ORIGINAL_SHOW(*args, **kwargs)


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
def test_plots_are_served_matplotlib_and_plotnine():
    port = 8765
    base_url = f"http://127.0.0.1:{port}"
    plot_url = f"{base_url}/plot"

    plotnine = pytest.importorskip("plotnine")
    ggplot = plotnine.ggplot
    aes = plotnine.aes
    geom_point = plotnine.geom_point

    dat = pd.DataFrame(
        {
            "age": [10, 20, 30, 40, 50],
            "fare": [5.0, 10.5, 3.2, 7.7, 12.0],
        }
    )

    try:
        # Start server once, but DO NOT patch plt.show for this test
        start_plot_server(port=port, auto_on_show=False)
        _wait_for_status_ok(plot_url)

        # --- PART 1: matplotlib / seaborn ---
        sns.scatterplot(data=dat, x="age", y="fare")
        plt.title("CI test scatterplot")

        # Instead of plt.show(), explicitly push the current figure
        refresh_plot_server()

        resp = requests.get(plot_url, timeout=3.0)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")
        assert len(resp.content) > 100

        # --- PART 2: plotnine ---
        p = ggplot(dat, aes("age", "fare")) + geom_point()
        refresh_plot_server(p)

        resp2 = requests.get(plot_url, timeout=3.0)
        assert resp2.status_code == 200
        assert resp2.headers["content-type"].startswith("image/")
        assert len(resp2.content) > 100

    finally:
        stop_plot_server()
