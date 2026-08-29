# tests/test_html.py
from __future__ import annotations

from dataclasses import replace

import pytest

from plotsrv.ui_config import FeaturedView, UISettings
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
        show_history_controls=True,
        show_history_banner=True,
        show_freshness=True,
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
        show_history_controls=True,
        show_history_banner=True,
        show_freshness=True,
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


def test_render_index_escapes_view_labels_and_header_text() -> None:
    ui = UISettings(
        logo_url="javascript:alert(1)",
        header_text="<script>alert(1)</script>",
        header_fill_colour="#fff",
        terminate_process_option=True,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_history_controls=True,
        show_history_banner=True,
        show_freshness=True,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="<b>bad</b>",
        favicon_url="javascript:alert(1)",
    )

    views = [
        ViewMeta(
            view_id='bad:view" onclick="alert(1)',
            kind="none",
            label="<b>bad</b>",
            section="<script>sec</script>",
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
        active_view_id='bad:view" onclick="alert(1)',
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;bad&lt;/b&gt;" in html
    assert "javascript:alert(1)" not in html
    assert 'onclick="alert(1)' not in html
    assert "&quot; onclick=&quot;alert(1)" in html


def test_render_index_empty_state_mentions_python_outputs_and_watched_files() -> None:
    ui = UISettings(
        logo_url="/static/x.png",
        header_text="",
        header_fill_colour="#fff",
        terminate_process_option=False,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_history_controls=True,
        show_history_banner=True,
        show_freshness=True,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="test",
        favicon_url="/static/x.png",
    )

    html = html_mod.render_index(
        kind="none",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=[],
        active_view_id="default",
    )

    assert "Waiting for content" in html
    assert "plotsrv is running" in html
    assert "Python outputs" in html
    assert "watched file updates" in html


@pytest.mark.parametrize("kind", ["none", "plot", "table", "artifact", "stream"])
def test_render_index_uses_shared_accessible_header_status_for_every_view_kind(
    kind: str,
) -> None:
    ui = UISettings(
        logo_url="/static/x.png",
        header_text="",
        header_fill_colour="#fff",
        terminate_process_option=False,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_history_controls=True,
        show_history_banner=True,
        show_freshness=True,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="test",
        favicon_url="/static/x.png",
    )

    rendered = html_mod.render_index(
        kind=kind,  # type: ignore[arg-type]
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=[
            ViewMeta(
                view_id="default:example",
                kind="artifact",
                label="example",
                section="default",
            )
        ],
        active_view_id="default",
    )

    assert rendered.count('id="header-status-button"') == 1
    assert 'aria-haspopup="dialog"' in rendered
    assert 'aria-controls="status-modal"' in rendered
    assert 'id="status-modal"' in rendered
    assert 'role="dialog"' in rendered
    assert 'aria-modal="true"' in rendered
    assert 'id="status-modal-return-latest"' in rendered
    assert "header-history" not in rendered
    assert "header-freshness-dot" not in rendered
    header_right = rendered.split(
        '<div class="header-right ps-header__right">', 1
    )[1].split("</header>", 1)[0]
    assert header_right.index('id="header-status"') < header_right.index(
        'data-plotsrv-viewselect="1"'
    )


def test_header_status_settings_are_independent_from_bottom_file_indicator() -> None:
    ui = UISettings(
        logo_url="/static/x.png",
        header_text="",
        header_fill_colour="#fff",
        terminate_process_option=False,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_history_controls=True,
        show_history_banner=False,
        show_freshness=False,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="test",
        favicon_url="/static/x.png",
    )

    rendered = html_mod.render_index(
        kind="none",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=[],
        active_view_id="default",
    )

    assert 'id="header-status-button"' not in rendered
    assert 'class="ps-bottom-bar__meta"' not in rendered
    assert 'id="status-updated"' not in rendered
    assert 'id="status-file-backed"' in rendered
    assert '"show_header_freshness": false' in rendered
    assert '"show_header_history": false' in rendered

    without_lower_status = html_mod.render_index(
        kind="none",
        table_view_mode="simple",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=replace(
            ui,
            show_freshness=True,
            show_history_banner=True,
            show_statusline=False,
        ),
        views=[],
        active_view_id="default",
    )

    assert 'id="header-status-button"' in without_lower_status
    assert 'id="status-file-backed"' not in without_lower_status


def test_view_browser_renders_grouped_and_az_modes_without_empty_featured_tab() -> None:
    ui = UISettings(
        page_title="test",
        favicon_url="/static/x.png",
        logo_url="/static/x.png",
        header_text="",
        header_fill_colour="#fff",
        show_view_selector=True,
        terminate_process_option=False,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_history_controls=True,
        show_history_banner=True,
        show_freshness=True,
        show_statusline=True,
        show_help_note=True,
    )
    views = [
        ViewMeta(
            view_id="reports:daily",
            kind="table",
            label="Daily report",
            section="Reports",
            icon_key="table",
        ),
        ViewMeta(
            view_id="ops:health",
            kind="plot",
            label="Health",
            section="Operations",
            icon_key="plot",
        ),
    ]

    rendered = html_mod.render_index(
        kind="table",
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=views,
        active_view_id="reports:daily",
    )

    assert 'class="ps-viewselect__search"' in rendered
    assert 'data-view-mode="grouped"' in rendered
    assert 'data-view-mode="az"' in rendered
    assert 'data-view-mode="featured"' not in rendered
    assert rendered.index(">Reports</h3>") < rendered.index(">Operations</h3>")
    assert 'data-plotsrv-view="reports:daily"' in rendered
    assert 'aria-selected="true" aria-current="page"' in rendered
    assert 'role="dialog" aria-label="Browse views"' in rendered


def test_view_browser_puts_featured_at_top_of_grouped_and_escapes_copy() -> None:
    ui = UISettings(
        page_title="test",
        favicon_url="/static/x.png",
        logo_url="/static/x.png",
        header_text="",
        header_fill_colour="#fff",
        show_view_selector=True,
        terminate_process_option=False,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_history_controls=True,
        show_history_banner=True,
        show_freshness=True,
        show_statusline=True,
        show_help_note=True,
        featured_views=(
            FeaturedView(
                view_id="reports:daily",
                title="Daily <overview>",
                caption="Safe </script><b>caption</b>",
            ),
            FeaturedView(view_id="missing:view", title="Missing"),
        ),
    )
    views = [
        ViewMeta(
            view_id="reports:daily",
            kind="table",
            label="Daily report",
            section="Reports",
            icon_key="table",
        ),
        ViewMeta(
            view_id="ops:health",
            kind="plot",
            label="Health",
            section="Operations",
            icon_key="plot",
        ),
    ]

    rendered = html_mod.render_index(
        kind="table",
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui,
        views=views,
        active_view_id="reports:daily",
    )

    assert 'data-view-mode="featured"' not in rendered
    assert 'data-view-mode="grouped"' in rendered
    assert ">Featured</h3>" in rendered
    assert 'class="ps-viewselect__feature-fallback"' in rendered
    assert rendered.index(">Featured</h3>") < rendered.index(">Operations</h3>")
    assert rendered.count('data-plotsrv-view="reports:daily"') == 1
    assert "Daily &lt;overview&gt;" in rendered
    assert "Safe &lt;/script&gt;&lt;b&gt;caption&lt;/b&gt;" in rendered
    assert "Missing</span>" not in rendered
    assert "</script><b>caption</b>" not in rendered
    assert r"Safe \u003c/script\u003e\u003cb\u003ecaption\u003c/b\u003e" in rendered
