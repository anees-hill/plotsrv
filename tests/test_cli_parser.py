# tests/test_cli_parser.py
from __future__ import annotations

from plotsrv.cli import build_parser


def test_cli_parses_run_args() -> None:
    p = build_parser()
    args = p.parse_args(
        [
            "run",
            "some.mod:fn",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--quiet",
        ]
    )

    assert args.cmd == "run"
    assert args.target == "some.mod:fn"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.quiet is True

    # new defaults
    assert args.mode == "passive"
    assert args.call_every is None
    assert args.keep_alive is False


def test_cli_parses_callable_scheduler_args() -> None:
    p = build_parser()
    args = p.parse_args(
        [
            "run",
            "some.mod:fn",
            "--mode",
            "callable",
            "--call-every",
            "2.5",
            "--keep-alive",
        ]
    )

    assert args.cmd == "run"
    assert args.target == "some.mod:fn"
    assert args.mode == "callable"
    assert args.call_every == 2.5
    assert args.keep_alive is True
