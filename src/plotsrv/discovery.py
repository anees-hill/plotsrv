# src/plotsrv/discovery.py
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DiscoveredView:
    kind: str  # "plot"|"table"|"artifact"
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
       @view(...)
       @ps.view(...)
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


def _call_name(call: ast.Call) -> str | None:
    """
    Return call function name for:
       publish_view(...)
       ps.publish_view(...)
       plotsrv.publish_view(...)
    """
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _extract_publish_view_discovery(call: ast.Call) -> DiscoveredView | None:
    """
    Extract a discoverable view from a publish_view(...) call.

    Only literal string label/section/view_id values are supported. Dynamic
    labels are intentionally ignored because discovery is static and does not
    execute user code.
    """
    if _call_name(call) != "publish_view":
        return None

    view_id = _extract_kw_str(call, "view_id")
    label = _extract_kw_str(call, "label")
    section = _extract_kw_str(call, "section")

    if view_id:
        if ":" in view_id:
            sec, lab = view_id.split(":", 1)
            section = section or (sec.strip() or None)
            label = label or (lab.strip() or view_id)
        else:
            label = label or view_id

    if not label:
        return None

    return DiscoveredView(
        kind="artifact",
        label=label,
        section=section,
    )


def discover_views(root: str | Path) -> list[DiscoveredView]:
    """
    Walk a directory or Python file and discover plotsrv views.

    We AST-parse .py files and extract:
      - @view decorators on functions
      - simple publish_view(...) calls with literal label/section/view_id

    Dynamic labels/sections are ignored because discovery does not execute code.
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
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    dec_name = _decorator_name(dec)
                    if dec_name != "view":
                        continue

                    label = None
                    section = None

                    if isinstance(dec, ast.Call):
                        label = _extract_kw_str(dec, "label")
                        section = _extract_kw_str(dec, "section")

                    found.append(
                        DiscoveredView(
                            kind="artifact",
                            label=(label or node.name),
                            section=section,
                        )
                    )

            if isinstance(node, ast.Call):
                discovered = _extract_publish_view_discovery(node)
                if discovered is not None:
                    found.append(discovered)

    # stable ordering: section then label
    found.sort(key=lambda x: ((x.section or ""), x.label))
    return found
