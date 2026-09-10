"""Optional, invocation-only configuration tool; importing this does not load Textual."""

from __future__ import annotations

import sys


def launch(args) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "plotsrv config init needs an interactive terminal. "
            "Use 'plotsrv config create --help' or 'plotsrv config populate --help' "
            "for noninteractive configuration.",
            file=sys.stderr,
        )
        return 2
    try:
        from .tui import ConfigWizard
    except ModuleNotFoundError as error:
        if error.name != "textual" and not (error.name or "").startswith("textual."):
            raise
        print(
            "The configuration wizard needs the optional extra: "
            "pip install 'plotsrv[config]'. Nothing was installed or changed. "
            "Noninteractive commands: plotsrv config create/populate --help.",
            file=sys.stderr,
        )
        return 2
    from .draft import Draft

    try:
        draft = Draft.load(config=args.config, name=args.name, target=args.target)
        ConfigWizard(draft).run()
    except (ValueError, OSError):
        # YAML/IO exceptions may contain source lines, including credentials.
        print(
            "Cannot open this configuration draft. Check the path and YAML mapping; aliases, duplicate keys and oversized/deep YAML are unsupported. No files changed.",
            file=sys.stderr,
        )
        return 2
    print("Configuration draft closed without saving. No files changed.")
    return 0
