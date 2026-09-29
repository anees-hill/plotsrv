"""Small, dependency-free prompts and human-friendly config input parsing."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
import glob
import os
import re
import sys
from typing import Callable, TypeVar

from ..config import _parse_duration_seconds

T = TypeVar("T")
_SIZE = re.compile(r"^(\d+(?:\.\d+)?)\s*(b|bytes?|k(?:i)?b|m(?:i)?b|g(?:i)?b)?$", re.I)
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhd])$", re.I)
_FACTORS = {"b": 1, "byte": 1, "bytes": 1, "kb": 1024, "kib": 1024,
            "mb": 1024**2, "mib": 1024**2, "gb": 1024**3, "gib": 1024**3}


def parse_size(value: str, *, megabytes: bool = False) -> int | float:
    """Use plotsrv's binary MiB convention for KB/MB/GB input."""
    match = _SIZE.fullmatch(value.strip())
    if not match:
        raise ValueError("Enter a size such as 500 KB, 10 MB or 1.5 GB.")
    try:
        amount = Decimal(match.group(1))
        factor = _FACTORS[(match.group(2) or ("mb" if megabytes else "b")).lower()]
        size = amount * factor
    except (InvalidOperation, OverflowError):
        raise ValueError("Enter a finite, positive size.") from None
    if size <= 0:
        raise ValueError("Enter a size greater than zero.")
    if megabytes:
        return float(size / (1024**2))
    if size != size.to_integral_value():
        raise ValueError("The size must resolve to a whole number of bytes.")
    return int(size)


def format_size(value: int | float, *, megabytes: bool = False) -> str:
    size = Decimal(str(value)) * (1024**2 if megabytes else 1)
    for factor, unit in ((1024**3, "GiB"), (1024**2, "MiB"), (1024, "KiB")):
        amount = size / factor
        if amount >= 1:
            rounded = amount.quantize(Decimal("0.01"))
            shown = format(rounded.normalize(), "f")
            if amount == rounded:
                return f"{shown} {unit}"
            return f"{shown} {unit} ({size:,.0f} B)"
    return f"{size:,.0f} B"


def parse_duration(value: str) -> str | None:
    raw = value.strip().lower()
    if raw in {"off", "none"}:
        return None
    match = _DURATION.fullmatch(raw)
    if not match:
        raise ValueError("Enter a duration such as 30m, 4h or 2d; use off to unset.")
    canonical = match.group(1) + match.group(2)
    if _parse_duration_seconds(canonical) is None:
        raise ValueError("Duration must be at least one second.")
    return canonical


class Prompts:
    def __init__(self, reader: Callable[[], str] | None = None, output=None) -> None:
        self.reader = reader or input
        self.output = output or sys.stdout
        self.color = (
            hasattr(self.output, "isatty") and self.output.isatty()
            and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
        )
        self._shown_hints: set[str] = set()

    def say(self, message: str = "") -> None:
        print(message, file=self.output)

    def section(self, title: str) -> None:
        self.say("\n" + (f"\033[1m{title}\033[0m" if self.color else title))

    def hint_once(self, key: str, message: str) -> None:
        if key not in self._shown_hints:
            self._shown_hints.add(key)
            self.say("  " + message)

    def ask(
        self,
        label: str,
        *,
        default: T | None = None,
        display: str | None = None,
        parse: Callable[[str], T] | None = None,
        help_text: str = "",
        required: bool = False,
        path_completion: bool = False,
    ) -> T | None:
        suffix = f" [{display}]" if display is not None else ""
        while True:
            print(f"{label}{suffix}: ", end="", file=self.output, flush=True)
            with self._path_completion(path_completion):
                answer = self.reader().strip()
            if not (hasattr(self.output, "isatty") and self.output.isatty()):
                self.say()
            if answer == "?":
                self.say("  " + (help_text or "Press Enter to keep the shown value."))
                continue
            if not answer:
                if required and default is None:
                    self.say("  Enter a value, or ? for help.")
                    continue
                return default
            try:
                return parse(answer) if parse else answer  # type: ignore[return-value]
            except ValueError as error:
                self.say(f"  {error}")

    @contextmanager
    def _path_completion(self, enabled: bool):
        if not enabled or self.reader is not input or not sys.stdin.isatty():
            yield
            return
        try:
            import readline
        except ImportError:
            yield
            return
        old_completer = readline.get_completer()
        old_delims = readline.get_completer_delims()

        def complete(text: str, state: int):
            expanded = os.path.expanduser(text)
            matches = sorted(glob.glob(glob.escape(expanded) + "*"))
            values = [
                ("~" + path[len(os.path.expanduser("~")):] if text.startswith("~")
                 and path.startswith(os.path.expanduser("~")) else path)
                + (os.sep if os.path.isdir(path) else "")
                for path in matches
            ]
            return values[state] if state < len(values) else None

        try:
            readline.set_completer_delims("\t\n")
            readline.set_completer(complete)
            readline.parse_and_bind("tab: complete")
            yield
        finally:
            readline.set_completer(old_completer)
            readline.set_completer_delims(old_delims)

    def yes_no(self, label: str, *, default: bool, help_text: str) -> bool:
        mark = "Y/n/?" if default else "y/N/?"
        return bool(self.ask(
            label, default=default, display=mark,
            parse=lambda answer: _parse_bool(answer), help_text=help_text,
        ))

    def choice(
        self, label: str, options: list[tuple[str, str]], *, default: str,
        help_text: str,
    ) -> str:
        for index, (_, title) in enumerate(options, 1):
            self.say(f"  {index}  {title}")
        values = {str(index): key for index, (key, _) in enumerate(options, 1)}
        values.update({key.lower(): key for key, _ in options})

        def parse(answer: str) -> str:
            if answer.lower() not in values:
                raise ValueError("Choose one of the listed numbers.")
            return values[answer.lower()]

        return str(self.ask(label, default=default, display=default,
                            parse=parse, help_text=help_text))

    def numbers(self, label: str, *, count: int, help_text: str,
                default: tuple[int, ...] = ()) -> tuple[int, ...]:
        def parse(answer: str) -> tuple[int, ...]:
            if answer.lower() in {"none", "clear"}:
                return ()
            parts = [part.strip() for part in answer.split(",")]
            if any(not part.isdigit() for part in parts):
                raise ValueError("Enter numbers separated by commas.")
            selected = tuple(int(part) for part in parts)
            if any(number < 1 or number > count for number in selected):
                raise ValueError(f"Choose numbers from 1 to {count}.")
            if len(set(selected)) != len(selected):
                raise ValueError("Each number may appear only once.")
            return selected

        return tuple(self.ask(label, default=default,
                              display=",".join(map(str, default)) or "none",
                              parse=parse, help_text=help_text))


def _parse_bool(value: str) -> bool:
    if value.lower() in {"y", "yes"}:
        return True
    if value.lower() in {"n", "no"}:
        return False
    raise ValueError("Enter y or n, or press Enter for the shown choice.")
