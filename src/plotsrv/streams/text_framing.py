"""Bounded physical framing, independent of log meaning or stream delivery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import BinaryIO

MAX_LINE_BYTES = 4096
MAX_FRAME_BYTES = 8192
MAX_FRAME_LINES = 32
MAX_CYCLE_BYTES = 64 * 1024
MAX_CYCLE_LINES = 128
FRAME_WAIT_S = 1.0

_ANSI = re.compile(rb"\x1b\[[0-?]{0,64}[ -/]{0,16}[@-~]")

TRACEBACK = b"Traceback (most recent call last):"
CHAINS = (
    b"During handling of the above exception, another exception occurred:",
    b"The above exception was the direct cause of the following exception:",
)


@dataclass(slots=True)
class ReadBudget:
    bytes_left: int = MAX_CYCLE_BYTES
    lines_left: int = MAX_CYCLE_LINES

    def line(self, source: BinaryIO, limit: int = MAX_LINE_BYTES + 1) -> bytes | None:
        if self.bytes_left < limit or self.lines_left <= 0:
            return None
        raw = source.readline(min(limit, self.bytes_left))
        self.bytes_left -= len(raw)
        self.lines_left -= 1
        return raw


@dataclass(frozen=True, slots=True)
class TextFrame:
    raw: bytes
    start: int
    end: int
    kind: str = "text"
    partial: bool = False
    truncated: bool = False
    ambiguous: bool = False


class TextFramer:
    """Read a frame with at most one bounded line of lookahead.

    An incomplete frame is reread from its offset during the one-second grace
    period; no growing partial payload is retained between polls. A long line
    emits its prefix once, then discards its suffix in bounded turns. The caller
    must acknowledge that notice before committing later skipped byte ranges.
    """

    def __init__(self) -> None:
        self.discarding = False
        self.waiting_offset: int | None = None
        self.waiting_since = 0.0
        self.continuation = False

    def read(
        self,
        source: BinaryIO,
        offset: int,
        *,
        now: float,
        budget: ReadBudget,
        finalize: bool = False,
    ) -> tuple[TextFrame | None, int]:
        source.seek(offset)
        if self.discarding:
            end = offset
            while True:
                raw = budget.line(source)
                if not raw:
                    return None, end
                end += len(raw)
                if raw.endswith(b"\n"):
                    self.discarding = False
                    self.continuation = False
                    return None, end

        raw = budget.line(source)
        if not raw:
            return None, offset
        if self.waiting_offset != offset:
            self.waiting_offset, self.waiting_since = offset, now
        expired = finalize or now - self.waiting_since >= FRAME_WAIT_S
        end = offset + len(raw)
        if len(raw) > MAX_LINE_BYTES:
            self.discarding = not raw.endswith(b"\n")
            ambiguous = self.continuation
            if not self.discarding:
                self.continuation = False
            self.waiting_offset = None
            return (
                TextFrame(
                    raw[:MAX_LINE_BYTES],
                    offset,
                    end,
                    truncated=True,
                    ambiguous=ambiguous,
                ),
                end,
            )
        if not raw.endswith(b"\n"):
            if not expired:
                return None, offset
            frame = TextFrame(
                raw, offset, end, partial=True, ambiguous=self.continuation
            )
            self.continuation = True
            self.waiting_offset = None
            return frame, end

        if _ANSI.sub(b"", raw).strip() != TRACEBACK or self.continuation:
            frame = TextFrame(raw, offset, end, ambiguous=self.continuation)
            self.continuation = False
            self.waiting_offset = None
            return frame, end

        parts = [raw]
        size = len(raw)
        terminal = False
        chain = False
        # Every grouped traceback remains unattributed: even plausible lines
        # can be interleaved by multiple writers without a stable identifier.
        while len(parts) < MAX_FRAME_LINES:
            next_line = budget.line(source)
            if next_line is None:
                return None, offset
            if not next_line:
                if not expired:
                    return None, offset
                break
            shape = _ANSI.sub(b"", next_line)
            stripped = shape.strip()
            if (
                len(next_line) > MAX_LINE_BYTES
                or size + len(next_line) > MAX_FRAME_BYTES
            ):
                self.waiting_offset = None
                return (
                    TextFrame(
                        b"".join(parts),
                        offset,
                        end,
                        "traceback",
                        truncated=True,
                        ambiguous=True,
                    ),
                    end,
                )
            if not next_line.endswith(b"\n"):
                if not expired:
                    return None, offset
                # Leave the incomplete line for a separate bounded frame.
                break
            if stripped == TRACEBACK:
                if not chain:
                    break
                terminal, chain = False, False
            elif stripped in CHAINS:
                if not terminal:
                    break
                chain = True
            elif not stripped:
                pass
            elif shape.startswith((b" ", b"\t")):
                if terminal:
                    break
            elif not terminal and self._exception_line(stripped):
                terminal = True
            else:
                break
            parts.append(next_line)
            size += len(next_line)
            end += len(next_line)
        self.waiting_offset = None
        return (
            TextFrame(
                b"".join(parts),
                offset,
                end,
                "traceback",
                truncated=len(parts) >= MAX_FRAME_LINES,
                ambiguous=True,
            ),
            end,
        )

    @staticmethod
    def _exception_line(line: bytes) -> bool:
        name = line.split(b":", 1)[0]
        return (
            0 < len(name) <= 128
            and name.endswith(
                (
                    b"Error",
                    b"Exception",
                    b"Warning",
                    b"Exit",
                    b"Interrupt",
                    b"StopIteration",
                )
            )
            and all(
                c in b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_."
                for c in name
            )
        )
