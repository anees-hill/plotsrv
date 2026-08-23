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


def test_get_artifact_render_settings_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
artifact-render-settings:
  default:
    html_sanitize: true
    html_sandbox: "allow-scripts"
    markdown_sanitize: false
    markdown_sandbox: "allow-forms"
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_html_sanitize() is True
    assert cfg.get_html_sandbox() == "allow-scripts"
    assert cfg.get_markdown_sanitize() is False
    assert cfg.get_markdown_sandbox() == "allow-forms"


def test_limits_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
limits:
  watched_files:
    max_bytes: off
  render:
    text: 123456
    html: off
    markdown: off
  tables:
    max_rows: 123
    max_columns: 45
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_watch_max_bytes() is None
    assert cfg.get_truncation_max_chars("text") == 123456
    assert cfg.get_truncation_max_chars("html") is None
    assert cfg.get_truncation_max_chars("markdown") is None
    assert cfg.get_table_truncate_rows() == 123
    assert cfg.get_table_truncate_columns() == 45
    assert cfg.get_publish_max_table_rows() == 100_000
    assert cfg.get_publish_max_table_columns() == 200


def test_limits_view_overrides_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
limits:
  watched_files:
    max_bytes: 5000000
  render:
    text: 1000000
    html: off
    markdown: off
  views:
    live-logs:api:
      render:
        text: off
    live-logs:jobs:
      render:
        text: 30000
    reports:rr2c-check:
      render:
        html: 90000
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    # watched file input limit is global only
    assert cfg.get_watch_max_bytes() == 5_000_000
    assert cfg.get_watch_max_bytes("live-logs:api") == 5_000_000
    assert cfg.get_watch_max_bytes("missing:view") == 5_000_000

    # renderer limits support per-view overrides
    assert cfg.get_truncation_max_chars("text") == 1_000_000
    assert cfg.get_truncation_max_chars("text", view_id="live-logs:api") is None
    assert cfg.get_truncation_max_chars("text", view_id="live-logs:jobs") == 30000
    assert cfg.get_truncation_max_chars("html", view_id="reports:rr2c-check") == 90000
    assert cfg.get_truncation_max_chars("markdown", view_id="missing:view") is None


def test_get_storage_latest_settings_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  latest:
    enabled: true
    restore_on_startup: false
    restore_scope: all
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_latest_enabled() is True
    assert cfg.get_storage_restore_latest_on_startup() is False
    assert cfg.get_storage_latest_restore_scope() == "none"


def test_get_storage_latest_restore_scope_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  latest:
    enabled: true
    restore_scope: all
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_storage_latest_restore_scope() == "all"


def test_new_limits_schema_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
limits:
  published_objects:
    max_plot_bytes: 12345
    max_table_rows: 111
    max_table_columns: 22
    max_artifact_text_chars: 333
    max_json_container_items: 44
  watched_files:
    max_mb: 2
  truncate_after:
    text: 123456
    html: off
    markdown: 98765
    table_rows: 123
    table_columns: 45
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_watch_max_bytes() == 2 * 1024 * 1024

    assert cfg.get_truncation_max_chars("text") == 123456
    assert cfg.get_truncation_max_chars("html") is None
    assert cfg.get_truncation_max_chars("markdown") == 98765

    assert cfg.get_render_text_max_chars() == 123456
    assert cfg.get_render_html_max_chars() is None
    assert cfg.get_render_markdown_max_chars() == 98765

    assert cfg.get_table_truncate_rows() == 123
    assert cfg.get_table_truncate_columns() == 45

    assert cfg.get_publish_max_plot_bytes() == 12345
    assert cfg.get_publish_max_table_rows() == 111
    assert cfg.get_publish_max_table_columns() == 22
    assert cfg.get_publish_max_artifact_text_chars() == 333
    assert cfg.get_publish_max_json_container_items() == 44


def test_new_limit_keys_win_over_legacy_keys(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
publish-limits:
  max_table_rows: 10
  max_table_columns: 11
limits:
  published_objects:
    max_table_rows: 100
    max_table_columns: 101
  watched_files:
    max_mb: 3
    max_bytes: 9
  truncate_after:
    text: 222
    markdown: 333
    table_rows: 444
    table_columns: 55
  render:
    text: 111
    markdown: 112
  tables:
    max_rows: 12
    max_columns: 13
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_watch_max_bytes() == 3 * 1024 * 1024

    assert cfg.get_truncation_max_chars("text") == 222
    assert cfg.get_truncation_max_chars("markdown") == 333

    assert cfg.get_table_truncate_rows() == 444
    assert cfg.get_table_truncate_columns() == 55

    assert cfg.get_publish_max_table_rows() == 100
    assert cfg.get_publish_max_table_columns() == 101


def test_watched_files_max_mb_off_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
limits:
  watched_files:
    max_mb: off
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_watch_max_bytes() is None


def test_legacy_limits_schema_still_works(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
publish-limits:
  max_artifact_text_chars: 1234
limits:
  watched_files:
    max_bytes: 999
  render:
    text: 888
    html: off
    markdown: off
  tables:
    max_rows: 77
    max_columns: 66
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_watch_max_bytes() == 999
    assert cfg.get_truncation_max_chars("text") == 888
    assert cfg.get_truncation_max_chars("html") is None
    assert cfg.get_truncation_max_chars("markdown") is None
    assert cfg.get_table_truncate_rows() == 77
    assert cfg.get_table_truncate_columns() == 66
    assert cfg.get_publish_max_artifact_text_chars() == 1234

    # B7: legacy limits.tables still controls display/truncation compatibility,
    # but no longer controls hard publish rejection limits.
    assert cfg.get_publish_max_table_rows() == 100_000
    assert cfg.get_publish_max_table_columns() == 200


def test_limits_view_truncate_after_overrides_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
limits:
  truncate_after:
    text: 1000000
    html: off
    markdown: 100000
  views:
    live-logs:api:
      truncate_after:
        text: off
    live-logs:jobs:
      truncate_after:
        text: 30000
    reports:rr2c-check:
      truncate_after:
        html: 90000
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_truncation_max_chars("text") == 1_000_000
    assert cfg.get_truncation_max_chars("markdown") == 100_000
    assert cfg.get_truncation_max_chars("html") is None

    assert cfg.get_truncation_max_chars("text", view_id="live-logs:api") is None
    assert cfg.get_truncation_max_chars("text", view_id="live-logs:jobs") == 30000
    assert cfg.get_truncation_max_chars("html", view_id="reports:rr2c-check") == 90000


def test_new_render_settings_default_reads_table_and_artifact_options(
    tmp_path: Path,
) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
render-settings:
  default:
    table_view_mode: simple
    html_sanitize: true
    html_sandbox: "allow-scripts"
    markdown_sanitize: false
    markdown_sandbox: "allow-forms"
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_table_view_mode() == "simple"
    assert cfg.get_html_sanitize() is True
    assert cfg.get_html_sandbox() == "allow-scripts"
    assert cfg.get_markdown_sanitize() is False
    assert cfg.get_markdown_sandbox() == "allow-forms"


def test_new_render_settings_win_over_legacy_table_and_artifact_settings(
    tmp_path: Path,
) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
table-settings:
  table_view_mode: rich

artifact-render-settings:
  html_sanitize: false
  html_sandbox: "legacy-html"
  markdown_sanitize: true
  markdown_sandbox: "legacy-md"

render-settings:
  default:
    table_view_mode: simple
    html_sanitize: true
    html_sandbox: "new-html"
    markdown_sanitize: false
    markdown_sandbox: "new-md"
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_table_view_mode() == "simple"
    assert cfg.get_html_sanitize() is True
    assert cfg.get_html_sandbox() == "new-html"
    assert cfg.get_markdown_sanitize() is False
    assert cfg.get_markdown_sandbox() == "new-md"


def test_legacy_table_and_artifact_settings_still_work_without_new_render_keys(
    tmp_path: Path,
) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
table-settings:
  table_view_mode: simple

artifact-render-settings:
  html_sanitize: true
  html_sandbox: "legacy-html"
  markdown_sanitize: false
  markdown_sandbox: "legacy-md"
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_table_view_mode() == "simple"
    assert cfg.get_html_sanitize() is True
    assert cfg.get_html_sandbox() == "legacy-html"
    assert cfg.get_markdown_sanitize() is False
    assert cfg.get_markdown_sandbox() == "legacy-md"


def test_watch_settings_from_yaml(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
watch-settings:
  materialization: memory
  file_threshold_mb: 12.5
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_watch_materialization() == "memory"
    assert cfg.get_watch_file_threshold_bytes() == int(12.5 * 1024 * 1024)


def test_invalid_watch_settings_from_yaml_fall_back(tmp_path: Path) -> None:
    _reset_runtime()

    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
watch-settings:
  materialization: invalid
  file_threshold_mb: off
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert cfg.get_watch_materialization() == "auto"
    assert cfg.get_watch_file_threshold_bytes() == 10 * 1024 * 1024
