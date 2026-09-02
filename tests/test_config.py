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


def test_browser_table_plot_point_limit_has_a_safe_default_and_hard_cap(
    tmp_path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        "render-settings:\n  default:\n    table_plot_max_points: 100000\n",
        encoding="utf-8",
    )

    assert config.get_table_plot_max_points() == 5_000
    settings.set_runtime_context(config_path=yml)
    assert config.get_table_plot_max_points() == 25_000


def test_default_limits_are_generous() -> None:
    assert config.get_watch_max_bytes() == 500 * 1024 * 1024
    assert config.get_truncation_max_chars("text") == 1_000_000
    assert config.get_truncation_max_chars("html") is None
    assert config.get_truncation_max_chars("markdown") == 100_000


def test_default_watch_materialisation_settings(tmp_path) -> None:
    # Do not let an ignored working-directory plotsrv.yml override the code
    # defaults this test is intended to verify.
    yml = tmp_path / "plotsrv.yml"
    yml.write_text("", encoding="utf-8")
    settings.set_runtime_context(config_path=yml)

    assert config.get_watch_materialization() == "auto"
    assert config.get_watch_file_threshold_bytes() == 10 * 1024 * 1024
    assert config.get_watch_active_load_max_concurrent() == 2
    assert config.get_watch_active_load_wait_timeout_s() == 1.0


def test_default_live_publish_settings_are_safe_and_synchronous() -> None:
    assert config.get_publish_async_enabled() is False
    assert config.get_publish_max_pending_views() == 32
    assert config.get_publish_max_pending_bytes() == 64 * 1024 * 1024
    assert config.get_publish_flush_timeout_s() == 1.0


def test_default_stream_settings_bound_recovery_without_affecting_publish() -> None:
    assert config.get_stream_poll_interval_s() == 0.1
    assert config.get_stream_request_timeout_s() == 1.0
    assert config.get_stream_retry_initial_delay_s() == 0.1
    assert config.get_stream_retry_max_delay_s() == 5.0
    assert config.get_stream_heartbeat_interval_s() == 1.0
    assert config.get_stream_heartbeat_timeout_s() == 3.0
    assert config.get_stream_shutdown_drain_timeout_s() == 1.0
    assert config.get_stream_process_exit_cleanup_timeout_s() == 0.25
    assert config.get_stream_raw_max_records() == 200
    assert config.get_stream_raw_max_bytes() == 8 * 1024 * 1024
    assert config.get_stream_raw_max_age_s() is None
    assert config.get_stream_fine_window_s() == 60
    assert config.get_stream_max_fine_summary_windows() == 32
    assert config.get_stream_max_coarse_summary_windows() == 24
    assert config.get_stream_coarse_window_factor() == 60
    assert config.get_stream_max_summary_fields() == 64
    assert config.get_stream_max_categorical_values() == 16
    assert config.get_stream_max_categorical_value_bytes() == 128
    assert config.get_stream_max_noteworthy_items() == 64
    assert config.get_publish_async_enabled() is False


def test_stream_settings_use_yaml(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
stream-settings:
  poll_interval_s: 0.02
  request_timeout_s: 0.5
  retry_initial_delay_s: 0.03
  retry_max_delay_s: 0.2
  heartbeat_interval_s: 0.04
  heartbeat_timeout_s: 0.12
  shutdown_drain_timeout_s: 0.3
  process_exit_cleanup_timeout_s: 0.05
  retention:
    max_raw_records: 3
    max_raw_bytes: 1234
    max_raw_age_s: 0.2
    fine_window_s: 5
    max_fine_summary_windows: 4
    max_coarse_summary_windows: 3
    coarse_window_factor: 6
    max_summary_fields: 7
    max_categorical_values: 8
    max_categorical_value_bytes: 9
    max_noteworthy_items: 10
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert config.get_stream_poll_interval_s() == 0.02
    assert config.get_stream_request_timeout_s() == 0.5
    assert config.get_stream_retry_initial_delay_s() == 0.03
    assert config.get_stream_retry_max_delay_s() == 0.2
    assert config.get_stream_heartbeat_interval_s() == 0.04
    assert config.get_stream_heartbeat_timeout_s() == 0.12
    assert config.get_stream_shutdown_drain_timeout_s() == 0.3
    assert config.get_stream_process_exit_cleanup_timeout_s() == 0.05
    assert config.get_stream_raw_max_records() == 3
    assert config.get_stream_raw_max_bytes() == 1234
    assert config.get_stream_raw_max_age_s() == 0.2
    assert config.get_stream_fine_window_s() == 5
    assert config.get_stream_max_fine_summary_windows() == 4
    assert config.get_stream_max_coarse_summary_windows() == 3
    assert config.get_stream_coarse_window_factor() == 6
    assert config.get_stream_max_summary_fields() == 7
    assert config.get_stream_max_categorical_values() == 8
    assert config.get_stream_max_categorical_value_bytes() == 9
    assert config.get_stream_max_noteworthy_items() == 10


def test_live_publish_settings_use_yaml(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
publish-settings:
  live:
    async_enabled: true
    max_pending_views: 7
    max_pending_mb: 3
    flush_timeout_s: 0.25
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert config.get_publish_async_enabled() is True
    assert config.get_publish_max_pending_views() == 7
    assert config.get_publish_max_pending_bytes() == 3 * 1024 * 1024
    assert config.get_publish_flush_timeout_s() == 0.25


def test_storage_latest_defaults_disabled() -> None:
    assert config.get_storage_enabled() is False
    assert config.get_storage_latest_enabled() is False
    assert config.get_storage_restore_latest_on_startup() is False
    assert config.get_storage_latest_restore_scope() == "none"


def test_storage_latest_is_enabled_when_storage_is_enabled_without_override(
    tmp_path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        "storage-settings:\n  enabled: true\n",
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert config.get_storage_latest_enabled() is True
    assert config.get_storage_restore_latest_on_startup() is True


def test_stream_storage_defaults_to_compact_history_only_when_storage_is_enabled(
    tmp_path,
) -> None:
    assert config.get_storage_stream_enabled() is False
    assert config.get_storage_stream_raw_enabled() is False

    yml = tmp_path / "plotsrv.yml"
    yml.write_text("storage-settings:\n  enabled: true\n", encoding="utf-8")
    settings.set_runtime_context(config_path=yml)

    assert config.get_storage_stream_enabled("logs:worker") is True
    assert config.get_storage_stream_summary_retention("logs:worker") == 64
    assert config.get_storage_stream_noteworthy_keep_last("logs:worker") == 64
    assert config.get_storage_stream_keep_last_sessions("logs:worker") == 8
    assert config.get_storage_stream_max_bytes_per_view("logs:worker") == 16 * 1024 * 1024
    assert config.get_storage_stream_raw_retention("logs:worker") is None
    assert config.get_storage_stream_raw_enabled("logs:worker") is False


def test_stream_raw_opt_in_does_not_bypass_the_global_storage_master_switch(
    tmp_path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: false
  streams:
    raw_retention:
      max_blocks: 2
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert config.get_storage_stream_raw_retention("logs:worker") == {"max_blocks": 2}
    assert config.get_storage_stream_raw_enabled("logs:worker") is False


def test_stream_storage_settings_support_explicit_raw_opt_in_and_view_overrides(
    tmp_path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
storage-settings:
  enabled: true
  streams:
    summary_retention: 9
    noteworthy_keep_last: 8
    keep_last_sessions: 7
    max_bytes_per_view_mb: 2
    raw_retention:
      max_age_s: 60
      max_blocks: 3
  views:
    logs:worker:
      stream:
        enabled: false
    logs:raw-worker:
      stream:
        summary_retention: 4
        raw_retention:
          enabled: true
          max_age_s: 30
          max_blocks: 2
""".strip(),
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=yml)

    assert config.get_storage_stream_enabled("logs:worker") is False
    assert config.get_storage_stream_enabled("logs:raw-worker") is True
    assert config.get_storage_stream_summary_retention("logs:raw-worker") == 4
    assert config.get_storage_stream_noteworthy_keep_last("logs:raw-worker") == 8
    assert config.get_storage_stream_raw_enabled("logs:raw-worker") is True
    assert config.get_storage_stream_raw_retention("logs:raw-worker") == {
        "max_age_s": 30,
        "max_blocks": 2,
        "enabled": True,
    }


def test_get_render_text_max_chars_default() -> None:
    from plotsrv import config

    assert config.get_render_text_max_chars() == 1_000_000


def test_get_render_markdown_max_chars_default() -> None:
    from plotsrv import config

    assert config.get_render_markdown_max_chars() == 100_000


def test_get_render_html_max_chars_default() -> None:
    from plotsrv import config

    assert config.get_render_html_max_chars() is None


def test_default_table_truncate_limits() -> None:
    assert config.get_table_truncate_rows() == 100_000
    assert config.get_table_truncate_columns() == 200


def test_default_published_object_limits() -> None:
    assert config.get_publish_max_plot_bytes() == 5 * 1024 * 1024
    assert config.get_publish_max_table_rows() == 100_000
    assert config.get_publish_max_table_columns() == 200
    assert config.get_publish_max_artifact_text_chars() == 200_000
    assert config.get_publish_max_json_container_items() == 20_000


def test_published_object_limits_use_new_limits_section(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
limits:
  published_objects:
    max_plot_bytes: 123
    max_table_rows: 456
    max_table_columns: 78
    max_artifact_text_chars: 910
    max_json_container_items: 1112
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert config.get_publish_max_plot_bytes() == 123
    assert config.get_publish_max_table_rows() == 456
    assert config.get_publish_max_table_columns() == 78
    assert config.get_publish_max_artifact_text_chars() == 910
    assert config.get_publish_max_json_container_items() == 1112


def test_published_object_limits_new_section_wins_over_legacy_publish_limits(
    tmp_path,
) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
publish-limits:
  max_table_rows: 10
  max_table_columns: 11
  max_artifact_text_chars: 12

limits:
  published_objects:
    max_table_rows: 100
    max_table_columns: 101
    max_artifact_text_chars: 102
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert config.get_publish_max_table_rows() == 100
    assert config.get_publish_max_table_columns() == 101
    assert config.get_publish_max_artifact_text_chars() == 102


def test_watch_materialisation_settings_use_yaml(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
watch-settings:
  materialization: file
  file_threshold_mb: 7
  active-loads:
    max-concurrent: 3
    wait-timeout-s: 0.25
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert config.get_watch_materialization() == "file"
    assert config.get_watch_file_threshold_bytes() == 7 * 1024 * 1024
    assert config.get_watch_active_load_max_concurrent() == 3
    assert config.get_watch_active_load_wait_timeout_s() == 0.25


def test_invalid_watch_materialisation_falls_back_to_auto(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
watch-settings:
  materialization: banana
  file_threshold_mb: nope
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert config.get_watch_materialization() == "auto"
    assert config.get_watch_file_threshold_bytes() == 10 * 1024 * 1024


def test_watch_file_threshold_off_falls_back_to_default(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
watch-settings:
  file_threshold_mb: off
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert config.get_watch_file_threshold_bytes() == 10 * 1024 * 1024


def test_legacy_publish_limits_still_work_without_new_section(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
publish-limits:
  max_table_rows: 10
  max_table_columns: 11
  max_artifact_text_chars: 12
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert config.get_publish_max_table_rows() == 10
    assert config.get_publish_max_table_columns() == 11
    assert config.get_publish_max_artifact_text_chars() == 12


def test_limits_tables_no_longer_affect_publish_limits(tmp_path) -> None:
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        """
limits:
  tables:
    max_rows: 10
    max_columns: 11
""".strip(),
        encoding="utf-8",
    )

    settings.set_runtime_context(config_path=yml)

    assert config.get_publish_max_table_rows() == 100_000
    assert config.get_publish_max_table_columns() == 200


def test_default_render_settings_include_table_and_artifact_behaviour() -> None:
    assert config.get_table_view_mode() == "rich"
    assert config.get_html_sanitize() is False
    assert config.get_html_sandbox() == ""
    assert config.get_markdown_sanitize() is True
    assert config.get_markdown_sandbox() == ""
