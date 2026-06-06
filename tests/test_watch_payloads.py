# tests/test_watch_payloads.py
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plotsrv.runtime import (
    WatchConfig,
    build_watch_publish_payload,
    publish_prepared_watch_payload,
)


def test_build_watch_publish_payload_text_tail_adds_anchor(tmp_path: Path) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    out = build_watch_publish_payload(
        path=p,
        raw=b"hello\n",
        watch_config=WatchConfig(path=p, kind="text", encoding="utf-8"),
        read_mode="tail",
        max_bytes=1000,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "text"
    assert str(out.artifact).startswith("\ufeffPLOTSRV_ANCHOR=tail\n")
    assert "hello" in str(out.artifact)
    assert out.table_df is None


def test_build_watch_publish_payload_text_head_has_no_anchor(tmp_path: Path) -> None:
    p = tmp_path / "README.md"
    p.write_text("# hello\n", encoding="utf-8")

    out = build_watch_publish_payload(
        path=p,
        raw=b"# hello\n",
        watch_config=WatchConfig(path=p, kind="text", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "text"
    assert out.artifact == "# hello\n"
    assert out.table_df is None


def test_build_watch_publish_payload_json_success(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    out = build_watch_publish_payload(
        path=p,
        raw=b'{"a": 1}',
        watch_config=WatchConfig(path=p, kind="json", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "json"
    assert out.artifact == {"a": 1}
    assert out.table_df is None


def test_build_watch_publish_payload_json_parse_error(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text("{bad", encoding="utf-8")

    out = build_watch_publish_payload(
        path=p,
        raw=b"{bad",
        watch_config=WatchConfig(path=p, kind="json", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "text"
    assert "JSON parse error" in str(out.artifact)
    assert "{bad" in str(out.artifact)
    assert out.table_df is None


def test_build_watch_publish_payload_auto_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pd = pytest.importorskip("pandas")

    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    df = pd.DataFrame({"a": [1]})

    monkeypatch.setattr(
        "plotsrv.runtime.coerce_file_to_publishable",
        lambda *args, **kwargs: SimpleNamespace(
            publish_kind="table",
            obj=df,
            artifact_kind=None,
        ),
    )

    out = build_watch_publish_payload(
        path=p,
        raw=b"a\n1\n",
        watch_config=WatchConfig(path=p, kind="auto", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
        max_rows=10,
    )

    assert out.kind == "table"
    assert out.table_df is df
    assert out.artifact is None
    assert out.artifact_kind is None


def test_build_watch_publish_payload_auto_markdown_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "README.md"
    p.write_text("# hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.coerce_file_to_publishable",
        lambda *args, **kwargs: SimpleNamespace(
            publish_kind="artifact",
            obj="# hello\n",
            artifact_kind="markdown",
        ),
    )

    out = build_watch_publish_payload(
        path=p,
        raw=b"# hello\n",
        watch_config=WatchConfig(path=p, kind="auto", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
        max_rows=10,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "markdown"
    assert out.artifact == "# hello\n"


def test_build_watch_publish_payload_auto_html_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "page.html"
    p.write_text("<h1>Hello</h1>", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.coerce_file_to_publishable",
        lambda *args, **kwargs: SimpleNamespace(
            publish_kind="artifact",
            obj="<h1>Hello</h1>",
            artifact_kind="html",
        ),
    )

    out = build_watch_publish_payload(
        path=p,
        raw=b"<h1>Hello</h1>",
        watch_config=WatchConfig(path=p, kind="auto", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
        max_rows=10,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "html"
    assert out.artifact == "<h1>Hello</h1>"


def test_build_watch_publish_payload_auto_unknown_text_artifact_adds_tail_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.unknown"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.coerce_file_to_publishable",
        lambda *args, **kwargs: SimpleNamespace(
            publish_kind="artifact",
            obj="hello\n",
            artifact_kind="text",
        ),
    )

    out = build_watch_publish_payload(
        path=p,
        raw=b"hello\n",
        watch_config=WatchConfig(path=p, kind="auto", encoding="utf-8"),
        read_mode="tail",
        max_bytes=1000,
        max_rows=10,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "text"
    assert str(out.artifact).startswith("\ufeffPLOTSRV_ANCHOR=tail\n")
    assert "hello" in str(out.artifact)


def test_build_watch_publish_payload_auto_parse_error_falls_back_to_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "broken.dat"
    p.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.coerce_file_to_publishable",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("nope")),
    )

    out = build_watch_publish_payload(
        path=p,
        raw=b"hello",
        watch_config=WatchConfig(path=p, kind="auto", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
        max_rows=10,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "text"
    assert "parse error" in str(out.artifact)
    assert "RuntimeError: nope" in str(out.artifact)
    assert "hello" in str(out.artifact)


def test_publish_prepared_watch_payload_delegates_to_publish_watch_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "plotsrv.runtime.publish_watch_payload",
        lambda **kwargs: captured.update(kwargs) or True,
    )

    from plotsrv.runtime import WatchPublishPayload

    ok = publish_prepared_watch_payload(
        host="127.0.0.1",
        port=8000,
        label="L",
        section="S",
        payload=WatchPublishPayload(
            kind="artifact",
            artifact="hello",
            artifact_kind="text",
        ),
        update_limit_s=10,
        force=True,
    )

    assert ok is True
    assert captured == {
        "host": "127.0.0.1",
        "port": 8000,
        "label": "L",
        "section": "S",
        "kind": "artifact",
        "artifact": "hello",
        "artifact_kind": "text",
        "table_df": None,
        "update_limit_s": 10,
        "force": True,
    }
