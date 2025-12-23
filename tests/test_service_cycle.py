from __future__ import annotations

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
        quiet=True,
    )
    svc = RunnerService(cfg)
    svc.run()

    assert published == [123]
