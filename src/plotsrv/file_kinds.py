# src/plotsrv/file_kinds.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

FileKind = Literal[
    "text",
    "json",
    "markdown",
    "ini",
    "toml",
    "yaml",
    "csv",
    "image",
    "html",
    "unknown",
]

PublishKind = Literal["artifact", "table"]

ArtifactKind = Literal["text", "json", "markdown", "image", "html"]


@dataclass(frozen=True, slots=True)
class FileCoerceResult:
    publish_kind: PublishKind
    artifact_kind: ArtifactKind | None
    obj: Any
    file_kind: FileKind
    mime: str | None = None

    # New: preserve original source where relevant
    raw_text: str | None = None
    source_format: str | None = None
    source_filename: str | None = None


def infer_file_kind(path: Path) -> FileKind:
    suf = path.suffix.lower()

    if suf == ".json":
        return "json"
    if suf in (".ini", ".cfg"):
        return "ini"
    if suf == ".toml":
        return "toml"
    if suf in (".yaml", ".yml"):
        return "yaml"
    if suf in (".md", ".markdown"):
        return "markdown"
    if suf == ".csv":
        return "csv"
    if suf in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
        return "image"
    if suf in (".html", ".htm"):
        return "html"

    return "unknown"


def _infer_image_mime(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".png":
        return "image/png"
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".gif":
        return "image/gif"
    if suf == ".webp":
        return "image/webp"
    if suf == ".bmp":
        return "image/bmp"
    if suf == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def coerce_file_to_publishable(
    path: Path,
    *,
    encoding: str = "utf-8",
    max_bytes: int | None = None,
    max_rows: int | None = None,
    raw: bytes | None = None,
) -> FileCoerceResult:
    """
    Convert a file to a publishable object.

    - json/ini/toml/yaml -> artifact(json) with dict/list, preserving raw text
    - markdown -> artifact(markdown) with text
    - csv -> publish as table using pandas DataFrame
    - image -> artifact(image) with {mime, data_b64}
    - unknown -> artifact(text) with text
    """
    fk = infer_file_kind(path)

    if raw is None:
        raw2 = path.read_bytes()
        if max_bytes is not None:
            raw2 = raw2[-max(1, int(max_bytes)) :]
        raw = raw2

    # --- JSON ---
    if fk == "json":
        import json

        txt = raw.decode(encoding, errors="replace")
        obj = json.loads(txt)
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=obj,
            file_kind=fk,
            raw_text=txt,
            source_format="json",
            source_filename=path.name,
        )

    # --- INI/CFG ---
    if fk == "ini":
        import configparser

        txt = raw.decode(encoding, errors="replace")
        cfg = configparser.ConfigParser()
        cfg.read_string(txt)

        out: dict[str, Any] = {}
        for section in cfg.sections():
            out[section] = {k: v for k, v in cfg.items(section)}

        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=out,
            file_kind=fk,
            raw_text=txt,
            source_format="ini",
            source_filename=path.name,
        )

    # --- TOML ---
    if fk == "toml":
        txt = raw.decode(encoding, errors="replace")
        try:
            import tomllib  # py3.11+
        except Exception:  # pragma: no cover
            return FileCoerceResult(
                publish_kind="artifact",
                artifact_kind="text",
                obj=txt,
                file_kind="unknown",
                raw_text=txt,
                source_format="toml",
                source_filename=path.name,
            )

        obj = tomllib.loads(txt)
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=obj,
            file_kind=fk,
            raw_text=txt,
            source_format="toml",
            source_filename=path.name,
        )

    # --- YAML ---
    if fk == "yaml":
        txt = raw.decode(encoding, errors="replace")
        try:
            import yaml  # type: ignore
        except Exception:
            return FileCoerceResult(
                publish_kind="artifact",
                artifact_kind="text",
                obj=f"[plotsrv] YAML parsing requires PyYAML. Showing raw text.\n\n{txt}",
                file_kind=fk,
                raw_text=txt,
                source_format="yaml",
                source_filename=path.name,
            )

        obj = yaml.safe_load(txt)
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=obj,
            file_kind=fk,
            raw_text=txt,
            source_format="yaml",
            source_filename=path.name,
        )

    # --- Markdown ---
    if fk == "markdown":
        txt = raw.decode(encoding, errors="replace")
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="markdown",
            obj=txt,
            file_kind=fk,
            raw_text=txt,
            source_format="markdown",
            source_filename=path.name,
        )

    # --- HTML ---
    if fk == "html":
        txt = raw.decode(encoding, errors="replace")
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="html",
            obj=txt,
            file_kind=fk,
            raw_text=txt,
            source_format="html",
            source_filename=path.name,
        )

    # --- CSV ---
    if fk == "csv":
        import io
        import pandas as pd

        nrows = None
        if max_rows is not None:
            try:
                nrows = max(1, int(max_rows))
            except Exception:
                nrows = None

        txt = raw.decode(encoding, errors="replace")
        buf = io.StringIO(txt)

        df = pd.read_csv(
            buf,
            nrows=nrows,
            engine="python",
            on_bad_lines="skip",
        )
        return FileCoerceResult(
            publish_kind="table",
            artifact_kind=None,
            obj=df,
            file_kind=fk,
            raw_text=txt,
            source_format="csv",
            source_filename=path.name,
        )

    # --- Image ---
    if fk == "image":
        import base64

        mime = _infer_image_mime(path)
        data_b64 = base64.b64encode(raw).decode("ascii")
        payload = {"mime": mime, "data_b64": data_b64, "filename": path.name}
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="image",
            obj=payload,
            file_kind=fk,
            mime=mime,
            source_filename=path.name,
        )

    # --- Default -> text ---
    txt = raw.decode(encoding, errors="replace")
    return FileCoerceResult(
        publish_kind="artifact",
        artifact_kind="text",
        obj=txt,
        file_kind=fk,
        raw_text=txt,
        source_format="text",
        source_filename=path.name,
    )
