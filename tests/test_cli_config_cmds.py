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

    assert "storage-settings:" in text
    assert "watch_enabled: false" in text
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

    assert data["storage-settings"]["enabled"] is False
    assert data["storage-settings"]["watch_enabled"] is False

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

    assert "publish-limits" not in data
    assert "table-settings" not in data
    assert "artifact-render-settings" not in data

    assert data["limits"]["watched_files"]["max_mb"] == 500
    assert data["render-settings"]["default"]["table_view_mode"] == "rich"
