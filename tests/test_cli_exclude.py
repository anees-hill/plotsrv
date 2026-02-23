# tests/test_cli_exclude.py
from __future__ import annotations

from typing import Callable
from dataclasses import fields

import pytest

import plotsrv.cli as cli_mod
from plotsrv.discovery import DiscoveredView
from plotsrv import store


def _reset_store_state() -> None:
    """
    Best-effort reset, to avoid tests leaking store state.
    Tries a few likely helper names; falls back to clearing common internals.
    """
    for name in (
        "reset_for_tests",
        "_reset_for_tests",
        "reset_state",
        "_reset_state",
        "reset",
    ):
        fn = getattr(store, name, None)
        if callable(fn):
            fn()
            return

    # Fallback: clear common internal dicts if they exist
    for attr in ("_VIEWS", "_views", "VIEWS", "_STORE", "_state"):
        obj = getattr(store, attr, None)
        if isinstance(obj, dict):
            obj.clear()

    # Ensure there's no stale active view pointing at something invalid
    if hasattr(store, "set_active_view"):
        try:
            store.set_active_view("default")
        except Exception:
            pass


def _dv(section: str, label: str) -> DiscoveredView:
    """
    Build a DiscoveredView instance without assuming its exact constructor.
    This makes the test resilient to schema changes in DiscoveredView.
    """
    present = {f.name for f in fields(DiscoveredView)}

    payload: dict[str, object] = {}
    if "section" in present:
        payload["section"] = section
    if "label" in present:
        payload["label"] = label

    # common optional fields (only set if they exist)
    if "kind" in present:
        payload["kind"] = "none"
    if "view_kind" in present:
        payload["view_kind"] = "none"
    if "decorator" in present:
        payload["decorator"] = "plotsrv"

    # Some versions store where it was found; set a safe placeholder if supported.
    if "path" in present:
        payload["path"] = "dummy.py"
    if "module" in present:
        payload["module"] = "dummy"
    if "qualname" in present:
        payload["qualname"] = "dummy.fn"

    return DiscoveredView(**payload)  # type: ignore[arg-type]


def test_run_passive_dir_mode_excludes_views(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    In passive directory mode, excluded views should not be registered.
    Exclude strings are matched against:
      - label
      - section
      - full view_id (section:label)
    """
    _reset_store_state()

    discovered = [
        _dv("etl-1", "import"),
        _dv("etl-1", "metrics"),
        _dv("etl-2", "metrics"),
    ]

    monkeypatch.setattr(cli_mod, "discover_views", lambda _root: discovered)

    excludes = {"metrics", "etl-2", "etl-1:import"}
    includes: set[str] = set()

    cli_mod._passive_register_views("dummy-root", excludes=excludes, includes=includes)

    views = store.list_views()
    view_ids = {v.view_id for v in views}

    # metrics excluded (label match) => both metrics disappear
    assert "etl-1:metrics" not in view_ids
    assert "etl-2:metrics" not in view_ids

    # explicit view_id exclusion
    assert "etl-1:import" not in view_ids

    # nothing left => default view is registered
    assert "default" in view_ids


def test_run_passive_dir_mode_includes_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    In passive directory mode, include acts as an allow-list (label/section/view_id).
    """
    _reset_store_state()

    discovered = [
        _dv("etl-1", "import"),
        _dv("etl-1", "metrics"),
        _dv("etl-2", "metrics"),
        _dv("ops", "health"),
    ]

    monkeypatch.setattr(cli_mod, "discover_views", lambda _root: discovered)

    excludes: set[str] = set()
    includes = {"etl-1", "ops:health"}  # section include + explicit view_id

    cli_mod._passive_register_views("dummy-root", excludes=excludes, includes=includes)

    views = store.list_views()
    view_ids = {v.view_id for v in views}

    # all of etl-1 included
    assert "etl-1:import" in view_ids
    assert "etl-1:metrics" in view_ids

    # explicit view_id included
    assert "ops:health" in view_ids

    # not included
    assert "etl-2:metrics" not in view_ids


def test_run_passive_dir_mode_include_then_exclude_exclude_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    If something is included but also excluded, exclude wins.
    """
    _reset_store_state()

    discovered = [
        _dv("etl-1", "import"),
        _dv("etl-1", "metrics"),
        _dv("etl-2", "metrics"),
    ]

    monkeypatch.setattr(cli_mod, "discover_views", lambda _root: discovered)

    includes = {"etl-1", "etl-2"}  # would allow everything
    excludes = {"etl-2:metrics"}  # but exclude one explicit view

    cli_mod._passive_register_views("dummy-root", excludes=excludes, includes=includes)

    views = store.list_views()
    view_ids = {v.view_id for v in views}

    assert "etl-1:import" in view_ids
    assert "etl-1:metrics" in view_ids

    # excluded wins
    assert "etl-2:metrics" not in view_ids
