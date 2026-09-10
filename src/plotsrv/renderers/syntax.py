"""Lazy, bounded built-in Pygments highlighting. No source reads or plugin paths."""

from dataclasses import dataclass
from html import escape
from threading import BoundedSemaphore
import time

MAX_INPUT_CHARS = 16 * 1024
MAX_INPUT_BYTES = 64 * 1024
MAX_TOKENS = 4096
MAX_OUTPUT_BYTES = 256 * 1024
MAX_LINES = 2000
_SLOTS = BoundedSemaphore(2)

# Deliberately supported built-ins: never fall through to entry-point plugins.
from ..source_info import LANGUAGES as ALIASES


@dataclass(frozen=True)
class Highlight:
    html: str | None = None
    language: str | None = None
    reason: str | None = None


def presentation(view_id, source_info=None, *, default_language=None):
    from ..settings import get_section

    cfg = get_section("code-settings")
    views = cfg.get("views", {})
    own = views.get(view_id, {}) if type(views) is dict else {}
    if type(own) is not dict:
        own = {}
    info = source_info or {}
    language = own.get("language", cfg.get("language", "auto"))
    if language == "auto":
        language = info.get("language") or info.get("format") or default_language
    language = ALIASES.get(language.lower()) if type(language) is str else None
    style = own.get("style", cfg.get("style", "auto"))
    return language, style if type(style) is str else "auto"


def highlight(text, language, *, partial_tail=False):
    if partial_tail:
        return Highlight(
            reason="Tail preview: earlier string/comment context is unavailable; showing plain text."
        )
    if language not in ALIASES.values():
        return Highlight(reason="No supported source language; showing plain text.")
    if len(text) > MAX_INPUT_CHARS or text.count("\n") >= MAX_LINES:
        return Highlight(
            language=language,
            reason="Syntax preview limit reached; showing plain text.",
        )
    if len(text.encode("utf-8", errors="replace")) > MAX_INPUT_BYTES:
        return Highlight(
            language=language, reason="Syntax byte limit reached; showing plain text."
        )
    if not _SLOTS.acquire(False):
        return Highlight(
            language=language, reason="Syntax renderer busy; showing plain text."
        )
    try:
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token

        lexer = get_lexer_by_name(language, stripnl=False, ensurenl=False)
        deadline = time.monotonic() + 0.025
        parts, cost, consumed = [], 0, 0
        groups = (
            (Token.Comment, "comment"),
            (Token.Literal.String, "string"),
            (Token.Literal.Number, "number"),
            (Token.Keyword.Constant, "constant"),
            (Token.Keyword, "keyword"),
            (Token.Name.Builtin, "builtin"),
            (Token.Name.Decorator, "decorator"),
        )
        classes = {}
        for n, (offset, token, value) in enumerate(lexer.get_tokens_unprocessed(text)):
            if n >= MAX_TOKENS or time.monotonic() > deadline or offset != consumed:
                raise ValueError("Syntax token/time limit")
            consumed += len(value)
            if token not in classes:
                classes[token] = next(
                    (name for group, name in groups if token in group), None
                )
            klass = classes[token]
            # Close wrappers at every newline, preserving multiline lexer state.
            # Browser line numbers/reversal can then reorder balanced lines safely.
            for i, line in enumerate(value.split("\n")):
                item = ("\n" if i else "") + (
                    '<span class="ps-code-token ps-code-token--'
                    + klass
                    + '">'
                    + escape(line)
                    + "</span>"
                    if klass and line
                    else escape(line)
                )
                cost += len(item.encode("utf-8", errors="replace"))
                if cost > MAX_OUTPUT_BYTES:
                    raise ValueError("Syntax output limit")
                parts.append(item)
        if consumed != len(text):
            raise ValueError("Incomplete syntax output")
        return Highlight("".join(parts), language)
    except Exception:
        return Highlight(
            language=language,
            reason="Syntax highlighting unavailable or limited; showing plain text.",
        )
    finally:
        _SLOTS.release()
