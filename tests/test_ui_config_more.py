# tests/test_ui_config_more.py
from __future__ import annotations

from pathlib import Path
import pytest

import plotsrv.ui_config as ui


def _reset_ui_cache() -> None:
    ui._UI_SETTINGS = None


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    _reset_ui_cache()
    yield
    _reset_ui_cache()


def test_load_ui_settings_ini_exists_but_no_ui_settings_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ini = tmp_path / "plotsrv.ini"
    ini.write_text("[other]\nx=1\n", encoding="utf-8")
    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    s = ui.load_ui_settings()
    assert s.page_title == ui.DEFAULT_PAGE_TITLE
    assert s.logo_url == ui.DEFAULT_LOGO_URL
    assert s.assets_dir is None


def test_load_ui_settings_invalid_bool_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        """
[ui-settings]
show_help_note = definitely-not-a-bool
show_statusline = ????
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    s = ui.load_ui_settings()
    # defaults are True
    assert s.show_help_note is True
    assert s.show_statusline is True


def test_load_ui_settings_relative_logo_and_favicon_sets_assets_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Create dummy asset files next to ini
    logo = tmp_path / "my_logo.png"
    favicon = tmp_path / "my_favicon.ico"
    logo.write_bytes(b"logo")
    favicon.write_bytes(b"fav")

    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        f"""
[ui-settings]
logo = {logo.name}
favicon = {favicon.name}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    s = ui.load_ui_settings()
    assert s.logo_url == f"/assets/{logo.name}"
    assert s.favicon_url == f"/assets/{favicon.name}"
    assert s.assets_dir == tmp_path.resolve()


def test_load_ui_settings_bad_logo_path_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        """
[ui-settings]
logo = does-not-exist.png
favicon = also-missing.ico
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    s = ui.load_ui_settings()
    assert s.logo_url == ui.DEFAULT_LOGO_URL
    assert s.favicon_url == ui.DEFAULT_FAVICON_URL
    assert s.assets_dir is None


def test_get_ui_settings_caches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ini1 = tmp_path / "plotsrv.ini"
    ini1.write_text("[ui-settings]\npage_title = One\n", encoding="utf-8")
    monkeypatch.setenv("PLOTSRV_INI", str(ini1))

    s1 = ui.get_ui_settings()
    assert s1.page_title == "One"

    # Change env; cached value should remain until reset
    ini2 = tmp_path / "plotsrv2.ini"
    ini2.write_text("[ui-settings]\npage_title = Two\n", encoding="utf-8")
    monkeypatch.setenv("PLOTSRV_INI", str(ini2))

    s2 = ui.get_ui_settings()
    assert s2 is s1
    assert s2.page_title == "One"

    # After reset, it should pick up the new ini
    _reset_ui_cache()
    s3 = ui.get_ui_settings()
    assert s3.page_title == "Two"
