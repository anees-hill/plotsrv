"""Bounded narrow YAML edits and reviewed, best-effort atomic local saving.

No runtime globals, network calls or service lifecycle operations. Unedited bytes
are copied verbatim. Unsupported edits fail rather than approximating YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import difflib
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from uuid import uuid4

import yaml

MAX_BYTES = 1024 * 1024
DELETE = object()


class SaveError(ValueError):
    pass


@dataclass(frozen=True)
class Snapshot:
    raw: bytes | None = field(repr=False)
    stamp: tuple | None = None
    mode: int = 0o600


def read_snapshot(path: Path) -> Snapshot:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return Snapshot(None)
    except OSError:
        raise SaveError(
            "Cannot read config. Use a regular file you can access; symlinks are not save targets."
        ) from None
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise SaveError("Configuration must be a regular file.")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > MAX_BYTES:
        raise SaveError("Config exceeds 1 MiB; choose a smaller configuration file.")

    def identity(s):
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    if identity(before) != identity(after):
        raise SaveError("Config changed while reading. Review it again.")
    return Snapshot(
        raw,
        (*identity(after), hashlib.sha256(raw).digest()),
        stat.S_IMODE(after.st_mode),
    )


def assign(document, path, value):
    node = document
    for key in path[:-1]:
        if value is DELETE and key not in node:
            return
        if key not in node or (key == "destination" and node[key] is None):
            node[key] = {}
        if not isinstance(node[key], dict):
            raise SaveError(
                "A setting parent is not a mapping. Repair the YAML manually or choose a new file."
            )
        node = node[key]
    if value is DELETE:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = copy.deepcopy(value)


def scoped_path(config, path, name):
    section = config.get(path[0], {})
    if not isinstance(section, dict):
        raise SaveError(
            "Configuration section must be a mapping; repair it before editing."
        )
    if name:
        group = (
            "instance"
            if "instance" in section and "instances" not in section
            else "instances"
        )
        return (path[0], group, name, *path[1:])
    return (path[0], "default", *path[1:]) if "default" in section else path


def narrow_yaml(raw: bytes | None, edits: dict) -> bytes:
    from .draft import _load_bounded

    text = (raw or b"").decode("utf-8")
    original = _load_bounded(raw) if raw else {}
    desired = copy.deepcopy(original)
    for path, value in edits.items():
        assign(desired, path, value)

    def checked(result):
        if len(result) > MAX_BYTES:
            raise SaveError(
                "Proposed config exceeds 1 MiB; reduce the configuration before saving."
            )
        if _load_bounded(result) != desired:
            raise SaveError(
                "Cannot preserve this YAML layout safely. Repair the layout manually."
            )
        return result

    if desired == original:
        return checked(raw or b"{}\n")
    newline = "\r\n" if "\r\n" in text else "\n"

    def emit(value):
        return (
            yaml.safe_dump(
                value,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=True,
                width=1_000_000,
            )
            .removesuffix("...\n")
            .rstrip("\n")
        )

    if not original and not text.strip():
        return checked(
            yaml.safe_dump(desired, sort_keys=False, allow_unicode=True).encode()
        )
    root = yaml.compose(text)
    if root is None:  # Comments-only file.
        return checked(
            (
                text
                + ("" if text.endswith("\n") else newline)
                + yaml.safe_dump(desired, sort_keys=False, allow_unicode=True).replace(
                    "\n", newline
                )
            ).encode()
        )
    replacements = []

    def walk(node, old, new):
        if old == new:
            return
        if isinstance(node, yaml.MappingNode) and isinstance(old, dict) and new == {}:
            start, end = node.start_mark.index, node.end_mark.index
            previous = text[start:end]
            comments = "".join(
                line
                for line in previous.splitlines(keepends=True)
                if line.lstrip().startswith("#")
            )
            replacements.append(
                (
                    start,
                    end,
                    "{}"
                    + (newline if previous.endswith("\n") or comments else "")
                    + comments,
                )
            )
            return
        if (
            isinstance(node, yaml.SequenceNode)
            and isinstance(old, list)
            and isinstance(new, list)
            and new[: len(old)] == old
        ):
            additions = new[len(old) :]
            if node.flow_style:
                at = node.end_mark.index - 1
                replacements.append(
                    (at, at, (", " if old else "") + emit(additions)[1:-1])
                )
            else:
                at = node.end_mark.index
                if node.end_mark.column:
                    at = text.rfind("\n", 0, at) + 1
                snippet = (
                    newline.join(
                        " " * node.start_mark.column + line
                        for line in yaml.safe_dump(
                            additions, sort_keys=False, allow_unicode=True
                        ).splitlines()
                    )
                    + newline
                )
                replacements.append(
                    (at, at, (newline if at and text[at - 1] != "\n" else "") + snippet)
                )
            return
        if (
            isinstance(node, yaml.MappingNode)
            and isinstance(old, dict)
            and isinstance(new, dict)
        ):
            known = {key.value: (key, value) for key, value in node.value}
            for key, value in old.items():
                key_node, value_node = known[key]
                if key not in new:
                    # Delete only ordinary block entries; ambiguous flow removal is refused.
                    if (
                        node.flow_style
                        or key_node.start_mark.column != node.start_mark.column
                    ):
                        raise SaveError(
                            "Removing this flow/complex YAML entry requires manual editing."
                        )
                    start = text.rfind("\n", 0, key_node.start_mark.index) + 1
                    end = value_node.end_mark.index
                    if (
                        isinstance(value_node, (yaml.MappingNode, yaml.SequenceNode))
                        and not value_node.flow_style
                    ):
                        # Block collections end at the next sibling's indentation.
                        line_start = text.rfind("\n", 0, end) + 1
                        if not text[line_start:end].strip():
                            end = line_start
                    elif value_node.end_mark.column:
                        end = text.find("\n", end)
                        end = len(text) if end < 0 else end + 1
                    comments = "".join(
                        line
                        for line in text[start:end].splitlines(keepends=True)
                        if line.lstrip().startswith("#")
                    )
                    replacements.append((start, end, comments))
                else:
                    walk(value_node, value, new[key])
            additions = {k: v for k, v in new.items() if k not in old}
            if additions:
                if node.flow_style:
                    at = node.end_mark.index - 1
                    additions_text = emit(additions)[1:-1]
                    replacements.append(
                        (at, at, (", " if old else "") + additions_text)
                    )
                else:
                    at = node.end_mark.index
                    indent = node.start_mark.column
                    lines = yaml.safe_dump(
                        additions, sort_keys=False, allow_unicode=True
                    ).splitlines()
                    snippet = (
                        newline.join(" " * indent + line for line in lines) + newline
                    )
                    # End marks may be at the following sibling's indentation.
                    if node.end_mark.column:
                        at = text.rfind("\n", 0, at) + 1
                    prefix = newline if at and text[at - 1] != "\n" else ""
                    replacements.append((at, at, prefix + snippet))
            return
        start, end = node.start_mark.index, node.end_mark.index
        old_text = text[start:end]
        if isinstance(node, (yaml.SequenceNode, yaml.MappingNode)) and "#" in old_text:
            raise SaveError(
                "This edited list/structure contains comments. Keep it unchanged, repair it manually, or choose a new file."
            )
        replacement = emit(new)
        if old_text.endswith("\n"):
            replacement += newline
        replacements.append((start, end, replacement))

    walk(root, original, desired)
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    result = text.encode("utf-8")
    return checked(result)


@dataclass(frozen=True)
class Review:
    path: Path
    original: Snapshot
    source_path: Path
    source_snapshot: Snapshot
    proposed: bytes = field(repr=False)
    text: str


def prepare(draft, destination: str) -> Review:
    from .schema import validate_document, review_projection, review_layout
    from .draft import _load_bounded, saved_target

    path = Path(destination).expanduser().absolute()
    if not path.parent.is_dir():
        raise SaveError(
            "Choose an existing destination directory; the wizard does not create directories."
        )
    current_source = read_snapshot(draft.path)
    if current_source.raw != draft.original or (
        draft.original_stamp is not None
        and current_source.stamp != draft.original_stamp
    ):
        raise SaveError(
            "Source config changed since opening. Reopen the wizard to review the current file, or copy your draft choices before exiting."
        )
    target = current_source if path == draft.path else read_snapshot(path)
    if path != draft.path and target.raw is not None:
        raise SaveError(
            "That other file already exists. Open it with --config to edit it, or choose an unused filename."
        )
    edits = draft.save_edits()
    if path.parent != draft.path.parent:
        if draft.original is not None:
            raise SaveError(
                "An existing config may contain unrelated relative paths. Save beside the original, or start a new config in the destination directory with --config."
            )
        if draft.role != "server":
            from dataclasses import asdict

            sources = draft.sources()
            if sources.watches:
                edits[
                    scoped_path(
                        draft.config, ("publisher-settings", "watch"), draft.name
                    )
                ] = [asdict(w) for w in sources.watches]
            if sources.target and not draft.discovery_skipped:
                edits[
                    scoped_path(
                        draft.config,
                        ("publisher-settings", "discovery", "target"),
                        draft.name,
                    )
                ] = saved_target(sources.target, base=sources.target_base)
        for field_path, value in list(edits.items()):
            if (
                field_path[-1] == "root_dir"
                and isinstance(value, str)
                and not Path(value).expanduser().is_absolute()
            ):
                edits[field_path] = str(draft.path.parent / value)
    proposed = narrow_yaml(draft.original, edits)
    document = _load_bounded(proposed)
    validate_document(document, draft.name, path.parent, draft.role)
    # Same production YAML loader used for runtime files, without setting globals.
    from ..settings import parse_yaml_config

    if parse_yaml_config(proposed) != document:
        raise SaveError("Runtime loader disagrees with the reviewed document.")
    before = review_projection(draft.config, draft.name, draft.role)
    after = review_projection(document, draft.name, draft.role)
    display = yaml.safe_dump(after, sort_keys=False, allow_unicode=True)
    diff = "".join(
        difflib.unified_diff(
            yaml.safe_dump(before, sort_keys=False).splitlines(True),
            display.splitlines(True),
            fromfile="effective before",
            tofile="effective after",
        )
    )
    layout = yaml.safe_dump(
        review_layout(document, draft.name, draft.role),
        sort_keys=False,
        allow_unicode=True,
    )
    commands = draft.commands(path)
    notice = f"Selected instance: {draft.name or '(global)'}.\nProposed YAML excerpts, in their actual global/default/instance placement (unrelated content, other instances, comments and webhook endpoints are hidden here and preserved in the file). Built-in defaults apply where omitted.\n"
    return Review(
        path,
        target,
        draft.path,
        current_source,
        proposed,
        notice
        + layout
        + "\nEffective changes:\n"
        + (diff or "(no effective changes)\n")
        + "\nAfter saving (services are not changed):\n"
        + commands,
    )


def save(review: Review):
    """Explicit confirmation must happen before this function is called."""
    temp = None
    backup = None
    try:
        if (
            read_snapshot(review.source_path) != review.source_snapshot
            or read_snapshot(review.path) != review.original
        ):
            raise SaveError(
                "Config changed after review. Return to Review before saving."
            )
        fd, temp_name = tempfile.mkstemp(
            prefix="." + review.path.name + ".", suffix=".tmp", dir=review.path.parent
        )
        temp = Path(temp_name)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), review.original.mode)
            stream.write(review.proposed)
            stream.flush()
            os.fsync(stream.fileno())
        if review.original.raw is not None:
            backup = review.path.with_name(review.path.name + ".bak." + uuid4().hex)
            fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(review.original.raw)
                stream.flush()
                os.fsync(stream.fileno())
        if (
            read_snapshot(review.source_path) != review.source_snapshot
            or read_snapshot(review.path) != review.original
        ):
            raise SaveError(
                "Config changed while saving. Return to Review; the current target was not replaced."
            )
        if review.original.raw is None:
            os.link(temp, review.path)  # Atomic no-clobber creation.
        else:
            os.replace(temp, review.path)
        return backup
    except SaveError:
        raise
    except OSError:
        raise SaveError(
            "Save failed: check directory/file permissions and free space, then Review again. The previous target is intact."
        ) from None
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
