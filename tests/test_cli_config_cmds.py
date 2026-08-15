from __future__ import annotations

from typing import Any
from pathlib import Path
import yaml

import pytest

import plotsrv.cli as cli_mod


def test_run_store_stats_prints(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(
        cli_mod,
        "get_storage_stats",
        lambda root_dir: {
            "root_dir": str(root_dir),
            "view_count": 2,
            "snapshot_count": 3,
            "total_bytes": 2048,
        },
    )
    monkeypatch.setattr(
        cli_mod,
        "get_latest_stats",
        lambda root_dir: {
            "root_dir": str(root_dir),
            "latest_count": 4,
            "total_bytes": 1024,
        },
    )

    rc = cli_mod._run_store_stats()

    out = capsys.readouterr().out
    assert rc == 0
    assert "root_dir: /tmp/store" in out
    assert "snapshot_view_count: 2" in out
    assert "snapshot_count: 3" in out
    assert "snapshot_bytes: 2048 (2.0 KB)" in out
    assert "latest_count: 4" in out
    assert "latest_bytes: 1024 (1.0 KB)" in out
    assert "total_bytes: 3072 (3.0 KB)" in out


def test_run_store_list_views_empty(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "list_latest_views", lambda root_dir: [])
    monkeypatch.setattr(cli_mod, "list_stored_views", lambda root_dir: [])

    rc = cli_mod._run_store_list(view_id=None)

    out = capsys.readouterr().out
    assert rc == 0
    assert "(no stored views)" in out


def test_run_store_list_snapshot_views_with_data(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "list_latest_views", lambda root_dir: [])
    monkeypatch.setattr(
        cli_mod,
        "list_stored_views",
        lambda root_dir: [
            {
                "view_id": "a:b",
                "snapshot_count": 2,
                "total_bytes": 1024,
                "last_created_at": "now",
            }
        ],
    )

    rc = cli_mod._run_store_list(view_id=None)

    out = capsys.readouterr().out
    assert rc == 0
    assert "snapshots:" in out
    assert "a:b" in out
    assert "snapshots=2" in out
    assert "1.0 KB" in out


def test_run_store_list_latest_views_with_data(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(
        cli_mod,
        "list_latest_views",
        lambda root_dir: [
            {
                "view_id": "a:b",
                "kind": "text",
                "updated_at": "now",
                "size_bytes": 1024,
                "payload_exists": True,
                "payload_filename": "latest__payload.txt",
            }
        ],
    )
    monkeypatch.setattr(cli_mod, "list_stored_views", lambda root_dir: [])

    rc = cli_mod._run_store_list(view_id=None)

    out = capsys.readouterr().out
    assert rc == 0
    assert "latest:" in out
    assert "a:b" in out
    assert "kind=text" in out
    assert "1.0 KB" in out
    assert "ok" in out


def test_run_store_list_views_with_latest_and_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(
        cli_mod,
        "list_latest_views",
        lambda root_dir: [
            {
                "view_id": "latest:view",
                "kind": "json",
                "updated_at": "latest-now",
                "size_bytes": 2048,
                "payload_exists": True,
                "payload_filename": "latest__payload.json",
            }
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "list_stored_views",
        lambda root_dir: [
            {
                "view_id": "snap:view",
                "snapshot_count": 3,
                "total_bytes": 4096,
                "last_created_at": "snap-now",
            }
        ],
    )

    rc = cli_mod._run_store_list(view_id=None)

    out = capsys.readouterr().out
    assert rc == 0
    assert "latest:" in out
    assert "latest:view" in out
    assert "snapshots:" in out
    assert "snap:view" in out


class Snap:
    snapshot_id = "snap1"
    created_at = "created"
    kind = "json"
    size_bytes = 123
    payload_exists = True
    payload_filename = "payload.json"


def test_run_store_list_view_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "list_latest_views", lambda root_dir: [])
    monkeypatch.setattr(cli_mod, "list_snapshots", lambda root_dir, view_id: [])

    rc = cli_mod._run_store_list(view_id="a:b")

    out = capsys.readouterr().out
    assert rc == 0
    assert "view_id: a:b" in out
    assert "(no snapshots)" in out


def test_run_store_list_view_with_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "list_latest_views", lambda root_dir: [])
    monkeypatch.setattr(cli_mod, "list_snapshots", lambda root_dir, view_id: [Snap()])

    rc = cli_mod._run_store_list(view_id="a:b")

    out = capsys.readouterr().out
    assert rc == 0
    assert "view_id: a:b" in out
    assert "snapshot_count: 1" in out
    assert "snap1" in out
    assert "json" in out
    assert "payload.json" in out


def test_run_store_list_view_with_latest(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(
        cli_mod,
        "list_latest_views",
        lambda root_dir: [
            {
                "view_id": "a:b",
                "kind": "text",
                "updated_at": "now",
                "size_bytes": 123,
                "payload_exists": True,
                "payload_filename": "latest__payload.txt",
            }
        ],
    )
    monkeypatch.setattr(cli_mod, "list_snapshots", lambda root_dir, view_id: [])

    rc = cli_mod._run_store_list(view_id="a:b")

    out = capsys.readouterr().out
    assert rc == 0
    assert "view_id: a:b" in out
    assert "latest:" in out
    assert "latest__payload.txt" in out
    assert "text" in out
    assert "(no snapshots)" in out


def test_run_store_list_view_with_latest_and_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(
        cli_mod,
        "list_latest_views",
        lambda root_dir: [
            {
                "view_id": "a:b",
                "kind": "table",
                "updated_at": "latest-now",
                "size_bytes": 1000,
                "payload_exists": True,
                "payload_filename": "latest__payload.csv",
            }
        ],
    )
    monkeypatch.setattr(cli_mod, "list_snapshots", lambda root_dir, view_id: [Snap()])

    rc = cli_mod._run_store_list(view_id="a:b")

    out = capsys.readouterr().out
    assert rc == 0
    assert "latest:" in out
    assert "latest__payload.csv" in out
    assert "snapshot_count: 1" in out
    assert "snap1" in out


def test_run_store_clear_requires_target() -> None:
    assert (
        cli_mod._run_store_clear(
            view_id=None,
            clear_all=False,
            assume_yes=True,
        )
        == 2
    )


def test_run_store_clear_rejects_all_and_view() -> None:
    assert (
        cli_mod._run_store_clear(
            view_id="a:b",
            clear_all=True,
            assume_yes=True,
        )
        == 2
    )


def test_run_store_clear_all_aborted(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "_confirm", lambda prompt: False)

    rc = cli_mod._run_store_clear(
        view_id=None,
        clear_all=True,
        assume_yes=False,
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Aborted." in out


def test_run_store_clear_all_yes(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "delete_all_snapshots", lambda root_dir: 5)
    monkeypatch.setattr(cli_mod, "delete_all_latest", lambda root_dir: 3)

    rc = cli_mod._run_store_clear(
        view_id=None,
        clear_all=True,
        assume_yes=True,
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Removed 8" in out
    assert "3 latest" in out
    assert "5 snapshots" in out


def test_run_store_clear_view_aborted(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "_confirm", lambda prompt: False)

    rc = cli_mod._run_store_clear(
        view_id="a:b",
        clear_all=False,
        assume_yes=False,
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Aborted." in out


def test_run_store_clear_view_yes(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(
        cli_mod,
        "delete_latest_for_view",
        lambda root_dir, view_id: 1,
    )
    monkeypatch.setattr(
        cli_mod,
        "delete_all_snapshots_for_view",
        lambda root_dir, view_id: 2,
    )

    rc = cli_mod._run_store_clear(
        view_id="a:b",
        clear_all=False,
        assume_yes=True,
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Removed 3" in out
    assert "1 latest" in out
    assert "2 snapshots" in out


def test_default_config_text_uses_new_config_layout() -> None:
    from plotsrv.config_writer import default_config_text

    text = default_config_text()

    assert "limits:" in text
    assert "published_objects:" in text
    assert "watched_files:" in text
    assert "max_mb: 500" in text
    assert "truncate_after:" in text
    assert "table_rows: 100000" in text
    assert "table_columns: 200" in text

    assert "render-settings:" in text
    assert "default:" in text
    assert "table_view_mode: rich" in text
    assert "html_sanitize: false" in text
    assert "markdown_sanitize: true" in text

    assert "watch-settings:" in text
    assert "materialization: auto" in text
    assert "file_threshold_mb: 10" in text
    assert "active_loads:" in text
    assert "max_concurrent: 2" in text
    assert "wait_timeout_s: 1.0" in text

    assert "publish-settings:" in text
    assert "async_enabled: false" in text
    assert "max_pending_views: 32" in text
    assert "max_pending_mb: 64" in text
    assert "flush_timeout_s: 1.0" in text

    assert "storage-settings:" in text
    assert "watch_enabled: false" in text
    assert "latest:" in text
    assert "    enabled: true" in text
    assert "freshness-settings:" in text
    assert "security-settings:" in text
    assert "tracebacks_enabled: false" in text

    assert "configuration-reference" in text


def test_default_config_text_no_longer_emits_legacy_sections() -> None:
    from plotsrv.config_writer import default_config_text

    text = default_config_text()

    assert "publish-limits:" not in text
    assert "table-settings:" not in text
    assert "artifact-render-settings:" not in text

    assert "max_table_rows_simple" not in text
    assert "max_table_rows_rich" not in text

    assert "max_bytes:" not in text
    assert "  render:" not in text
    assert "  tables:" not in text


def test_default_config_text_parses_as_yaml() -> None:
    from plotsrv.config_writer import default_config_text

    data = yaml.safe_load(default_config_text())

    assert isinstance(data, dict)

    assert data["limits"]["published_objects"]["max_plot_bytes"] == 5 * 1024 * 1024
    assert data["limits"]["published_objects"]["max_table_rows"] == 100000
    assert data["limits"]["published_objects"]["max_table_columns"] == 200

    assert data["limits"]["watched_files"]["max_mb"] == 500

    assert data["limits"]["truncate_after"]["text"] == 1000000
    assert data["limits"]["truncate_after"]["markdown"] == 100000
    assert data["limits"]["truncate_after"]["html"] is False
    assert data["limits"]["truncate_after"]["table_rows"] == 100000
    assert data["limits"]["truncate_after"]["table_columns"] == 200

    assert data["render-settings"]["default"]["table_view_mode"] == "rich"
    assert data["render-settings"]["default"]["html_sanitize"] is False
    assert data["render-settings"]["default"]["markdown_sanitize"] is True

    assert data["watch-settings"]["materialization"] == "auto"
    assert data["watch-settings"]["file_threshold_mb"] == 10
    assert data["watch-settings"]["active_loads"] == {
        "max_concurrent": 2,
        "wait_timeout_s": 1.0,
    }

    assert data["publish-settings"]["live"] == {
        "async_enabled": False,
        "max_pending_views": 32,
        "max_pending_mb": 64,
        "flush_timeout_s": 1.0,
    }

    assert data["storage-settings"]["enabled"] is False
    assert data["storage-settings"]["watch_enabled"] is False
    assert data["storage-settings"]["default_keep_last"] == 2
    assert data["storage-settings"]["latest"]["enabled"] is True

    assert data["freshness-settings"]["enabled"] is False
    assert data["freshness-settings"]["expected_every"] == "60s"
    assert data["freshness-settings"]["warn_after"] == "2m"
    assert data["freshness-settings"]["overdue_after"] == "10m"

    assert data["security-settings"]["tracebacks_enabled"] is False


def test_create_config_file_writes_new_layout(tmp_path: Path) -> None:
    from plotsrv.config_writer import create_config_file

    path = tmp_path / "plotsrv.yml"

    result = create_config_file(path)

    assert result.created is True
    assert result.overwritten is False
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert "limits" in data
    assert "published_objects" in data["limits"]
    assert "watched_files" in data["limits"]
    assert "truncate_after" in data["limits"]

    assert "watch-settings" in data
    assert data["watch-settings"]["materialization"] == "auto"
    assert data["watch-settings"]["file_threshold_mb"] == 10

    assert "publish-limits" not in data
    assert "table-settings" not in data
    assert "artifact-render-settings" not in data

    assert data["limits"]["watched_files"]["max_mb"] == 500
    assert data["render-settings"]["default"]["table_view_mode"] == "rich"


def test_populate_limits_writes_new_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv import config_writer

    monkeypatch.setattr(
        config_writer,
        "discover_view_ids",
        lambda target: ["etl:import", "ops:logs"],
    )

    path = tmp_path / "plotsrv.yml"

    result = config_writer.populate_limits(
        path=path,
        target=tmp_path,
        mode="merge",
        text="123",
        markdown="456",
        html="off",
    )

    assert result.created is True
    assert result.section == "limits"
    assert result.discovered_count == 2
    assert result.added_count == 2

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    limits = data["limits"]

    assert "published_objects" in limits
    assert limits["published_objects"]["max_plot_bytes"] == 5 * 1024 * 1024
    assert limits["published_objects"]["max_table_rows"] == 100000
    assert limits["published_objects"]["max_table_columns"] == 200

    assert limits["watched_files"]["max_mb"] == 500
    assert "max_bytes" not in limits["watched_files"]

    assert limits["truncate_after"]["text"] == 1000000
    assert limits["truncate_after"]["markdown"] == 100000
    assert limits["truncate_after"]["html"] is False
    assert limits["truncate_after"]["table_rows"] == 100000
    assert limits["truncate_after"]["table_columns"] == 200

    assert "render" not in limits
    assert "tables" not in limits

    assert limits["views"]["etl:import"] == {
        "truncate_after": {
            "text": "123",
            "markdown": "456",
            "html": "off",
        }
    }
    assert limits["views"]["ops:logs"] == {
        "truncate_after": {
            "text": "123",
            "markdown": "456",
            "html": "off",
        }
    }


def test_populate_limits_merge_preserves_existing_view_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv import config_writer

    monkeypatch.setattr(
        config_writer,
        "discover_view_ids",
        lambda target: ["etl:import", "ops:logs"],
    )

    path = tmp_path / "plotsrv.yml"
    path.write_text(
        """
limits:
  truncate_after:
    text: 999
  views:
    etl:import:
      truncate_after:
        text: 111
""".strip(),
        encoding="utf-8",
    )

    result = config_writer.populate_limits(
        path=path,
        target=tmp_path,
        mode="merge",
        text="123",
        markdown="456",
        html="off",
    )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    views = data["limits"]["views"]

    assert result.created is False
    assert result.added_count == 1
    assert result.preserved_count == 1

    assert views["etl:import"]["truncate_after"]["text"] == 111
    assert views["ops:logs"]["truncate_after"] == {
        "text": "123",
        "markdown": "456",
        "html": "off",
    }


def test_populate_limits_replace_replaces_view_entries_with_new_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv import config_writer

    monkeypatch.setattr(
        config_writer,
        "discover_view_ids",
        lambda target: ["etl:import"],
    )

    path = tmp_path / "plotsrv.yml"
    path.write_text(
        """
limits:
  views:
    old:view:
      render:
        text: 111
""".strip(),
        encoding="utf-8",
    )

    result = config_writer.populate_limits(
        path=path,
        target=tmp_path,
        mode="replace",
        text="123",
        markdown="456",
        html="off",
    )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert result.replaced is True
    assert "old:view" not in data["limits"]["views"]
    assert data["limits"]["views"]["etl:import"] == {
        "truncate_after": {
            "text": "123",
            "markdown": "456",
            "html": "off",
        }
    }


def test_populate_limits_does_not_delete_existing_legacy_limit_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv import config_writer

    monkeypatch.setattr(
        config_writer,
        "discover_view_ids",
        lambda target: ["etl:import"],
    )

    path = tmp_path / "plotsrv.yml"
    path.write_text(
        """
limits:
  watched_files:
    max_bytes: 123
  render:
    text: 456
  tables:
    max_rows: 789
""".strip(),
        encoding="utf-8",
    )

    config_writer.populate_limits(
        path=path,
        target=tmp_path,
        mode="merge",
    )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    limits = data["limits"]

    # B3 adds the new schema.
    assert "truncate_after" in limits
    assert limits["watched_files"]["max_mb"] == 500

    # B3 does not delete user-provided legacy keys.
    assert limits["watched_files"]["max_bytes"] == 123
    assert limits["render"]["text"] == 456
    assert limits["tables"]["max_rows"] == 789
