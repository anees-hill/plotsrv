# tests/test_discovery.py
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plotsrv.discovery import (
    _call_name,
    _decorator_name,
    _extract_kw_int,
    _extract_kw_str,
    _extract_publish_view_discovery,
    discover_views,
)


def test_discover_views_finds_view(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text(
        """
from plotsrv import view

@view(label="V1", section="Vsec")
def f1():
    pass

@view()
def f2():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert [(v.kind, v.label, v.section) for v in found] == [
        ("artifact", "f2", None),
        ("artifact", "V1", "Vsec"),
    ]


def test_discover_views_ignores_syntax_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def x(:\n", encoding="utf-8")  # syntax error

    found = discover_views(tmp_path)
    assert found == []


def test_discover_views_single_file_path(tmp_path: Path) -> None:
    p = tmp_path / "one.py"
    p.write_text(
        """
from plotsrv import view

@view()
def f():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(p)
    assert len(found) == 1
    assert found[0].kind == "artifact"
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
@view
def a():
    pass

@ps.view()
def b():
    pass

@unknown()
def c():
    pass

@factory("x")
def d():
    pass
"""
    tree = ast.parse(src)
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]

    assert _decorator_name(funcs[0].decorator_list[0]) == "view"
    assert _decorator_name(funcs[1].decorator_list[0]) == "view"
    assert _decorator_name(funcs[2].decorator_list[0]) == "unknown"
    assert _decorator_name(funcs[3].decorator_list[0]) == "factory"

    assert _decorator_name(ast.Constant(value=1)) is None


def test_discover_views_handles_attribute_decorators(tmp_path: Path) -> None:
    p = tmp_path / "attr.py"
    p.write_text(
        """
import plotsrv as ps

@ps.view(label="Generic View", section="V")
def make_view():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert [(x.kind, x.label, x.section) for x in found] == [
        ("artifact", "Generic View", "V"),
    ]


def test_discover_views_falls_back_when_label_or_section_not_string(
    tmp_path: Path,
) -> None:
    p = tmp_path / "fallback.py"
    p.write_text(
        """
from plotsrv import view

@view(label=123, section=456)
def fallback_name():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert len(found) == 1
    assert found[0].kind == "artifact"
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
from plotsrv import view
 
@view()
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
from plotsrv import view 

@view()
def f():
    pass
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(p)
    assert found == []


def test_call_name_handles_name_and_attribute() -> None:
    tree = ast.parse("""
publish_view(x, label="A")
ps.publish_view(x, label="B")
factory()(x)
""".strip())

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    names = [_call_name(call) for call in calls]

    assert "publish_view" in names
    assert names.count("publish_view") == 2


def test_discover_views_finds_publish_view_call(tmp_path: Path) -> None:
    p = tmp_path / "pub.py"
    p.write_text(
        """
from plotsrv import publish_view

def main():
    df = object()
    publish_view(df, label="Data", section="EDA")
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert [(v.kind, v.label, v.section) for v in found] == [
        ("artifact", "Data", "EDA"),
    ]


def test_discover_views_finds_attribute_publish_view_call(tmp_path: Path) -> None:
    p = tmp_path / "pub_attr.py"
    p.write_text(
        """
import plotsrv as ps

def main():
    df = object()
    ps.publish_view(df, label="Orders", section="ETL")
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert [(v.kind, v.label, v.section) for v in found] == [
        ("artifact", "Orders", "ETL"),
    ]


def test_discover_views_ignores_publish_view_dynamic_label(tmp_path: Path) -> None:
    p = tmp_path / "dynamic.py"
    p.write_text(
        """
import plotsrv as ps

def main():
    label = "Data"
    ps.publish_view(object(), label=label, section="EDA")
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert found == []


def test_discover_views_finds_publish_view_literal_view_id(tmp_path: Path) -> None:
    p = tmp_path / "view_id.py"
    p.write_text(
        """
import plotsrv as ps

def main():
    ps.publish_view(object(), view_id="etl:orders")
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert [(v.kind, v.label, v.section) for v in found] == [
        ("artifact", "orders", "etl"),
    ]


def test_discover_views_publish_view_label_overrides_view_id_label(
    tmp_path: Path,
) -> None:
    p = tmp_path / "view_id_label.py"
    p.write_text(
        """
import plotsrv as ps

def main():
    ps.publish_view(object(), view_id="etl:orders", label="Orders nice")
""".strip(),
        encoding="utf-8",
    )

    found = discover_views(tmp_path)

    assert [(v.kind, v.label, v.section) for v in found] == [
        ("artifact", "Orders nice", "etl"),
    ]
