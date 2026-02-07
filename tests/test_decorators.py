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


def test_plot_decorator_wraps_and_calls_plot_launch(monkeypatch) -> None:
    calls = []
    def fake_plot_launch(obj, *, label, section, host, port, update_limit_s, force=False):
        calls.append((obj, label, section, host, port, update_limit_s))

    monkeypatch.setattr(decorators, "plot_launch", fake_plot_launch)

    @decorators.plot(label="x", section="s", host="127.0.0.1", port=8000, update_limit_s=12)
    def f():
        return 123

    out = f()
    assert out == 123
    assert calls == [(123, "x", "s", "127.0.0.1", 8000, 12)]


def test_plot_decorator_does_not_publish_when_port_none(monkeypatch) -> None:
    called = False
    def fake_plot_launch(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(decorators, "plot_launch", fake_plot_launch)

    @decorators.plot(label="x", port=None)
    def f():
        return 1

    _ = f()
    assert called is False
