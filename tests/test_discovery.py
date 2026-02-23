# tests/test_discovery.py
from __future__ import annotations

from pathlib import Path

import pytest

from plotsrv.discovery import discover_views


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
