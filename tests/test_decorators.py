# tests/test_decorators.py
from __future__ import annotations

from plotsrv import decorators
from plotsrv.decorators import plot, table, get_plotsrv_spec


def test_plot_decorator_attaches_spec() -> None:
    @plot(label="air_quality")
    def f() -> int:
        return 1

    spec = get_plotsrv_spec(f)
    assert spec is not None
    assert spec.kind == "plot"
    assert spec.label == "air_quality"


def test_table_decorator_attaches_spec() -> None:
    @table(label="readings")
    def f() -> int:
        return 1

    spec = get_plotsrv_spec(f)
    assert spec is not None
    assert spec.kind == "table"
    assert spec.label == "readings"


def _install_publish_spy(monkeypatch):
    """
    Decorators have evolved; some versions call plot_launch/table_launch,
    others call publish_view(kind=...).

    This helper patches whichever exists and returns a calls list.
    """
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
    ):
        calls.append(
            (
                "publish_view",
                obj,
                label,
                section,
                host,
                port,
                update_limit_s,
                force,
                kind,
            )
        )

    def fake_plot_launch(
        obj, *, label, section, host, port, update_limit_s, force=False
    ):
        calls.append(
            ("plot_launch", obj, label, section, host, port, update_limit_s, force)
        )

    def fake_table_launch(
        obj, *, label, section, host, port, update_limit_s, force=False
    ):
        calls.append(
            ("table_launch", obj, label, section, host, port, update_limit_s, force)
        )

    if hasattr(decorators, "publish_view"):
        monkeypatch.setattr(decorators, "publish_view", fake_publish_view)
    if hasattr(decorators, "plot_launch"):
        monkeypatch.setattr(decorators, "plot_launch", fake_plot_launch)
    if hasattr(decorators, "table_launch"):
        monkeypatch.setattr(decorators, "table_launch", fake_table_launch)

    return calls


def test_plot_decorator_wraps_and_publishes(monkeypatch) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.plot(
        label="x", section="s", host="127.0.0.1", port=8000, update_limit_s=12
    )
    def f():
        return 123

    out = f()
    assert out == 123
    assert len(calls) == 1

    tag = calls[0][0]
    if tag == "publish_view":
        _, obj, label, section, host, port, update_limit_s, force, kind = calls[0]
        assert obj == 123
        assert label == "x"
        assert section == "s"
        assert host == "127.0.0.1"
        assert port == 8000
        assert update_limit_s == 12
        assert force is False
        assert kind in (None, "plot")  # depending on your decorator impl
    else:
        _, obj, label, section, host, port, update_limit_s, force = calls[0]
        assert obj == 123
        assert label == "x"
        assert section == "s"
        assert host == "127.0.0.1"
        assert port == 8000
        assert update_limit_s == 12
        assert force is False


def test_plot_decorator_does_not_publish_when_port_none(monkeypatch) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.plot(label="x", port=None)
    def f():
        return 1

    _ = f()
    assert calls == []


def test_table_decorator_does_not_publish_when_port_none(monkeypatch) -> None:
    calls = _install_publish_spy(monkeypatch)

    @decorators.table(label="t", port=None)
    def f():
        return 1

    _ = f()
    assert calls == []
