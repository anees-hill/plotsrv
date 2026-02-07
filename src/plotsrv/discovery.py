# src/plotsrv/discovery.py
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DiscoveredView:
    kind: str  # "plot"|"table"
    label: str
    section: str | None


def _extract_kw_str(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg != name:
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _extract_kw_int(call: ast.Call, name: str) -> int | None:
    for kw in call.keywords:
        if kw.arg != name:
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
            return kw.value.value
    return None


def _decorator_name(d: ast.expr) -> str | None:
    """
    Return decorator function name for:
      @plot(...)
      @table(...)
      @plotsrv.plot(...)
    """
    if isinstance(d, ast.Call):
        fn = d.func
        if isinstance(fn, ast.Name):
            return fn.id
        if isinstance(fn, ast.Attribute):
            return fn.attr
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        return d.attr
    return None


def discover_views(root: str | Path) -> list[DiscoveredView]:
    """
    Walk a directory and discover @plot/@table decorated functions.

    We AST-parse .py files and extract:
      - decorator type: plot/table
      - label kwarg (fallback: function name)
      - section kwarg (optional)
    """
    rootp = Path(root).resolve()
    if rootp.is_file() and rootp.suffix == ".py":
        py_files = [rootp]
    else:
        py_files = list(rootp.rglob("*.py"))

    found: list[DiscoveredView] = []

    for f in py_files:
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            continue

        try:
            tree = ast.parse(src, filename=str(f))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue

            for dec in node.decorator_list:
                dec_name = _decorator_name(dec)
                if dec_name not in ("plot", "table"):
                    continue

                label = None
                section = None

                if isinstance(dec, ast.Call):
                    label = _extract_kw_str(dec, "label")
                    section = _extract_kw_str(dec, "section")

                found.append(
                    DiscoveredView(
                        kind="plot" if dec_name == "plot" else "table",
                        label=(label or node.name),
                        section=section,
                    )
                )

    # stable ordering: section then label
    found.sort(key=lambda x: ((x.section or ""), x.label))
    return found
