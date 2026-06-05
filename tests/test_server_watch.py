# tests/test_server_watch.py
from __future__ import annotations

from typing import Any

import pytest

import plotsrv.server as server_mod


def test_server_client_host_for_bind_host_maps_all_interfaces() -> None:
    assert server_mod._client_host_for_bind_host("0.0.0.0") == "127.0.0.1"
    assert server_mod._client_host_for_bind_host("") == "127.0.0.1"
    assert server_mod._client_host_for_bind_host("*") == "127.0.0.1"
    assert server_mod._client_host_for_bind_host("::") == "127.0.0.1"


def test_server_client_host_for_bind_host_preserves_normal_hosts() -> None:
    assert server_mod._client_host_for_bind_host("127.0.0.1") == "127.0.0.1"
    assert server_mod._client_host_for_bind_host("localhost") == "localhost"


def test_start_server_watches_registers_then_starts_threads_with_client_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_apply_runtime_options(**kwargs: Any) -> None:
        calls.append("apply_runtime_options")

    def fake_restore_latest_views_from_storage() -> int:
        calls.append("restore_latest")
        return 0

    def fake_ensure_server_running(host: str, port: int, quiet: bool) -> bool:
        calls.append(f"ensure:{host}:{port}")
        return True

    def fake_register_watch_views(watches: Any, **kwargs: Any) -> list[Any]:
        calls.append("register_watch_views")
        return []

    def fake_wait_for_server_ready(
        host: str,
        port: int,
        *,
        timeout_s: float = 5.0,
    ) -> bool:
        calls.append(f"wait:{host}:{port}")
        return True

    def fake_start_watch_threads(
        watches: Any,
        *,
        host: str,
        port: int,
        register_views: bool = True,
    ) -> list[Any]:
        calls.append(f"start_watch_threads:{host}:{port}:{register_views}")
        return []

    monkeypatch.setattr(
        "plotsrv.runtime.apply_runtime_options",
        fake_apply_runtime_options,
    )
    monkeypatch.setattr(
        server_mod,
        "restore_latest_views_from_storage",
        fake_restore_latest_views_from_storage,
    )
    monkeypatch.setattr(
        server_mod, "_ensure_server_running", fake_ensure_server_running
    )
    monkeypatch.setattr(
        server_mod, "_wait_for_server_ready", fake_wait_for_server_ready
    )
    monkeypatch.setattr(
        "plotsrv.runtime.register_watch_views",
        fake_register_watch_views,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.start_watch_threads",
        fake_start_watch_threads,
    )

    server_mod.start_server(
        host="0.0.0.0",
        port=8356,
        auto_on_show=False,
        quiet=True,
        watches=[{"path": "README.md"}],
        restore_latest=True,
    )

    assert calls == [
        "apply_runtime_options",
        "restore_latest",
        "ensure:0.0.0.0:8356",
        "register_watch_views",
        "wait:127.0.0.1:8356",
        "start_watch_threads:127.0.0.1:8356:False",
    ]
