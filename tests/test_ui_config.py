# tests/test_ui_config.py
from __future__ import annotations

from pathlib import Path

import plotsrv.settings as settings
import plotsrv.ui_config as ui_config


def _reset_ui_cache() -> None:
    ui_config._UI_SETTINGS = None  # type: ignore[attr-defined]
    ui_config._UI_CACHE_KEY = None  # type: ignore[attr-defined]
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]


def test_load_ui_settings_defaults_when_no_config(monkeypatch, tmp_path: Path) -> None:
    _reset_ui_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)

    ui = ui_config.load_ui_settings()

    assert ui.logo_url == ui_config.DEFAULT_LOGO_URL
    assert ui.logo_url == "/static/plotsrv_icon_title_colour_swash_logo.png"
    assert ui.header_text == ui_config.DEFAULT_HEADER_TEXT
    assert ui.header_fill_colour == ui_config.DEFAULT_HEADER_FILL
    assert ui.page_title == ui_config.DEFAULT_PAGE_TITLE
    assert ui.favicon_url == ui_config.DEFAULT_FAVICON_URL
    assert ui.icon_url == ""
    assert ui.show_view_selector is True
    assert ui.show_view_descriptions is True
    assert ui.featured_views == ()
    assert ui.compact_views == ()
    assert ui.asset_files == ()


def test_dropdown_description_setting_preserves_source_policy():
    assert ui_config.load_ui_settings(section={"show_view_descriptions": False}).show_view_descriptions is False
    assert ui_config.load_ui_settings(section={"show_view_descriptions": "false"}).show_view_descriptions is False
    assert ui_config.load_ui_settings(section={"show_view_descriptions": "invalid"}).show_view_descriptions is True


def test_load_ui_settings_reads_page_title_and_favicon_from_yaml(
    tmp_path: Path,
) -> None:
    _reset_ui_cache()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
ui-settings:
  default:
    page_title: "My YAML Title"
    favicon: "/assets/my.ico"
    icon_url: "https://example.com/monitor"
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    ui = ui_config.load_ui_settings()

    assert ui.page_title == "My YAML Title"
    assert ui.favicon_url == "/assets/my.ico"
    assert ui.icon_url == "https://example.com/monitor"


def test_icon_url_accepts_web_links_and_ignores_unsafe_values() -> None:
    for value in (
        "https://example.com/home?view=1",
        "http://localhost:8000/",
        "/dashboard",
    ):
        assert ui_config.load_ui_settings(section={"icon_url": value}).icon_url == value

    for value in (
        "",
        "javascript:alert(1)",
        "data:text/html,hello",
        "//example.com",
        "https:///missing-host",
        "https://user@example.com",
        "https://example.com:bad/",
        "https://example.com/has space",
        "https://example.com/\nheader",
        123,
    ):
        assert ui_config.load_ui_settings(section={"icon_url": value}).icon_url == ""
