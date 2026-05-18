# tests/test_decorators.py
from __future__ import annotations

from plotsrv import decorators
from plotsrv.decorators import view, get_plotsrv_spec


def test_view_decorator_attaches_generic_spec() -> None:
    @view(label="status", section="ops")
    def f() -> dict[str, str]:
        return {"status": "ok"}

    spec = get_plotsrv_spec(f)
    assert spec is not None
    assert spec.kind == "artifact"
    assert spec.label == "status"
    assert spec.section == "ops"


def _install_publish_spy(monkeypatch):
    calls = []

    def fake_publish_view(
        obj,
        *,
        host="127.0.0.1",
        port=8000,
        label,
        section=None,
        update_limit_s=None,
        force=False,
        kind=None,
        artifact_kind=None,
    ):
        calls.append(
            {
                "obj": obj,
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


def test_view_decorator_wraps_and_publishes(monkeypatch) -> None:
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


def test_view_decorator_does_not_publish_when_port_none(monkeypatch) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.view(label="x", port=None)
    def f():
        return 1

    _ = f()
    assert calls == []
