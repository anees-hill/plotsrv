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
