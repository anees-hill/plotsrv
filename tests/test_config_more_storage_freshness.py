from __future__ import annotations

from pathlib import Path

import pytest

import plotsrv.config as cfg
import plotsrv.settings as settings


def _reset_runtime() -> None:
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]
    cfg._RUNTIME_TABLE_VIEW_MODE = None  # type: ignore[attr-defined]


def test_as_bool_variants() -> None:
    assert cfg._as_bool(True, False) is True
    assert cfg._as_bool(False, True) is False
    assert cfg._as_bool(1, False) is True
    assert cfg._as_bool(0, True) is False
    assert cfg._as_bool("yes", False) is True
    assert cfg._as_bool("off", True) is False
    assert cfg._as_bool("weird", True) is True


def test_as_int_or_inf_variants() -> None:
    assert cfg._as_int_or_inf(None, 5) == 5
    assert cfg._as_int_or_inf("inf", 5) == cfg._MAX_TABLE_ROWS_INF
    assert cfg._as_int_or_inf("10", 5) == 10
    assert cfg._as_int_or_inf("0", 5) == 5
    assert cfg._as_int_or_inf("bad", 5) == 5
    assert cfg._as_int_or_inf(7, 5) == 7


def test_as_float_variants() -> None:
    assert cfg._as_float(None, 1.5) == 1.5
    assert cfg._as_float("2.5", 1.5) == 2.5
    assert cfg._as_float("-1", 1.5, min_value=0.0) == 1.5
    assert cfg._as_float("bad", 1.5) == 1.5


def test_parse_figsize_variants() -> None:
    assert cfg._parse_figsize([10, 4]) == (10.0, 4.0)
    assert cfg._parse_figsize((8, 3)) == (8.0, 3.0)
    assert cfg._parse_figsize({"w": 6, "h": 2}) == (6.0, 2.0)
    assert cfg._parse_figsize("12x5") == (12.0, 5.0)
    assert cfg._parse_figsize("12,5") == (12.0, 5.0)
    assert cfg._parse_figsize("") is None
    assert cfg._parse_figsize({"w": -1, "h": 2}) is None
    assert cfg._parse_figsize("bad") is None


def test_parse_duration_seconds_variants() -> None:
    assert cfg._parse_duration_seconds(None) is None
    assert cfg._parse_duration_seconds(300) == 300
    assert cfg._parse_duration_seconds("300") == 300
    assert cfg._parse_duration_seconds("30s") == 30
    assert cfg._parse_duration_seconds("5m") == 300
    assert cfg._parse_duration_seconds("1h") == 3600
    assert cfg._parse_duration_seconds("2d") == 172800
    assert cfg._parse_duration_seconds("off") is None
    assert cfg._parse_duration_seconds("0") is None
    assert cfg._parse_duration_seconds("bad") is None


def test_as_keep_last_variants() -> None:
    assert cfg._as_keep_last(None, 2) == 2
    assert cfg._as_keep_last("inf", 2) is None
    assert cfg._as_keep_last("none", 2) is None
    assert cfg._as_keep_last("5", 2) == 5
    assert cfg._as_keep_last(3, 2) == 3
    assert cfg._as_keep_last(0, 2) == 2
    assert cfg._as_keep_last("bad", 2) == 2


def test_merged_section_defaults_when_no_yaml() -> None:
    _reset_runtime()
    sec = cfg._merged_section("table-settings")
    assert "table_view_mode" in sec
    assert "max_table_rows_simple" in sec


def test_storage_settings_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  watch_enabled: true
  root_dir: ".plotsrv/custom_store"
  max_snapshot_size_mb: 1.5
  default_keep_last: 4
  default_min_store_interval: "5m"
  views:
    etl:import:
      enabled: false
      watch_enabled: false
      keep_last: 7
      min_store_interval: "30s"
      max_snapshot_size_mb: 2.5
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_enabled() is True
    assert cfg.get_storage_watch_enabled() is True
    assert cfg.get_storage_root_dir() == (tmp_path / ".plotsrv/custom_store").resolve()
    assert cfg.get_storage_default_keep_last() == 4
    assert cfg.get_storage_default_min_store_interval_s() == 300
    assert cfg.get_storage_keep_last("etl:import") == 7
    assert cfg.get_storage_min_store_interval_s("etl:import") == 30
    assert cfg.get_storage_max_snapshot_size_bytes("etl:import") == int(
        2.5 * 1024 * 1024
    )


def test_storage_root_dir_absolute_path_stays_absolute(tmp_path: Path) -> None:
    _reset_runtime()
    abs_dir = (tmp_path / "abs_store").resolve()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        f"""
storage-settings:
  root_dir: '{abs_dir.as_posix()}'
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)
    assert cfg.get_storage_root_dir() == abs_dir


def test_storage_view_settings_empty_when_missing(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text("storage-settings: {}", encoding="utf-8")
    settings.set_runtime_context(config_path=yml)
    assert cfg.get_storage_view_settings("missing") == {}


def test_storage_view_enabled_source_aware_logic(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  watch_enabled: false
  views:
    etl:import:
      enabled: false
      watch_enabled: true
    ops:log:
      enabled: true
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_view_enabled("etl:import", source=None) is False
    assert cfg.get_storage_view_enabled("etl:import", source="watch") is True
    assert cfg.get_storage_view_enabled("ops:log", source=None) is True
    assert cfg.get_storage_view_enabled("ops:log", source="watch") is False
    assert cfg.get_storage_view_enabled("missing", source=None) is True
    assert cfg.get_storage_view_enabled("missing", source="watch") is False


def test_storage_view_enabled_false_when_global_disabled(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: false
  watch_enabled: true
  views:
    etl:import:
      enabled: true
      watch_enabled: true
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)
    assert cfg.get_storage_view_enabled("etl:import", source=None) is False
    assert cfg.get_storage_view_enabled("etl:import", source="watch") is False


def test_truncation_defaults_and_parsing(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
truncation:
  text: "600"
  html: "off"
  markdown: null
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_truncation_max_chars("text") == 600
    assert cfg.get_truncation_max_chars("html") is None
    assert cfg.get_truncation_max_chars("markdown") is None


def test_freshness_settings_and_legacy_error_after(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
freshness-settings:
  enabled: true
  expected_every: "5m"
  warn_after: "10m"
  error_after: "20m"
  views:
    etl:import:
      expected_every: "30s"
      warn_after: "45s"
      overdue_after: "60s"
    ops:log:
      error_after: "2m"
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_freshness_enabled() is True
    assert cfg.get_freshness_expected_every_s() == 300
    assert cfg.get_freshness_warn_after_s() == 600
    assert cfg.get_freshness_overdue_after_s() == 1200

    assert cfg.get_freshness_expected_every_s("etl:import") == 30
    assert cfg.get_freshness_warn_after_s("etl:import") == 45
    assert cfg.get_freshness_overdue_after_s("etl:import") == 60

    assert cfg.get_freshness_overdue_after_s("ops:log") == 120
    assert cfg.get_freshness_error_after_s("ops:log") == 120


def test_freshness_view_settings_empty_when_missing(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text("freshness-settings: {}", encoding="utf-8")
    settings.set_runtime_context(config_path=yml)
    assert cfg.get_freshness_view_settings("missing") == {}


def test_plot_render_defaults_without_yaml() -> None:
    _reset_runtime()
    assert cfg.get_plot_dpi() == 200
    assert cfg.get_plot_default_figsize_in() == (12.0, 6.0)
    assert cfg.get_plot_bbox_tight() is True
    assert cfg.get_plot_pad_inches() == 0.10


def test_view_order_returns_none_for_non_list_shapes(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
view-order-settings:
  sections: "ops"
  labels:
    ops: "cpu"
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)
    assert cfg.get_view_order_sections() is None
    assert cfg.get_view_order_labels("ops") is None


def test_storage_latest_settings_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  root_dir: ".plotsrv/custom_store"
  latest:
    enabled: true
    restore_on_startup: true
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_enabled() is True
    assert cfg.get_storage_latest_enabled() is True
    assert cfg.get_storage_restore_latest_on_startup() is True


def test_storage_latest_disabled_when_global_storage_disabled(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: false
  latest:
    enabled: true
    restore_on_startup: true
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_enabled() is False
    assert cfg.get_storage_latest_enabled() is False
    assert cfg.get_storage_restore_latest_on_startup() is False


def test_storage_latest_restore_defaults_true_when_latest_enabled(
    tmp_path: Path,
) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  latest:
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_latest_enabled() is True
    assert cfg.get_storage_restore_latest_on_startup() is True


def test_storage_latest_restore_can_be_disabled(tmp_path: Path) -> None:
    _reset_runtime()
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  latest:
    enabled: true
    restore_on_startup: false
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_latest_enabled() is True
    assert cfg.get_storage_restore_latest_on_startup() is False
