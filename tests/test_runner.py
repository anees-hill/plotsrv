from __future__ import annotations

import pytest

from plotsrv.decorators import plot, table
from plotsrv.runner import run_once


def test_run_once_uses_decorator_kind_and_label_plot() -> None:
    @plot(label="p1")
    def f() -> int:
        return 123

    res = run_once(f)
    assert res.kind == "plot"
    assert res.label == "p1"
    assert res.value == 123


def test_run_once_uses_decorator_kind_and_label_table() -> None:
    @table(label="t1")
    def f() -> list[int]:
        return [1, 2, 3]

    res = run_once(f)
    assert res.kind == "table"
    assert res.label == "t1"


def test_run_once_rejects_required_args() -> None:
    def f(x: int) -> int:
        return x

    with pytest.raises(TypeError):
        run_once(f)


def test_run_once_allows_optional_args_with_defaults() -> None:
    def f(x: int = 1) -> int:
        return x

    res = run_once(f)
    assert res.value == 1
