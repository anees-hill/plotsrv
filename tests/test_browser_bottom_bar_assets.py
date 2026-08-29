from __future__ import annotations

from pathlib import Path

import pytest

import plotsrv.html as html_mod
from plotsrv.ui_config import UISettings

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def _ui(**overrides: object) -> UISettings:
    values: dict[str, object] = {
        "logo_url": "/static/x.png",
        "header_text": "",
        "header_fill_colour": "#fff",
        "terminate_process_option": True,
        "auto_refresh_option": True,
        "export_image": True,
        "export_table": True,
        "show_history_controls": True,
        "show_history_banner": True,
        "show_freshness": True,
        "show_statusline": True,
        "show_help_note": True,
        "show_view_selector": True,
        "assets_dir": None,
        "page_title": "test",
        "favicon_url": "/static/x.png",
    }
    values.update(overrides)
    return UISettings(**values)  # type: ignore[arg-type]


def _render(
    kind: html_mod.ViewKind,
    *,
    table_mode: str = "rich",
    ui: UISettings | None = None,
) -> str:
    return html_mod.render_index(
        kind=kind,
        table_view_mode=table_mode,  # type: ignore[arg-type]
        table_html_simple=(
            "<table><tr><td>1</td></tr></table>" if table_mode == "simple" else None
        ),
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=ui or _ui(),
        views=[],
        active_view_id="demo:view",
    )


@pytest.mark.parametrize("kind", ["none", "plot", "table", "artifact", "stream"])
def test_every_renderer_uses_the_persistent_bottom_dock(
    kind: html_mod.ViewKind,
) -> None:
    rendered = _render(kind)

    assert 'class="ps-bottom-dock"' in rendered
    assert 'aria-label="View actions and status"' in rendered
    assert 'id="snapshots-control"' in rendered
    assert ">Snapshots<" in rendered
    assert 'id="status-error-wrap"' in rendered
    assert 'id="status"' in rendered
    assert ">Refresh<" not in rendered
    assert "Auto-refresh" not in rendered
    assert "Terminate plotsrv server" in rendered
    assert ">Stop server<" in rendered


def test_rich_table_export_scopes_are_filtered_view_and_complete_publish() -> None:
    rendered = _render("table")

    assert 'aria-haspopup="menu"' in rendered
    assert 'data-export-scope="filtered"' in rendered
    assert "Current filtered view" in rendered
    assert 'data-export-scope="complete"' in rendered
    assert "Complete published table" in rendered
    assert 'data-export-scope="retained"' not in rendered


def test_stream_export_scopes_name_only_the_bounded_retained_window() -> None:
    rendered = _render("stream")

    assert 'data-export-scope="filtered"' in rendered
    assert 'data-export-scope="retained"' in rendered
    assert "Retained raw window" in rendered
    assert "whole dataset" not in rendered.lower()
    assert "all stream data" not in rendered.lower()
    assert 'data-export-scope="complete"' not in rendered


@pytest.mark.parametrize(
    ("kind", "action"),
    [("plot", "plot"), ("artifact", "artifact")],
)
def test_single_scope_renderers_use_a_plain_export_action(
    kind: html_mod.ViewKind, action: str
) -> None:
    rendered = _render(kind)

    assert f'data-export-action="{action}"' in rendered
    assert 'id="export-menu"' not in rendered


def test_simple_table_has_one_complete_export_action() -> None:
    rendered = _render("table", table_mode="simple")

    assert 'data-export-action="table-complete"' in rendered
    assert 'id="export-menu"' not in rendered


def test_empty_view_keeps_export_visible_but_disabled() -> None:
    rendered = _render("none")

    assert 'data-export-action="none" disabled' in rendered
    assert "Nothing is available to export yet." in rendered


def test_ui_options_can_hide_exports_snapshots_and_termination() -> None:
    rendered = _render(
        "plot",
        ui=_ui(
            export_image=False,
            show_history_controls=False,
            terminate_process_option=False,
        ),
    )

    assert 'id="export-control"' not in rendered
    assert 'id="snapshots-control"' not in rendered
    assert ">Stop server<" not in rendered
    assert 'class="ps-bottom-dock"' in rendered


def test_history_client_uses_explicit_capability_and_preserves_snapshot_urls() -> None:
    source = (STATIC / "js" / "core" / "history.js").read_text(encoding="utf-8")

    assert "data.capability" in source
    assert "capability.enabled === true" in source
    assert "No snapshots yet" in source
    assert "Snapshot availability could not be loaded." in source
    assert 'url.searchParams.set("snapshot", snapshotId)' in source
    assert 'url.searchParams.delete("snapshot")' in source
    assert "core.reloadCurrentView()" in source
    assert "Live (latest)" in source


def test_export_client_keeps_filtered_complete_and_retained_meanings_distinct() -> None:
    table_source = (STATIC / "js" / "renderers" / "table.js").read_text(
        encoding="utf-8"
    )
    bar_source = (STATIC / "js" / "core" / "bottom_bar.js").read_text(encoding="utf-8")

    assert 'scope === "filtered"' in table_source
    assert 'scope === "complete"' in table_source
    assert 'scope === "retained"' in table_source
    assert 'state.tabulatorInstance.getData("active")' in table_source
    assert "state.tableRows" in table_source
    assert '"/table/export?view="' in table_source
    assert "Complete source CSV file" in bar_source
    complete_export = table_source.split("function exportCompletePublishedTable()", 1)[
        1
    ].split("function exportTable(scope)", 1)[0]
    assert "exportFilteredRichTable" not in complete_export


def test_artifact_export_handles_source_files_images_and_displayed_text() -> None:
    source = (STATIC / "js" / "renderers" / "artifact.js").read_text(encoding="utf-8")

    assert "plotsrvSourceDownloadUrl" in source
    assert 'img[src^="data:image/"]' in source
    assert "exportEmbeddedImage(root, base, stamp)" in source
    assert ".plotsrv-html-iframe" in source
    assert "getIframeExportHtml(root)" in source
    assert 'iframe.getAttribute("srcdoc")' in source
    assert 'stamp + ".html"' in source
    assert "if (!text) return false" in source


def test_dock_is_fixed_and_pages_reserve_mobile_and_desktop_space() -> None:
    controls = (STATIC / "css" / "controls.css").read_text(encoding="utf-8")
    layout = (STATIC / "css" / "layout.css").read_text(encoding="utf-8")
    bar_source = (STATIC / "js" / "core" / "bottom_bar.js").read_text(encoding="utf-8")

    assert ".ps-bottom-dock" in controls
    assert "position: fixed" in controls
    assert "env(safe-area-inset-bottom)" in controls
    assert "var(--ps-bottom-dock-height" in layout
    assert "window.ResizeObserver" in bar_source
    assert 'style.setProperty("--ps-bottom-dock-height"' in bar_source
