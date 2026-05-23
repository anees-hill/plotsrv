from __future__ import annotations

import pytest

from plotsrv import config
import plotsrv.settings as settings


@pytest.fixture(autouse=True)
def reset_config_state() -> None:
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]
    config._RUNTIME_TABLE_VIEW_MODE = None  # type: ignore[attr-defined]
    yield
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]
    config._RUNTIME_TABLE_VIEW_MODE = None  # type: ignore[attr-defined]


def test_default_table_view_mode_is_rich() -> None:
    assert config.get_table_view_mode() == "rich"


@pytest.mark.parametrize("mode", ["simple", "rich"])
def test_set_table_view_mode_valid_values(mode: str) -> None:
    config.set_table_view_mode(mode)
    assert config.get_table_view_mode() == mode


def test_set_table_view_mode_invalid_raises() -> None:
    with pytest.raises(ValueError):
        config.set_table_view_mode("invalid")  # type: ignore[arg-type]


def test_max_table_rows_constants_positive() -> None:
    assert config.get_max_table_rows_simple() > 0
    assert config.get_max_table_rows_rich() > 0
    assert config.get_max_table_rows_rich() >= config.get_max_table_rows_simple()


def test_default_limits_are_generous() -> None:
    assert config.get_watch_max_bytes() == 5_000_000
    assert config.get_truncation_max_chars("text") == 1_000_000
    assert config.get_truncation_max_chars("html") is None
    assert config.get_truncation_max_chars("markdown") is None

    def test_storage_latest_defaults_disabled() -> None:
        assert config.get_storage_enabled() is False
        assert config.get_storage_latest_enabled() is False
        assert config.get_storage_restore_latest_on_startup() is False
