"""Dependency-free sequential configuration wizard."""

from __future__ import annotations

import sys


def launch(args) -> int:
    from .draft import Draft
    from .flow import run
    from .inputs import Prompts
    from .saving import SaveError

    try:
        if args.source is not None and args.target is not None:
            raise ValueError("Use either --source or the positional discovery target, not both")
        draft = Draft.load(config=args.config, name=args.name, target=args.source or args.target)
        run(draft, Prompts())
    except (KeyboardInterrupt, EOFError):
        print("\nConfiguration cancelled. No files changed.", file=sys.stderr)
        return 130
    except (SaveError, ValueError, OSError) as error:
        print(f"Cannot complete configuration: {error}", file=sys.stderr)
        return 2
    return 0
