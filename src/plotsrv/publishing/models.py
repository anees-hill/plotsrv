from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
from urllib.parse import urlsplit

from ..contracts import ProtocolCapabilities, normalise_base_url

PublishTargetKind = Literal["local", "remote"]

# Context hashes are salted per process to avoid an offline token oracle.
_CONTEXT_SALT = os.urandom(32)


def credential_value(env_name: str) -> str:
    if not isinstance(env_name, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]{0,127}", env_name
    ):
        raise ValueError("bearer_token_env must be an environment variable name")
    token = os.environ.get(env_name)
    if (
        not token
        or len(token) > 8192
        or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token)
    ):
        raise ValueError("configured bearer environment value is missing or invalid")
    return token


def credential_context(env_name: str | None) -> str:
    if env_name is None:
        return "anonymous"
    return hmac.new(
        _CONTEXT_SALT, credential_value(env_name).encode(), hashlib.sha256
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PublishTarget:
    """Resolved destination with a credential reference, never a token value.

    Context keys are process-local and change when credentials rotate. Pending
    work fails closed on rotation; re-resolve to use the new credential.
    """

    kind: PublishTargetKind
    host: str = "127.0.0.1"
    port: int = 8000
    base_url: str | None = None
    bearer_token_env: str | None = None
    request_timeout_s: float = 2.0
    stream_request_timeout_s: float = 1.0
    protocol: ProtocolCapabilities | None = None
    credential_context: str = field(init=False)

    def __post_init__(self) -> None:
        if self.protocol is not None and not isinstance(
            self.protocol, ProtocolCapabilities
        ):
            raise ValueError("invalid negotiated protocol metadata")
        if self.kind not in ("local", "remote"):
            raise ValueError("invalid publication target kind")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        for timeout in (self.request_timeout_s, self.stream_request_timeout_s):
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 0 < timeout <= 300
            ):
                raise ValueError(
                    "request timeout must be finite, positive and at most 300 seconds"
                )
        if not isinstance(self.host, str) or any(c in self.host for c in "/?#@"):
            raise ValueError("invalid target host")
        host = self.host.strip("[]")
        authority = f"[{host}]" if ":" in host else host
        url = normalise_base_url(self.base_url or f"http://{authority}:{self.port}/")
        if self.kind == "local" and (
            self.base_url is not None or self.bearer_token_env is not None
        ):
            raise ValueError(
                "local targets cannot have a remote URL or bearer credential"
            )
        if self.base_url is not None:
            p = urlsplit(url)
            object.__setattr__(self, "host", p.hostname)
            object.__setattr__(
                self, "port", p.port or (443 if p.scheme == "https" else 80)
            )
            object.__setattr__(self, "base_url", url)
        if self.bearer_token_env is not None and urlsplit(url).scheme == "http":
            hostname = urlsplit(url).hostname
            try:
                loopback = ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                loopback = hostname == "localhost"
            if not loopback:
                raise ValueError("bearer publication requires HTTPS outside loopback")
        object.__setattr__(
            self, "credential_context", credential_context(self.bearer_token_env)
        )

    def url_for(self, path: str) -> str:
        # Routes, not arbitrary URLs: a leading / preserves proxy prefixes.
        if not isinstance(path, str) or not re.fullmatch(r"/?[A-Za-z0-9_/-]+", path):
            raise ValueError("invalid destination route")
        host = self.host.strip("[]")
        authority = f"[{host}]" if ":" in host else host
        base = self.base_url or normalise_base_url(f"http://{authority}:{self.port}/")
        return base + path.lstrip("/")

    def authorization_headers(self) -> dict[str, str]:
        if self.bearer_token_env is None:
            return {}
        token = credential_value(self.bearer_token_env)
        context = hmac.new(_CONTEXT_SALT, token.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(context, self.credential_context):
            raise ValueError("publisher credential changed; resolve destination again")
        return {"Authorization": "Bearer " + token}

    @property
    def key(self) -> str:
        return json.dumps([self.kind, self.url_for("/"), self.credential_context])


@dataclass(frozen=True, slots=True)
class PublishTask:
    """One replaceable live-view update waiting for background delivery."""

    obj: Any
    target: PublishTarget
    coalesce_view_id: str
    label: str | None = None
    section: str | None = None
    view_id: str | None = None
    update_limit_s: int | None = None
    force: bool = False
    kind: str | None = None
    artifact_kind: str | None = None
    estimated_bytes: int = 0

    @property
    def coalesce_key(self) -> str:
        return json.dumps([self.target.key, self.coalesce_view_id])


@dataclass(frozen=True, slots=True)
class PublishQueueStats:
    """A point-in-time, JSON-ready summary of the live publish worker."""

    queued: int
    in_flight: int
    pending_bytes: int
    max_pending_views: int
    max_pending_bytes: int
    submitted: int
    processed: int
    coalesced: int
    dropped: int
    rejected: int
    failed: int
    last_error: str | None
    running: bool
