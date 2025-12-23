from __future__ import annotations

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
