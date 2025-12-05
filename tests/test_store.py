from __future__ import annotations

import pandas as pd
import pytest

from plotsrv import store


@pytest.fixture(autouse=True)
def reset_store() -> None:
    # ensure clean state around each test
    store.reset()
    yield
    store.reset()


def test_set_plot_sets_kind_and_bytes() -> None:
    png = b"fake-bytes"
    store.set_plot(png)
    assert store.get_kind() == "plot"
    assert store.has_plot() is True
    assert store.get_plot() == png
    assert store.has_table() is False


def test_get_plot_raises_if_none() -> None:
    with pytest.raises(LookupError):
        store.get_plot()


def test_set_table_sets_kind_and_dataframe_and_html() -> None:
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    html = "<table>hi</table>"

    store.set_table(df, html)

    assert store.get_kind() == "table"
    assert store.has_table() is True
    assert store.has_plot() is False

    out_df = store.get_table_df()
    assert out_df.equals(df)

    assert store.get_table_html_simple() == html


def test_get_table_df_raises_if_none() -> None:
    with pytest.raises(LookupError):
        store.get_table_df()


def test_get_table_html_simple_raises_if_none() -> None:
    df = pd.DataFrame({"x": [1]})
    store.set_table(df, html_simple=None)

    with pytest.raises(LookupError):
        store.get_table_html_simple()


def test_reset_clears_all_state() -> None:
    df = pd.DataFrame({"x": [1]})
    store.set_plot(b"abc")
    store.set_table(df, "<table></table>")

    store.reset()
    assert store.get_kind() == "none"
    assert store.has_plot() is False
    assert store.has_table() is False
