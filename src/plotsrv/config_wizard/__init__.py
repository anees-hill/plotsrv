"""Dependency-free sequential configuration wizard."""

from __future__ import annotations

import sys


def launch(args) -> int:
    from .draft import Draft
    from .flow import run
    from .inputs import Prompts
    from .saving import SaveError

    try:
        draft = Draft.load(config=args.config, name=args.name, target=args.target)
        run(draft, Prompts())
    except (KeyboardInterrupt, EOFError):
        print("\nConfiguration cancelled. No files changed.", file=sys.stderr)
        return 130
    except (SaveError, ValueError, OSError) as error:
        print(f"Cannot complete configuration: {error}", file=sys.stderr)
        return 2
    return 0
