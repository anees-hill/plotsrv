"""Short plain-text source metadata; never inspect source files or user objects."""

from __future__ import annotations

import re
from types import FunctionType

MAX_DESCRIPTION_CHARS = 512
MAX_SCAN_CHARS = 4096


def clean(value):
    if type(value) is not str:
        return None
    if (
        len(value) <= MAX_DESCRIPTION_CHARS
        and value.isprintable()
        and value.strip() == value
        and "  " not in value
    ):
        return value
    prefix = value[:MAX_SCAN_CHARS]
    prefix = "".join(c for c in prefix if c >= " " or c in "\n\r\t")
    return " ".join(prefix.split())[:MAX_DESCRIPTION_CHARS]


def source_description(view_id, fallback=None, *, docstring=None, policy=None):
    """Config wins, including explicit empty text. Call during setup or serving."""
    if policy is None:
        from . import settings

        policy = settings.get_section("description-settings")
    views = policy.get("views", {})
    entry = views.get(view_id, {}) if type(views) is dict else {}
    if type(entry) is str:
        return clean(entry)
    if type(entry) is not dict:
        entry = {}
    if "description" in entry:
        return clean(entry["description"])
    if fallback is not None:
        return clean(fallback)
    if (
        entry.get("extract_docstrings", policy.get("extract_docstrings", True))
        is not True
    ):
        return None
    if type(docstring) is not str:
        return None
    prefix = (
        docstring[:MAX_SCAN_CHARS].replace("\r\n", "\n").replace("\r", "\n").lstrip()
    )
    return clean(re.split(r"\n[^\S\n]*\n", prefix, maxsplit=1)[0]) or None


def function_description(func, *, view_id):
    # Exact Python functions only: no inherited docs, inspect.getdoc, unwrapping,
    # arbitrary attributes, or retained callable references.
    doc = func.__doc__ if type(func) is FunctionType else None
    try:
        return source_description(view_id, docstring=doc)
    except Exception:
        # Optional metadata must not prevent application import/decoration.
        # Fail closed if an extraction policy cannot be read.
        return None


def received_description(payload):
    """Validate wire text before any visible catalogue mutation."""
    value = payload.get("description")
    if value is not None:
        from .contracts import bounded_text

        bounded_text(value, "description", 2048, empty=True)
    return clean(value)
