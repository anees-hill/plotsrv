# tests/test_cli_main_edges.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import plotsrv.cli as cli_mod


# ----------------------------
# _coerce_watch_specs: error paths
# ----------------------------


def test_main_run_watch_label_count_mismatch_returns_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ensure we don't accidentally hit _default_run_target() logic
    # and we don't enter the long-running server loop.
    monkeypatch.setattr(cli_mod, "_run_passive_server_forever", lambda *a, **k: 0)

    # Two watches, but only one --watch-label -> should error and return 2
    rc = cli_mod.main(
        [
            "run",
            ".",  # safe explicit target
            "--watch",
            "a.txt",
            "--watch-label",
            "only-one-label",
            "--watch",
            "b.txt",
        ]
    )
    assert rc == 2


def test_main_run_watch_section_count_mismatch_returns_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_mod, "_run_passive_server_forever", lambda *a, **k: 0)

    # Two watches, but two sections is OK; mismatch is: provide 2 watches and 3 sections
    rc = cli_mod.main(
        [
            "run",
            ".",
            "--watch",
            "a.txt",
            "--watch",
            "b.txt",
            "--watch-section",
            "s1",
            "--watch-section",
            "s2",
            "--watch-section",
            "s3",
        ]
    )
    assert rc == 2


# ----------------------------
# main(): callable mode KeyboardInterrupt cleanup
# ----------------------------


def test_main_callable_mode_keyboardinterrupt_stops_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # IMPORTANT: cli.main() imports start_server/stop_server from plotsrv.server
    import plotsrv.server as server_mod

    started: dict[str, int] = {"n": 0}
    stopped: dict[str, int] = {"n": 0}

    def fake_start_server(**kwargs: Any) -> None:
        started["n"] += 1

    def fake_stop_server(**kwargs: Any) -> None:
        stopped["n"] += 1

    monkeypatch.setattr(server_mod, "start_server", fake_start_server)
    monkeypatch.setattr(server_mod, "stop_server", fake_stop_server)

    monkeypatch.setattr(cli_mod, "_start_watch_threads", lambda *a, **k: [])
    monkeypatch.setattr(cli_mod, "_passive_register_views", lambda *a, **k: None)

    def boom(**kwargs: Any) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli_mod, "_callable_loop", boom)

    rc = cli_mod.main(
        [
            "run",
            ".",
            "--mode",
            "callable",
        ]
    )
    assert rc == 0
    assert started["n"] == 1
    assert stopped["n"] == 1


# ----------------------------
# _run_watch_mode: missing file path -> _die branch
# ----------------------------


def test_run_watch_mode_missing_file_returns_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nope.txt"

    # Prevent server import/use
    monkeypatch.setattr(cli_mod, "start_server", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(cli_mod, "stop_server", lambda **kwargs: None, raising=False)

    rc = cli_mod._run_watch_mode(
        str(missing),
        host="127.0.0.1",
        port=8000,
        every=1.0,
        kind="text",
        section="watch",
        label=None,
        view_id=None,
        max_bytes=10,
        encoding="utf-8",
        update_limit_s=None,
        force=False,
        quiet=True,
        read_mode=None,
    )
    assert rc == 2
