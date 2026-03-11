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
    assert ui.header_text == ui_config.DEFAULT_HEADER_TEXT
    assert ui.header_fill_colour == ui_config.DEFAULT_HEADER_FILL
    assert ui.page_title == ui_config.DEFAULT_PAGE_TITLE
    assert ui.favicon_url == ui_config.DEFAULT_FAVICON_URL
    assert ui.show_view_selector is True


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
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    ui = ui_config.load_ui_settings()

    assert ui.page_title == "My YAML Title"
    assert ui.favicon_url == "/assets/my.ico"
