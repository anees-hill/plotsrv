"""Shared source precedence, selection and reviewable logical manifests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence

from . import settings
from .cli_parser import WatchSpec
from .connection_config import get_publisher_sources
from .contracts import (
    MAX_CATALOGUE_VIEWS,
    ViewDescriptor,
    SourceMetadata,
    validate_catalogue,
)
from .discovery import DiscoveredView, DiscoveryResult
from .source_targets import resolve_source_target


@dataclass(frozen=True, slots=True)
class SourceSetup:
    target: str | None
    watches: tuple[WatchSpec, ...]
    selection: tuple[str, ...]
    include_pruned: bool
    messages: tuple[str, ...]
    target_base: Path
    unscoped: bool

    def scan_root(self, default_target: str | None = None) -> Path:
        target = self.target if self.target is not None else default_target
        if target is None:
            raise ValueError("A default project scope has not been resolved")
        return resolve_source_target(target, base=self.target_base)


def resolve_source_setup(
    *,
    target: str | None = None,
    watches: Sequence[WatchSpec] | None = None,
    selection: Sequence[str] | None = None,
    include_pruned: bool | None = None,
) -> SourceSetup:
    cfg = get_publisher_sources()
    messages = []
    if target is not None and cfg.discovery_target is not None:
        messages.append(
            "Using the explicit target instead of configured discovery target."
        )
    if watches is not None and cfg.watch:
        messages.append("Using the explicit watch set instead of configured watches.")
    if selection is not None and cfg.selection:
        messages.append(
            "Using the explicit selection instead of configured discovery selection."
        )
    return SourceSetup(
        target if target is not None else cfg.discovery_target,
        tuple(watches) if watches is not None else cfg.watch,
        tuple(selection) if selection is not None else cfg.selection,
        cfg.include_pruned if include_pruned is None else include_pruned,
        tuple(messages),
        (
            Path.cwd()
            if target is not None
            else (settings.get_runtime_config_dir() or Path.cwd())
        ),
        target is None and cfg.discovery_target is None,
    )


def select_views(
    views: Sequence[DiscoveredView], *, selection=(), excluded=()
) -> list[DiscoveredView]:
    includes, excludes = set(selection), set(excluded)
    result = []
    for view in views:
        identities = {view.descriptor().view_id, view.label, view.section or "default"}
        if (not includes or includes & identities) and not excludes & identities:
            result.append(view)
    return result


def watch_descriptor(spec: WatchSpec) -> ViewDescriptor:
    from .store import normalize_view_id

    path = Path(spec.path)
    label = (spec.label or path.name).strip() or path.name
    section = (spec.section or "watch").strip() or "watch"
    from .descriptions import source_description

    vid = normalize_view_id(spec.view_id, section=section, label=label)
    return ViewDescriptor(
        vid,
        label,
        section,
        source=SourceMetadata(basename=path.name, source_type="watch"),
        description=source_description(vid),
    )


def build_manifest(
    discovery: DiscoveryResult | Sequence[DiscoveredView],
    *,
    watches=(),
    added_ids=(),
    selection=(),
    excluded=(),
    reviewed: bool = False,
) -> dict:
    """Build from metadata/config; no network, source-data reads or implicit sealing.

    A completed scan with unresolved/failed source files needs explicit review.
    Cancellation/resource exhaustion always rejects partial manifests. Explicit
    added IDs represent caller-reviewed dynamic declarations, never AST guesses.
    """
    if isinstance(discovery, DiscoveryResult):
        if not discovery.complete:
            raise ValueError("Cannot build a manifest from a cancelled or limited scan")
        if discovery.issue_count and not reviewed:
            raise ValueError(
                "Review unresolved declarations and skipped sources before building a complete manifest"
            )
        views = discovery.views
    else:
        views = discovery
    if len(views) > MAX_CATALOGUE_VIEWS:
        raise ValueError("Catalogue count exceeds the source limit")
    descriptors = []
    wire_bytes = 64

    def append(descriptor):
        nonlocal wire_bytes
        if len(descriptors) >= MAX_CATALOGUE_VIEWS:
            raise ValueError("Catalogue count exceeds the source limit")
        wire_bytes += (
            len(json.dumps(descriptor.to_dict(), ensure_ascii=False).encode()) + 2
        )
        if wire_bytes > 1024 * 1024:
            raise ValueError("Catalogue manifest exceeds the 1 MiB ingestion bound")
        descriptors.append(descriptor)

    for view in select_views(views, selection=selection, excluded=excluded):
        append(view.descriptor())
    for watch in watches:
        append(watch_descriptor(watch))
    for vid in added_ids:
        append(ViewDescriptor(view_id=vid, label=vid))
    manifest = {
        "protocol_version": 1,
        "views": [v.to_dict() for v in validate_catalogue(descriptors)],
    }
    if len(json.dumps(manifest, ensure_ascii=False).encode()) > 1024 * 1024:
        raise ValueError("Catalogue manifest exceeds the 1 MiB ingestion bound")
    return manifest
