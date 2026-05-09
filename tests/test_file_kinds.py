# tests/test_file_kinds.py
from __future__ import annotations

import base64
import builtins
from pathlib import Path
from typing import Any

import pytest

import plotsrv.file_kinds as fk


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.json", "json"),
        ("a.ini", "ini"),
        ("a.cfg", "ini"),
        ("a.toml", "toml"),
        ("a.yaml", "yaml"),
        ("a.yml", "yaml"),
        ("a.md", "markdown"),
        ("a.markdown", "markdown"),
        ("a.csv", "csv"),
        ("a.png", "image"),
        ("a.jpg", "image"),
        ("a.jpeg", "image"),
        ("a.gif", "image"),
        ("a.webp", "image"),
        ("a.bmp", "image"),
        ("a.svg", "image"),
        ("a.html", "html"),
        ("a.htm", "html"),
        ("a.txt", "unknown"),
        ("a", "unknown"),
    ],
)
def test_infer_file_kind(name: str, expected: fk.FileKind) -> None:
    assert fk.infer_file_kind(Path(name)) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("x.png", "image/png"),
        ("x.jpg", "image/jpeg"),
        ("x.jpeg", "image/jpeg"),
        ("x.gif", "image/gif"),
        ("x.webp", "image/webp"),
        ("x.bmp", "image/bmp"),
        ("x.svg", "image/svg+xml"),
        ("x.unknown", "application/octet-stream"),
    ],
)
def test_infer_image_mime(name: str, expected: str) -> None:
    assert fk._infer_image_mime(Path(name)) == expected


def _doc_value(doc: dict[str, Any], key: str) -> dict[str, Any]:
    root = doc["root"]
    for child in root["children"]:
        if child["display_key"] == key:
            return child
    raise AssertionError(f"Missing JSON document child: {key}")


def test_coerce_json(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text('{"a": 1, "b": [2, 3]}', encoding="utf-8")

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.artifact_kind == "json"
    assert out.file_kind == "json"

    doc = out.obj
    assert doc["type"] == "plotsrv_json_document"
    assert doc["source_format"] == "json_file"
    assert doc["raw_text"] == '{"a": 1, "b": [2, 3]}'
    assert '"a": 1' in doc["pretty_text"]

    a = _doc_value(doc, "a")
    assert a["full_value"] == "1"

    b = _doc_value(doc, "b")
    assert b["value_kind"] == "list"
    assert b["child_count"] == 2
    assert doc["version"] == 1
    assert doc["meta"]["source_filename"] == "x.json"


def test_coerce_ini(tmp_path: Path) -> None:
    p = tmp_path / "x.ini"
    p.write_text(
        """
[sec]
a = 1
b = two
""".strip(),
        encoding="utf-8",
    )

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.artifact_kind == "json"
    assert out.file_kind == "ini"

    doc = out.obj
    assert doc["type"] == "plotsrv_json_document"
    assert doc["source_format"] == "ini_file"

    sec = _doc_value(doc, "sec")
    assert sec["value_kind"] == "dict"

    children = {ch["display_key"]: ch for ch in sec["children"]}
    assert children["a"]["full_value"] == "1"
    assert children["b"]["full_value"] == "two"
    assert doc["version"] == 1
    assert doc["meta"]["source_filename"] == "x.ini"


def test_coerce_toml(tmp_path: Path) -> None:
    p = tmp_path / "x.toml"
    p.write_text(
        """
a = 1
name = "sam"
[b]
c = 2
""".strip(),
        encoding="utf-8",
    )

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.artifact_kind == "json"
    assert out.file_kind == "toml"

    doc = out.obj
    assert doc["type"] == "plotsrv_json_document"
    assert doc["source_format"] == "toml_file"

    assert _doc_value(doc, "a")["full_value"] == "1"
    assert _doc_value(doc, "name")["full_value"] == "sam"

    b = _doc_value(doc, "b")
    children = {ch["display_key"]: ch for ch in b["children"]}
    assert children["c"]["full_value"] == "2"
    assert doc["version"] == 1
    assert doc["meta"]["source_filename"] == "x.toml"


def test_coerce_yaml_missing_pyyaml_falls_back_to_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "x.yaml"
    p.write_text("a: 1\nb:\n  - 2\n", encoding="utf-8")

    # Force `import yaml` to fail even if PyYAML is installed
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.file_kind == "yaml"
    assert out.artifact_kind == "text"
    assert "requires PyYAML" in str(out.obj)


def test_coerce_markdown(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("# Title\n\nHello", encoding="utf-8")

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.artifact_kind == "markdown"
    assert out.file_kind == "markdown"
    assert "# Title" in out.obj


def test_coerce_html(tmp_path: Path) -> None:
    p = tmp_path / "x.html"
    p.write_text("<h1>Hello</h1>", encoding="utf-8")

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.artifact_kind == "html"
    assert out.file_kind == "html"
    assert "<h1>" in out.obj


def test_coerce_csv_respects_max_rows(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")

    out = fk.coerce_file_to_publishable(p, max_rows=1)
    assert out.publish_kind == "table"
    assert out.file_kind == "csv"
    df = out.obj
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 1


def test_coerce_image_payload(tmp_path: Path) -> None:
    p = tmp_path / "x.png"
    raw = b"\x89PNG\r\n\x1a\n" + b"abc123"
    p.write_bytes(raw)

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.file_kind == "image"
    assert out.artifact_kind == "image"
    assert out.mime == "image/png"
    assert out.obj["mime"] == "image/png"
    assert out.obj["filename"] == "x.png"
    assert out.obj["data_b64"] == base64.b64encode(raw).decode("ascii")


def test_coerce_unknown_defaults_to_text(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("hello", encoding="utf-8")

    out = fk.coerce_file_to_publishable(p)
    assert out.publish_kind == "artifact"
    assert out.file_kind == "unknown"
    assert out.artifact_kind == "text"
    assert out.obj == "hello"


def test_coerce_uses_raw_bytes_without_reread(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    # pass raw that differs from file contents
    out = fk.coerce_file_to_publishable(p, raw=b'{"a": 2}')
    assert out.obj["raw_text"] == '{"a": 2}'
    assert _doc_value(out.obj, "a")["full_value"] == "2"


def test_markdown_coerce_preserves_raw_metadata(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("# Hello", encoding="utf-8")

    out = fk.coerce_file_to_publishable(p)

    assert out.raw_text is None or out.raw_text == "# Hello"
    assert out.obj == "# Hello"


def test_coerce_markdown_metadata_current_behaviour(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("# Hello", encoding="utf-8")

    out = fk.coerce_file_to_publishable(p)

    assert out.publish_kind == "artifact"
    assert out.artifact_kind == "markdown"
    assert out.obj == "# Hello"
    assert out.raw_text is None
    assert out.source_format is None
    assert out.source_filename is None


def test_file_json_document_uses_canonical_json_model_shape(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    out = fk.coerce_file_to_publishable(p)
    doc = out.obj

    assert doc["type"] == "plotsrv_json_document"
    assert doc["version"] == 1
    assert doc["source_format"] == "json_file"
    assert doc["raw_text"] == '{"a": 1}'
    assert doc["meta"]["source_filename"] == "x.json"

    root = doc["root"]
    assert root["id"] == "root"
    assert root["path"] == []
    assert root["value_kind"] == "dict"
    assert root["type_label"] == "dict"

    a = _doc_value(doc, "a")
    assert a["id"] == "root/a"
    assert a["path"] == ["a"]
    assert a["value_kind"] == "int"
    assert a["type_label"] == "int"
    assert a["full_value"] == "1"
