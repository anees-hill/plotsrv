from __future__ import annotations

from pathlib import Path

import pytest

from plotsrv import settings
from plotsrv.runtime import (
    WatchConfig,
    apply_runtime_options,
    coerce_watch_config,
    coerce_watch_configs,
    parse_truncate_arg,
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
