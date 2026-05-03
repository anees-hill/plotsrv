# tests/test_watch_args.py
from __future__ import annotations

import pytest

from plotsrv.cli import build_parser, _coerce_watch_specs
import plotsrv.cli as cli_mod
import pytest


def test_watch_head_before_watch_binds_to_next_watch() -> None:
    """
    `--watch-head` before a `--watch` should apply to the NEXT watch,
    due to the pending mode behaviour in _WatchReadModeAction.
    """
    p = build_parser()
    args = p.parse_args(
        [
            "run",
            ".",
            "--watch-head",
            "--watch",
            "a.log",
            "--watch",
            "b.csv",
        ]
    )

    # The first watch should get 'head', second remains None (defaults later)
    assert args.watch == ["a.log", "b.csv"]
    assert args.watch_read_mode == ["head", None]


def test_watch_tail_after_watch_binds_to_most_recent_watch() -> None:
    """
    `--watch-tail` after a `--watch` should bind to that most recent watch.
    """
    p = build_parser()
    args = p.parse_args(
        [
            "run",
            ".",
            "--watch",
            "a.log",
            "--watch-tail",
        ]
    )

    assert args.watch == ["a.log"]
    assert args.watch_read_mode == ["tail"]


def test_coerce_watch_specs_validates_labels_length() -> None:
    with pytest.raises(ValueError) as e:
        _coerce_watch_specs(
            ["a.log", "b.log"],
            labels=["only-one-label"],
            sections=[],
            read_modes=[],
        )
    assert "--watch-label" in str(e.value)


def test_coerce_watch_specs_sections_apply_once_to_all() -> None:
    specs = _coerce_watch_specs(
        ["a.log", "b.log"],
        labels=[],
        sections=["ops"],
        read_modes=["tail", None],
    )

    assert len(specs) == 2
    assert specs[0].section == "ops"
    assert specs[1].section == "ops"
    assert specs[0].read_mode == "tail"
    assert specs[1].read_mode is None


def test_coerce_watch_specs_rejects_too_many_read_modes() -> None:
    with pytest.raises(ValueError) as e:
        _coerce_watch_specs(
            ["a.log"],
            labels=[],
            sections=[],
            read_modes=["head", "tail"],
        )
    assert "watch-head" in str(e.value) or "watch read mode" in str(e.value)


def test_coerce_watch_specs_defaults() -> None:
    specs = cli_mod._coerce_watch_specs(
        ["a.log", "b.log"],
        labels=[],
        sections=[],
        read_modes=[],
    )

    assert specs == [
        cli_mod.WatchSpec(path="a.log", label=None, section="watch", read_mode=None),
        cli_mod.WatchSpec(path="b.log", label=None, section="watch", read_mode=None),
    ]


def test_coerce_watch_specs_one_section_applies_to_all() -> None:
    specs = cli_mod._coerce_watch_specs(
        ["a.log", "b.log"],
        labels=["A", "B"],
        sections=["logs"],
        read_modes=["tail"],
    )

    assert specs[0] == cli_mod.WatchSpec(
        path="a.log", label="A", section="logs", read_mode="tail"
    )
    assert specs[1] == cli_mod.WatchSpec(
        path="b.log", label="B", section="logs", read_mode=None
    )


def test_coerce_watch_specs_per_watch_sections_and_modes() -> None:
    specs = cli_mod._coerce_watch_specs(
        ["a.log", "b.log"],
        labels=["A", "B"],
        sections=["s1", "s2"],
        read_modes=["head", "tail"],
    )

    assert specs == [
        cli_mod.WatchSpec(path="a.log", label="A", section="s1", read_mode="head"),
        cli_mod.WatchSpec(path="b.log", label="B", section="s2", read_mode="tail"),
    ]


def test_coerce_watch_specs_empty_paths_returns_empty() -> None:
    assert (
        cli_mod._coerce_watch_specs(
            ["", "   "],
            labels=[],
            sections=[],
            read_modes=[],
        )
        == []
    )


def test_coerce_watch_specs_bad_read_mode_raises() -> None:
    with pytest.raises(ValueError, match="Invalid watch read mode"):
        cli_mod._coerce_watch_specs(
            ["a.log"],
            labels=[],
            sections=[],
            read_modes=["sideways"],
        )


def test_coerce_watch_specs_too_many_read_modes_raises() -> None:
    with pytest.raises(ValueError, match="too many"):
        cli_mod._coerce_watch_specs(
            ["a.log"],
            labels=[],
            sections=[],
            read_modes=["head", "tail"],
        )
