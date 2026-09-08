"""Publisher/server-owned configuration. Resolution is explicit and does no IO
beyond reading the selected YAML and configured environment values.

Existing render/storage/UI namespaces retain their existing resolvers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import settings
from .contracts import MAX_CATALOGUE_VIEWS, bounded_text
from .cli_parser import WatchSpec
from .publishing.models import PublishTarget, credential_context


def _mapping(value: object, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() - keys:
        raise ValueError(f"invalid {name} configuration fields")
    return value


def normalise_publish_mode(mode: str | None) -> str:
    raw = str(mode or "auto").strip().lower()
    if raw not in ("auto", "local", "remote"):
        raise ValueError("publish_view mode must be one of: 'auto', 'local', 'remote'")
    return raw


def resolve_publish_target(
    *,
    destination: str | PublishTarget | None = None,
    host: str | None = None,
    port: int | None = None,
    mode: str | None = None,
    launch_server: bool | None = None,
) -> PublishTarget:
    """Explicit URL conflicts with explicit host/port or a local launch.

    Explicit legacy host/port/local intent replaces a configured destination
    (including its credential). Otherwise configured URL is always remote.
    None means unspecified; explicit default host/port still means remote.
    """
    mode2 = normalise_publish_mode(mode)
    if destination is not None:
        if host is not None or port is not None:
            raise ValueError("destination conflicts with explicit host/port")
        if launch_server is True or (launch_server is None and mode2 == "local"):
            raise ValueError("destination conflicts with local server launch")
        if isinstance(destination, PublishTarget):
            if destination.kind != "remote":
                raise ValueError("destination must be remote")
            return destination
        return PublishTarget(kind="remote", base_url=destination)

    explicit_local = launch_server is True or (
        launch_server is None and mode2 == "local"
    )
    if host is None and port is None and not explicit_local:
        cfg = _mapping(
            settings.get_section("publisher-settings", strict=True),
            "publisher",
            {"destination", "discovery", "watch"},
        )
        raw = cfg.get("destination")
        if raw is not None:
            raw = _mapping(
                raw,
                "publisher destination",
                {
                    "url",
                    "bearer_token_env",
                    "request_timeout_s",
                    "stream_request_timeout_s",
                },
            )
            if not raw.get("url"):
                raise ValueError("publisher destination requires url")
            return PublishTarget(
                kind="remote",
                base_url=raw["url"],
                **{k: v for k, v in raw.items() if k != "url"},
            )

    launch = (
        bool(launch_server)
        if launch_server is not None
        else mode2 == "local" or (mode2 == "auto" and host is None and port is None)
    )
    return PublishTarget(
        kind="local" if launch else "remote",
        host=host or "127.0.0.1",
        port=port if port is not None else 8000,
    )


@dataclass(frozen=True, slots=True)
class PublisherSources:
    discovery_target: str | None = None
    selection: tuple[str, ...] = ()
    watch: tuple[WatchSpec, ...] = ()
    include_pruned: bool = False


def _ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_CATALOGUE_VIEWS:
        raise ValueError(f"{name} must contain at most {MAX_CATALOGUE_VIEWS} IDs")
    values = tuple(bounded_text(item, name, 512) for item in value)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name}")
    return values


def get_publisher_sources() -> PublisherSources:
    """Config paths resolve beside config on the publisher; never open sources."""
    cfg = _mapping(
        settings.get_section("publisher-settings", strict=True),
        "publisher",
        {"destination", "discovery", "watch"},
    )
    discovery = _mapping(
        cfg.get("discovery", {}), "discovery", {"target", "selection", "include_pruned"}
    )
    include_pruned = discovery.get("include_pruned", False)
    if type(include_pruned) is not bool:
        raise ValueError("discovery include_pruned must be a boolean")
    target = discovery.get("target")
    base = settings.get_runtime_config_dir() or Path.cwd()
    if target is not None:
        bounded_text(target, "discovery target", 4096)
        # Preserve module/package[:callable] expressions. Explicit filesystem
        # expressions resolve beside config; module:callable keeps its import name.
        if (
            "/" in target
            or "\\" in target
            or target.startswith((".", "~"))
            or target.split(":", 1)[0].endswith(".py")
        ):
            path = Path(target).expanduser()
            target = str(path if path.is_absolute() else base / path)
    raw_watch = cfg.get("watch", [])
    if not isinstance(raw_watch, list) or len(raw_watch) > MAX_CATALOGUE_VIEWS:
        raise ValueError("watch must be a bounded list")
    watch = []
    for raw in raw_watch:
        raw = _mapping(
            raw,
            "watch",
            {"path", "view_id", "label", "section", "read_mode", "materialization"},
        )
        spec = WatchSpec(**raw)
        bounded_text(spec.path, "watch path", 4096)
        for name in ("view_id", "label", "section"):
            if getattr(spec, name) is not None:
                bounded_text(getattr(spec, name), name, 512)
        if spec.read_mode not in (None, "head", "tail"):
            raise ValueError("invalid watch read_mode")
        if spec.materialization not in (None, "auto", "memory", "file"):
            raise ValueError("invalid watch materialization")
        path = Path(spec.path).expanduser()
        watch.append(
            WatchSpec(
                **{**raw, "path": str(path if path.is_absolute() else base / path)}
            )
        )
    _ids([w.view_id for w in watch if w.view_id is not None], "watch view_id")
    return PublisherSources(
        target,
        _ids(discovery.get("selection", []), "selection"),
        tuple(watch),
        include_pruned,
    )


@dataclass(frozen=True, slots=True)
class ServerConnectionConfig:
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    bearer_token_env: str | None = None
    allow_remote_without_key: bool = False
    admission_mode: str = "dynamic"
    allowed_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if type(self.allow_remote_without_key) is not bool:
            raise ValueError("allow_remote_without_key must be a boolean")
        PublishTarget(kind="local", host=self.bind_host, port=self.bind_port)
        credential_context(
            self.bearer_token_env
        )  # Missing configured key fails setup closed.
        if self.admission_mode not in ("dynamic", "catalogue-locked"):
            raise ValueError("invalid server admission mode")
        if self.allowed_ids is not None:
            object.__setattr__(
                self, "allowed_ids", _ids(self.allowed_ids, "allowed_ids")
            )
            if self.admission_mode != "catalogue-locked":
                raise ValueError("allowed_ids requires catalogue-locked admission")


def get_server_connection_config() -> ServerConnectionConfig:
    cfg = _mapping(
        settings.get_section("server-settings", strict=True),
        "server",
        {"bind", "ingestion", "admission"},
    )
    bind = _mapping(cfg.get("bind", {}), "server bind", {"host", "port"})
    ingestion = _mapping(
        cfg.get("ingestion", {}),
        "server ingestion",
        {"bearer_token_env", "allow_remote_without_key"},
    )
    admission = _mapping(
        cfg.get("admission", {}), "server admission", {"mode", "allowed_ids"}
    )
    return ServerConnectionConfig(
        bind_host=bind.get("host", "127.0.0.1"),
        bind_port=bind.get("port", 8000),
        bearer_token_env=ingestion.get("bearer_token_env"),
        allow_remote_without_key=ingestion.get("allow_remote_without_key", False),
        admission_mode=admission.get("mode", "dynamic"),
        allowed_ids=admission.get("allowed_ids"),
    )
