from __future__ import annotations

from pathlib import Path

import pytest

from plotsrv import settings
import plotsrv.store as store
from plotsrv.runtime import (
    WatchConfig,
    _WATCH_MAX_BYTES_UNSET,
    apply_runtime_options,
    build_watched_file_meta,
    coerce_watch_config,
    coerce_watch_configs,
    default_watch_read_mode,
    parse_truncate_arg,
    parse_watch_max_bytes,
    read_csv_tail_with_header_bytes,
    read_file_backed_artifact_preview,
    read_head_bytes,
    read_tail_bytes,
    register_watch_views,
    resolve_watch_max_bytes,
    resolve_watch_materialization,
    coerce_watch_materialization_request,
    watch_config_from_meta,
    note_file_backed_watch_change,
    refresh_watched_file_meta,
    count_csv_data_rows,
    read_file_backed_csv_preview,
    start_watch_threads,
)


def test_parse_truncate_arg() -> None:
    assert parse_truncate_arg(None, no_truncate=False) is settings._UNSET
    assert parse_truncate_arg("off", no_truncate=False) is settings._TRUNCATE_OFF
    assert parse_truncate_arg("none", no_truncate=False) is settings._TRUNCATE_OFF
    assert parse_truncate_arg(60_000, no_truncate=False) == 60_000
    assert parse_truncate_arg("60000", no_truncate=False) == 60_000
    assert parse_truncate_arg("bad", no_truncate=False) is settings._UNSET
    assert parse_truncate_arg(60_000, no_truncate=True) is settings._TRUNCATE_OFF


def test_parse_watch_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_max_bytes", lambda view_id=None: 5_000_000
    )

    assert parse_watch_max_bytes(None) == 5_000_000
    assert parse_watch_max_bytes("off") is None
    assert parse_watch_max_bytes("none") is None
    assert parse_watch_max_bytes("0") is None
    assert parse_watch_max_bytes(123) == 123
    assert parse_watch_max_bytes("123") == 123
    assert parse_watch_max_bytes(False) is None

    with pytest.raises(ValueError):
        parse_watch_max_bytes("bad")


def test_watch_config_default_max_bytes_is_unset() -> None:
    cfg = WatchConfig(path="README.md")
    assert cfg.max_bytes is _WATCH_MAX_BYTES_UNSET


def test_coerce_watch_config_from_dataclass() -> None:
    cfg = WatchConfig(path="README.md", label="readme")
    assert coerce_watch_config(cfg) is cfg
    assert cfg.max_bytes is _WATCH_MAX_BYTES_UNSET


def test_coerce_watch_config_from_mapping() -> None:
    cfg = coerce_watch_config(
        {
            "path": "README.md",
            "label": "readme",
            "section": "docs",
            "kind": "text",
            "read_mode": "tail",
            "max_bytes": 123,
            "encoding": "utf-8",
            "update_limit_s": 10,
            "force": True,
        }
    )

    assert cfg.path == "README.md"
    assert cfg.label == "readme"
    assert cfg.section == "docs"
    assert cfg.kind == "text"
    assert cfg.read_mode == "tail"
    assert cfg.max_bytes == 123
    assert cfg.encoding == "utf-8"
    assert cfg.update_limit_s == 10
    assert cfg.force is True


def test_coerce_watch_config_omitted_max_bytes_is_unset() -> None:
    cfg = coerce_watch_config({"path": "README.md"})
    assert cfg.max_bytes is _WATCH_MAX_BYTES_UNSET


def test_coerce_watch_config_accepts_max_bytes_off() -> None:
    cfg = coerce_watch_config({"path": "README.md", "max_bytes": "off"})
    assert cfg.max_bytes is None


def test_coerce_watch_config_rejects_bad_kind() -> None:
    with pytest.raises(ValueError):
        coerce_watch_config({"path": "x.txt", "kind": "bad"})


def test_coerce_watch_config_rejects_bad_read_mode() -> None:
    with pytest.raises(ValueError):
        coerce_watch_config({"path": "x.txt", "read_mode": "middle"})


def test_coerce_watch_config_requires_path() -> None:
    with pytest.raises(ValueError):
        coerce_watch_config({"label": "x"})


def test_coerce_watch_configs() -> None:
    out = coerce_watch_configs(
        [
            WatchConfig(path="a.txt"),
            {"path": "b.txt", "label": "B"},
        ]
    )

    assert len(out) == 2
    assert out[0].path == "a.txt"
    assert out[0].max_bytes is _WATCH_MAX_BYTES_UNSET
    assert out[1].path == "b.txt"
    assert out[1].label == "B"
    assert out[1].max_bytes is _WATCH_MAX_BYTES_UNSET


def test_resolve_watch_max_bytes_uses_global_config_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_max_bytes",
        lambda view_id=None: 123,
    )

    spec = WatchConfig(path="app.log")
    assert resolve_watch_max_bytes(spec, view_id="logs:api") == 123


def test_resolve_watch_max_bytes_respects_explicit_off() -> None:
    spec = WatchConfig(path="app.log", max_bytes=None)
    assert resolve_watch_max_bytes(spec, view_id="logs:api") is None


def test_resolve_watch_max_bytes_respects_explicit_number() -> None:
    spec = WatchConfig(path="app.log", max_bytes=456)
    assert resolve_watch_max_bytes(spec, view_id="logs:api") == 456


def test_default_watch_read_mode_by_file_kind(tmp_path: Path) -> None:
    cases = {
        "x.csv": "head",
        "x.json": "head",
        "x.yaml": "head",
        "x.yml": "head",
        "x.toml": "head",
        "x.ini": "head",
        "x.cfg": "head",
        "x.md": "head",
        "x.html": "head",
        "x.png": "head",
        "x.log": "tail",
        "x.txt": "tail",
        "x": "tail",
    }

    for name, expected in cases.items():
        p = tmp_path / name
        p.write_text("hello\n", encoding="utf-8")
        assert default_watch_read_mode(p) == expected


def test_read_tail_bytes_drops_first_partial_line(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    p.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")

    out = read_tail_bytes(p, max_bytes=12)

    assert out == b"line-3\n"


def test_read_head_bytes_drops_last_partial_line(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    p.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")

    out = read_head_bytes(p, max_bytes=12)

    assert out == b"line-1\n"


def test_read_bytes_small_file_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    p.write_text("line-1\nline-2\n", encoding="utf-8")

    assert read_head_bytes(p, max_bytes=1000) == b"line-1\nline-2\n"
    assert read_tail_bytes(p, max_bytes=1000) == b"line-1\nline-2\n"


def test_read_bytes_single_line_not_emptied(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    p.write_text("abcdef", encoding="utf-8")

    assert read_head_bytes(p, max_bytes=3) == b"abc"
    assert read_tail_bytes(p, max_bytes=3) == b"def"


def test_read_bytes_none_reads_full_file(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    p.write_text("line-1\nline-2\n", encoding="utf-8")

    assert read_head_bytes(p, max_bytes=None) == b"line-1\nline-2\n"
    assert read_tail_bytes(p, max_bytes=None) == b"line-1\nline-2\n"


def test_read_csv_tail_with_header_drops_partial_row(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text(
        "a,b\n" "1,one\n" "2,two\n" "3,three\n" "4,four\n",
        encoding="utf-8",
    )

    out = read_csv_tail_with_header_bytes(p, max_bytes=15)
    text = out.decode("utf-8")

    assert text.startswith("a,b\n")
    assert "4,four\n" in text
    assert "three\n" not in text  # partial row should not survive


def test_read_csv_tail_with_header_none_reads_full_file(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    content = "a,b\n1,one\n2,two\n"
    p.write_text(content, encoding="utf-8")

    out = read_csv_tail_with_header_bytes(p, max_bytes=None)

    assert out == content.encode("utf-8")


def test_register_watch_views_registers_text_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "README.md"
    p.write_text("# hello\n", encoding="utf-8")

    calls: list[dict[str, object]] = []
    active: list[str] = []

    def fake_register_view(**kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr("plotsrv.runtime.store.register_view", fake_register_view)
    monkeypatch.setattr("plotsrv.runtime.store.get_active_view_id", lambda: None)
    monkeypatch.setattr("plotsrv.runtime.store.set_active_view", active.append)

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "memory",
    )

    out = register_watch_views([WatchConfig(path=p)])

    assert len(out) == 1
    assert out[0].path == p.resolve()
    assert out[0].section == "watch"
    assert out[0].label == "README.md"
    assert out[0].kind == "artifact"
    assert out[0].read_mode == "head"
    assert out[0].materialization in ("memory", "file")
    assert out[0].materialization == "memory"

    assert calls == [
        {
            "view_id": "watch:README.md",
            "section": "watch",
            "label": "README.md",
            "kind": "artifact",
            "activate_if_first": False,
        }
    ]
    assert active == ["watch:README.md"]


def test_register_watch_views_registers_csv_as_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")

    calls: list[dict[str, object]] = []
    active: list[str] = []

    monkeypatch.setattr(
        "plotsrv.runtime.store.register_view",
        lambda **kwargs: calls.append(dict(kwargs)),
    )
    monkeypatch.setattr("plotsrv.runtime.store.get_active_view_id", lambda: None)
    monkeypatch.setattr("plotsrv.runtime.store.set_active_view", active.append)

    out = register_watch_views([WatchConfig(path=p)])

    assert len(out) == 1
    assert out[0].kind == "table"
    assert out[0].read_mode == "head"
    assert calls[0]["kind"] == "table"
    assert active == ["watch:data.csv"]


def test_register_watch_views_respects_label_and_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "plotsrv.runtime.store.register_view",
        lambda **kwargs: calls.append(dict(kwargs)),
    )
    monkeypatch.setattr("plotsrv.runtime.store.get_active_view_id", lambda: None)
    monkeypatch.setattr("plotsrv.runtime.store.set_active_view", lambda _vid: None)

    out = register_watch_views(
        [WatchConfig(path=p, label="api", section="logs", read_mode="tail")]
    )

    assert out[0].view_id == "logs:api"
    assert out[0].section == "logs"
    assert out[0].label == "api"
    assert out[0].read_mode == "tail"

    assert calls[0]["view_id"] == "logs:api"
    assert calls[0]["section"] == "logs"
    assert calls[0]["label"] == "api"


def test_register_watch_views_does_not_override_existing_active_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    active_calls: list[str] = []

    monkeypatch.setattr("plotsrv.runtime.store.register_view", lambda **kwargs: None)
    monkeypatch.setattr(
        "plotsrv.runtime.store.get_active_view_id",
        lambda: "existing:view",
    )
    monkeypatch.setattr("plotsrv.runtime.store.set_active_view", active_calls.append)

    out = register_watch_views([WatchConfig(path=p)])

    assert len(out) == 1
    assert active_calls == []


def test_register_watch_views_can_skip_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    active_calls: list[str] = []

    monkeypatch.setattr("plotsrv.runtime.store.register_view", lambda **kwargs: None)
    monkeypatch.setattr("plotsrv.runtime.store.get_active_view_id", lambda: None)
    monkeypatch.setattr("plotsrv.runtime.store.set_active_view", active_calls.append)

    out = register_watch_views(
        [WatchConfig(path=p)],
        activate_first_if_none=False,
    )

    assert len(out) == 1
    assert active_calls == []


def test_start_watch_threads_can_skip_view_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    register_calls: list[dict[str, object]] = []
    thread_calls: list[dict[str, object]] = []

    class FakeThread:
        def __init__(self, **kwargs: object) -> None:
            thread_calls.append(dict(kwargs))

        def start(self) -> None:
            pass

    monkeypatch.setattr(
        "plotsrv.runtime.store.register_view",
        lambda **kwargs: register_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr("plotsrv.runtime.threading.Thread", FakeThread)

    from plotsrv.runtime import start_watch_threads

    threads = start_watch_threads(
        [WatchConfig(path=p)],
        host="127.0.0.1",
        port=8000,
        register_views=False,
    )

    assert len(threads) == 1
    assert register_calls == []
    assert len(thread_calls) == 1


def test_start_watch_threads_registers_views_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    register_calls: list[dict[str, object]] = []
    active_calls: list[str] = []

    class FakeThread:
        def __init__(self, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr(
        "plotsrv.runtime.store.register_view",
        lambda **kwargs: register_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr("plotsrv.runtime.store.get_active_view_id", lambda: None)
    monkeypatch.setattr("plotsrv.runtime.store.set_active_view", active_calls.append)
    monkeypatch.setattr("plotsrv.runtime.threading.Thread", FakeThread)

    from plotsrv.runtime import start_watch_threads

    threads = start_watch_threads(
        [WatchConfig(path=p)],
        host="127.0.0.1",
        port=8000,
    )

    assert len(threads) == 1
    assert len(register_calls) == 1
    assert register_calls[0]["view_id"] == "watch:app.log"
    assert active_calls == ["watch:app.log"]


def test_build_watched_file_meta_from_registered_view(tmp_path: Path) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    registered = register_watch_views(
        [WatchConfig(path=p, label="api", section="logs", read_mode="tail")],
        activate_first_if_none=False,
    )[0]

    meta = build_watched_file_meta(
        registered=registered,
        spec=WatchConfig(path=p, label="api", section="logs", read_mode="tail"),
        materialization="file",
        max_bytes=123,
    )

    assert meta.view_id == "logs:api"
    assert meta.path == str(p.resolve())
    assert meta.file_kind == "unknown"
    assert meta.read_mode == "tail"
    assert meta.encoding == "utf-8"
    assert meta.materialization == "file"
    assert meta.size_bytes == len("hello\n".encode("utf-8"))
    assert isinstance(meta.mtime_ns, int)
    assert meta.max_bytes == 123
    assert meta.last_error is None


def test_build_watched_file_meta_records_stat_error(tmp_path: Path) -> None:
    p = tmp_path / "missing.log"

    # Build a RegisteredWatchView directly so we do not require the path to
    # exist during normal registration.
    from plotsrv.runtime import RegisteredWatchView

    registered = RegisteredWatchView(
        path=p.resolve(),
        view_id="logs:missing",
        section="logs",
        label="missing",
        kind="artifact",
        read_mode="tail",
    )

    spec = WatchConfig(path=p, label="missing", section="logs", read_mode="tail")

    meta = build_watched_file_meta(
        registered=registered,
        spec=spec,
        materialization="file",
        max_bytes=None,
    )

    assert meta.view_id == "logs:missing"
    assert meta.path == str(p.resolve())
    assert meta.file_kind == "unknown"
    assert meta.size_bytes is None
    assert meta.mtime_ns is None
    assert meta.last_error is not None
    assert "FileNotFoundError" in meta.last_error


def test_coerce_watch_materialization_request_valid_values() -> None:
    assert coerce_watch_materialization_request("auto") == "auto"
    assert coerce_watch_materialization_request("memory") == "memory"
    assert coerce_watch_materialization_request("file") == "file"
    assert coerce_watch_materialization_request(" FILE ") == "file"


def test_coerce_watch_materialization_request_invalid_uses_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_materialization",
        lambda: "auto",
    )

    assert coerce_watch_materialization_request(None) == "auto"
    assert coerce_watch_materialization_request("") == "auto"
    assert coerce_watch_materialization_request("banana") == "auto"


def test_resolve_watch_materialization_explicit_memory(tmp_path: Path) -> None:
    p = tmp_path / "big.log"
    p.write_text("x" * 100, encoding="utf-8")

    assert resolve_watch_materialization(p, requested="memory") == "memory"


def test_resolve_watch_materialization_explicit_file_for_missing_path(
    tmp_path: Path,
) -> None:
    p = tmp_path / "missing.log"

    assert resolve_watch_materialization(p, requested="file") == "file"


def test_resolve_watch_materialization_auto_small_file_uses_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "small.log"
    p.write_text("small", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_file_threshold_bytes",
        lambda: 10,
    )

    assert resolve_watch_materialization(p, requested="auto") == "memory"


def test_resolve_watch_materialization_auto_large_file_uses_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.log"
    p.write_text("x" * 10, encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_file_threshold_bytes",
        lambda: 10,
    )

    assert resolve_watch_materialization(p, requested="auto") == "file"


def test_resolve_watch_materialization_auto_missing_path_uses_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "missing.log"

    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_file_threshold_bytes",
        lambda: 10,
    )

    assert resolve_watch_materialization(p, requested="auto") == "memory"


def test_resolve_watch_materialization_uses_config_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.log"
    p.write_text("x" * 10, encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_materialization",
        lambda: "auto",
    )
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_file_threshold_bytes",
        lambda: 10,
    )

    assert resolve_watch_materialization(p) == "file"


def test_register_watch_views_stores_memory_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "memory",
    )
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_max_bytes",
        lambda view_id=None: 123,
    )

    import plotsrv.store as store

    store.reset()
    try:
        out = register_watch_views(
            [WatchConfig(path=p, label="api", section="logs", read_mode="tail")]
        )

        assert len(out) == 1
        assert out[0].materialization == "memory"

        meta = store.get_watched_file_meta(view_id="logs:api")

        assert meta.view_id == "logs:api"
        assert meta.path == str(p.resolve())
        assert meta.read_mode == "tail"
        assert meta.materialization == "memory"
        assert meta.max_bytes == 123
        assert meta.size_bytes == len("hello\n".encode("utf-8"))
        assert meta.last_error is None
    finally:
        store.reset()


def test_register_watch_views_stores_file_backed_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.log"
    p.write_text("x" * 20, encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_watch_max_bytes",
        lambda view_id=None: 456,
    )

    import plotsrv.store as store

    store.reset()
    try:
        out = register_watch_views([WatchConfig(path=p)])

        assert out[0].view_id == "watch:large.log"
        assert out[0].materialization == "file"

        meta = store.get_watched_file_meta(view_id="watch:large.log")

        assert meta.materialization == "file"
        assert meta.path == str(p.resolve())
        assert meta.max_bytes == 456
        assert meta.size_bytes == 20
    finally:
        store.reset()


def _watched_meta(
    path: Path,
    *,
    file_kind: str = "unknown",
    read_mode: str = "tail",
    encoding: str = "utf-8",
    max_bytes: int | None = None,
) -> store.WatchFileMeta:
    import plotsrv.store as store

    p = path.resolve()
    size_bytes = None
    mtime_ns = None

    if p.exists():
        st = p.stat()
        size_bytes = int(st.st_size)
        mtime_ns = int(st.st_mtime_ns)

    return store.WatchedFileMeta(
        view_id="watch:test",
        path=str(p),
        file_kind=file_kind,
        read_mode=read_mode,  # type: ignore[arg-type]
        encoding=encoding,
        materialization="file",
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        max_bytes=max_bytes,
    )


def test_watch_config_from_meta_uses_json_kind(tmp_path: Path) -> None:
    meta = _watched_meta(
        tmp_path / "data.json",
        file_kind="json",
        read_mode="head",
        max_bytes=123,
    )

    cfg = watch_config_from_meta(meta)  # type: ignore[arg-type]

    assert cfg.path == meta.path
    assert cfg.kind == "json"
    assert cfg.read_mode == "head"
    assert cfg.max_bytes == 123
    assert cfg.encoding == "utf-8"


def test_watch_config_from_meta_uses_auto_for_text_like_files(tmp_path: Path) -> None:
    meta = _watched_meta(
        tmp_path / "README.md",
        file_kind="markdown",
        read_mode="head",
        max_bytes=456,
    )

    cfg = watch_config_from_meta(meta)  # type: ignore[arg-type]

    assert cfg.kind == "auto"
    assert cfg.read_mode == "head"
    assert cfg.max_bytes == 456


def test_read_file_backed_artifact_preview_unknown_tail_text(tmp_path: Path) -> None:
    p = tmp_path / "app.log"
    p.write_text("first\nsecond\nthird\n", encoding="utf-8")

    meta = _watched_meta(
        p,
        file_kind="unknown",
        read_mode="tail",
        max_bytes=12,
    )

    out = read_file_backed_artifact_preview(meta)  # type: ignore[arg-type]

    assert out.artifact_kind == "text"
    assert isinstance(out.artifact, str)
    assert str(out.artifact).startswith("\ufeffPLOTSRV_ANCHOR=tail\n")
    assert "third" in out.artifact
    assert "first" not in out.artifact
    assert out.raw == b"third\n"


def test_read_file_backed_artifact_preview_markdown_head(tmp_path: Path) -> None:
    p = tmp_path / "README.md"
    p.write_text("# Title\n\nHello", encoding="utf-8")

    meta = _watched_meta(
        p,
        file_kind="markdown",
        read_mode="head",
        max_bytes=100,
    )

    out = read_file_backed_artifact_preview(meta)  # type: ignore[arg-type]

    assert out.artifact_kind == "markdown"
    assert out.artifact == "# Title\n\nHello"
    assert out.raw == b"# Title\n\nHello"


def test_read_file_backed_artifact_preview_html_head(tmp_path: Path) -> None:
    p = tmp_path / "page.html"
    p.write_text("<h1>Hello</h1>", encoding="utf-8")

    meta = _watched_meta(
        p,
        file_kind="html",
        read_mode="head",
        max_bytes=100,
    )

    out = read_file_backed_artifact_preview(meta)  # type: ignore[arg-type]

    assert out.artifact_kind == "html"
    assert out.artifact == "<h1>Hello</h1>"
    assert out.raw == b"<h1>Hello</h1>"


def test_read_file_backed_artifact_preview_json_head(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    meta = _watched_meta(
        p,
        file_kind="json",
        read_mode="head",
        max_bytes=100,
    )

    out = read_file_backed_artifact_preview(meta)  # type: ignore[arg-type]

    assert out.artifact_kind == "json"
    assert out.artifact == {"a": 1}
    assert out.raw == b'{"a": 1}'


def test_read_file_backed_artifact_preview_rejects_csv(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    meta = _watched_meta(
        p,
        file_kind="csv",
        read_mode="head",
        max_bytes=100,
    )

    with pytest.raises(TypeError, match="CSV"):
        read_file_backed_artifact_preview(meta)  # type: ignore[arg-type]


def test_read_file_backed_artifact_preview_rejects_image(tmp_path: Path) -> None:
    p = tmp_path / "image.png"
    p.write_bytes(b"not really png")

    meta = _watched_meta(
        p,
        file_kind="image",
        read_mode="head",
        max_bytes=100,
    )

    with pytest.raises(TypeError, match="image"):
        read_file_backed_artifact_preview(meta)  # type: ignore[arg-type]


def test_refresh_watched_file_meta_updates_size(
    tmp_path: Path,
) -> None:
    import plotsrv.store as store
    from plotsrv.runtime import RegisteredWatchView

    p = tmp_path / "app.log"
    p.write_text("one\n", encoding="utf-8")

    registered = RegisteredWatchView(
        path=p.resolve(),
        view_id="logs:api",
        section="logs",
        label="api",
        kind="artifact",
        read_mode="tail",
        materialization="file",
    )
    spec = WatchConfig(path=p, label="api", section="logs", read_mode="tail")

    store.reset()
    try:
        meta1 = refresh_watched_file_meta(registered=registered, spec=spec)
        assert meta1.size_bytes == len("one\n".encode("utf-8"))

        p.write_text("one\ntwo\n", encoding="utf-8")

        meta2 = refresh_watched_file_meta(registered=registered, spec=spec)
        assert meta2.size_bytes == len("one\ntwo\n".encode("utf-8"))

        stored = store.get_watched_file_meta(view_id="logs:api")
        assert stored.size_bytes == meta2.size_bytes
        assert stored.materialization == "file"
    finally:
        store.reset()


def test_note_file_backed_watch_change_marks_success(
    tmp_path: Path,
) -> None:
    import plotsrv.store as store
    from plotsrv.runtime import RegisteredWatchView

    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    registered = RegisteredWatchView(
        path=p.resolve(),
        view_id="logs:api",
        section="logs",
        label="api",
        kind="artifact",
        read_mode="tail",
        materialization="file",
    )
    spec = WatchConfig(path=p, label="api", section="logs", read_mode="tail")

    store.reset()
    try:
        store.register_view(
            view_id="logs:api",
            section="logs",
            label="api",
            kind="artifact",
            activate_if_first=False,
        )

        note_file_backed_watch_change(registered=registered, spec=spec)

        status = store.get_status(view_id="logs:api")
        assert status["last_error"] is None
        assert status["publish_source"] == "watch"

        meta = store.get_watched_file_meta(view_id="logs:api")
        assert meta.materialization == "file"
        assert meta.size_bytes == len("hello\n".encode("utf-8"))
    finally:
        store.reset()


def test_start_watch_threads_file_backed_does_not_read_or_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "large.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    read_calls: list[object] = []
    publish_calls: list[object] = []
    note_calls: list[object] = []

    def fake_read_watch_file_bytes(*args: object, **kwargs: object) -> bytes:
        read_calls.append((args, kwargs))
        return b"should-not-read"

    def fake_publish_prepared_watch_payload(*args: object, **kwargs: object) -> bool:
        publish_calls.append((args, kwargs))
        return True

    def fake_note_file_backed_watch_change(**kwargs: object) -> None:
        note_calls.append(kwargs)

    class FakeThread:
        def __init__(self, *, target, **kwargs: object) -> None:
            self.target = target

        def start(self) -> None:
            # Run once. Stop the infinite loop after the first sleep.
            self.target()

    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "plotsrv.runtime.read_watch_file_bytes",
        fake_read_watch_file_bytes,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.publish_prepared_watch_payload",
        fake_publish_prepared_watch_payload,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.note_file_backed_watch_change",
        fake_note_file_backed_watch_change,
    )
    monkeypatch.setattr("plotsrv.runtime.threading.Thread", FakeThread)
    monkeypatch.setattr("plotsrv.runtime.time.sleep", fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        start_watch_threads(
            [WatchConfig(path=p, label="large", section="logs")],
            host="127.0.0.1",
            port=8000,
            register_views=True,
        )

    assert len(note_calls) == 1
    assert read_calls == []
    assert publish_calls == []


def test_start_watch_threads_memory_backed_still_reads_and_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "small.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "memory",
    )

    read_calls: list[object] = []
    publish_calls: list[object] = []
    note_calls: list[object] = []

    def fake_read_watch_file_bytes(*args: object, **kwargs: object) -> bytes:
        read_calls.append((args, kwargs))
        return b"hello\n"

    def fake_publish_prepared_watch_payload(*args: object, **kwargs: object) -> bool:
        publish_calls.append((args, kwargs))
        return True

    def fake_note_file_backed_watch_change(**kwargs: object) -> None:
        note_calls.append(kwargs)

    class FakeThread:
        def __init__(self, *, target, **kwargs: object) -> None:
            self.target = target

        def start(self) -> None:
            self.target()

    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "plotsrv.runtime.read_watch_file_bytes",
        fake_read_watch_file_bytes,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.publish_prepared_watch_payload",
        fake_publish_prepared_watch_payload,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.note_file_backed_watch_change",
        fake_note_file_backed_watch_change,
    )
    monkeypatch.setattr("plotsrv.runtime.threading.Thread", FakeThread)
    monkeypatch.setattr("plotsrv.runtime.time.sleep", fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        start_watch_threads(
            [WatchConfig(path=p, label="small", section="logs")],
            host="127.0.0.1",
            port=8000,
            register_views=True,
        )

    assert len(read_calls) == 1
    assert len(publish_calls) == 1
    assert note_calls == []


def test_watch_config_mapping_accepts_materialization() -> None:
    from plotsrv.runtime import coerce_watch_config

    cfg = coerce_watch_config(
        {
            "path": "app.log",
            "materialization": "file",
        }
    )

    assert cfg.materialization == "file"


def test_register_watch_views_uses_materialization_override(
    tmp_path: Path,
) -> None:
    import plotsrv.store as store
    from plotsrv.runtime import WatchConfig, register_watch_views

    p = tmp_path / "small.log"
    p.write_text("hello\n", encoding="utf-8")

    store.reset()
    try:
        registered = register_watch_views(
            [
                WatchConfig(
                    path=p,
                    label="small",
                    section="logs",
                    materialization="file",
                )
            ],
            activate_first_if_none=True,
        )

        assert registered[0].materialization == "file"

        meta = store.get_watched_file_meta(view_id="logs:small")
        assert meta.materialization == "file"
    finally:
        store.reset()


def test_count_csv_data_rows_counts_rows_after_header(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a,b\n1,one\n2,two\n", encoding="utf-8")

    assert count_csv_data_rows(p) == 2


def test_count_csv_data_rows_empty_file_returns_zero(tmp_path: Path) -> None:
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")

    assert count_csv_data_rows(p) == 0


def test_read_file_backed_csv_preview_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text(
        "a,b\n" "1,one\n" "2,two\n" "3,three\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.config.get_table_truncate_rows",
        lambda: 2,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_table_truncate_columns",
        lambda: 10,
    )

    meta = _watched_meta(
        p,
        file_kind="csv",
        read_mode="head",
        max_bytes=1000,
    )

    out = read_file_backed_csv_preview(meta)  # type: ignore[arg-type]

    assert out.source == "file_backed_csv"
    assert out.returned_rows == 2
    assert out.total_rows == 3
    assert out.returned_columns == 2
    assert out.total_columns == 2
    assert out.truncated is True
    assert list(out.table_df["a"]) == [1, 2]
    assert b"3,three" in out.raw


def test_read_file_backed_csv_preview_tail_preserves_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text(
        "a,b\n" "1,one\n" "2,two\n" "3,three\n" "4,four\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.config.get_table_truncate_rows",
        lambda: 10,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_table_truncate_columns",
        lambda: 10,
    )

    meta = _watched_meta(
        p,
        file_kind="csv",
        read_mode="tail",
        max_bytes=12,
    )

    out = read_file_backed_csv_preview(meta)  # type: ignore[arg-type]

    assert out.total_rows == 4
    assert out.returned_rows >= 1
    assert "4" in {str(x) for x in out.table_df["a"].tolist()}
    assert out.raw.startswith(b"a,b\n")
    assert b"4,four" in out.raw
    assert out.truncated is True


def test_read_file_backed_csv_preview_records_column_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "wide.csv"
    p.write_text(
        "a,b,c\n" "1,2,3\n" "4,5,6\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.config.get_table_truncate_rows",
        lambda: 10,
    )
    monkeypatch.setattr(
        "plotsrv.runtime.config.get_table_truncate_columns",
        lambda: 2,
    )

    meta = _watched_meta(
        p,
        file_kind="csv",
        read_mode="head",
        max_bytes=1000,
    )

    out = read_file_backed_csv_preview(meta)  # type: ignore[arg-type]

    assert out.total_columns == 3
    assert out.returned_columns == 2
    assert list(out.table_df.columns) == ["a", "b"]
    assert out.truncated is True


def test_read_file_backed_csv_preview_rejects_non_csv(tmp_path: Path) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    meta = _watched_meta(
        p,
        file_kind="unknown",
        read_mode="tail",
        max_bytes=100,
    )

    with pytest.raises(TypeError, match="csv"):
        read_file_backed_csv_preview(meta)  # type: ignore[arg-type]


def test_read_file_backed_csv_preview_rejects_memory_backed_meta(
    tmp_path: Path,
) -> None:
    import plotsrv.store as store

    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    meta = store.WatchedFileMeta(
        view_id="watch:data",
        path=str(p.resolve()),
        file_kind="csv",
        read_mode="head",
        encoding="utf-8",
        materialization="memory",
        size_bytes=p.stat().st_size,
        mtime_ns=p.stat().st_mtime_ns,
        max_bytes=100,
    )

    with pytest.raises(TypeError, match="file materialization"):
        read_file_backed_csv_preview(meta)
