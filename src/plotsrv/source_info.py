"""Small inert source hints, shared by watch, rendering and stored versions."""

from pathlib import PurePath

# Filename recognition is explicit, separate from configuration/format aliases.
CODE_EXTENSIONS = {
    ".py": "python", ".pyi": "python", ".r": "r", ".sql": "sql",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".js": "javascript", ".ts": "typescript", ".css": "css",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".go": "go", ".rs": "rust",
}

LANGUAGES = {
    "py": "python",
    "pyi": "python",
    "python": "python",
    "r": "r",
    "sql": "sql",
    "sh": "bash",
    "bash": "bash",
    "zsh": "bash",
    "json": "json",
    "json_file": "json",
    "python_object": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "yaml_file": "yaml",
    "toml": "toml",
    "toml_file": "toml",
    "ini": "ini",
    "cfg": "ini",
    "ini_file": "ini",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "css": "css",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "go": "go",
    "rs": "rust",
    "rust": "rust",
}


def validate(value):
    if value is None:
        return None
    from .contracts import SourceMetadata, bounded_text

    if type(value) is not dict or set(value) - {
        "basename",
        "format",
        "language",
        "anchor",
        "partial",
    }:
        raise ValueError("Invalid source hints")
    SourceMetadata(basename=value.get("basename"))
    for key in ("format", "language"):
        if value.get(key) is not None:
            bounded_text(value[key], key, 32)
            if not value[key].isascii() or not all(
                c.isalnum() or c in "_+-" for c in value[key]
            ):
                raise ValueError("Invalid source hint")
    if value.get("anchor", "head") not in ("head", "tail"):
        raise ValueError("Invalid source anchor")
    if type(value.get("partial", False)) is not bool:
        raise ValueError("Invalid source preview flag")
    return dict(value)


def for_file(path, *, anchor="head", partial=False):
    name = PurePath(path).name
    suffix = PurePath(name).suffix.lower().lstrip(".")
    # Unknown/long suffixes remain harmless plain text.
    fmt = (
        suffix if len(suffix) <= 32 and suffix.isascii() and suffix.isalnum() else None
    )
    return validate(
        dict(
            basename=name,
            format=fmt,
            language=CODE_EXTENSIONS.get(PurePath(name).suffix.lower()) or LANGUAGES.get(fmt),
            anchor=anchor,
            partial=partial,
        )
    )
