from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version


def _build_root_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plotsrv",
        description=(
            "plotsrv - inspect data, files, and live outputs in your browser\n\n"
            "Documentation: https://docs.plotsrv.com"
        ),
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
        choices=("run", "watch", "store", "config"),
        help="run, watch, store, or config",
    )
    return parser


def _print_root_help() -> None:
    parser = _build_root_parser()
    parser.print_help()
    print(
        "\ncommands:\n"
        "  run     Discover and serve project views; optionally execute targets\n"
        "  watch   Watch a file and publish live updates as a view\n"
        "  store   Inspect or clear persisted views and snapshots\n"
        "  config  Create configs or populate settings from discovered views\n"
        "\nRun 'plotsrv COMMAND --help' for command-specific options."
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args in (["-h"], ["--help"]):
        _print_root_help()
        return 0

    if args == ["--version"]:
        print(f"plotsrv {version('plotsrv')}")
        return 0

    from .cli import main as full_main

    return full_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
