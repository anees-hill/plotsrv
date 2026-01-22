from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ImportPath:
    module: str
    attr: str  # can include dots, e.g. "foo.bar"


def parse_import_path(value: str) -> ImportPath:
    """
    Parse "package.module:callable" into (module, attr).

    Supports dotted attr after the ":" e.g. "pkg.mod:obj.method".
    """
    if ":" not in value:
        raise ValueError("Import path must be in the form 'package.module:callable'")

    module, attr = value.split(":", 1)
    module = module.strip()
    attr = attr.strip()

    if not module:
        raise ValueError("Import path module part is empty")
    if not attr:
        raise ValueError("Import path attribute part is empty")

    return ImportPath(module=module, attr=attr)


def load_object(path: str) -> Any:
    """
    Load an object from "package.module:attr" where attr may contain dots.
    """
    parsed = parse_import_path(path)
    mod = importlib.import_module(parsed.module)

    obj: Any = mod
    for part in parsed.attr.split("."):
        obj = getattr(obj, part)

    return obj


def load_callable(path: str) -> Callable[..., Any]:
    """
    Load a callable from "package.module:callable".
    """
    obj = load_object(path)
    if not callable(obj):
        raise TypeError(f"Loaded object is not callable: {path!r} (type={type(obj)!r})")
    return obj
