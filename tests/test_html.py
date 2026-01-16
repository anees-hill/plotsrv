from __future__ import annotations

from plotsrv import html as html_mod
from plotsrv.config import TableViewMode


def test_render_index_none_shows_empty_state() -> None:
    html = html_mod.render_index(
        kind="none",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )
    assert "No plot or table has been published yet" in html


def test_render_index_plot_has_img_tag_and_plot_src() -> None:
    html = html_mod.render_index(
        kind="plot",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )
    assert '<img id="plot"' in html
    assert "/plot" in html


def test_render_index_table_simple_embeds_html() -> None:
    table_html = "<table><tr><td>hi</td></tr></table>"
    html = html_mod.render_index(
        kind="table",
        table_view_mode="simple",
        table_html_simple=table_html,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )

    assert table_html in html

    # Don't assert on substring "table-grid" (it may appear in shared CSS/JS)
    assert 'id="table-grid"' not in html
    assert "tabulator-tables" not in html  # CDN should only be in rich mode


def test_render_index_table_rich_has_tabulator_div_and_scripts() -> None:
    html = html_mod.render_index(
        kind="table",
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )

    assert 'id="table-grid"' in html
    assert "tabulator-tables" in html
    assert "function loadTable" in html


def test_render_index_plot_has_refresh_js() -> None:
    html = html_mod.render_index(
        kind="plot",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )
    assert "function refreshPlot" in html
    assert "function refreshStatus" in html
