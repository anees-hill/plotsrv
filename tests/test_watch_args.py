# tests/test_watch_args.py
from __future__ import annotations

import pytest

from plotsrv.cli import build_parser, _coerce_watch_specs


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
