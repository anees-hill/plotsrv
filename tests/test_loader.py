from __future__ import annotations

import sys
import types
import pytest

from plotsrv.loader import parse_import_path, load_callable


def test_parse_import_path() -> None:
    p = parse_import_path("pkg.mod:func")
    assert p.module == "pkg.mod"
    assert p.attr == "func"

    p2 = parse_import_path("pkg.mod:obj.method")
    assert p2.module == "pkg.mod"
    assert p2.attr == "obj.method"

    with pytest.raises(ValueError):
        parse_import_path("no_colon_here")


def test_load_callable_from_dynamic_module() -> None:
    mod = types.ModuleType("plotsrv_test_mod")

    def hello() -> str:
        return "hi"

    mod.hello = hello  # type: ignore[attr-defined]
    sys.modules["plotsrv_test_mod"] = mod

    fn = load_callable("plotsrv_test_mod:hello")
    assert fn() == "hi"


def test_load_callable_raises_if_not_callable() -> None:
    mod = types.ModuleType("plotsrv_test_mod2")
    mod.x = 123  # type: ignore[attr-defined]
    sys.modules["plotsrv_test_mod2"] = mod

    with pytest.raises(TypeError):
        load_callable("plotsrv_test_mod2:x")
