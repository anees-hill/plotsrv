from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version

from .cli_help import COMMANDS, ROOT_DESCRIPTION, ROOT_EPILOG


def _build_root_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plotsrv",
        description=ROOT_DESCRIPTION,
        epilog=ROOT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="show this help message and exit",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="show the installed version and exit",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=tuple(COMMANDS),
        help="command to run (see below)",
    )
    return parser


def _print_root_help() -> None:
    parser = _build_root_parser()
    parser.print_help()


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args in (["-h"], ["--help"]):
        _print_root_help()
        return 0

    if args == ["--version"]:
        print(f"plotsrv {version('plotsrv')}")
        return 0

    # Help must exit before importing runtime, discovery, or either wizard.
    option_args = args[:args.index("--")] if "--" in args else args
    if any(arg in ("-h", "--help") for arg in option_args):
        from .cli_parser import build_parser

        build_parser().parse_args(args)
        return 0

    if args[:2] == ["config", "init"]:
        # The optional configuration UI needs neither server nor renderer imports.
        from .cli_parser import build_parser
        from .config_wizard import launch

        return launch(build_parser().parse_args(args))

    if args[:2] == ["config", "ui"]:
        from .cli_parser import build_parser
        from .ui_customiser import launch

        return launch(build_parser().parse_args(args))

    from .cli import main as full_main

    return full_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
