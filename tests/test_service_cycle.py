from __future__ import annotations

import threading
import time
import types
import sys

from plotsrv.service import RunnerService, ServiceConfig


def test_service_runs_once_and_publishes(monkeypatch) -> None:
    # Create a fake module with a function
    mod = types.ModuleType("plotsrv_service_testmod")

    def f():
        return 123

    mod.f = f  # type: ignore[attr-defined]
    sys.modules["plotsrv_service_testmod"] = mod

    published: list[object] = []

    # Patch server methods so we don't start uvicorn
    monkeypatch.setattr("plotsrv.service.start_server", lambda **kwargs: None)
    monkeypatch.setattr("plotsrv.service.stop_server", lambda: None)
    monkeypatch.setattr(
        "plotsrv.service.refresh_view", lambda obj=None, **kwargs: published.append(obj)
    )

    cfg = ServiceConfig(
        target="plotsrv_service_testmod:f",
        host="127.0.0.1",
        port=8000,
        refresh_rate=120,
        once=True,
        keep_alive=False,
        quiet=True,
    )
    svc = RunnerService(cfg)
    svc.run()

    assert published == [123]


def test_once_stops_server_by_default(monkeypatch) -> None:
    mod = types.ModuleType("plotsrv_service_once_mod")

    def f():
        return 123

    mod.f = f  # type: ignore[attr-defined]
    sys.modules["plotsrv_service_once_mod"] = mod

    calls: list[str] = []

    monkeypatch.setattr(
        "plotsrv.service.start_server", lambda **kwargs: calls.append("start")
    )
    monkeypatch.setattr("plotsrv.service.stop_server", lambda: calls.append("stop"))
    monkeypatch.setattr(
        "plotsrv.service.refresh_view",
        lambda obj=None, **kwargs: calls.append("publish"),
    )
    monkeypatch.setattr(
        "plotsrv.service.store.mark_success", lambda **kwargs: calls.append("success")
    )
    monkeypatch.setattr(
        "plotsrv.service.store.mark_error",
        lambda *args, **kwargs: calls.append("error"),
    )

    cfg = ServiceConfig(
        target="plotsrv_service_once_mod:f",
        host="127.0.0.1",
        port=8000,
        refresh_rate=120,
        once=True,
        keep_alive=False,
        quiet=True,
    )
    svc = RunnerService(cfg)
    svc.run()

    assert calls[0] == "start"
    assert "publish" in calls
    assert "stop" in calls  # <-- key behaviour


def test_once_keep_alive_waits_until_stop(monkeypatch) -> None:
    mod = types.ModuleType("plotsrv_service_keepalive_mod")

    def f():
        return 456

    mod.f = f  # type: ignore[attr-defined]
    sys.modules["plotsrv_service_keepalive_mod"] = mod

    calls: list[str] = []

    monkeypatch.setattr(
        "plotsrv.service.start_server", lambda **kwargs: calls.append("start")
    )
    monkeypatch.setattr("plotsrv.service.stop_server", lambda: calls.append("stop"))
    monkeypatch.setattr(
        "plotsrv.service.refresh_view",
        lambda obj=None, **kwargs: calls.append("publish"),
    )
    monkeypatch.setattr(
        "plotsrv.service.store.mark_success", lambda **kwargs: calls.append("success")
    )
    monkeypatch.setattr(
        "plotsrv.service.store.mark_error",
        lambda *args, **kwargs: calls.append("error"),
    )

    cfg = ServiceConfig(
        target="plotsrv_service_keepalive_mod:f",
        host="127.0.0.1",
        port=8000,
        refresh_rate=120,
        once=True,
        keep_alive=True,
        quiet=True,
    )
    svc = RunnerService(cfg)

    t = threading.Thread(target=svc.run, daemon=True)
    t.start()

    # Let it start + publish once
    time.sleep(0.2)
    assert "start" in calls
    assert "publish" in calls

    # It should still be alive until we stop it
    assert t.is_alive()

    svc.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert "stop" in calls
