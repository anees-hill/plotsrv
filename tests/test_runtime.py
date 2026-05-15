from __future__ import annotations

from pathlib import Path

import pytest

from plotsrv import settings
from plotsrv.runtime import (
    WatchConfig,
    apply_runtime_options,
    coerce_watch_config,
    coerce_watch_configs,
    default_watch_read_mode,
    parse_truncate_arg,
    parse_watch_max_bytes,
    read_csv_tail_with_header_bytes,
    read_head_bytes,
    read_tail_bytes,
)


def test_parse_truncate_arg() -> None:
    assert parse_truncate_arg(None, no_truncate=False) is settings._UNSET
    assert parse_truncate_arg("off", no_truncate=False) is settings._TRUNCATE_OFF
    assert parse_truncate_arg("none", no_truncate=False) is settings._TRUNCATE_OFF
    assert parse_truncate_arg(60_000, no_truncate=False) == 60_000
    assert parse_truncate_arg("60000", no_truncate=False) == 60_000
    assert parse_truncate_arg("bad", no_truncate=False) is settings._UNSET
    assert parse_truncate_arg(60_000, no_truncate=True) is settings._TRUNCATE_OFF


def test_coerce_watch_config_from_dataclass() -> None:
    cfg = WatchConfig(path="README.md", label="readme")
    assert coerce_watch_config(cfg) is cfg


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
    assert out[1].path == "b.txt"
    assert out[1].label == "B"


def test_parse_watch_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("plotsrv.runtime.config.get_watch_max_bytes", lambda: 5_000_000)

    assert parse_watch_max_bytes(None) == 5_000_000
    assert parse_watch_max_bytes("off") is None
    assert parse_watch_max_bytes("none") is None
    assert parse_watch_max_bytes("0") is None
    assert parse_watch_max_bytes(123) == 123
    assert parse_watch_max_bytes("123") == 123
    assert parse_watch_max_bytes(False) is None

    with pytest.raises(ValueError):
        parse_watch_max_bytes("bad")


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
