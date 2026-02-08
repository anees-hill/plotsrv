# tests/test_ui_config.py
from __future__ import annotations

from pathlib import Path

import plotsrv.ui_config as ui_config


def _reset_ui_cache() -> None:
    ui_config._UI_SETTINGS = None  # type: ignore[attr-defined]


def test_load_ui_settings_defaults_when_no_ini(monkeypatch, tmp_path: Path) -> None:
    """
    Ensure we do NOT accidentally read ./plotsrv.ini from the repo root.
    """
    _reset_ui_cache()

    # Run in empty temp dir so ./plotsrv.ini resolution can't find a real one
    monkeypatch.chdir(tmp_path)

    # And ensure env var not set
    monkeypatch.delenv("PLOTSRV_INI", raising=False)

    ui = ui_config.load_ui_settings()

    assert ui.logo_url == ui_config.DEFAULT_LOGO_URL
    assert ui.header_text == ui_config.DEFAULT_HEADER_TEXT
    assert ui.header_fill_colour == ui_config.DEFAULT_HEADER_FILL
    assert ui.page_title == ui_config.DEFAULT_PAGE_TITLE
    assert ui.favicon_url == ui_config.DEFAULT_FAVICON_URL
    assert ui.show_view_selector is True


def test_load_ui_settings_reads_page_title_and_favicon_from_ini(monkeypatch, tmp_path: Path) -> None:
    """
    G2: Confirm ini keys work.
    NOTE: your parser uses key 'favicon' (not favicon_url).
    """
    _reset_ui_cache()
    monkeypatch.chdir(tmp_path)

    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        "\n".join(
            [
                "[ui-settings]",
                'page_title = "My INI Title"',
                'favicon = "/assets/my.ico"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    ui = ui_config.load_ui_settings()

    assert ui.page_title == "My INI Title"
    assert ui.favicon_url == "/assets/my.ico"
