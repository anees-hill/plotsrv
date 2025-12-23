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
