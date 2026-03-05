# tests/test_config_yaml.py
from __future__ import annotations

from pathlib import Path

import plotsrv.config as cfg
import plotsrv.settings as settings


def _reset_runtime() -> None:
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]
    cfg._RUNTIME_TABLE_VIEW_MODE = None  # type: ignore[attr-defined]


def test_get_table_settings_from_yaml_default(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
table-settings:
  table_view_mode: simple
  max_table_rows_simple: 123
  max_table_rows_rich: inf
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_table_view_mode() == "simple"
    assert cfg.get_max_table_rows_simple() == 123
    assert cfg.get_max_table_rows_rich() == cfg._MAX_TABLE_ROWS_INF


def test_get_view_order_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
view-order-settings:
  sections: [ops, etl]
  labels:
    ops: ["CPU%%", "MEM"]
    etl: ["import", "metrics"]
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_view_order_sections() == ["ops", "etl"]
    assert cfg.get_view_order_labels("ops") == ["CPU%%", "MEM"]
    assert cfg.get_view_order_labels("etl") == ["import", "metrics"]
    assert cfg.get_view_order_labels("missing") is None


def test_get_render_settings_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
render-settings:
  default:
    plot_dpi: 250
    plot_default_figsize_in: "10,4"
    plot_bbox_tight: false
    plot_pad_inches: 0.25
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_plot_dpi() == 250
    assert cfg.get_plot_default_figsize_in() == (10.0, 4.0)
    assert cfg.get_plot_bbox_tight() is False
    assert cfg.get_plot_pad_inches() == 0.25


def test_blank_figsize_disables_in_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
render-settings:
  default:
    plot_default_figsize_in: null
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_plot_default_figsize_in() is None


def test_instance_specific_section_overrides_default(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
ui-settings:
  default:
    header_text: "Default Header"
  instances:
    smoke:
      header_text: "Smoke Header"
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml, name="smoke")

    sec = settings.get_section("ui-settings")
    assert sec["header_text"] == "Smoke Header"


def test_runtime_table_view_mode_override_beats_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
table-settings:
  table_view_mode: rich
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)
    cfg.set_table_view_mode("simple")

    assert cfg.get_table_view_mode() == "simple"


def test_truncation_default_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
truncation:
  default:
    text: 55000
    html: off
    markdown: off
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_truncation_max_chars("text") == 55000
    assert cfg.get_truncation_max_chars("html") is None
    assert cfg.get_truncation_max_chars("markdown") is None


def test_truncation_cli_override_beats_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
truncation:
  default:
    text: 55000
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml, truncate_override=60000)

    assert cfg.get_truncation_max_chars("text") == 60000


def test_truncation_cli_off_beats_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
truncation:
  default:
    text: 55000
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(
        config_path=yml, truncate_override=settings._TRUNCATE_OFF
    )

    assert cfg.get_truncation_max_chars("text") is None
