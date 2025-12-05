from __future__ import annotations

import pytest

from plotsrv import config


def test_default_table_view_mode_is_simple() -> None:
    assert config.get_table_view_mode() == "simple"


@pytest.mark.parametrize("mode", ["simple", "rich"])
def test_set_table_view_mode_valid_values(mode: str) -> None:
    config.set_table_view_mode(mode)
    assert config.get_table_view_mode() == mode


def test_set_table_view_mode_invalid_raises() -> None:
    with pytest.raises(ValueError):
        config.set_table_view_mode("invalid")  # type: ignore[arg-type]


def test_max_table_rows_constants_positive() -> None:
    assert config.MAX_TABLE_ROWS_SIMPLE > 0
    assert config.MAX_TABLE_ROWS_RICH > 0
    assert config.MAX_TABLE_ROWS_RICH >= config.MAX_TABLE_ROWS_SIMPLE
