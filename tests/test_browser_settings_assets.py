from __future__ import annotations

from pathlib import Path

import plotsrv.html as html_mod
from plotsrv.ui_config import UISettings


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"


def _ui(*, show_status: bool = True) -> UISettings:
    return UISettings(
        logo_url="/static/x.png",
        header_text="",
        header_fill_colour="#fff",
        terminate_process_option=True,
        auto_refresh_option=True,
        export_image=True,
        export_table=True,
        show_history_controls=True,
        show_history_banner=show_status,
        show_freshness=show_status,
        show_statusline=True,
        show_help_note=True,
        show_view_selector=True,
        assets_dir=None,
        page_title="test",
        favicon_url="/static/x.png",
    )


def _render(*, show_status: bool = True) -> str:
    return html_mod.render_index(
        kind="plot",
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
        ui_settings=_ui(show_status=show_status),
        views=[],
        active_view_id="demo:view",
    )


def test_settings_trigger_uses_supplied_icon_and_precedes_freshness() -> None:
    rendered = _render()
    header_right = rendered.split(
        '<div class="header-right ps-header__right">', 1
    )[1].split("</header>", 1)[0]

    assert 'id="settings-button"' in header_right
    assert 'src="/static/settings-cog.png"' in header_right
    assert 'aria-controls="settings-page"' in header_right
    assert header_right.index('id="settings-button"') < header_right.index(
        'id="header-status"'
    )
    assert (STATIC / "settings-cog.png").is_file()


def test_settings_remains_available_when_freshness_is_disabled() -> None:
    rendered = _render(show_status=False)

    assert 'id="settings-button"' in rendered
    assert 'id="settings-page"' in rendered
    assert 'id="header-status"' not in rendered


def test_settings_page_is_full_page_accessible_and_offers_three_modes() -> None:
    rendered = _render()

    assert 'id="settings-page"' in rendered
    assert 'role="dialog"' in rendered
    assert 'aria-modal="true"' in rendered
    assert 'aria-labelledby="settings-title"' in rendered
    assert 'aria-describedby="settings-intro"' in rendered
    assert 'data-theme-option="light"' in rendered
    assert 'data-theme-option="dark"' in rendered
    assert 'data-theme-option="system"' in rendered
    assert "Plot pixels," in rendered
    assert "embedded HTML reports keep their original colours" in rendered


def test_settings_page_shows_installed_version_and_documentation_link(
    monkeypatch,
) -> None:
    monkeypatch.setattr(html_mod, "_plotsrv_version", lambda: "9.8.7")
    rendered = _render()

    assert 'id="settings-about-title">About plotsrv</h2>' in rendered
    assert "<dt>Version</dt>" in rendered
    assert "<code>9.8.7</code>" in rendered
    assert 'href="https://docs.plotsrv.com/"' in rendered
    assert 'target="_blank" rel="noopener noreferrer"' in rendered
    assert "docs.plotsrv.com" in rendered


def test_theme_is_restored_before_the_stylesheet_to_avoid_a_colour_flash() -> None:
    rendered = _render()
    theme_bootstrap = rendered.index('localStorage.getItem("plotsrv:v1:theme")')
    stylesheet = rendered.index('<link rel="stylesheet"')

    assert theme_bootstrap < stylesheet
    assert 'setAttribute("data-theme", theme)' in rendered
    assert 'theme === "system" ? "light dark" : theme' in rendered


def test_theme_interaction_persists_locally_and_has_keyboard_dialog_behaviour() -> None:
    source = (STATIC / "js" / "core" / "settings.js").read_text(encoding="utf-8")
    storage = (STATIC / "js" / "core" / "storage.js").read_text(encoding="utf-8")
    app = (STATIC / "js" / "core" / "app.js").read_text(encoding="utf-8")

    assert 'theme: "plotsrv:v1:theme"' in storage
    assert 'const THEMES = ["light", "dark", "system"]' in source
    assert "core.savePref(core.storageKeys.theme, theme)" in source
    assert 'root.setAttribute("data-theme", theme)' in source
    assert 'event.key === "Escape"' in source
    assert 'event.key !== "Tab"' in source
    assert "focusableElements(page)" in source
    assert "returnFocus = document.activeElement" in source
    assert 'document.body.classList.add("ps-settings-open")' in source
    assert "core.bindSettings()" in app


def test_theme_css_covers_browser_chrome_and_readable_artifact_surfaces() -> None:
    source = (STATIC / "css" / "themes.css").read_text(encoding="utf-8")

    assert 'html[data-theme="light"]' in source
    assert 'html[data-theme="dark"]' in source
    assert 'html[data-theme="system"]' in source
    assert "@media (prefers-color-scheme: dark)" in source
    assert ".ps-settings-page" in source
    assert "min-height: 100dvh" in source
    assert ".ps-table--rich .tabulator-row" in source
    assert ".plotsrv-markdown--sanitized" in source
    assert ".plotsrv-pre" in source
    assert ".ps-code" in source
    assert ".ps-json-panel" in source
    assert ".ps-traceback__frame" in source


def test_dark_theme_overrides_snapshot_and_json_pinned_hover_surfaces() -> None:
    source = (STATIC / "css" / "themes.css").read_text(encoding="utf-8")

    shared_controls = source.split(".ps-btn,", 1)[1].split("{", 1)[0]
    assert ".ps-snapshots__selector," in shared_controls
    assert ".ps-snapshots__selector select," in shared_controls
    disabled_snapshot = source.split(
        ".ps-snapshots__selector select:disabled", 1
    )[1].split("}", 1)[0]
    assert "color: var(--ps-muted)" in disabled_snapshot

    pinned_hover = source.split(
        '.ps-json-toolbar-group[data-json-toolbar-group="pins"] .artifact-btn:hover',
        1,
    )[1].split("}", 1)[0]
    assert "background: var(--ps-history-bg)" in pinned_hover
    assert "color: var(--ps-history-text)" in pinned_hover


def test_authored_visual_content_is_not_recoloured_by_the_theme() -> None:
    source = (STATIC / "css" / "themes.css").read_text(encoding="utf-8")

    assert ".plotsrv-html-iframe," in source
    assert ".plotsrv-markdown-iframe {" in source
    assert "color-scheme: normal" in source
    assert "filter: invert" not in source
    assert "#plot" not in source
    assert ".ps-plot" not in source
