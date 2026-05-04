from __future__ import annotations

from typing import Any

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

    rc = cli_mod._run_store_stats()

    out = capsys.readouterr().out
    assert rc == 0
    assert "view_count: 2" in out
    assert "snapshot_count: 3" in out
    assert "2.0 KB" in out


def test_run_store_list_views_empty(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "list_stored_views", lambda root_dir: [])

    rc = cli_mod._run_store_list(view_id=None)

    out = capsys.readouterr().out
    assert rc == 0
    assert "(no stored views)" in out


def test_run_store_list_views_with_data(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
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
    assert "a:b" in out
    assert "snapshots=2" in out
    assert "1.0 KB" in out


class Snap:
    snapshot_id = "snap1"
    created_at = "created"
    kind = "json"
    size_bytes = 123
    payload_exists = True
    payload_filename = "payload.json"


def test_run_store_list_snapshots_empty(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "list_snapshots", lambda root_dir, view_id: [])

    rc = cli_mod._run_store_list(view_id="a:b")

    out = capsys.readouterr().out
    assert rc == 0
    assert "(no snapshots)" in out


def test_run_store_list_snapshots_with_data(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
    monkeypatch.setattr(cli_mod, "list_snapshots", lambda root_dir, view_id: [Snap()])

    rc = cli_mod._run_store_list(view_id="a:b")

    out = capsys.readouterr().out
    assert rc == 0
    assert "snap1" in out
    assert "json" in out
    assert "payload.json" in out


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

    rc = cli_mod._run_store_clear(
        view_id=None,
        clear_all=True,
        assume_yes=True,
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Removed 5" in out


def test_run_store_clear_view_yes(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli_mod.config, "get_storage_root_dir", lambda: "/tmp/store")
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
    assert "Removed 2" in out
