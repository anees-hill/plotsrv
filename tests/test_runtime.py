from __future__ import annotations

from pathlib import Path

import pytest

from plotsrv import settings
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
    read_head_bytes,
    read_tail_bytes,
    register_watch_views,
    resolve_watch_max_bytes,
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

    out = register_watch_views([WatchConfig(path=p)])

    assert len(out) == 1
    assert out[0].path == p.resolve()
    assert out[0].section == "watch"
    assert out[0].label == "README.md"
    assert out[0].kind == "artifact"
    assert out[0].read_mode == "head"

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
