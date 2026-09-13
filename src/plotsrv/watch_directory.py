"""Bounded startup discovery for the watch launcher; never reads file contents."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import replace
from pathlib import Path

from .file_kinds import infer_file_kind
from .runtime import WatchConfig
from .source_setup import build_manifest
from .watch_capture import MAX_WATCHES

DEFAULT_DEPTH = 2
DEFAULT_VIEWS = 32
MAX_DEPTH = 16
MAX_VIEWS = MAX_WATCHES
MAX_ENTRIES = 10_000
TEXT_SUFFIXES = {".txt", ".text", ".log"}


def discover_directory(
    template: WatchConfig,
    *,
    max_depth: int = DEFAULT_DEPTH,
    max_views: int = DEFAULT_VIEWS,
    include: list[str] | None = None,
) -> list[WatchConfig]:
    """Expand regular recognised files into ordinary watch configurations.

    Depth zero includes only root files. Patterns containing '/' match relative
    paths; other patterns match basenames at every included depth. Limits reject
    the entire discovery, so enumeration order never selects a partial catalogue.
    """
    if not 0 <= max_depth <= MAX_DEPTH:
        raise ValueError(f"--max-depth must be between 0 and {MAX_DEPTH}")
    if not 1 <= max_views <= MAX_VIEWS:
        raise ValueError(f"--max-views must be between 1 and {MAX_VIEWS}")
    if template.label is not None or template.view_id is not None:
        raise ValueError("--label and --view-id apply only to a single watched file")
    patterns = include or []
    if len(patterns) > 32 or any(not p or len(p) > 512 for p in patterns):
        raise ValueError(
            "--include accepts at most 32 nonempty patterns of 512 characters"
        )
    root = Path(template.path).expanduser().resolve()
    examined = 0
    watches = []

    def visit(directory: Path, depth: int) -> None:
        nonlocal examined
        # Bound enumeration before sorting, including unsupported/hidden entries.
        with os.scandir(directory) as entries:
            children = []
            for entry in entries:
                examined += 1
                if examined > MAX_ENTRIES:
                    raise ValueError(
                        f"Directory discovery exceeded {MAX_ENTRIES:,} entries; "
                        "choose a narrower directory or lower --max-depth. Nothing was started."
                    )
                if not entry.name.startswith(".") and not entry.is_symlink():
                    children.append(entry)
        for entry in sorted(children, key=lambda item: item.name):
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                if depth < max_depth:
                    visit(path, depth + 1)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if (
                infer_file_kind(path) == "unknown"
                and path.suffix.lower() not in TEXT_SUFFIXES
            ):
                continue
            relative = path.relative_to(root)
            if patterns and not any(
                fnmatch.fnmatchcase(relative.as_posix() if "/" in p else path.name, p)
                for p in patterns
            ):
                continue
            parent = relative.parent.as_posix()
            if template.section is not None:
                section = (
                    template.section
                    if parent == "."
                    else f"{template.section}/{parent}"
                )
            else:
                section = (root.name or "watch") if parent == "." else parent
            watches.append(
                replace(template, path=path, section=section, label=path.name)
            )
            if len(watches) > max_views:
                raise ValueError(
                    f"Directory contains more than {max_views} matching files; narrow --include "
                    f"or --max-depth, or raise --max-views (maximum {MAX_VIEWS}). Nothing was started."
                )

    try:
        visit(root, 0)
    except OSError as error:
        raise ValueError(f"Cannot discover watched directory: {error}") from None
    if not watches:
        raise ValueError(
            "No supported files match within the requested directory depth"
        )
    # Reuse protocol validation, including duplicate logical identities and lengths.
    build_manifest([], watches=watches)
    return watches
