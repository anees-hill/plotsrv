# tests/test_html.py
from __future__ import annotations

from plotsrv.ui_config import UISettings
from plotsrv.store import ViewMeta
import plotsrv.html as html_mod


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

    # New custom selector exists
    assert 'data-plotsrv-viewselect="1"' in html
    assert 'class="ps-viewselect__btn"' in html
    assert 'role="listbox"' in html

    # Both items present
    assert 'data-plotsrv-view="etl-1:import"' in html
    assert 'data-plotsrv-view="etl-1:metrics"' in html

    # Selected state present for active view
    assert (
        'data-plotsrv-view="etl-1:metrics"' in html and 'aria-selected="true"' in html
    )


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

    # Title + favicon still rendered
    assert "<title>plotsrv - live view</title>" in html
    assert 'rel="icon" href="/static/plotsrv_favicon.png"' in html

    # New custom selector exists
    assert 'data-plotsrv-viewselect="1"' in html
    assert 'data-plotsrv-view="etl-1:metrics"' in html
