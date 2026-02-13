# tests/test_cli_exclude.py
from __future__ import annotations

import time

import pytest

from plotsrv import store
import plotsrv.cli as cli_mod
from plotsrv.discovery import DiscoveredView


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store.reset()
    yield
    store.reset()


def test_run_passive_dir_mode_excludes_views(monkeypatch) -> None:
    """
    In passive directory mode, excluded views should not be registered.
    Exclude strings are matched against:
      - label
      - section
      - full view_id (section:label)
    """

    # Avoid starting server
    monkeypatch.setattr(cli_mod, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "stop_server", lambda *a, **k: None)

    # Force discover_views output
    discovered = [
        DiscoveredView(kind="plot", label="MEM%", section="Resource Usage"),
        DiscoveredView(kind="plot", label="CPU%", section="Resource Usage"),
        DiscoveredView(kind="plot", label="metrics", section="etl-1"),
    ]
    monkeypatch.setattr(cli_mod, "discover_views", lambda _target: list(discovered))

    # Exit loop immediately
    def _sleep_then_interrupt(_: float) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(time, "sleep", _sleep_then_interrupt)

    rc = cli_mod._run_passive_dir_mode(  # type: ignore[attr-defined]
        target="dummy",
        host="127.0.0.1",
        port=8000,
        quiet=True,
        excludes={"Resource Usage:MEM%", "etl-1:metrics"},
        includes=set(),
    )

    assert rc == 0

    metas = store.list_views()
    view_ids = {m.view_id for m in metas}

    # Should have CPU but not MEM or metrics
    assert "Resource Usage:CPU%" in view_ids
    assert "Resource Usage:MEM%" not in view_ids
    assert "etl-1:metrics" not in view_ids


def test_run_passive_dir_mode_includes_only(monkeypatch) -> None:
    """
    In passive directory mode, include acts as an allow-list (label/section/view_id).
    """
    monkeypatch.setattr(cli_mod, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "stop_server", lambda *a, **k: None)

    discovered = [
        DiscoveredView(kind="plot", label="MEM%", section="Resource Usage"),
        DiscoveredView(kind="plot", label="CPU%", section="Resource Usage"),
        DiscoveredView(kind="plot", label="metrics", section="etl-1"),
    ]
    monkeypatch.setattr(cli_mod, "discover_views", lambda _target: list(discovered))

    def _sleep_then_interrupt(_: float) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(time, "sleep", _sleep_then_interrupt)

    # Include only Resource Usage section (should keep CPU + MEM)
    rc = cli_mod._run_passive_dir_mode(  # type: ignore[attr-defined]
        target="dummy",
        host="127.0.0.1",
        port=8000,
        quiet=True,
        excludes=set(),
        includes={"Resource Usage"},
    )
    assert rc == 0

    view_ids = {m.view_id for m in store.list_views()}
    assert "Resource Usage:CPU%" in view_ids
    assert "Resource Usage:MEM%" in view_ids
    assert "etl-1:metrics" not in view_ids


def test_run_passive_dir_mode_include_then_exclude_exclude_wins(monkeypatch) -> None:
    """
    If something is included but also excluded, exclude wins.
    """
    monkeypatch.setattr(cli_mod, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "stop_server", lambda *a, **k: None)

    discovered = [
        DiscoveredView(kind="plot", label="MEM%", section="Resource Usage"),
        DiscoveredView(kind="plot", label="CPU%", section="Resource Usage"),
    ]
    monkeypatch.setattr(cli_mod, "discover_views", lambda _target: list(discovered))

    def _sleep_then_interrupt(_: float) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(time, "sleep", _sleep_then_interrupt)

    rc = cli_mod._run_passive_dir_mode(  # type: ignore[attr-defined]
        target="dummy",
        host="127.0.0.1",
        port=8000,
        quiet=True,
        excludes={"Resource Usage:MEM%"},
        includes={"Resource Usage"},
    )
    assert rc == 0

    view_ids = {m.view_id for m in store.list_views()}
    assert "Resource Usage:CPU%" in view_ids
    assert "Resource Usage:MEM%" not in view_ids
