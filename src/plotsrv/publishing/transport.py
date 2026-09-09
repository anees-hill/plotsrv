"""Bounded HTTP exchange and capability cache shared by direct publishers.

No delivery queue, persistent sockets, or background threads live here. Ordinary
latest-state and ordered stream delivery retain their separate owners.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import json
import http.client
import io
import logging
import math
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from ..contracts import ProtocolCapabilities
from .models import PublishTarget

MAX_TARGETS = 64
MAX_RESPONSE_BYTES = 64 * 1024
CAPABILITY_TTL_S = 30.0
FAILURE_COOLDOWN_S = 5.0
PERMANENT_COOLDOWN_S = 30.0


class TransportError(RuntimeError):
    def __init__(
        self, category: str, *, status: int | None = None, reason: str | None = None
    ):
        self.category = category
        self.status = status
        self.reason = reason
        super().__init__(
            f"plotsrv publisher: {category}"
            + (f" (HTTP {status})" if status else "")
            + (f": {reason}" if reason else "")
        )


@dataclass
class _Context:
    lock: threading.Lock = field(default_factory=threading.Lock)
    capabilities: ProtocolCapabilities | None = None
    expires: float = 0.0
    retry_at: float = 0.0
    last_error: str | None = None
    last_reason: str | None = None
    next_log: float = 0.0


_contexts: OrderedDict[str, _Context] = OrderedDict()
_lock = threading.Lock()
_setup_next_log = 0.0


def report_invalid_setup() -> None:
    """Bound diagnostics even when no valid target/security key can be formed."""
    global _setup_next_log
    with _lock:
        now = time.monotonic()
        if now < _setup_next_log:
            return
        _setup_next_log = now + PERMANENT_COOLDOWN_S
    logging.getLogger(__name__).warning(
        "Publisher setup invalid: check destination and credential configuration"
    )


def _context(target: PublishTarget) -> _Context:
    with _lock:
        key = target.key
        context = _contexts.get(key)
        if context is None:
            if len(_contexts) >= MAX_TARGETS:
                _contexts.popitem(last=False)
            context = _contexts[key] = _Context()
        _contexts.move_to_end(key)
        return context


def reset_transport() -> None:
    """Discard process-local cached metadata/diagnostics; owns no sockets."""
    global _setup_next_log
    with _lock:
        _contexts.clear()
        _setup_next_log = 0.0


def health(target: PublishTarget) -> dict[str, Any]:
    ctx = _context(target)
    return {
        "last_error": ctx.last_error,
        "last_reason": ctx.last_reason,
        "retry_delay_s": max(0.0, ctx.retry_at - time.monotonic()),
        "server_generation": (
            ctx.capabilities.server_generation if ctx.capabilities else None
        ),
    }


def invalidate(target: PublishTarget) -> None:
    _context(target).expires = 0.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("publisher exchange deadline")
    return remaining


class _DeadlineReader(io.RawIOBase):
    """Check the total deadline on every socket read, including HTTP headers.

    A socket inactivity timeout alone resets on each byte from a trickling peer.
    No timer or worker is needed; closing this file releases its socket reference.
    """

    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
        self.raw = sock.makefile("rb", buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode):
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))


def _connection_type(base, deadline):
    class Connection(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            create = self._create_connection

            def connect(address, timeout, source_address):
                sock = create(address, _remaining(deadline), source_address)
                try:
                    sock.settimeout(_remaining(deadline))
                    return sock
                except BaseException:
                    sock.close()
                    raise

            self._create_connection = connect
            self.response_class = lambda sock, *a, **kw: http.client.HTTPResponse(
                _DeadlineSocket(sock, deadline), *a, **kw
            )

        def send(self, data):
            if self.sock is None:
                self.connect()
            self.sock.settimeout(_remaining(deadline))
            return super().send(data)

    return Connection


def _open(request, *, timeout):
    deadline = time.monotonic() + timeout
    http_connection = _connection_type(http.client.HTTPConnection, deadline)
    https_connection = _connection_type(http.client.HTTPSConnection, deadline)

    class HTTP(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(http_connection, req)

    class HTTPS(urllib.request.HTTPSHandler):
        def https_open(self, req):
            # HTTPSConnection's default context verifies certificates/hostnames.
            return self.do_open(https_connection, req, context=self._context)

    return urllib.request.build_opener(_NoRedirect(), HTTP(), HTTPS()).open(
        request, timeout=_remaining(deadline)
    )


def _exchange(
    target: PublishTarget, path: str, payload: dict | None, timeout: float
) -> dict:
    deadline = time.monotonic() + timeout
    try:
        headers = target.authorization_headers()
    except ValueError:
        raise TransportError("invalid_credential") from None
    body = None
    if payload is not None:
        body = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        maximum = (
            384 * 1024
            if path.startswith("/watch/")
            else (
                640 * 1024
                if path.startswith("/stream/")
                else (
                    1024 * 1024 if path.startswith("/catalogue/") else 8 * 1024 * 1024
                )
            )
        )
        if len(body) > maximum:
            raise TransportError("oversize_data")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        target.url_for(path),
        data=body,
        headers=headers,
        method="GET" if body is None else "POST",
    )
    try:
        with _open(request, timeout=_remaining(deadline)) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise TransportError("oversize_response")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise TransportError("invalid_response")
        _remaining(deadline)
        return decoded
    except urllib.error.HTTPError as error:
        status = error.code
        reason = None
        try:
            raw_error = error.read(MAX_RESPONSE_BYTES + 1)
            detail = (
                json.loads(raw_error).get("detail")
                if len(raw_error) <= MAX_RESPONSE_BYTES
                else None
            )
            if isinstance(detail, dict) and detail.get("reason") in (
                "catalogue_awaiting_bootstrap",
                "view_not_admitted",
                "catalogue_already_sealed",
                "unsupported_protocol",
                "view_kind_conflict",
                "publisher_key_required",
                "remote_ingestion_requires_key",
                "publisher_key_not_configured",
                "watch_session_conflict",
                "watch_owner_conflict",
            ):
                reason = detail["reason"]
        except Exception:
            pass
        finally:
            error.close()
        categories = {
            401: "unauthorised_publisher",
            403: "inadmissible_view",
            409: "inadmissible_view",
            404: "registration_required",
            413: "oversize_data",
            400: "invalid_request",
            415: "invalid_request",
            422: "invalid_request",
            429: "ingestion_busy",
        }
        category = (
            "redirect_refused"
            if 300 <= status < 400
            else categories.get(status, "server_unavailable")
        )
        if reason == "unsupported_protocol":
            category = "incompatible_protocol"
        raise TransportError(category, status=status, reason=reason) from None
    except TransportError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise TransportError("invalid_response") from None
    except Exception:
        # Exception text may contain a URL, credential, proxy details or body.
        raise TransportError("server_unavailable") from None


def _failure(ctx: _Context, error: TransportError) -> None:
    now = time.monotonic()
    ctx.expires = 0.0
    ctx.last_error = error.category
    ctx.last_reason = error.reason
    if error.category in (
        "invalid_credential",
        "unauthorised_publisher",
        "incompatible_protocol",
        "redirect_refused",
        "inadmissible_view",
        "invalid_request",
        "oversize_data",
    ):
        ctx.retry_at = now + PERMANENT_COOLDOWN_S
    elif error.category in (
        "server_unavailable",
        "ingestion_busy",
        "invalid_response",
        "oversize_response",
    ):
        ctx.retry_at = now + FAILURE_COOLDOWN_S
    if now >= ctx.next_log:
        logging.getLogger(__name__).warning("Publisher delivery paused: %s", error)
        ctx.next_log = now + PERMANENT_COOLDOWN_S


def handshake(
    target: PublishTarget, *, feature: str, timeout_s: float | None = None
) -> ProtocolCapabilities:
    ctx = _context(target)
    timeout = target.request_timeout_s if timeout_s is None else timeout_s
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise TransportError("request_timeout")
    deadline = time.monotonic() + timeout
    # Competing producers do not wait behind a slow handshake on another target.
    if not ctx.lock.acquire(timeout=max(0.0, timeout)):
        raise TransportError("handshake_busy")
    try:
        now = time.monotonic()
        if now < ctx.retry_at:
            raise TransportError(
                ctx.last_error or "server_unavailable", reason=ctx.last_reason
            )
        if ctx.capabilities is None or now >= ctx.expires:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError("request_timeout")
            response = _exchange(target, "/capabilities", None, remaining)
            try:
                ctx.capabilities = ProtocolCapabilities(
                    **{
                        name: response[name]
                        for name in (
                            "protocol_version",
                            "stream_protocol_version",
                            "server_generation",
                            "dashboard_scope",
                            "capabilities",
                        )
                    }
                )
            except (KeyError, ValueError, TypeError):
                raise TransportError("incompatible_protocol") from None
            ctx.expires = time.monotonic() + CAPABILITY_TTL_S
        if feature not in ctx.capabilities.capabilities:
            raise TransportError("incompatible_protocol")
        ctx.last_error = None
        ctx.last_reason = None
        return ctx.capabilities
    except TransportError as error:
        # Cached rejection must not extend the cooldown on every pipeline call.
        if time.monotonic() >= ctx.retry_at:
            _failure(ctx, error)
        raise
    finally:
        ctx.lock.release()


def request_json(
    target: PublishTarget,
    path: str,
    payload: dict,
    *,
    feature: str,
    timeout_s: float | None = None,
) -> dict:
    timeout = target.request_timeout_s if timeout_s is None else timeout_s
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise TransportError("request_timeout")
    deadline = time.monotonic() + timeout
    handshake(target, feature=feature, timeout_s=timeout)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TransportError("request_timeout")
    try:
        result = _exchange(target, path, payload, remaining)
        _context(target).last_error = None
        _context(target).last_reason = None
        return result
    except TransportError as error:
        _failure(_context(target), error)
        raise
