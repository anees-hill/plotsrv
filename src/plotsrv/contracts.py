"""Small JSON metadata contracts. No IO, discovery, or server policy mutation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

METADATA_VERSION = 1
MAX_DESCRIPTOR_BYTES = 16 * 1024
MAX_CATALOGUE_VIEWS = 1024


def bounded_text(value: object, name: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if (
        len(value) > limit
        or (not empty and not value.strip())
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise ValueError(f"{name} exceeds its text contract")
    return value  # Identity is never stripped or reconstructed.


def normalise_base_url(value: str) -> str:
    try:
        bounded_text(value, "destination URL", 2048)
        p = urlsplit(value)
        if (
            p.scheme not in ("http", "https")
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or p.query
            or p.fragment
            or "\\" in value
            or any(c.isspace() for c in value)
        ):
            raise ValueError
        host = p.hostname.lower()
        host = f"[{host}]" if ":" in host else host.encode("idna").decode("ascii")
        port = p.port
        if port == 0:
            raise ValueError
        authority = (
            host
            if port in (None, 443 if p.scheme == "https" else 80)
            else f"{host}:{port}"
        )
        # Reject dot segments rather than silently changing the destination.
        from urllib.parse import unquote

        if any(part in (".", "..") for part in unquote(p.path).split("/")):
            raise ValueError
        return urlunsplit((p.scheme, authority, p.path.rstrip("/") + "/", "", ""))
    except (ValueError, UnicodeError):
        raise ValueError(
            "destination must be an HTTP(S) base URL without credentials, query or fragment"
        ) from None


def dashboard_scope(serving_url: str, instance_name: str | None = None) -> str:
    """Stable browser preference identity; never use a reconnect generation here."""
    name = bounded_text(instance_name or "", "instance name", 512, empty=True)
    material = json.dumps([name, normalise_base_url(serving_url)], ensure_ascii=False)
    return "dashboard-v1:" + hashlib.sha256(material.encode()).hexdigest()


class ErrorCategory(str, Enum):
    INCOMPATIBLE_PROTOCOL = "incompatible_protocol"
    UNAUTHORISED_PUBLISHER = "unauthorised_publisher"
    INADMISSIBLE_VIEW = "inadmissible_view"
    OVERSIZE_DATA = "oversize_data"


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    basename: str | None = None
    source_type: str | None = None
    scope: str = "publisher"

    def __post_init__(self) -> None:
        if self.scope not in ("publisher", "server", "unknown"):
            raise ValueError("invalid provenance scope")
        if self.basename is not None:
            bounded_text(self.basename, "source basename", 255)
            if (
                "/" in self.basename
                or "\\" in self.basename
                or self.basename in (".", "..")
            ):
                raise ValueError("source basename must not be a path")
        if self.source_type is not None:
            bounded_text(self.source_type, "source type", 64)


@dataclass(frozen=True, slots=True)
class ViewDescriptor:
    view_id: str
    label: str
    section: str | None = None
    kind: str = "unknown"
    description: str | None = None
    capabilities: tuple[str, ...] = ()
    source: SourceMetadata | None = None
    metadata_version: int = METADATA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.metadata_version) is not int
            or self.metadata_version != METADATA_VERSION
        ):
            raise ValueError(ErrorCategory.INCOMPATIBLE_PROTOCOL.value)
        bounded_text(self.view_id, "view_id", 512)
        bounded_text(self.label, "label", 512)
        if self.section is not None:
            bounded_text(self.section, "section", 512, empty=True)
        if self.description is not None:
            bounded_text(self.description, "description", 2048, empty=True)
        if self.kind not in ("unknown", "plot", "table", "artifact", "stream"):
            raise ValueError("invalid descriptor kind")
        if (
            not isinstance(self.capabilities, (tuple, list))
            or len(self.capabilities) > 32
        ):
            raise ValueError("too many capabilities")
        for capability in self.capabilities:
            bounded_text(capability, "capability", 64)
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        if self.kind == "unknown" and self.capabilities:
            raise ValueError("unknown kind cannot guarantee capabilities")
        if self.source is not None and not isinstance(self.source, SourceMetadata):
            raise ValueError("invalid source metadata")
        if len(self.to_json().encode("utf-8")) > MAX_DESCRIPTOR_BYTES:
            raise ValueError(ErrorCategory.OVERSIZE_DATA.value)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["capabilities"] = list(self.capabilities)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ViewDescriptor:
        # Explicit fields only: future owners add validated fields here. Never
        # accept arbitrary extra metadata as policy or filesystem instructions.
        if not isinstance(value, dict) or len(value) > 8:
            raise ValueError("invalid descriptor fields")
        fields = dict(value)
        if fields.get("source") is not None:
            if not isinstance(fields["source"], dict) or len(fields["source"]) > 3:
                raise ValueError("invalid source metadata fields")
            fields["source"] = SourceMetadata(**fields["source"])
        return cls(**fields)

    @classmethod
    def from_json(cls, value: str | bytes) -> ViewDescriptor:
        if not isinstance(value, (str, bytes)) or len(value) > MAX_DESCRIPTOR_BYTES:
            raise ValueError(ErrorCategory.OVERSIZE_DATA.value)
        try:
            if (
                isinstance(value, str)
                and len(value.encode("utf-8")) > MAX_DESCRIPTOR_BYTES
            ):
                raise ValueError(ErrorCategory.OVERSIZE_DATA.value)
            return cls.from_dict(json.loads(value))
        except (UnicodeError, RecursionError, TypeError):
            raise ValueError("invalid descriptor JSON") from None


def validate_catalogue(views: list[ViewDescriptor]) -> tuple[ViewDescriptor, ...]:
    if len(views) > MAX_CATALOGUE_VIEWS:
        raise ValueError(ErrorCategory.OVERSIZE_DATA.value)
    seen: set[str] = set()
    for view in views:
        if not isinstance(view, ViewDescriptor):
            raise ValueError("invalid catalogue descriptor")
        if view.view_id in seen:
            raise ValueError("duplicate catalogue view_id")
        seen.add(view.view_id)
    return tuple(views)


@dataclass(frozen=True, slots=True)
class ProtocolCapabilities:
    """Response shape for the later handshake; advertises no future routes."""

    server_generation: str
    dashboard_scope: str
    capabilities: tuple[str, ...] = ()
    protocol_version: int = METADATA_VERSION
    stream_protocol_version: int = 4

    def __post_init__(self) -> None:
        from .streams.models import STREAM_PROTOCOL_VERSION

        if (
            type(self.protocol_version) is not int
            or self.protocol_version != METADATA_VERSION
            or type(self.stream_protocol_version) is not int
            or self.stream_protocol_version != STREAM_PROTOCOL_VERSION
        ):
            raise ValueError(ErrorCategory.INCOMPATIBLE_PROTOCOL.value)
        bounded_text(self.server_generation, "server generation", 512)
        bounded_text(self.dashboard_scope, "dashboard scope", 512)
        if (
            not isinstance(self.capabilities, (tuple, list))
            or len(self.capabilities) > 32
        ):
            raise ValueError("too many capabilities")
        for capability in self.capabilities:
            bounded_text(capability, "capability", 64)
        object.__setattr__(self, "capabilities", tuple(self.capabilities))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "capabilities": list(self.capabilities)}
