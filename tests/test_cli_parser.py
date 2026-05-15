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


def test_cli_parses_watch_subcommand_args() -> None:
    p = build_parser()
    args = p.parse_args(
        [
            "watch",
            "app.log",
            "--host",
            "0.0.0.0",
            "--port",
            "8101",
            "--every",
            "0.5",
            "--kind",
            "text",
            "--section",
            "logs",
            "--label",
            "api",
            "--view-id",
            "logs:api",
            "--max-bytes",
            "1234",
            "--encoding",
            "latin-1",
            "--update-limit-s",
            "10",
            "--force",
            "--quiet",
            "--tail",
        ]
    )

    assert args.cmd == "watch"
    assert args.path == "app.log"
    assert args.host == "0.0.0.0"
    assert args.port == 8101
    assert args.every == 0.5
    assert args.kind == "text"
    assert args.section == "logs"
    assert args.label == "api"
    assert args.view_id == "logs:api"
    assert args.max_bytes == "1234"
    assert args.encoding == "latin-1"
    assert args.update_limit_s == 10
    assert args.force is True
    assert args.quiet is True
    assert args.tail is True
    assert args.head is False


def test_cli_parses_store_subcommands() -> None:
    p = build_parser()

    stats = p.parse_args(
        ["store", "--name", "prod", "--config", "plotsrv.yml", "stats"]
    )
    assert stats.cmd == "store"
    assert stats.name == "prod"
    assert stats.config == "plotsrv.yml"
    assert stats.store_cmd == "stats"

    listed = p.parse_args(["store", "list", "--view", "a:b"])
    assert listed.store_cmd == "list"
    assert listed.view == "a:b"

    cleared = p.parse_args(["store", "clear", "--all", "-y"])
    assert cleared.store_cmd == "clear"
    assert cleared.all is True
    assert cleared.yes is True


def test_cli_run_watch_head_tail_binding() -> None:
    p = build_parser()
    args = p.parse_args(
        [
            "run",
            ".",
            "--watch-tail",
            "--watch",
            "a.log",
            "--watch",
            "b.log",
            "--watch-head",
        ]
    )

    assert args.watch == ["a.log", "b.log"]
    assert args.watch_read_mode == ["tail", "head"]


def test_cli_parses_watch_max_bytes_off() -> None:
    p = build_parser()

    run_args = p.parse_args(
        ["run", ".", "--watch", "a.log", "--watch-max-bytes", "off"]
    )
    assert run_args.watch_max_bytes == "off"

    watch_args = p.parse_args(["watch", "a.log", "--max-bytes", "off"])
    assert watch_args.max_bytes == "off"
