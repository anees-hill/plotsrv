"""Filesystem-only discovery target resolution; never consult import hooks."""

from __future__ import annotations

from pathlib import Path
import sys


def resolve_source_target(target: str | Path, *, base: Path | None = None) -> Path:
    base = (base or Path.cwd()).resolve()
    raw = str(target).strip().split(":", 1)[0]
    path = Path(raw).expanduser()
    candidate = path if path.is_absolute() else base / path
    if candidate.exists():
        return candidate.resolve()
    if not raw or not all(part.isidentifier() for part in raw.split(".")):
        raise ValueError(
            "Discovery target is not an existing path or static Python module"
        )
    # Searching regular files avoids find_spec importing parents (and avoids
    # executing custom sys.meta_path/path hooks). Include conventional src layouts.
    roots = list(
        dict.fromkeys(
            [base, base / "src", *(Path(p or ".").resolve() for p in sys.path)]
        )
    )
    parts = raw.split(".")
    for index, part in enumerate(parts):
        namespaces = []
        concrete = None
        for root in roots:
            directory = root / part
            module = root / (part + ".py")
            if (directory / "__init__.py").is_file():
                concrete = directory
                break
            if module.is_file():
                concrete = module
                break
            if directory.is_dir():
                namespaces.append(directory)
        if concrete is not None:
            if index == len(parts) - 1:
                return concrete.resolve()
            if concrete.is_file():
                break
            roots = [concrete]
        elif namespaces:
            if index == len(parts) - 1:
                if len(namespaces) != 1:
                    raise ValueError(
                        "Namespace package has multiple source roots; choose an explicit path"
                    )
                return namespaces[0].resolve()
            roots = namespaces
        else:
            break
    raise ValueError(
        "Discovery target could not be resolved statically; choose an existing source path"
    )
