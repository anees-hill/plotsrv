# tests/test_config_ini.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

import plotsrv.config as cfg


def _reset_config_state() -> None:
    # reset the "load once" guard
    cfg._LOADED_RENDER_SETTINGS = False  # type: ignore[attr-defined]

    # reset globals to module defaults (match the source file)
    cfg.TABLE_VIEW_MODE = "rich"
    cfg.MAX_TABLE_ROWS_SIMPLE = 200
    cfg.MAX_TABLE_ROWS_RICH = 1000

    cfg.PLOT_DPI = 200
    cfg.PLOT_DEFAULT_FIGSIZE_IN = (12.0, 6.0)
    cfg.PLOT_BBOX_TIGHT = True
    cfg.PLOT_PAD_INCHES = 0.10

    cfg.VIEW_ORDER_SECTIONS = None
    cfg.VIEW_ORDER_LABELS.clear()


def test_strip_quotes() -> None:
    assert cfg._strip_quotes("'abc'") == "abc"
    assert cfg._strip_quotes('"abc"') == "abc"
    assert cfg._strip_quotes(" abc ") == "abc"
    assert cfg._strip_quotes("' abc '") == "abc"


def test_parse_listish_commas_and_multiline() -> None:
    assert cfg._parse_listish("a, b, c") == ["a", "b", "c"]
    assert cfg._parse_listish("a\nb\nc\n") == ["a", "b", "c"]
    assert cfg._parse_listish("a, b\nc") == ["a", "b", "c"]
    assert cfg._parse_listish("") == []


@pytest.mark.parametrize(
    ("raw", "default", "expected"),
    [
        ("inf", 100, cfg._MAX_TABLE_ROWS_INF),  # type: ignore[attr-defined]
        ("Infinity", 100, cfg._MAX_TABLE_ROWS_INF),  # type: ignore[attr-defined]
        ("none", 100, cfg._MAX_TABLE_ROWS_INF),  # type: ignore[attr-defined]
        ("1000", 5, 1000),
        ("1000.0", 5, 1000),
        ("-1", 7, 7),
        ("abc", 7, 7),
        ("", 7, cfg._MAX_TABLE_ROWS_INF),  # type: ignore[attr-defined]
    ],
)
def test_parse_int_or_inf(raw: str, default: int, expected: int) -> None:
    assert cfg._parse_int_or_inf(raw, default=default, min_value=1) == expected


def test_resolve_ini_path_env_var_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ini = tmp_path / "plotsrv.ini"
    ini.write_text("[table-settings]\ntable_view_mode=simple\n", encoding="utf-8")

    monkeypatch.setenv("PLOTSRV_INI", str(ini))
    monkeypatch.chdir(tmp_path)  # ensure cwd lookup doesn't matter

    assert cfg._resolve_ini_path() == ini


def test_load_ini_settings_once_parses_table_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_config_state()

    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        """
[table-settings]
table_view_mode = "simple"
max_table_rows_simple = 123
max_table_rows_rich = inf
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PLOTSRV_INI", str(ini))
    # trigger load via public getter
    assert cfg.get_table_view_mode() == "simple"
    assert cfg.get_max_table_rows_simple() == 123
    assert cfg.get_max_table_rows_rich() == cfg._MAX_TABLE_ROWS_INF  # type: ignore[attr-defined]


def test_load_ini_settings_once_parses_view_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_config_state()

    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        """
[view-order-settings]
sections =
  ops
  etl

labels.ops = CPU%%, MEM
labels.etl =
  import
  metrics
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    assert cfg.get_view_order_sections() == ["ops", "etl"]
    assert cfg.get_view_order_labels("ops") == ["CPU%", "MEM"]
    assert cfg.get_view_order_labels("etl") == ["import", "metrics"]
    assert cfg.get_view_order_labels("missing") is None


def test_load_ini_settings_once_parses_render_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_config_state()

    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        """
[render-settings]
plot_dpi = 250
plot_default_figsize_in = 10, 4
plot_bbox_tight = false
plot_pad_inches = 0.25
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    assert cfg.get_plot_dpi() == 250
    assert cfg.get_plot_default_figsize_in() == (10.0, 4.0)
    assert cfg.get_plot_bbox_tight() is False
    assert cfg.get_plot_pad_inches() == pytest.approx(0.25)


def test_load_ini_settings_once_blank_figsize_disables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_config_state()

    ini = tmp_path / "plotsrv.ini"
    ini.write_text(
        """
[render-settings]
plot_default_figsize_in =
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PLOTSRV_INI", str(ini))

    assert cfg.get_plot_default_figsize_in() is None
