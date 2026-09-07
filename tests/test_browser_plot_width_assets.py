from __future__ import annotations

from pathlib import Path

from plotsrv.html import render_index


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def _render_plot_page() -> str:
    return render_index(
        kind="plot",
        active_view_id="plots:dashboard",
        views=[],
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=100,
        max_table_rows_rich=100,
    )


def test_plot_page_uses_the_available_width_without_changing_table_layout() -> None:
    css = (STATIC / "css" / "layout.css").read_text("utf-8")

    generic_page = css.split(".page {", 1)[1].split("}", 1)[0]
    plot_page = css.split('body[data-kind="plot"] .page {', 1)[1].split(
        "}", 1
    )[0]
    table_page = css.split('body[data-kind="table"] .page {', 1)[1].split(
        "}", 1
    )[0]

    assert "max-width: 1240px" in generic_page
    assert "max-width: none" in plot_page
    assert "max-width: none" in table_page


def test_plot_surface_and_raster_preserve_responsive_aspect_ratio() -> None:
    plot_css = (STATIC / "css" / "renderers" / "plot.css").read_text("utf-8")
    page = _render_plot_page()

    frame = plot_css.split(".plot-frame--plot {", 1)[1].split("}", 1)[0]
    image = plot_css.split("#plot,", 1)[1].split("}", 1)[0]

    assert "box-sizing: border-box" in frame
    assert "width: 100%" in frame
    assert "min-width: 0" in frame
    assert "max-width: 100%" in image
    assert "height: auto" in image
    assert "\n  width: 100%" not in image
    assert 'data-kind="plot"' in page
    assert 'class="plot-frame ps-frame ps-frame--plot plot-frame--plot"' in page
    assert 'class="ps-plot"' in page


def test_supported_plot_backends_share_the_static_png_path() -> None:
    publisher = (ROOT / "src" / "plotsrv" / "publisher.py").read_text("utf-8")
    backend = (ROOT / "src" / "plotsrv" / "backends.py").read_text("utf-8")
    app = (ROOT / "src" / "plotsrv" / "app.py").read_text("utf-8")

    assert "PlotnineGGPlot" in publisher
    assert "fig_to_png_bytes(fig)" in publisher
    assert '"format": "png"' in backend
    assert 'media_type="image/png"' in app
