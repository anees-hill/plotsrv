"""Process-local publisher admission and bounded HTTP ingress.

Store transactions use the existing store lock. No per-publisher/ID rejection
cache, background retry queue, filesystem instructions or administrative rights.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import settings
from .connection_config import get_server_connection_config
from .contracts import (
    MAX_CATALOGUE_VIEWS,
    ViewDescriptor,
    ProtocolCapabilities,
    bounded_text,
    dashboard_scope,
    validate_catalogue,
    ErrorCategory,
)
from .http_security import _is_loopback_ip
from .publishing.models import credential_value

MAX_PUBLISH_REQUEST_BYTES = 8 * 1024 * 1024
MAX_CATALOGUE_REQUEST_BYTES = 1024 * 1024
MAX_INGESTION_CONCURRENT = 4
MAX_INGESTION_REQUESTS_PER_SECOND = 100
BODY_TIMEOUT_S = 10.0
MAX_JSON_STRUCTURAL_TOKENS = 500_000


class IngestionError(ValueError):
    def __init__(self, category: str, status: int, reason: str):
        # All call sites use fixed reasons, never publisher input or a token.
        self.category, self.status, self.reason = (
            ErrorCategory(category).value,
            status,
            reason,
        )
        super().__init__(reason)

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status,
            content={
                "detail": {
                    "category": self.category,
                    "reason": self.reason,
                }
            },
            headers={"WWW-Authenticate": "Bearer"} if self.status == 401 else None,
        )


def inadmissible(reason: str = "view_not_admitted") -> IngestionError:
    return IngestionError("inadmissible_view", 403, reason)


class IngestionState:
    def __init__(self):
        cfg = get_server_connection_config()
        self.config = cfg
        self.generation = uuid4().hex
        self._key_digest = (
            hashlib.sha256(credential_value(cfg.bearer_token_env).encode()).digest()
            if cfg.bearer_token_env
            else None
        )
        self.allowed = (
            frozenset(cfg.allowed_ids) if cfg.allowed_ids is not None else None
        )
        self.sealed = (
            cfg.admission_mode == "catalogue-locked" and self.allowed is not None
        )
        self.manifest_digest: str | None = None
        self.descriptors: dict[str, ViewDescriptor] = {}
        self._budget_lock = threading.Lock()
        self._active = 0
        self._tokens = float(MAX_INGESTION_REQUESTS_PER_SECOND)
        self._last_refill = time.monotonic()
        from .config import get_check_rules, get_webhook_config
        from .checks import configure
        configure(get_check_rules(), self.generation, webhooks=get_webhook_config())
        if cfg.allow_remote_without_key and self._key_digest is None:
            logging.getLogger(__name__).warning(
                "Publisher ingestion permits remote requests without a key; use only on a trusted private endpoint."
            )
        if cfg.admission_mode == "catalogue-locked" and self._key_digest is None:
            logging.getLogger(__name__).warning(
                "Catalogue bootstrap has no publisher key; every permitted local/private publisher is trusted to seal the complete manifest."
            )

    def authenticate(self, request: Request) -> None:
        headers = request.headers.getlist("authorization")
        if self._key_digest is not None:
            value = headers[0] if len(headers) == 1 else ""
            if len(value) > 8200 or not value.startswith("Bearer "):
                raise IngestionError(
                    "unauthorised_publisher", 401, "publisher_key_required"
                )
            supplied = hashlib.sha256(value[7:].encode()).digest()
            if not hmac.compare_digest(supplied, self._key_digest):
                raise IngestionError(
                    "unauthorised_publisher", 401, "publisher_key_required"
                )
        elif headers:
            # An auth-config mismatch must not silently become anonymous.
            raise IngestionError(
                "unauthorised_publisher", 401, "publisher_key_not_configured"
            )
        elif not self.config.allow_remote_without_key:
            if (
                request.client is None
                or not _is_loopback_ip(request.client.host)
                or any(
                    key in request.headers
                    for key in ("forwarded", "x-forwarded-for", "x-forwarded-host")
                )
            ):
                raise IngestionError(
                    "unauthorised_publisher", 403, "remote_ingestion_requires_key"
                )
        # Browsers do not need publisher mutation rights, even on loopback.
        if request.method != "GET" and "origin" in request.headers:
            raise IngestionError(
                "unauthorised_publisher", 403, "browser_ingestion_not_allowed"
            )

    def trusts_html_reports(self, request: Request) -> bool:
        """Call only after authenticate: publisher authority includes reports.

        Opting into anonymous remote ingestion does not grant active HTML
        privileges. A payload can never choose its own provenance.
        """
        return self._key_digest is not None or (
            request.client is not None
            and _is_loopback_ip(request.client.host)
            and not any(key in request.headers for key in (
                "forwarded", "x-forwarded-for", "x-forwarded-host"
            ))
        )

    def enter(self) -> None:
        with self._budget_lock:
            now = time.monotonic()
            self._tokens = min(
                float(MAX_INGESTION_REQUESTS_PER_SECOND),
                self._tokens
                + (now - self._last_refill) * MAX_INGESTION_REQUESTS_PER_SECOND,
            )
            self._last_refill = now
            if self._active >= MAX_INGESTION_CONCURRENT or self._tokens < 1:
                raise IngestionError(
                    "ingestion_busy", 429, "ingestion_budget_exhausted"
                )
            self._tokens -= 1
            self._active += 1

    def leave(self) -> None:
        with self._budget_lock:
            self._active -= 1


_state: IngestionState | None = None
_setup_lock = threading.RLock()


def state() -> IngestionState:
    global _state
    with _setup_lock:
        if _state is None:
            _state = IngestionState()
        return _state


def reset_ingestion() -> None:
    """Explicit process-state reset, used with store.reset; not an HTTP action."""
    global _state
    with _setup_lock:
        from .checks import reset
        reset()
        _state = None


def setup_ingestion(bind_host: str | None = None) -> None:
    current = state()
    from .checks import current as current_checks, configure
    from .config import get_check_rules, get_webhook_config
    if current_checks() is not None and current_checks()._closed:
        configure(get_check_rules(), uuid4().hex, webhooks=get_webhook_config())
    fresh = get_server_connection_config()
    if fresh != current.config:
        raise ValueError("ingestion configuration changed; restart the process")
    if fresh.bearer_token_env and not hmac.compare_digest(
        hashlib.sha256(credential_value(fresh.bearer_token_env).encode()).digest(),
        current._key_digest,
    ):
        raise ValueError("ingestion credential changed; restart the process")
    if (
        bind_host is not None
        and not _is_loopback_ip(bind_host)
        and bind_host != "localhost"
        and current._key_digest is None
        and not current.config.allow_remote_without_key
    ):
        logging.getLogger(__name__).warning(
            "Non-loopback dashboard bind: remote anonymous ingestion remains disabled; protect dashboard reads and exclude administration routes at the proxy."
        )


def require_admitted(view_id: str) -> None:
    from . import store

    try:
        bounded_text(view_id, "view_id", 512)
    except ValueError:
        raise inadmissible("invalid_view_id") from None
    with store._STORE_LOCK:
        current = state()
        if current.config.admission_mode == "catalogue-locked":
            if not current.sealed:
                raise inadmissible("catalogue_awaiting_bootstrap")
            if view_id not in current.allowed:
                raise inadmissible()
        if view_id not in store._VIEWS and len(store._VIEWS) >= MAX_CATALOGUE_VIEWS:
            raise IngestionError("oversize_data", 413, "catalogue_capacity")


def clear_observation_capability(view_id: str) -> None:
    """Called under the store lock when current content is replaced."""
    from dataclasses import replace

    current = state()
    descriptor = current.descriptors.get(view_id)
    if descriptor is not None and "observation-v1" in descriptor.capabilities:
        current.descriptors[view_id] = replace(
            descriptor, kind="unknown", capabilities=(), source=None
        )


def register_catalogue(views: list[ViewDescriptor], *, seal: bool) -> dict[str, Any]:
    """Validate everything before an atomic metadata transaction and seal.

    Identical means the complete canonical descriptor manifest, independent of
    order. A configured ID allowlist may receive matching initial metadata once.
    """
    from . import store

    try:
        descriptors = validate_catalogue(views)
    except (ValueError, TypeError):
        raise inadmissible("invalid_catalogue") from None
    canonical = json.dumps(
        [v.to_dict() for v in sorted(descriptors, key=lambda v: v.view_id)],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    with store._STORE_LOCK:
        current = state()
        ids = frozenset(v.view_id for v in descriptors)
        if seal:
            if current.config.admission_mode != "catalogue-locked":
                raise inadmissible("bootstrap_requires_locked_mode")
            if current.sealed:
                if current.manifest_digest == digest:
                    return {
                        "ok": True,
                        "sealed": True,
                        "idempotent": True,
                        "generation": current.generation,
                    }
                if current.manifest_digest is not None or current.allowed != ids:
                    raise IngestionError(
                        "inadmissible_view", 409, "catalogue_already_sealed"
                    )
        else:
            for view_id in ids:
                require_admitted(view_id)
        if len(set(store._VIEWS) | ids) > MAX_CATALOGUE_VIEWS:
            raise IngestionError("oversize_data", 413, "catalogue_capacity")
        for descriptor in descriptors:
            existing = store._VIEW_META.get(descriptor.view_id)
            if existing and (
                (
                    existing.kind == "stream"
                    and descriptor.kind not in ("unknown", "stream")
                )
                or (
                    descriptor.kind == "stream"
                    and existing.kind not in ("none", "stream")
                )
            ):
                raise IngestionError("inadmissible_view", 409, "view_kind_conflict")
        # All possible policy/shape failures were checked before visible writes.
        if seal:
            current.allowed, current.sealed = ids, True
            current.manifest_digest = digest
        for descriptor in descriptors:
            existing = store._VIEW_META.get(descriptor.view_id)
            store.register_view(
                view_id=descriptor.view_id,
                label=descriptor.label,
                description=descriptor.description,
                section=descriptor.section,
                kind="stream" if existing and existing.kind == "stream" else "none",
                activate_if_first=False,
            )
            current.descriptors[descriptor.view_id] = descriptor
        return {
            "ok": True,
            "sealed": current.sealed,
            "registered": len(descriptors),
            "generation": current.generation,
        }


async def read_payload(request: Request, maximum: int) -> dict[str, Any]:
    current = state()
    current.authenticate(request)
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) < 0 or int(declared) > maximum:
                raise IngestionError("oversize_data", 413, "request_too_large")
        except ValueError as error:
            if isinstance(error, IngestionError):
                raise
            raise IngestionError(
                "invalid_request", 422, "invalid_content_length"
            ) from None
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise IngestionError("invalid_request", 415, "content_encoding_not_supported")
    body = bytearray()
    try:
        async with asyncio.timeout(BODY_TIMEOUT_S):
            async for chunk in request.stream():
                if len(body) + len(chunk) > maximum:
                    raise IngestionError("oversize_data", 413, "request_too_large")
                body.extend(chunk)
    except TimeoutError:
        raise IngestionError("invalid_request", 408, "body_timeout") from None
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(_decode_payload, body)


def _reject_json_constant(value):
    raise ValueError("nonfinite JSON")


def _decode_payload(body: bytearray) -> dict[str, Any]:
    # Check nesting before json.loads; object/array expansion is wire bounded.
    depth = 0
    structural_tokens = 0
    quoted = escaped = False
    for byte in body:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (44, 58):
            structural_tokens += 1
        elif byte in (91, 123):
            depth += 1
            structural_tokens += 1
            if depth > 100:
                raise IngestionError("oversize_data", 413, "json_nesting_limit")
        elif byte in (93, 125):
            depth -= 1
        if structural_tokens > MAX_JSON_STRUCTURAL_TOKENS:
            raise IngestionError("oversize_data", 413, "json_complexity_limit")
    try:
        # The structural scan assumes UTF-8. Do not let json.loads auto-detect
        # UTF-16/32 and interpret quotes/escapes differently from that scan.
        payload = json.loads(body.decode("utf-8"), parse_constant=_reject_json_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise IngestionError("invalid_request", 422, "invalid_json") from None
    if not isinstance(payload, dict):
        raise IngestionError("invalid_request", 422, "json_object_required")
    return payload


INGESTION_PATHS = frozenset(
    (
        "/publish",
        "/stream/register",
        "/stream/append",
        "/stream/heartbeat",
        "/stream/close",
        "/catalogue/register",
        "/catalogue/bootstrap",
        "/watch/register",
        "/watch/update",
        "/watch/close",
        "/capabilities",
    )
)


class IngestionMiddleware:
    """ASGI admission slot spans read, conversion and mutation; no waiting queue."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("path", "").rstrip("/") not in INGESTION_PATHS
        ):
            return await self.app(scope, receive, send)
        current = state()
        entered = False
        try:
            current.enter()
            entered = True
            current.authenticate(Request(scope))
            await self.app(scope, receive, send)
        except IngestionError as error:
            await error.response()(scope, receive, send)
        finally:
            if entered:
                current.leave()


@asynccontextmanager
async def ingestion_lifespan(app):
    setup_ingestion()
    try:
        yield
    finally:
        from .checks import shutdown
        shutdown()


router = APIRouter()


@router.get("/capabilities")
def capabilities(request: Request):
    current = state()
    current.authenticate(request)
    from .streams.models import MAX_STREAM_REQUEST_BYTES

    envelope = ProtocolCapabilities(
        server_generation=current.generation,
        dashboard_scope=dashboard_scope(
            str(request.base_url), settings.get_runtime_name()
        ),
        capabilities=(
            "publish",
            "catalogue-register",
            "catalogue-bootstrap",
            "stream-v4",
            "watch-v1",
            "watch-v2",
            "observation-v1",
            "checks-v1",
            "view-descriptions-v1",
        ),
    ).to_dict()
    return {
        **envelope,
        "admission": {
            "mode": current.config.admission_mode,
            "sealed": current.sealed,
            "allowed_count": (
                len(current.allowed) if current.allowed is not None else None
            ),
        },
        "limits": {
            "publish_request_bytes": MAX_PUBLISH_REQUEST_BYTES,
            "catalogue_request_bytes": MAX_CATALOGUE_REQUEST_BYTES,
            "catalogue_views": MAX_CATALOGUE_VIEWS,
            "stream_request_bytes": MAX_STREAM_REQUEST_BYTES,
            "concurrent_requests": MAX_INGESTION_CONCURRENT,
            "requests_per_second": MAX_INGESTION_REQUESTS_PER_SECOND,
            "body_timeout_s": BODY_TIMEOUT_S,
            "json_structural_tokens": MAX_JSON_STRUCTURAL_TOKENS,
            "watch_request_bytes": 384 * 1024,
            "watch_source_bytes": 256 * 1024,
            "watch_hosted_bytes": 16 * 1024 * 1024,
            "watch_views": 64,
        },
    }


async def _catalogue_request(request: Request, *, seal: bool):
    payload = await read_payload(request, MAX_CATALOGUE_REQUEST_BYTES)
    if (
        type(payload.get("protocol_version")) is not int
        or payload["protocol_version"] != 1
    ):
        raise IngestionError("incompatible_protocol", 422, "unsupported_protocol")
    raw = payload.get("views")
    if not isinstance(raw, list) or len(raw) > MAX_CATALOGUE_VIEWS:
        raise IngestionError("oversize_data", 413, "catalogue_capacity")
    try:
        views = [ViewDescriptor.from_dict(value) for value in raw]
    except (ValueError, TypeError):
        raise inadmissible("invalid_descriptor") from None
    return register_catalogue(views, seal=seal)


@router.post("/catalogue/register")
async def register(request: Request):
    return await _catalogue_request(request, seal=False)


@router.post("/catalogue/bootstrap")
async def bootstrap(request: Request):
    return await _catalogue_request(request, seal=True)
