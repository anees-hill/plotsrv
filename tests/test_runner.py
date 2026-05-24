# tests/test_runner.py
from __future__ import annotations

import pandas as pd
import pytest

from plotsrv.decorators import get_plotsrv_spec, view
from plotsrv.runner import (
    infer_kind_from_value,
    run_once,
    validate_zero_arg_callable,
)


def test_run_once_uses_view_decorator_kind_and_label() -> None:
    @view(label="p1")
    def f() -> int:
        return 123

    res = run_once(f)

    assert res.kind == "artifact"
    assert res.label == "p1"
    assert res.value == 123


def test_run_once_uses_view_decorator_section_is_not_returned() -> None:
    @view(label="t1", section="s1")
    def f() -> list[int]:
        return [1, 2, 3]

    res = run_once(f)

    assert res.kind == "artifact"
    assert res.label == "t1"
    assert res.value == [1, 2, 3]


def test_run_once_uses_passive_view_metadata_even_without_publishing() -> None:
    @view(label="status", section="ops")
    def f() -> dict[str, str]:
        return {"status": "ok"}

    spec = get_plotsrv_spec(f)
    assert spec is not None
    assert spec.launch_server is False
    assert spec.host is None
    assert spec.port is None

    res = run_once(f)

    assert res.kind == "artifact"
    assert res.label == "status"
    assert res.value == {"status": "ok"}


def test_run_once_uses_launch_server_view_metadata() -> None:
    @view(label="status", section="ops", launch_server=True)
    def f() -> dict[str, str]:
        return {"status": "ok"}

    spec = get_plotsrv_spec(f)
    assert spec is not None
    assert spec.launch_server is True

    res = run_once(f)

    assert res.kind == "artifact"
    assert res.label == "status"
    assert res.value == {"status": "ok"}


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


def test_infer_kind_from_pandas_dataframe() -> None:
    df = pd.DataFrame({"a": [1]})

    assert infer_kind_from_value(df) == "table"


def test_infer_kind_from_non_dataframe_defaults_artifact() -> None:
    assert infer_kind_from_value({"not": "a dataframe"}) == "artifact"


def test_validate_zero_arg_callable_allows_args_and_kwargs() -> None:
    def f(*args, **kwargs):
        return 1

    validate_zero_arg_callable(f)


def test_run_once_rejects_non_callable() -> None:
    with pytest.raises(TypeError, match="expected a callable"):
        run_once(123)


def test_run_once_infers_table_for_undecorated_dataframe() -> None:
    def f() -> pd.DataFrame:
        return pd.DataFrame({"a": [1, 2]})

    res = run_once(f)

    assert res.kind == "table"
    assert res.label is None
    assert list(res.value.columns) == ["a"]


def test_run_once_infers_artifact_for_undecorated_non_dataframe() -> None:
    def f() -> dict[str, int]:
        return {"a": 1}

    res = run_once(f)

    assert res.kind == "artifact"
    assert res.label is None
    assert res.value == {"a": 1}
