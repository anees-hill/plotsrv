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
    choices: tuple[str, ...] = ()

    def parse(self, text: str):
        if len(text) > 4096:
            raise ValueError("Value is too long (maximum 4096 characters).")
        text = text.strip()
        if self.choices:
            if text not in self.choices:
                raise ValueError("Choose one of: " + ", ".join(self.choices))
            return text
        if self.kind in ("duration", "keep"):
            if self.kind == "duration" and text.lower() in ("false", "0"):
                return None
            if text.lower() in ("", "off", "none", "null"):
                return "off" if self.kind == "keep" else None
            if self.kind == "keep":
                try:
                    value = int(text)
                    if value >= 1:
                        return value
                except ValueError:
                    pass
                raise ValueError("Enter a positive snapshot count or off (unlimited).")
            from ..config import _parse_duration_seconds

            value = _parse_duration_seconds(text)
            if value is None:
                raise ValueError(
                    "Enter a positive interval such as 30s, 5m, 1h, or off."
                )
            return text
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
        return f"{self.meaning}\nUnits: {self.units}. Default: {self.default if self.default is not None else 'unset'}.\n{origin} Explicit command/API choices override configuration. * marks a value different from the displayed default."


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
    original_stamp: tuple | None = field(default=None, repr=False)
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
    manual_ids: list[str] | None = None

    @classmethod
    def load(cls, *, config=None, name=None, target=None):
        path = (
            Path(config).expanduser().resolve()
            if config
            else (settings.get_runtime_config_path() or Path.cwd() / "plotsrv.yml")
        )
        from .saving import read_snapshot

        snapshot = read_snapshot(path)
        raw = snapshot.raw
        return cls(
            path=path,
            original=raw,
            original_stamp=snapshot.stamp,
            config=_load_bounded(raw) if raw else {},
            name=name or settings.get_runtime_name(),
            cli_target=target,
        )

    def section(self, key):
        import copy
        from .saving import assign, scoped_path

        document = {key: copy.deepcopy(self.config.get(key, {}))}
        for path, value in self.edits.items():
            if path[0] == key:
                assign(document, scoped_path(self.config, path, self.name), value)
        return settings.effective_section(document, key, name=self.name, strict=True)

    def value(self, spec: FieldSpec):
        current = self.section(spec.path[0])
        for key in spec.path[1:]:
            if current is None and spec.path[:2] == (
                "publisher-settings",
                "destination",
            ):
                return spec.default
            if not isinstance(current, dict):
                raise ValueError("Configuration field parent must be a mapping")
            if key not in current:
                if key == "overdue_after" and "error_after" in current:
                    return spec.parse(str(current["error_after"]))
                return spec.default
            current = current[key]
        # Validate before showing potentially sensitive malformed legacy values.
        if (current is None or type(current) is bool) and spec.kind == "keep":
            return spec.default
        if (
            spec.kind in ("env", "url")
            and current is not None
            and type(current) is not str
        ):
            raise ValueError("Credential references and URLs must be strings.")
        return spec.parse("" if current is None else str(current))

    def origin(self, spec):
        if spec.path in self.edits:
            return "In-memory draft value."
        return f"Effective config/default for instance {self.name or '(global)'}; instance values inherit global settings."

    def set_value(self, spec, text):
        self.update_edits({spec.path: spec.parse(text)})

    def update_edits(self, edits):
        if len(self.edits.keys() | edits.keys()) > 2048:
            raise ValueError(
                "Draft edit limit reached. Save a smaller set of changes, then reopen to continue."
            )
        self.edits.update(edits)

    def reset_overrides(self, specs, view_id):
        from .saving import DELETE, scoped_path

        prefix = (specs[0].path[0], "views", view_id)
        row = self.config
        for part in scoped_path(self.config, prefix, self.name):
            row = row.get(part, {}) if isinstance(row, dict) else {}
        managed = {spec.path[-1] for spec in specs}
        for path in list(self.edits):
            if path[:3] == prefix and (len(path) == 3 or path[-1] in managed):
                del self.edits[path]
        if isinstance(row, dict) and row.keys() - managed:
            self.update_edits({spec.path: DELETE for spec in specs})
        else:
            self.update_edits({prefix: DELETE})

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
                for v in select_views(
                    result.views,
                    selection=self.sources().selection,
                    exact_selection=self.sources().exact_selection,
                )
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

    def configured_ids(self):
        if self.manual_ids is not None:
            return self.manual_ids
        if self.role == "server":
            return list(
                self.section("server-settings").get("admission", {}).get("allowed_ids")
                or []
            )
        return list(self.sources().additional_ids)

    def add_id(self, value):
        bounded_text(value, "logical ID", 512)
        ids = list(self.configured_ids())
        if value in ids:
            raise ValueError("That logical ID is already present.")
        if self.role != "server" and (
            value in (self.selected_ids or ())
            or value in {w.view_id for w in self.watches()}
        ):
            raise ValueError(
                "That ID already belongs to a selected source/watch; additional IDs are for unresolved declarations."
            )
        if len(ids) >= MAX_CATALOGUE_VIEWS:
            raise ValueError("Catalogue ID limit reached.")
        ids.append(value)
        self.manual_ids = ids

    def known_ids(self):
        ids = set(self.configured_ids()) | set(self.selected_ids or ())
        if self.role != "server":
            ids.update(w.view_id for w in self.watches())
        for section in ("storage-settings", "freshness-settings"):
            ids.update(self.section(section).get("views", {}))
        if len(ids) > MAX_CATALOGUE_VIEWS:
            raise ValueError("Combined view ID limit reached.")
        return sorted(ids)

    def save_edits(self):
        from .saving import scoped_path, DELETE

        edits = dict(self.edits)
        # Switching roles must not apply abandoned edits for the other machine.
        publisher_sections = {
            "publisher-settings",
            "publish-settings",
            "stream-settings",
            "watch-settings",
            "limits",
        }
        server_sections = {
            "server-settings",
            "storage-settings",
            "freshness-settings",
            "security-settings",
            "checks-settings",
            "webhook-settings",
        }
        allowed = (
            publisher_sections
            if self.role == "publisher"
            else (
                server_sections | {"watch-settings", "limits"}
                if self.role == "server"
                else publisher_sections | server_sections
            )
        )
        edits = {path: value for path, value in edits.items() if path[0] in allowed}
        if self.role != "server":
            self.known_ids()  # Validate the aggregate bound, including manual IDs.
            if self.watch_rows is not None:
                edits[("publisher-settings", "watch")] = self.watch_rows
            if self.manual_ids is not None:
                edits[("publisher-settings", "discovery", "additional_ids")] = (
                    self.manual_ids
                )
            if self.discovery_skipped:
                edits[("publisher-settings", "discovery", "exact_selection")] = []
            elif self.result is not None:
                if not self.result.complete:
                    raise ValueError(
                        "Discovery is incomplete. Narrow the scope and rescan, or explicitly continue without discovery."
                    )
                if any(
                    line.startswith("Duplicate logical ID")
                    for line in self.diagnostics()
                ):
                    raise ValueError(
                        "Resolve duplicate logical IDs before saving this discovered catalogue."
                    )
                edits[("publisher-settings", "discovery", "exact_selection")] = sorted(
                    self.selected_ids or ()
                )
            if self.cli_target is not None and not self.discovery_skipped:
                from ..source_targets import resolve_source_target

                # Store the reviewed scope on this machine, not a path reinterpreted
                # relative to a different config folder on the next launch.
                suffix = self.cli_target.partition(":")[2]
                edits[("publisher-settings", "discovery", "target")] = str(
                    resolve_source_target(self.cli_target)
                ) + (":" + suffix if suffix else "")
            elif self.result is not None and self.sources().target is None:
                from ..source_targets import default_source_target

                edits[("publisher-settings", "discovery", "target")] = (
                    default_source_target()
                )
            if not self.value(FIELDS["destination"]):
                for path in list(edits):
                    if path[:2] == ("publisher-settings", "destination"):
                        del edits[path]
                if self.section("publisher-settings").get("destination") is not None:
                    edits[("publisher-settings", "destination")] = None
        if self.role != "publisher":
            if self.value(FIELDS["admission"]) == "catalogue-locked":
                if self.manual_ids is not None:
                    edits[("server-settings", "admission", "allowed_ids")] = (
                        self.manual_ids
                    )
            elif (
                self.section("server-settings").get("admission", {}).get("allowed_ids")
                is not None
            ):
                edits[("server-settings", "admission", "allowed_ids")] = DELETE
        return {
            scoped_path(self.config, path, self.name): value
            for path, value in edits.items()
        }

    def commands(self, path):
        import shlex

        args = ["--config", str(path)]
        if self.name:
            args += ["--name", self.name]
        command = (
            "serve"
            if self.role == "server"
            else "publish" if self.role == "publisher" else "run"
        )
        suffix = " ".join(shlex.quote(a) for a in args)
        line = f"plotsrv {command} {suffix}"
        if (
            self.role == "publisher"
            and self.result is not None
            and self.result.issue_count
        ):
            line += " --reviewed"
        if self.role != "publisher":
            if self.value(FIELDS["admission"]) == "catalogue-locked":
                line += "\nLocked admission: configured IDs seal at startup. With no manifest, review the complete union on a publisher, then explicitly run plotsrv publish --seal-catalogue --reviewed --config <publisher-config>."
        else:
            line += "\nFor a locked receiver, review the complete multi-project ID union before explicitly adding --seal-catalogue --reviewed. Saving does not send that command."
        return line
