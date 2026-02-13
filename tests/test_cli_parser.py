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
            "--refresh-rate",
            "5",
            "--quiet",
        ]
    )
    assert args.cmd == "run"
    assert args.target == "some.mod:fn"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.refresh_rate == 5
    assert args.quiet is True


def test_cli_parses_exclude_args() -> None:
    """
    Parser should accept repeated --exclude arguments.
    """
    p = build_parser()
    args = p.parse_args(
        [
            "run",
            "src",
            "--exclude",
            "Resource Usage:MEM%",
            "--exclude",
            "etl-1:metrics",
        ]
    )
    assert args.cmd == "run"
    assert args.target == "src"
    assert args.exclude == ["Resource Usage:MEM%", "etl-1:metrics"]


def test_cli_parses_include_args() -> None:
    """
    Parser should accept repeated --include arguments.
    """
    p = build_parser()
    args = p.parse_args(
        [
            "run",
            "src",
            "--include",
            "Resource Usage",
            "--include",
            "etl-1:metrics",
        ]
    )
    assert args.cmd == "run"
    assert args.target == "src"
    assert args.include == ["Resource Usage", "etl-1:metrics"]
