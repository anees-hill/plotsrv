# tests/test_watch_limits.py
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plotsrv.runtime import (
    WatchConfig,
    build_watch_publish_payload,
    truncate_watch_text_like_artifact,
)


def test_truncate_watch_text_like_artifact_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 10)

    out = truncate_watch_text_like_artifact(
        "0123456789ABCDEFGHIJ",
        artifact_kind="text",
    )

    assert out.startswith("0123456789")
    assert "truncated 10 characters" in out
    assert "limits.render.text" in out


def test_truncate_watch_text_like_artifact_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 8)

    out = truncate_watch_text_like_artifact(
        "# title\n\nbody body body",
        artifact_kind="markdown",
    )

    assert out.startswith("# title\n")
    assert "truncated" in out
    assert "limits.render.markdown" in out


def test_truncate_watch_text_like_artifact_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 9)

    out = truncate_watch_text_like_artifact(
        "<h1>Hello</h1><p>World</p>",
        artifact_kind="html",
    )

    assert out.startswith("<h1>Hello")
    assert "truncated" in out
    assert "limits.render.html" in out


def test_truncate_watch_text_like_artifact_off_leaves_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: None)

    artifact = "x" * 10_000

    out = truncate_watch_text_like_artifact(
        artifact,
        artifact_kind="text",
    )

    assert out == artifact


def test_truncate_watch_text_like_artifact_ignores_json_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 5)

    artifact = {"a": "x" * 10_000}

    out = truncate_watch_text_like_artifact(
        artifact,
        artifact_kind="json",
    )

    assert out is artifact


def test_build_watch_publish_payload_truncates_text_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("x" * 100, encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 20)

    out = build_watch_publish_payload(
        path=p,
        raw=b"x" * 100,
        watch_config=WatchConfig(path=p, kind="text", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "text"
    assert isinstance(out.artifact, str)
    assert out.artifact.startswith("x" * 20)
    assert "truncated 80 characters" in out.artifact
    assert "limits.render.text" in out.artifact


def test_build_watch_publish_payload_truncates_json_parse_error_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{bad" + ("x" * 100), encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 40)

    out = build_watch_publish_payload(
        path=p,
        raw=("{bad" + ("x" * 100)).encode("utf-8"),
        watch_config=WatchConfig(path=p, kind="json", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "text"
    assert isinstance(out.artifact, str)
    assert "JSON parse error" in out.artifact
    assert "truncated" in out.artifact
    assert "limits.render.text" in out.artifact


def test_build_watch_publish_payload_truncates_auto_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "README.md"
    p.write_text("# hello\n" + ("x" * 100), encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 12)
    monkeypatch.setattr(
        "plotsrv.runtime.coerce_file_to_publishable",
        lambda *args, **kwargs: SimpleNamespace(
            publish_kind="artifact",
            obj="# hello\n" + ("x" * 100),
            artifact_kind="markdown",
        ),
    )

    out = build_watch_publish_payload(
        path=p,
        raw=("# hello\n" + ("x" * 100)).encode("utf-8"),
        watch_config=WatchConfig(path=p, kind="auto", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
        max_rows=10,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "markdown"
    assert isinstance(out.artifact, str)
    assert out.artifact.startswith("# hello\nxxxx")
    assert "truncated" in out.artifact
    assert "limits.render.markdown" in out.artifact


def test_build_watch_publish_payload_truncates_auto_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "page.html"
    p.write_text("<h1>Hello</h1>" + ("x" * 100), encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 12)
    monkeypatch.setattr(
        "plotsrv.runtime.coerce_file_to_publishable",
        lambda *args, **kwargs: SimpleNamespace(
            publish_kind="artifact",
            obj="<h1>Hello</h1>" + ("x" * 100),
            artifact_kind="html",
        ),
    )

    out = build_watch_publish_payload(
        path=p,
        raw=("<h1>Hello</h1>" + ("x" * 100)).encode("utf-8"),
        watch_config=WatchConfig(path=p, kind="auto", encoding="utf-8"),
        read_mode="head",
        max_bytes=1000,
        max_rows=10,
    )

    assert out.kind == "artifact"
    assert out.artifact_kind == "html"
    assert isinstance(out.artifact, str)
    assert out.artifact.startswith("<h1>Hello</")
    assert "truncated" in out.artifact
    assert "limits.render.html" in out.artifact


def test_build_watch_publish_payload_does_not_truncate_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pd = pytest.importorskip("pandas")

    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    df = pd.DataFrame({"a": [1]})

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 1)
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


def test_effective_watch_tail_read_uses_smaller_of_watch_and_render_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import get_effective_watch_read_max_bytes

    p = tmp_path / "app.log"
    p.write_text("x" * 100, encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 10)

    assert (
        get_effective_watch_read_max_bytes(
            p,
            read_mode="tail",
            max_bytes=50,
            watch_config=WatchConfig(path=p, kind="text"),
        )
        == 10
    )


def test_effective_watch_tail_read_uses_render_limit_when_watch_limit_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import get_effective_watch_read_max_bytes

    p = tmp_path / "app.log"
    p.write_text("x" * 100, encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 12)

    assert (
        get_effective_watch_read_max_bytes(
            p,
            read_mode="tail",
            max_bytes=None,
            watch_config=WatchConfig(path=p, kind="text"),
        )
        == 12
    )


def test_effective_watch_tail_read_uses_watch_limit_when_render_limit_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import get_effective_watch_read_max_bytes

    p = tmp_path / "app.log"
    p.write_text("x" * 100, encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: None)

    assert (
        get_effective_watch_read_max_bytes(
            p,
            read_mode="tail",
            max_bytes=25,
            watch_config=WatchConfig(path=p, kind="text"),
        )
        == 25
    )


def test_effective_watch_tail_read_has_no_limit_when_both_limits_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import get_effective_watch_read_max_bytes

    p = tmp_path / "app.log"
    p.write_text("x" * 100, encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: None)

    assert (
        get_effective_watch_read_max_bytes(
            p,
            read_mode="tail",
            max_bytes=None,
            watch_config=WatchConfig(path=p, kind="text"),
        )
        is None
    )


def test_effective_watch_read_does_not_apply_render_limit_to_head_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import get_effective_watch_read_max_bytes

    p = tmp_path / "app.log"
    p.write_text("x" * 100, encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 10)

    assert (
        get_effective_watch_read_max_bytes(
            p,
            read_mode="head",
            max_bytes=50,
            watch_config=WatchConfig(path=p, kind="text"),
        )
        == 50
    )


def test_read_watch_file_bytes_tail_uses_render_window_when_smaller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import read_watch_file_bytes

    p = tmp_path / "app.log"
    p.write_text("0123456789ABCDEFGHIJ", encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 6)

    raw = read_watch_file_bytes(
        p,
        read_mode="tail",
        max_bytes=20,
        watch_config=WatchConfig(path=p, kind="text"),
    )

    assert raw == b"EFGHIJ"


def test_read_watch_file_bytes_tail_uses_watch_window_when_render_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import read_watch_file_bytes

    p = tmp_path / "app.log"
    p.write_text("0123456789ABCDEFGHIJ", encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: None)

    raw = read_watch_file_bytes(
        p,
        read_mode="tail",
        max_bytes=5,
        watch_config=WatchConfig(path=p, kind="text"),
    )

    assert raw == b"FGHIJ"


def test_read_watch_file_bytes_tail_reads_all_when_both_limits_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import read_watch_file_bytes

    p = tmp_path / "app.log"
    p.write_text("0123456789", encoding="utf-8")

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: None)

    raw = read_watch_file_bytes(
        p,
        read_mode="tail",
        max_bytes=None,
        watch_config=WatchConfig(path=p, kind="text"),
    )

    assert raw == b"0123456789"


def test_csv_tail_does_not_use_render_text_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import read_watch_file_bytes

    p = tmp_path / "data.csv"
    p.write_text(
        "a,b\n" "1,one\n" "2,two\n" "3,three\n" "4,four\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("plotsrv.runtime.get_watch_render_limit", lambda ak: 1)

    raw = read_watch_file_bytes(
        p,
        read_mode="tail",
        max_bytes=20,
        watch_config=WatchConfig(path=p, kind="auto"),
    )

    text = raw.decode("utf-8", errors="replace")

    assert text.startswith("a,b\n")
    assert "4,four" in text


def test_publish_watch_payload_marks_publish_source_watch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plotsrv.runtime import publish_watch_payload

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "plotsrv.runtime.post_publish_payload",
        lambda *, host, port, payload: captured.update(
            {"host": host, "port": port, "payload": payload}
        )
        or True,
    )

    ok = publish_watch_payload(
        host="127.0.0.1",
        port=8000,
        label="log",
        section="watch",
        kind="artifact",
        artifact="hello",
        artifact_kind="text",
    )

    assert ok is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["payload"]["publish_source"] == "watch"
