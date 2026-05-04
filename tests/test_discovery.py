# tests/test_discovery.py
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plotsrv.discovery import (
    _decorator_name,
    _extract_kw_int,
    _extract_kw_str,
    discover_views,
)


def test_discover_views_finds_plot_table_and_plotsrv(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text(
        """
from plotsrv.decorators import plot, table, plotsrv

@plot(label="L1", section="S1", port=8000)
def f1():
    pass

@table()
def f2():
    pass

@plotsrv(label="A1", section="Asec", port=8000)
def f3():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)
    # stable sort: by section then label (empty section first)
    # f2 has section None, label defaults to function name
    assert [v.kind for v in found] == ["table", "artifact", "plot"]
    assert found[0].label == "f2"
    assert found[0].section is None

    assert found[1].kind == "artifact"
    assert found[1].label == "A1"
    assert found[1].section == "Asec"

    assert found[2].kind == "plot"
    assert found[2].label == "L1"
    assert found[2].section == "S1"


def test_discover_views_ignores_syntax_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def x(:\n", encoding="utf-8")  # syntax error

    found = discover_views(tmp_path)
    assert found == []


def test_discover_views_single_file_path(tmp_path: Path) -> None:
    p = tmp_path / "one.py"
    p.write_text(
        """
from plotsrv.decorators import plot

@plot()
def f():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(p)
    assert len(found) == 1
    assert found[0].kind == "plot"
    assert found[0].label == "f"


def test_extract_kw_helpers_handle_constants_and_wrong_types() -> None:
    expr = ast.parse('fn(label="hello", section=123, port=8000, dynamic=name)').body[0]
    assert isinstance(expr, ast.Expr)
    call = expr.value
    assert isinstance(call, ast.Call)

    assert _extract_kw_str(call, "label") == "hello"
    assert _extract_kw_str(call, "section") is None
    assert _extract_kw_str(call, "missing") is None
    assert _extract_kw_str(call, "dynamic") is None

    assert _extract_kw_int(call, "port") == 8000
    assert _extract_kw_int(call, "label") is None
    assert _extract_kw_int(call, "missing") is None
    assert _extract_kw_int(call, "dynamic") is None


def test_decorator_name_handles_name_attribute_call_and_unknown() -> None:
    src = """
@plot
def a():
    pass

@plotsrv.plot()
def b():
    pass

@module.table
def c():
    pass

@unknown()
def d():
    pass

@factory("x")
def e():
    pass
"""
    tree = ast.parse(src)
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]

    assert _decorator_name(funcs[0].decorator_list[0]) == "plot"
    assert _decorator_name(funcs[1].decorator_list[0]) == "plot"
    assert _decorator_name(funcs[2].decorator_list[0]) == "table"
    assert _decorator_name(funcs[3].decorator_list[0]) == "unknown"
    assert _decorator_name(funcs[4].decorator_list[0]) == "factory"

    assert _decorator_name(ast.Constant(value=1)) is None


def test_discover_views_handles_attribute_decorators(tmp_path: Path) -> None:
    p = tmp_path / "attr.py"
    p.write_text(
        """
import plotsrv

@plotsrv.plot(label="Plot Label", section="S")
def make_plot():
    pass

@plotsrv.table
def make_table():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert [(x.kind, x.label, x.section) for x in found] == [
        ("table", "make_table", None),
        ("plot", "Plot Label", "S"),
    ]


def test_discover_views_falls_back_when_label_or_section_not_string(
    tmp_path: Path,
) -> None:
    p = tmp_path / "fallback.py"
    p.write_text(
        """
from plotsrv import plot

@plot(label=123, section=456)
def fallback_name():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert len(found) == 1
    assert found[0].kind == "plot"
    assert found[0].label == "fallback_name"
    assert found[0].section is None


def test_discover_views_ignores_non_plotsrv_decorators(tmp_path: Path) -> None:
    p = tmp_path / "other.py"
    p.write_text(
        """
@staticmethod
def f1():
    pass

@something_else(label="x")
def f2():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)
    assert found == []


def test_discover_views_ignores_files_that_cannot_be_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "x.py"
    p.write_text(
        """
from plotsrv import plot

@plot()
def f():
    pass
""".strip(),
        encoding="utf-8",
    )

    def broken_read_text(self: Path, encoding: str = "utf-8") -> str:
        raise OSError("cannot read")

    monkeypatch.setattr(Path, "read_text", broken_read_text)

    found = discover_views(tmp_path)
    assert found == []


def test_discover_views_ignores_non_python_single_file(tmp_path: Path) -> None:
    p = tmp_path / "not_python.txt"
    p.write_text(
        """
from plotsrv import plot

@plot()
def f():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(p)
    assert found == []
