"""Terminal adapter for reusable discovery events; no terminal dependency."""

from __future__ import annotations

import sys
import time
from .discovery import DiscoveryProgress


class TerminalProgress:
    def __init__(self, *, quiet: bool = False, unscoped: bool = False, stream=None):
        self.stream = stream if stream is not None else sys.stderr
        self.quiet = quiet
        self.unscoped = unscoped
        self.last = -float("inf")
        self.phase = None
        self.tick = 0
        self.tip_shown = False
        self.issues_shown = 0

    def __call__(self, event: DiscoveryProgress) -> None:
        if self.quiet:
            return
        tty = self.stream.isatty()
        now = time.monotonic()
        final = event.phase in {"complete", "cancelled", "limited"}
        if (
            not final
            and self.phase == event.phase
            and now - self.last < (0.1 if tty else 2.0)
        ):
            return
        if event.phase == "enumerating":
            status = (
                f"Finding Python files: {event.files_found} found (total not yet known)"
            )
        else:
            status = f"Discovery {event.phase}: {event.processed}/{event.total} files; {event.skipped} skipped or unresolved"
        if tty:
            spinner = "|/-\\"[self.tick % 4]
            self.stream.write(
                "\r\033[2K"
                + ("" if final else spinner + " ")
                + status
                + ("\n" if final else "")
            )
        else:
            self.stream.write(status + "\n")
        self.stream.flush()
        self.tick += 1
        self.last, self.phase = now, event.phase
        if (
            self.unscoped
            and not self.tip_shown
            and (event.files_found >= 1000 or event.elapsed_s >= 5)
        ):
            self.stream.write(
                "\nTip: pass a package or source path to narrow discovery next time.\n"
            )
            self.stream.flush()
            self.tip_shown = True

    def issue(self, entry) -> None:
        if self.quiet or self.issues_shown >= 3:
            return
        self.issues_shown += 1
        self.stream.write(
            f"\nDiscovery: {entry.reason.replace('_', ' ')} in {entry.path[:256]!r}"
            + (f":{entry.line}" if entry.line else "")
            + "; not registered.\n"
        )
        self.stream.flush()
