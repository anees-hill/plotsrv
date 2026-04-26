# src/plotsrv/file_kinds.py
from __future__ import annotations

from dataclasses import dataclass
import json
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


def _json_safe_scalar(x: Any) -> Any:
    if x is None:
        return None
    if isinstance(x, (str, int, bool)):
        return x
    if isinstance(x, float):
        try:
            if x != x:
                return None
        except Exception:
            return None
        return x
    return str(x)


def _summarise_scalar(x: Any, *, max_chars: int = 120) -> str:
    s = str(_json_safe_scalar(x))
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "…"


def _infer_runtime_node_type_label(value: Any) -> tuple[str, str | None]:
    if isinstance(value, dict):
        return "dict", "json"
    if isinstance(value, list):
        return "list", "json"
    if isinstance(value, tuple):
        return "tuple", "json"
    if isinstance(value, str):
        return "str", None
    if isinstance(value, bool):
        return "bool", None
    if isinstance(value, int):
        return "int", None
    if isinstance(value, float):
        return "float", None
    if value is None:
        return "None", None
    return type(value).__name__, "python"


def _infer_file_node_type_label(value: Any) -> tuple[str, str | None]:
    if isinstance(value, dict):
        return "object", "json"
    if isinstance(value, list):
        return "list", "json"
    if isinstance(value, tuple):
        return "list", "json"
    if isinstance(value, str):
        return "str", None
    if isinstance(value, bool):
        return "bool", None
    if isinstance(value, int):
        return "int", None
    if isinstance(value, float):
        return "float", None
    if value is None:
        return "null", None
    return type(value).__name__, "python"


def _build_json_node(
    value: Any,
    *,
    display_key: str,
    depth: int = 0,
    source_kind: str = "runtime",
) -> tuple[dict[str, Any], int, int]:
    if source_kind == "file":
        type_label, icon_key = _infer_file_node_type_label(value)
    else:
        type_label, icon_key = _infer_runtime_node_type_label(value)

    if isinstance(value, dict):
        children: list[dict[str, Any]] = []
        node_count = 1
        max_depth_seen = depth
        descendant_count = 0
        descendant_layers = 0

        for k, v in value.items():
            child, child_nodes, child_max_depth = _build_json_node(
                v,
                display_key=str(k),
                depth=depth + 1,
                source_kind=source_kind,
            )
            children.append(child)
            node_count += child_nodes
            max_depth_seen = max(max_depth_seen, child_max_depth)
            descendant_count += child_nodes
            descendant_layers = max(descendant_layers, child_max_depth - depth)

        node = {
            "display_key": display_key,
            "node_kind": "container",
            "value_kind": "dict",
            "type_label": type_label,
            "icon_key": icon_key,
            "summary": f"{len(value)} keys",
            "preview": None,
            "expandable": True,
            "child_count": len(children),
            "descendant_count": descendant_count,
            "descendant_layer_count": descendant_layers,
            "depth": depth,
            "children": children,
            "truncated": False,
            "truncation_reason": None,
        }
        return node, node_count, max_depth_seen

    if isinstance(value, list):
        children = []
        node_count = 1
        max_depth_seen = depth
        descendant_count = 0
        descendant_layers = 0

        for i, v in enumerate(value):
            child, child_nodes, child_max_depth = _build_json_node(
                v,
                display_key=f"[{i}]",
                depth=depth + 1,
                source_kind=source_kind,
            )
            children.append(child)
            node_count += child_nodes
            max_depth_seen = max(max_depth_seen, child_max_depth)
            descendant_count += child_nodes
            descendant_layers = max(descendant_layers, child_max_depth - depth)

        node = {
            "display_key": display_key,
            "node_kind": "container",
            "value_kind": "list",
            "type_label": type_label,
            "icon_key": icon_key,
            "summary": f"{len(value)} items",
            "preview": None,
            "expandable": True,
            "child_count": len(children),
            "descendant_count": descendant_count,
            "descendant_layer_count": descendant_layers,
            "depth": depth,
            "children": children,
            "truncated": False,
            "truncation_reason": None,
        }
        return node, node_count, max_depth_seen

    if isinstance(value, tuple):
        children = []
        node_count = 1
        max_depth_seen = depth
        descendant_count = 0
        descendant_layers = 0

        for i, v in enumerate(value):
            child, child_nodes, child_max_depth = _build_json_node(
                v,
                display_key=f"[{i}]",
                depth=depth + 1,
                source_kind=source_kind,
            )
            children.append(child)
            node_count += child_nodes
            max_depth_seen = max(max_depth_seen, child_max_depth)
            descendant_count += child_nodes
            descendant_layers = max(descendant_layers, child_max_depth - depth)

        node = {
            "display_key": display_key,
            "node_kind": "container",
            "value_kind": "tuple",
            "type_label": type_label,
            "icon_key": icon_key,
            "summary": f"{len(value)} items",
            "preview": None,
            "expandable": True,
            "child_count": len(children),
            "descendant_count": descendant_count,
            "descendant_layer_count": descendant_layers,
            "depth": depth,
            "children": children,
            "truncated": False,
            "truncation_reason": None,
        }
        return node, node_count, max_depth_seen

    preview = _summarise_scalar(value)

    node = {
        "display_key": display_key,
        "node_kind": "scalar",
        "value_kind": "scalar",
        "type_label": type_label,
        "icon_key": icon_key,
        "summary": None,
        "preview": preview,
        "expandable": False,
        "child_count": 0,
        "descendant_count": 0,
        "descendant_layer_count": 0,
        "depth": depth,
        "children": [],
        "truncated": False,
        "truncation_reason": None,
    }
    return node, 1, depth


def _build_structured_document(
    parsed_obj: Any,
    *,
    raw_text: str | None,
    source_format: str,
) -> dict[str, Any]:
    root, node_count, max_depth_seen = _build_json_node(
        parsed_obj,
        display_key="root",
        depth=0,
        source_kind="file",
    )

    try:
        pretty_text = json.dumps(parsed_obj, indent=2, ensure_ascii=False)
    except Exception:
        pretty_text = repr(parsed_obj)

    return {
        "type": "plotsrv_json_document",
        "source_format": source_format,
        "raw_text": raw_text,
        "pretty_text": pretty_text,
        "root": root,
        "meta": {
            "node_count": node_count,
            "max_depth_seen": max_depth_seen,
            "truncated": False,
        },
    }


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

    - json/ini/toml/yaml -> artifact(json) with structured document wrapper
    - markdown -> artifact(markdown) with text
    - csv -> publish as table using pandas DataFrame (CAPPED rows)
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
        txt = raw.decode(encoding, errors="replace")
        parsed = json.loads(txt)
        doc = _build_structured_document(
            parsed,
            raw_text=txt,
            source_format="json_file",
        )
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=doc,
            file_kind=fk,
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

        doc = _build_structured_document(
            out,
            raw_text=txt,
            source_format="ini_file",
        )
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=doc,
            file_kind=fk,
        )

    # --- TOML ---
    if fk == "toml":
        try:
            import tomllib
        except Exception:  # pragma: no cover
            txt = raw.decode(encoding, errors="replace")
            return FileCoerceResult(
                publish_kind="artifact",
                artifact_kind="text",
                obj=txt,
                file_kind="unknown",
            )

        txt = raw.decode(encoding, errors="replace")
        parsed = tomllib.loads(txt)
        doc = _build_structured_document(
            parsed,
            raw_text=txt,
            source_format="toml_file",
        )
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=doc,
            file_kind=fk,
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
            )

        parsed = yaml.safe_load(txt)
        doc = _build_structured_document(
            parsed,
            raw_text=txt,
            source_format="yaml_file",
        )
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="json",
            obj=doc,
            file_kind=fk,
        )

    # --- Markdown ---
    if fk == "markdown":
        txt = raw.decode(encoding, errors="replace")
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="markdown",
            obj=txt,
            file_kind=fk,
        )

    # --- HTML ---
    if fk == "html":
        txt = raw.decode(encoding, errors="replace")
        return FileCoerceResult(
            publish_kind="artifact",
            artifact_kind="html",
            obj=txt,
            file_kind=fk,
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
        )

    # Default -> text
    txt = raw.decode(encoding, errors="replace")
    return FileCoerceResult(
        publish_kind="artifact",
        artifact_kind="text",
        obj=txt,
        file_kind=fk,
    )
