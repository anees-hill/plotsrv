# tests/test_ui_config_more.py
from __future__ import annotations

from pathlib import Path

import pytest

import plotsrv.settings as settings
import plotsrv.ui_config as ui


def _reset_ui_cache() -> None:
    ui._UI_SETTINGS = None
    ui._UI_CACHE_KEY = None
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    _reset_ui_cache()
    yield
    _reset_ui_cache()


def test_load_ui_settings_yaml_exists_but_no_ui_settings_section(
    tmp_path: Path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text("other:\n  x: 1\n", encoding="utf-8")
    settings.set_runtime_context(config_path=yml)

    s = ui.load_ui_settings()
    assert s.page_title == ui.DEFAULT_PAGE_TITLE
    assert s.logo_url == ui.DEFAULT_LOGO_URL
    assert s.assets_dir is None


def test_load_ui_settings_invalid_bool_falls_back(
    tmp_path: Path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
ui-settings:
  default:
    show_help_note: definitely-not-a-bool
    show_statusline: "????"
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    s = ui.load_ui_settings()
    assert s.show_help_note is True
    assert s.show_statusline is True


def test_load_ui_settings_relative_logo_and_favicon_sets_assets_dir(
    tmp_path: Path,
) -> None:
    logo = tmp_path / "my_logo.png"
    favicon = tmp_path / "my_favicon.ico"
    logo.write_bytes(b"logo")
    favicon.write_bytes(b"fav")

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        f"""
ui-settings:
  default:
    logo: {logo.name}
    favicon: {favicon.name}
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    s = ui.load_ui_settings()
    assert s.logo_url == f"/assets/{logo.name}"
    assert s.favicon_url == f"/assets/{favicon.name}"
    assert s.assets_dir == tmp_path.resolve()


def test_load_ui_settings_bad_logo_path_falls_back_to_default(
    tmp_path: Path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
ui-settings:
  default:
    logo: does-not-exist.png
    favicon: also-missing.ico
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    s = ui.load_ui_settings()
    assert s.logo_url == ui.DEFAULT_LOGO_URL
    assert s.favicon_url == ui.DEFAULT_FAVICON_URL
    assert s.assets_dir is None


def test_get_ui_settings_cache_invalidates_when_config_changes(tmp_path: Path) -> None:
    yml1 = tmp_path / "plotsrv.yml"
    yml1.write_text(
        """
ui-settings:
  default:
    page_title: One
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml1)

    s1 = ui.get_ui_settings()
    assert s1.page_title == "One"

    yml2 = tmp_path / "plotsrv2.yml"
    yml2.write_text(
        """
ui-settings:
  default:
    page_title: Two
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml2)

    s2 = ui.get_ui_settings()
    assert s2.page_title == "Two"
    assert s2 is not s1


def test_get_ui_settings_reuses_cache_when_runtime_key_is_unchanged(
    tmp_path: Path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
ui-settings:
  default:
    page_title: One
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    s1 = ui.get_ui_settings()
    s2 = ui.get_ui_settings()

    assert s2 is s1
    assert s2.page_title == "One"
