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


def find_project_root(start: Path) -> Path | None:
    """
    Walk upwards looking for something that indicates a Python project.
    """
    cur = start.resolve()
    for _ in range(30):
        if (cur / "pyproject.toml").is_file():
            return cur
        if (cur / "setup.cfg").is_file() or (cur / "setup.py").is_file():
            return cur
        if (cur / ".git").exists():
            return cur
        # Scope detection must not recursively scan before bounded discovery
        # (or before its cancellation/progress reporting) has begun.
        if (cur / "src").is_dir():
            return cur

        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def default_source_target() -> str:
    """
    If user runs `plotsrv run` with no target, use a safe project root.
    """
    root = find_project_root(Path.cwd())
    if root is None:
        raise ValueError(
            "No target provided and no Python project detected in current directory or parents. "
            "Run from a project directory (pyproject.toml/setup.cfg/.git), or pass an explicit target/path."
        )
    return str(root)
