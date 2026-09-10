"""In-memory edits against the existing schema, without runtime context mutation.

The original bytes are kept for the later review/atomic-save stage. This module
has no writer and never resolves secret values or contacts a destination.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, fields
from pathlib import Path
import math
import os
import re
from typing import Any

import yaml

from .. import settings
from ..connection_config import (
    PublisherSources,
    ServerConnectionConfig,
    get_publisher_sources,
)
from ..contracts import MAX_CATALOGUE_VIEWS, bounded_text, normalise_base_url
from ..discovery import DiscoveryResult
from ..publishing.models import PublishTarget
from ..source_setup import resolve_source_setup, select_views, watch_descriptor

MAX_CONFIG_BYTES = 1024 * 1024


def model_default(model, name):
    return next(f.default for f in fields(model) if f.name == name)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    path: tuple[str, ...]
    label: str
    kind: str
    default: Any
    meaning: str
    units: str = "text"
    minimum: float | None = None
    maximum: float | None = None
    per_view: bool = False

    def parse(self, text: str):
        if len(text) > 4096:
            raise ValueError("Value is too long (maximum 4096 characters).")
        text = text.strip()
        if self.kind == "env":
            if text and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", text):
                raise ValueError(
                    "Enter an environment-variable name, never a token value."
                )
            return text or None
        if self.kind == "url":
            return normalise_base_url(text) if text else None
        if self.kind == "bool":
            if text.lower() not in ("true", "false"):
                raise ValueError("Choose true or false.")
            return text.lower() == "true"
        if self.kind in ("int", "float"):
            try:
                value = int(text) if self.kind == "int" else float(text)
            except ValueError:
                raise ValueError("Enter a valid number.") from None
            if (
                not math.isfinite(value)
                or (self.minimum is not None and value < self.minimum)
                or (self.maximum is not None and value > self.maximum)
            ):
                raise ValueError(
                    f"Enter a value between {self.minimum} and {self.maximum} {self.units}."
                )
            return value
        if text:
            bounded_text(text, self.label, 4096)
        return text or self.default

    def help(self, origin: str) -> str:
        return f"{self.meaning}\nUnits: {self.units}. Default: {self.default if self.default is not None else 'unset'}.\n{origin} Explicit command/API choices override configuration. * marks a value different from the built-in default."


FIELDS = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "destination",
            ("publisher-settings", "destination", "url"),
            "Destination URL",
            "url",
            None,
            "HTTP(S) address of the receiving server, including any proxy prefix. Required for sending remotely. No connection is made here.",
        ),
        FieldSpec(
            "bearer",
            ("publisher-settings", "destination", "bearer_token_env"),
            "Bearer key environment variable",
            "env",
            None,
            "Name of the variable set on the publisher machine. Its value is never read or saved here. Use HTTPS outside loopback.",
        ),
        FieldSpec(
            "target",
            ("publisher-settings", "discovery", "target"),
            "Discovery package or path (optional)",
            "str",
            model_default(PublisherSources, "discovery_target"),
            "A package/path focuses static discovery. Empty uses detected project scope. Source code is read within scan limits, never executed. Config paths are relative to this config.",
        ),
        FieldSpec(
            "request_timeout",
            ("publisher-settings", "destination", "request_timeout_s"),
            "Request timeout",
            "float",
            model_default(PublishTarget, "request_timeout_s"),
            "Maximum transport wait for an ordinary publication request; this does not cancel arbitrary observation code.",
            "seconds",
            0.001,
            300,
        ),
        FieldSpec(
            "bind_port",
            ("server-settings", "bind", "port"),
            "Bind port",
            "int",
            model_default(ServerConnectionConfig, "bind_port"),
            "Port on the machine hosting plotsrv.",
            "port number",
            1,
            65535,
        ),
    )
}


def _load_bounded(raw: bytes) -> dict:
    # Bound structure BEFORE construction, disallow aliases to avoid graph expansion.
    depth = 0
    try:
        for count, event in enumerate(yaml.parse(raw)):
            if count > 20_000 or isinstance(event, yaml.AliasEvent):
                raise ValueError("Unsupported YAML structure")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            if depth > 32:
                raise ValueError("Configuration nesting exceeds limit")

        class UniqueLoader(yaml.SafeLoader):
            pass

        def mapping(loader, node):
            result = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node)
                if not isinstance(key, str) or key in result:
                    raise ValueError("Configuration keys must be unique strings")
                result[key] = loader.construct_object(value_node)
            return result

        UniqueLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping
        )
        data = yaml.load(raw, Loader=UniqueLoader)
    except (yaml.YAMLError, UnicodeError, RecursionError):
        raise ValueError("Unsupported or malformed YAML") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a mapping")
    return data


@dataclass
class Draft:
    path: Path
    original: bytes | None = field(default=None, repr=False)
    config: dict = field(default_factory=dict, repr=False)
    name: str | None = None
    cli_target: str | None = None
    role: str = "combined"
    edits: dict[tuple[str, ...], Any] = field(default_factory=dict)
    result: DiscoveryResult | None = None
    selected_ids: set[str] | None = None
    watch_rows: list[dict] | None = None
    scan_key: tuple | None = None
    discovery_skipped: bool = False

    @classmethod
    def load(cls, *, config=None, name=None, target=None):
        path = (
            Path(config).expanduser().resolve()
            if config
            else (settings.get_runtime_config_path() or Path.cwd() / "plotsrv.yml")
        )
        raw = None
        if path.exists():
            # Refuse special files; bounded read even when a regular file grows.
            import stat

            flags = os.O_RDONLY | os.O_NONBLOCK
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Configuration must be a regular file")
                raw = stream.read(MAX_CONFIG_BYTES + 1)
            if len(raw) > MAX_CONFIG_BYTES:
                raise ValueError("Configuration exceeds 1 MiB")
        return cls(
            path=path,
            original=raw,
            config=_load_bounded(raw) if raw else {},
            name=name or settings.get_runtime_name(),
            cli_target=target,
        )

    def section(self, key):
        return settings.effective_section(self.config, key, name=self.name, strict=True)

    def value(self, spec: FieldSpec):
        if spec.path in self.edits:
            return self.edits[spec.path]
        current = self.section(spec.path[0])
        for key in spec.path[1:]:
            if not isinstance(current, dict):
                raise ValueError("Configuration field parent must be a mapping")
            if key not in current:
                return spec.default
            current = current[key]
        # Validate before showing potentially sensitive malformed legacy values.
        return spec.parse("" if current is None else str(current))

    def origin(self, spec):
        if spec.path in self.edits:
            return "In-memory draft value."
        return f"Effective config/default for instance {self.name or '(global)'}; instance values inherit global settings."

    def set_value(self, spec, text):
        self.edits[spec.path] = spec.parse(text)

    def set_override(self, spec, view_id, text):
        if not spec.per_view:
            raise ValueError("This setting does not support per-view overrides")
        bounded_text(view_id, "view ID", 512)
        if len(self.edits) >= MAX_CATALOGUE_VIEWS:
            raise ValueError("Draft edit limit reached")
        self.edits[(spec.path[0], "views", view_id, *spec.path[1:])] = spec.parse(text)

    def sources(self):
        section = self.section("publisher-settings")
        if self.watch_rows is not None:
            section["watch"] = self.watch_rows
        target = self.value(FIELDS["target"])
        section["discovery"] = {**section.get("discovery", {})}
        if target is None:
            section["discovery"].pop("target", None)
        else:
            section["discovery"]["target"] = target
        sources = get_publisher_sources(section=section, base=self.path.parent)
        return resolve_source_setup(
            target=self.cli_target, sources=sources, config_dir=self.path.parent
        )

    def watches(self):
        return tuple(watch_descriptor(w) for w in self.sources().watches)

    def add_watch(self, path, view_id, read_mode):
        bounded_text(path, "watch path", 4096)
        bounded_text(view_id, "watch ID", 512)
        rows = list(
            self.watch_rows
            if self.watch_rows is not None
            else self.section("publisher-settings").get("watch", [])
        )
        if len(rows) >= MAX_CATALOGUE_VIEWS:
            raise ValueError("Watch count exceeds catalogue limit")
        rows.append(
            {
                "path": path,
                "view_id": view_id,
                **({"read_mode": read_mode} if read_mode else {}),
            }
        )
        get_publisher_sources(section={"watch": rows}, base=self.path.parent)
        self.watch_rows = rows

    def accept_scan(self, result, key):
        self.discovery_skipped = False
        self.result, self.scan_key = result, key
        ids = {v.descriptor().view_id for v in result.views}
        if self.selected_ids is None:
            self.selected_ids = {
                v.descriptor().view_id
                for v in select_views(result.views, selection=self.sources().selection)
            }
        else:
            self.selected_ids.intersection_update(ids)

    def diagnostics(self):
        if self.result is None:
            return []
        counts = Counter(v.descriptor().view_id for v in self.result.views)
        counts.update(w.view_id for w in self.watches())
        lines = [
            f"Duplicate logical ID ({count} declarations): {vid}"
            for vid, count in counts.items()
            if count > 1
        ]
        lines.extend(
            f"{Path(i.path).name}:{i.line or '-'}: {i.reason}"
            for i in self.result.issues
        )
        if not self.result.complete:
            lines.append(
                "Scan incomplete: narrow the scope and rescan before using a catalogue."
            )
        if self.result.issue_count > len(self.result.issues):
            lines.append(f"{self.result.issue_count} issues total; diagnostics capped.")
        return lines

    def preview(self):
        lines = [
            "UNSAVED DRAFT — settings pages and saving are not available yet.",
            f"Config: {self.path}",
            f"Instance: {self.name or '(global)'}",
            f"Role: {self.role} (wizard flow only; no new YAML role key)",
        ]
        if self.role == "server":
            bind = self.section("server-settings").get("bind", {})
            if not isinstance(bind, dict):
                raise ValueError("Server bind must be a mapping")
            host = bind.get("host", model_default(ServerConnectionConfig, "bind_host"))
            port = bind.get("port", model_default(ServerConnectionConfig, "bind_port"))
            connection = PublishTarget(kind="local", host=host, port=port)
            lines += [
                f"Bind: {connection.host}:{connection.port}",
                "No application source discovery. Admission, manual catalogue IDs and server settings follow in the settings stage.",
            ]
        else:
            for key in ("destination", "bearer", "target"):
                spec = FIELDS[key]
                value = self.value(spec)
                lines.append(
                    f"{'.'.join(spec.path)}: {value if value is not None else '(unset/default)'}"
                )
            if self.cli_target:
                lines.append(f"Explicit command target: {self.cli_target}")
            if self.discovery_skipped:
                lines.append(
                    "Discovery skipped for this preview. This does not disable discovery in the existing runtime configuration."
                )
            selection = self.sources().selection
            if selection:
                lines.append(
                    f"Original configured selection: {selection}. Undiscovered entries are retained in the original config; this is not a replacement manifest."
                )
            lines += [
                f"Selected discovery IDs: {len(self.selected_ids or ())}",
                *(f"  {vid}" for vid in sorted(self.selected_ids or ())),
            ]
            if self.selected_ids == set():
                lines.append(
                    "No discovery IDs selected. This is a draft-only exclusion: YAML selection: [] means ALL in the current runtime, so it is not emitted as an empty selection."
                )
            lines += [
                f"Watch ID: {w.view_id} (file stays on this machine)"
                for w in self.watches()
            ]
            lines += self.diagnostics()
            lines.append(
                "Dynamic servers accept new IDs. A locked server requires a complete, reviewed catalogue union and explicit bootstrap; this wizard never registers or seals it."
            )
        lines.append(
            "Unrelated config and secrets are omitted from this preview. Original bytes remain untouched. Use Back to revise or Close draft to abandon."
        )
        return "\n".join(lines)
