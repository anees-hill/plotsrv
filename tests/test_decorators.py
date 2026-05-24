# tests/test_decorators.py
from __future__ import annotations

from typing import Any

import plotsrv.decorators as decorators
from plotsrv.decorators import get_plotsrv_spec, view


def test_view_decorator_attaches_generic_spec() -> None:
    @view(label="status", section="ops")
    def f() -> dict[str, str]:
        return {"status": "ok"}

    spec = get_plotsrv_spec(f)
    assert spec is not None
    assert spec.kind == "artifact"
    assert spec.label == "status"
    assert spec.section == "ops"
    assert spec.host is None
    assert spec.port is None
    assert spec.launch_server is False


def test_view_decorator_attaches_launch_server_spec() -> None:
    @view(label="status", section="ops", launch_server=True)
    def f() -> dict[str, str]:
        return {"status": "ok"}

    spec = get_plotsrv_spec(f)
    assert spec is not None
    assert spec.kind == "artifact"
    assert spec.label == "status"
    assert spec.section == "ops"
    assert spec.launch_server is True


def _install_publish_spy(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_publish_view(
        obj: Any,
        *,
        launch_server: bool = False,
        host: str | None = None,
        port: int | None = None,
        label: str | None = None,
        section: str | None = None,
        update_limit_s: int | None = None,
        force: bool = False,
        kind: str | None = None,
        artifact_kind: str | None = None,
    ) -> None:
        calls.append(
            {
                "obj": obj,
                "launch_server": launch_server,
                "label": label,
                "section": section,
                "host": host,
                "port": port,
                "update_limit_s": update_limit_s,
                "force": force,
                "kind": kind,
                "artifact_kind": artifact_kind,
            }
        )

    monkeypatch.setattr(decorators, "publish_view", fake_publish_view)
    return calls


def test_view_decorator_wraps_and_publishes_when_port_supplied(monkeypatch) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.view(
        label="status",
        section="ops",
        host="127.0.0.1",
        port=8000,
        update_limit_s=12,
    )
    def f():
        return {"status": "ok"}

    out = f()

    assert out == {"status": "ok"}
    assert calls == [
        {
            "obj": {"status": "ok"},
            "launch_server": False,
            "label": "status",
            "section": "ops",
            "host": "127.0.0.1",
            "port": 8000,
            "update_limit_s": 12,
            "force": False,
            "kind": None,
            "artifact_kind": None,
        }
    ]


def test_view_decorator_wraps_and_publishes_when_launch_server_true(
    monkeypatch,
) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.view(
        label="status",
        section="ops",
        launch_server=True,
        update_limit_s=12,
    )
    def f():
        return {"status": "ok"}

    out = f()

    assert out == {"status": "ok"}
    assert calls == [
        {
            "obj": {"status": "ok"},
            "launch_server": True,
            "label": "status",
            "section": "ops",
            "host": None,
            "port": None,
            "update_limit_s": 12,
            "force": False,
            "kind": None,
            "artifact_kind": None,
        }
    ]


def test_view_decorator_wraps_and_publishes_when_host_supplied(monkeypatch) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.view(label="status", section="ops", host="127.0.0.1")
    def f():
        return {"status": "ok"}

    out = f()

    assert out == {"status": "ok"}
    assert calls == [
        {
            "obj": {"status": "ok"},
            "launch_server": False,
            "label": "status",
            "section": "ops",
            "host": "127.0.0.1",
            "port": None,
            "update_limit_s": None,
            "force": False,
            "kind": None,
            "artifact_kind": None,
        }
    ]


def test_view_decorator_does_not_publish_when_passive_metadata_only(
    monkeypatch,
) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.view(label="x")
    def f():
        return 1

    out = f()

    assert out == 1
    assert calls == []


def test_view_decorator_uses_function_name_as_default_label(monkeypatch) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.view(launch_server=True)
    def f():
        return 1

    out = f()

    assert out == 1
    assert len(calls) == 1
    assert calls[0]["label"] == "f"
    assert calls[0]["section"] is None
    assert calls[0]["launch_server"] is True
