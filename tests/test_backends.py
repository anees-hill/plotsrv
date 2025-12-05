from __future__ import annotations

import pandas as pd
from matplotlib.figure import Figure

from plotsrv.backends import fig_to_png_bytes, df_to_html_simple, df_to_rich_sample


def test_fig_to_png_bytes_returns_png_bytes() -> None:
    fig = Figure()
    ax = fig.add_subplot(111)
    ax.plot([1, 2, 3], [4, 5, 6])

    data = fig_to_png_bytes(fig)

    assert isinstance(data, bytes)
    assert len(data) > 0
    # PNG magic header
    assert data.startswith(b"\x89PNG")


def test_df_to_html_simple_honours_max_rows() -> None:
    df = pd.DataFrame({"x": list(range(10))})
    html = df_to_html_simple(df, max_rows=3)

    assert "<table" in html
    assert html.count("<tr") >= 3  # header + 3 rows
    # row with value "3" should not appear (0,1,2 only)
    assert ">3<" not in html


def test_df_to_rich_sample_structure_and_limits() -> None:
    df = pd.DataFrame({"x": list(range(10)), "y": list(range(10, 20))})

    sample = df_to_rich_sample(df, max_rows=4)

    assert sample["columns"] == ["x", "y"]
    assert len(sample["rows"]) == 4
    assert sample["total_rows"] == 10
    assert sample["returned_rows"] == 4

    first_row = sample["rows"][0]
    assert first_row == {"x": 0, "y": 10}
