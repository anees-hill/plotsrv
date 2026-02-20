# src/plotsrv/file_kinds.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

FileKind = Literal[
    "text", "json", "markdown", "ini", "toml", "yaml", "csv", "image", "unknown"
]


@dataclass(frozen=True, slots=True)
class FileCoerceResult:
    # What the UI should treat it as
    artifact_kind: Literal["text", "json"]
    # The object to publish (string or dict/list)
    obj: Any
    # Optional: a hint for UI/meta later
    file_kind: FileKind


def infer_file_kind(path: Path) -> FileKind:
    suf = path.suffix.lower()
    if suf in (".json",):
        return "json"
    if suf in (".ini", ".cfg"):
        return "ini"
    if suf in (".toml",):
        return "toml"
    if suf in (".yaml", ".yml"):
        return "yaml"
    if suf in (".md", ".markdown"):
        return "markdown"
    if suf in (".csv",):
        return "csv"
    if suf in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
        return "image"
    return "unknown"


def coerce_file_to_publishable(
    path: Path,
    *,
    encoding: str = "utf-8",
    max_bytes: int | None = None,
) -> FileCoerceResult:
    """
    Convert a file to a publishable object.
    - JSON -> dict/list (artifact_kind=json)
    - INI -> dict (artifact_kind=json)  [stdlib]
    - TOML -> dict (artifact_kind=json) [stdlib]
    - Everything else -> text (artifact_kind=text)

    Note: YAML/CSV/Markdown/Images are intentionally left for later steps.
    """
    fk = infer_file_kind(path)

    raw = path.read_bytes()
    if max_bytes is not None:
        raw = raw[-max(1, int(max_bytes)) :]

    # --- JSON ---
    if fk == "json":
        import json

        txt = raw.decode(encoding, errors="replace")
        obj = json.loads(txt)
        return FileCoerceResult(artifact_kind="json", obj=obj, file_kind=fk)

    # --- INI/CFG ---
    if fk == "ini":
        import configparser

        txt = raw.decode(encoding, errors="replace")
        cfg = configparser.ConfigParser()
        cfg.read_string(txt)

        out: dict[str, Any] = {}
        for section in cfg.sections():
            out[section] = {k: v for k, v in cfg.items(section)}
        return FileCoerceResult(artifact_kind="json", obj=out, file_kind=fk)

    # --- TOML ---
    if fk == "toml":
        try:
            import tomllib  # py3.11+
        except Exception:  # pragma: no cover
            # fallback to text if tomllib isn't available
            txt = raw.decode(encoding, errors="replace")
            return FileCoerceResult(artifact_kind="text", obj=txt, file_kind="unknown")

        obj = tomllib.loads(raw.decode(encoding, errors="replace"))
        return FileCoerceResult(artifact_kind="json", obj=obj, file_kind=fk)

    # Default - > text
    txt = raw.decode(encoding, errors="replace")
    return FileCoerceResult(artifact_kind="text", obj=txt, file_kind=fk)
