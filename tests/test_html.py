from __future__ import annotations

import json

from plotsrv import html as html_mod
from plotsrv.config import TableViewMode
from plotsrv.store import ViewMeta
from plotsrv.ui_config import UISettings


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
    assert '<script src="/static/plotsrv.js" defer></script>' in html
    assert "window.PLOTSRV_CONFIG" in html
    assert '"active_view_id"' in html
    assert '"max_table_rows_rich"' in html


def test_render_index_plot_has_refresh_js() -> None:
    html = html_mod.render_index(
        kind="plot",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )
    assert '<script src="/static/plotsrv.js" defer></script>' in html
    assert '<img id="plot"' in html
    assert 'onclick="refreshPlot()"' in html
    assert "window.PLOTSRV_CONFIG" in html


def test_render_index_includes_view_dropdown_and_selected_option_basic() -> None:
    ui = UISettings(
        logo_url="/static/x.png",
        header_text="t",
        header_fill_colour="#fff",
        terminate_process_option=True,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="test",
        favicon_url="/static/x.png",
    )

    views = [
        ViewMeta(view_id="etl-1:import", kind="none", label="import", section="etl-1"),
        ViewMeta(
            view_id="etl-1:metrics", kind="none", label="metrics", section="etl-1"
        ),
    ]

    html = html_mod.render_index(
        kind="plot",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=views,
        active_view_id="etl-1:metrics",
    )

    assert 'id="view-select"' in html
    assert 'option value="etl-1:metrics" selected' in html
    assert "/plot?view=etl-1:metrics" in html
    assert '<script src="/static/plotsrv.js" defer></script>' in html


def test_render_index_includes_view_dropdown_and_selected_option_with_title_and_favicon() -> (
    None
):
    ui = UISettings(
        logo_url="/static/x.png",
        header_text="t",
        header_fill_colour="#fff",
        terminate_process_option=True,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        # If you added these fields to UISettings, keep them.
        # If you didn't, remove them and the render_index defaults will apply.
        page_title="plotsrv - live view",
        favicon_url="/static/plotsrv_favicon.png",
    )

    views = [
        ViewMeta(view_id="etl-1:import", kind="none", label="import", section="etl-1"),
        ViewMeta(
            view_id="etl-1:metrics", kind="none", label="metrics", section="etl-1"
        ),
    ]

    html = html_mod.render_index(
        kind="plot",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=views,
        active_view_id="etl-1:metrics",
    )

    assert 'id="view-select"' in html
    assert 'option value="etl-1:metrics" selected' in html
    assert "/plot?view=etl-1:metrics" in html
    assert "<title>plotsrv - live view</title>" in html
    assert '<link rel="icon" href="/static/plotsrv_favicon.png">' in html


def test_render_index_includes_default_title_and_favicon() -> None:
    """
    G2: HTML head should include default title + favicon.
    Use explicit UISettings to avoid dependence on local plotsrv.ini / cache.
    """
    ui = UISettings(
        page_title="plotsrv - live view",
        favicon_url="/static/plotsrv_favicon.png",
        logo_url="/static/plotsrv_logo.jpg",
        header_text="live viewer",
        header_fill_colour="#ffffff",
        show_view_selector=True,
        terminate_process_option=True,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_statusline=True,
        show_help_note=True,
        assets_dir=None,
    )

    html = html_mod.render_index(
        kind="none",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
    )

    assert "<title>plotsrv - live view</title>" in html
    assert '<link rel="icon" href="/static/plotsrv_favicon.png">' in html


def test_render_index_allows_custom_title_and_favicon() -> None:
    """
    G2: Custom title/favicon via UISettings should appear in head.
    """
    ui = UISettings(
        logo_url="/static/x.png",
        header_text="t",
        header_fill_colour="#fff",
        terminate_process_option=True,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="My Custom Page",
        favicon_url="/assets/my.ico",
    )

    html = html_mod.render_index(
        kind="plot",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=[],
        active_view_id="default",
    )

    assert "<title>My Custom Page</title>" in html
    assert '<link rel="icon" href="/assets/my.ico">' in html


def test_render_index_includes_auto_refresh_persistence_hooks() -> None:
    """
    F3: Auto-refresh should persist across navigation (localStorage save/restore).
    We don't test JS execution, only that the HTML includes required hooks.
    """
    ui = UISettings(
        logo_url="/static/x.png",
        header_text="t",
        header_fill_colour="#fff",
        terminate_process_option=True,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="plotsrv - live view",
        favicon_url="/static/plotsrv_favicon.png",
    )

    html = html_mod.render_index(
        kind="plot",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=[],
        active_view_id="default",
    )

    # Persisted auto-refresh logic is in /static/plotsrv.js now.
    # Here we only assert HTML contains the required controls & script include.
    assert '<script src="/static/plotsrv.js" defer></script>' in html
    assert 'id="auto-refresh-toggle"' in html
    assert 'id="auto-refresh-interval"' in html
    assert "window.PLOTSRV_CONFIG" in html


def _extract_cfg(html: str) -> dict:
    marker = "window.PLOTSRV_CONFIG = "
    i = html.find(marker)
    assert i != -1
    j = html.find(";", i)
    assert j != -1
    raw = html[i + len(marker) : j].strip()
    return json.loads(raw)

    cfg = _extract_cfg(html)
    assert cfg["active_view_id"] == "etl-1:metrics"
    assert cfg["max_table_rows_rich"] == 1000
