"""Small background HTTP client for the dedicated stream protocol."""

from __future__ import annotations

import json
from dataclasses import replace
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from .file_source import JsonlBatch, JsonlRecord
from .models import (
    MAX_STREAM_REQUEST_BYTES,
    STREAM_PROTOCOL_VERSION,
    SourceHealth,
    SourceStatus,
    StreamRegistration,
    validate_source_health,
    validate_stream_batch,
)


REQUEST_TIMEOUT_S = 1.0
INITIAL_RETRY_DELAY_S = 0.1
MAX_RETRY_DELAY_S = 5.0
DEFAULT_HEARTBEAT_INTERVAL_S = 1.0


class StreamClient:
    """Register one stream session and acknowledge bounded follower batches.

    Its registration request runs in a daemon thread so ``stream_view`` returns
    immediately. The source follower retains exactly one batch until this
    client returns an acknowledgement. Failed delivery is retried after a
    bounded delay, with the original batch identity and sequence retained.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        registration: StreamRegistration,
        request_timeout_s: float | None = None,
        retry_initial_delay_s: float | None = None,
        retry_max_delay_s: float | None = None,
        heartbeat_interval_s: float | None = None,
        source_status_provider: Callable[[], SourceStatus] | None = None,
        source_health_provider: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        resolved_timeout = REQUEST_TIMEOUT_S if request_timeout_s is None else request_timeout_s
        resolved_initial_delay = (
            INITIAL_RETRY_DELAY_S
            if retry_initial_delay_s is None
            else retry_initial_delay_s
        )
        resolved_max_delay = (
            MAX_RETRY_DELAY_S if retry_max_delay_s is None else retry_max_delay_s
        )
        resolved_heartbeat_interval = (
            DEFAULT_HEARTBEAT_INTERVAL_S
            if heartbeat_interval_s is None
            else heartbeat_interval_s
        )
        if resolved_timeout <= 0:
            raise ValueError("request_timeout_s must be greater than zero")
        if resolved_initial_delay <= 0:
            raise ValueError("retry_initial_delay_s must be greater than zero")
        if resolved_max_delay < resolved_initial_delay:
            raise ValueError("retry_max_delay_s must not be below retry_initial_delay_s")
        if resolved_heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval_s must be greater than zero")

        self.host = host
        self.port = port
        self.registration = registration
        self._request_timeout_s = float(resolved_timeout)
        self._retry_initial_delay_s = float(resolved_initial_delay)
        self._retry_max_delay_s = float(resolved_max_delay)
        self._heartbeat_interval_s = float(resolved_heartbeat_interval)
        self._source_status_provider = source_status_provider
        self._source_health_provider = source_health_provider
        self._registered = threading.Event()
        self._heartbeat_stop = threading.Event()
        self._started = False
        self._start_lock = threading.Lock()
        self._append_lock = threading.RLock()
        self._server_instance_id: str | None = None
        self.on_session_changed: Callable[[str], None] | None = None
        # Source status and health are cumulative observations.  A heartbeat
        # and an append run on separate worker paths, so keep snapshot capture
        # and its HTTP delivery together: a delayed older snapshot must not
        # reach the registry after a newer one and look like a counter reset.
        self._source_telemetry_delivery_lock = threading.Lock()
        self._connection_lock = threading.Lock()
        self._heartbeat_thread: threading.Thread | None = None
        self._closed = False
        self._next_batch_sequence = 0
        self._pending_batch_id: str | None = None
        self._pending_batch_sequence: int | None = None
        self._registration_attempting = False
        self._next_retry_at = 0.0
        self._retry_delay_s = self._retry_initial_delay_s
        self.registration_attempts = 0
        self.registration_failures = 0
        self.delivery_attempts = 0
        self.delivery_failures = 0
        self.delivery_acknowledgements = 0
        self.heartbeat_attempts = 0
        self.heartbeat_failures = 0
        self.close_attempts = 0
        self.close_failures = 0
        self.last_error: BaseException | None = None

    def start(self) -> None:
        """Issue registration in a daemon worker exactly once."""
        with self._start_lock:
            if self._started:
                return
            self._started = True
            threading.Thread(
                target=self._ensure_registered,
                name=f"plotsrv-stream-register:{self.registration.view_id}",
                daemon=True,
            ).start()
            self._heartbeat_thread = threading.Thread(
                target=self._run_heartbeats,
                name=f"plotsrv-stream-heartbeat:{self.registration.view_id}",
                daemon=True,
            )
            self._heartbeat_thread.start()

    def append_batch(
        self,
        batch: JsonlBatch,
        *,
        timeout_s: float | None = None,
        force: bool = False,
    ) -> bool:
        """Attempt one retained batch without blocking the producer path."""
        # JsonlFollower validates source values first, but keep this direct
        # transport entry point strict for callers that construct JsonlRecord
        # themselves. Do not send a value the server cannot later return.
        validate_stream_batch(tuple(record.data for record in batch.records))
        with self._append_lock:
            if self._is_closed():
                return False
            if not self._registered.is_set():
                self._ensure_registered(timeout_s=timeout_s, force=force)
                if not self._registered.is_set():
                    return False
            if not force and self.retry_delay_s > 0:
                return False

            if self._pending_batch_id is None:
                self._pending_batch_id = batch.batch_id
                self._pending_batch_sequence = self._next_batch_sequence
            elif self._pending_batch_id != batch.batch_id:
                raise RuntimeError("stream client already has a batch awaiting acceptance")

            assert self._pending_batch_sequence is not None
            sequence = self._pending_batch_sequence
            try:
                with self._source_telemetry_delivery_lock:
                    payload = {
                        "protocol_version": STREAM_PROTOCOL_VERSION,
                        "view_id": self.registration.view_id,
                        "client_id": self.registration.client_id,
                        "session_id": self.registration.session_id,
                        "batch_id": batch.batch_id,
                        "batch_sequence": sequence,
                        "records": [record.data for record in batch.records],
                        **self._source_status_payload(),
                        **self._source_health_payload(),
                    }
                    with self._connection_lock:
                        self.delivery_attempts += 1
                    response = self._request_with_optional_timeout(
                        "/stream/append", payload, timeout_s=timeout_s
                    )
                next_sequence = response.get("next_batch_sequence")
                if (
                    not response.get("ok")
                    or isinstance(next_sequence, bool)
                    or not isinstance(next_sequence, int)
                    or next_sequence != sequence + 1
                ):
                    raise RuntimeError("stream append acknowledgement was invalid")
            except Exception as error:
                self._record_failure(error, operation="delivery")
                return False

            self._next_batch_sequence = next_sequence
            self._pending_batch_id = None
            self._pending_batch_sequence = None
            with self._connection_lock:
                self.delivery_acknowledgements += 1
            self._reset_retry()
        return True

    @property
    def retry_delay_s(self) -> float:
        """Time until another network attempt is permitted after failure."""
        with self._connection_lock:
            return max(0.0, self._next_retry_at - time.monotonic())

    def health(self) -> dict[str, object]:
        """Return bounded delivery counters suitable for local diagnostics."""
        with self._connection_lock:
            error = self.last_error
            return {
                "registered": self._registered.is_set(),
                "retry_delay_s": max(0.0, self._next_retry_at - time.monotonic()),
                "registration_attempts": self.registration_attempts,
                "registration_failures": self.registration_failures,
                "delivery_attempts": self.delivery_attempts,
                "delivery_failures": self.delivery_failures,
                "delivery_acknowledgements": self.delivery_acknowledgements,
                "heartbeat_attempts": self.heartbeat_attempts,
                "heartbeat_failures": self.heartbeat_failures,
                "close_attempts": self.close_attempts,
                "close_failures": self.close_failures,
                "closed": self._closed,
                "last_error": _bounded_error_text(error),
            }

    def append_record(self, record: JsonlRecord) -> None:
        """Compatibility adapter for direct one-record transport callers."""
        self.append_batch(
            JsonlBatch(
                batch_id=uuid4().hex,
                records=(record,),
                source_offset=record.source_offset,
                source_end_offset=record.source_end_offset,
            )
        )

    def heartbeat_once(self, *, source_status: SourceStatus | None = None) -> bool:
        """Send one lifecycle heartbeat while this client still owns its session."""
        if self._is_closed():
            return False
        if not self._registered.is_set():
            self._ensure_registered()
            if not self._registered.is_set():
                return False
        with self._append_lock:
            pending_delivery = self._pending_batch_id is not None
        delivery_state = "retrying" if pending_delivery or self.retry_delay_s > 0 else "live"
        try:
            with self._source_telemetry_delivery_lock:
                payload = {
                    "protocol_version": STREAM_PROTOCOL_VERSION,
                    "view_id": self.registration.view_id,
                    "client_id": self.registration.client_id,
                    "session_id": self.registration.session_id,
                    "delivery_state": delivery_state,
                    "pending_delivery": pending_delivery,
                    **self._source_status_payload(source_status),
                    **self._source_health_payload(),
                }
                with self._connection_lock:
                    self.heartbeat_attempts += 1
                response = self._request("/stream/heartbeat", payload)
            if response.get("ok") is not True or response.get("lifecycle") not in (
                "live",
                "retrying",
            ):
                raise RuntimeError("stream heartbeat acknowledgement was invalid")
            return True
        except Exception as error:
            self._record_failure(error, operation="heartbeat")
            return False

    def publish_source_status(self, status: SourceStatus) -> bool:
        """Publish one explicit, acknowledged safe source-status observation."""
        return self.heartbeat_once(source_status=status)

    def begin_shutdown(self) -> None:
        """Prevent future heartbeats before final drain and explicit close."""
        self._heartbeat_stop.set()

    def stop_heartbeats(self, *, timeout_s: float) -> bool:
        """Join the daemon heartbeat worker within a caller-provided budget."""
        self.begin_shutdown()
        thread = self._heartbeat_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout_s))
        return thread is None or not thread.is_alive()

    def close(self, *, drain_completed: bool, timeout_s: float) -> bool:
        """Attempt one bounded explicit-close request for this client session."""
        self.begin_shutdown()
        with self._connection_lock:
            if self._closed:
                return True
            self._closed = True
            self.close_attempts += 1
        if timeout_s <= 0:
            return False
        payload = {
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": self.registration.view_id,
            "client_id": self.registration.client_id,
            "session_id": self.registration.session_id,
            "drain_completed": drain_completed,
        }
        try:
            response = self._request_with_optional_timeout(
                "/stream/close", payload, timeout_s=timeout_s
            )
            expected = "ended" if drain_completed else "incomplete"
            if response.get("ok") is not True or response.get("lifecycle") != expected:
                raise RuntimeError("stream close acknowledgement was invalid")
            return True
        except Exception as error:
            with self._connection_lock:
                self.close_failures += 1
                self.last_error = error
            return False

    def _ensure_registered(
        self, *, timeout_s: float | None = None, force: bool = False
    ) -> bool:
        # Registration may be driven by either the heartbeat or the follower.
        # Serialize any receiver/session transition with pending-batch state.
        with self._append_lock:
            return self._register_locked(timeout_s=timeout_s, force=force)

    def _register_locked(
        self, *, timeout_s: float | None = None, force: bool = False
    ) -> bool:
        """Register the stable session once the retry window permits it."""
        if self._registered.is_set() or self._is_closed():
            return True
        with self._connection_lock:
            if self._registered.is_set() or self._closed:
                return True
            if self._registration_attempting or (
                not force and time.monotonic() < self._next_retry_at
            ):
                return False
            self._registration_attempting = True
            self.registration_attempts += 1
        try:
            with self._source_telemetry_delivery_lock:
                response = self._request_with_optional_timeout(
                    "/stream/register",
                    {
                        "protocol_version": STREAM_PROTOCOL_VERSION,
                        "view_id": self.registration.view_id,
                        "label": self.registration.label,
                        "section": self.registration.section,
                        "client_id": self.registration.client_id,
                        "session_id": self.registration.session_id,
                        "server_instance_id": self._server_instance_id,
                        **self._source_status_payload(),
                        **self._source_health_payload(),
                    },
                    timeout_s=timeout_s,
                )
            receiver = response.get("server_instance_id")
            if response.get("restart_required") is True:
                if not isinstance(receiver, str) or not receiver or len(receiver) > 512:
                    raise RuntimeError("stream receiver identity was invalid")
                self.registration = replace(self.registration, session_id=uuid4().hex)
                self._server_instance_id = receiver
                self._next_batch_sequence = 0
                if self._pending_batch_id is not None:
                    self._pending_batch_sequence = 0
                if self.on_session_changed is not None:
                    self.on_session_changed(self.registration.session_id)
                # One request per attempt: retry the new registration on the
                # next follower/heartbeat tick, without recursive reconnects.
                return False
            next_sequence = response.get("next_batch_sequence")
            if (
                not response.get("ok")
                or isinstance(next_sequence, bool)
                or not isinstance(next_sequence, int)
                or next_sequence < 0
            ):
                raise RuntimeError("stream registration acknowledgement was invalid")
            # When a request response was lost, the server may already have
            # advanced. The retained batch must retry at its original
            # sequence, so only adopt registration state when no batch awaits
            # acknowledgement.
            if self._pending_batch_id is None:
                self._next_batch_sequence = next_sequence
            if isinstance(receiver, str) and receiver:
                self._server_instance_id = receiver
            self._registered.set()
            self._reset_retry()
            return True
        except Exception as error:
            self._record_failure(error, operation="registration")
            return False
        finally:
            with self._connection_lock:
                self._registration_attempting = False

    def _run_heartbeats(self) -> None:
        """Renew server liveness while the source observer is active."""
        while not self._heartbeat_stop.wait(self._heartbeat_interval_s):
            self.heartbeat_once()

    def set_source_status_provider(
        self, provider: Callable[[], SourceStatus] | None
    ) -> None:
        """Set the follower status supplier before the asynchronous registration."""
        self._source_status_provider = provider

    def set_source_health_provider(
        self, provider: Callable[[], Mapping[str, object]] | None
    ) -> None:
        """Set the follower telemetry supplier before asynchronous registration."""
        self._source_health_provider = provider

    def _source_status_payload(
        self, source_status: SourceStatus | None = None
    ) -> dict[str, object]:
        """Return only the bounded source facts safe for browser transport."""
        if source_status is not None:
            status = source_status
        else:
            provider = self._source_status_provider
            if provider is None:
                status = SourceStatus()
            else:
                try:
                    status = provider()
                except Exception:
                    # Status reporting must not block record delivery or turn an
                    # internal source exception into a browser-facing OS message.
                    status = SourceStatus()
        return {
            "source_available": status.source_available,
            "source_transition": status.source_transition,
            "continuity_warning": status.continuity_warning,
        }

    def _source_health_payload(self) -> dict[str, object]:
        """Return fixed, optional source telemetry without blocking delivery."""
        provider = self._source_health_provider
        values: Mapping[str, object]
        if provider is None:
            values = {}
        else:
            try:
                supplied = provider()
                values = supplied if isinstance(supplied, Mapping) else {}
            except Exception:
                # Health presentation is best-effort and must neither block a
                # source batch nor expose an internal source error.
                values = {}

        health = SourceHealth(
            unread_source_bytes=_safe_source_health_count(
                values.get("unread_source_bytes")
            ),
            unacknowledged_source_bytes=_safe_source_health_count(
                values.get("unacknowledged_source_bytes")
            ),
            in_flight_records=_safe_source_health_count(values.get("in_flight_records")),
            records_seen=_safe_source_health_count(values.get("records_seen")),
            records_rejected=_safe_source_health_count(values.get("records_rejected")),
        )
        # The conversion above is deliberately defensive, but retain the
        # shared protocol validator as the single source of the wire bound.
        validate_source_health(health)
        return {"source_health": health.as_dict()}

    def _record_failure(
        self,
        error: BaseException,
        *,
        operation: str,
    ) -> None:
        """Schedule a bounded reconnect without spinning failed requests."""
        with self._connection_lock:
            self.last_error = error
            if operation == "delivery":
                self.delivery_failures += 1
            elif operation == "registration":
                self.registration_failures += 1
            elif operation == "heartbeat":
                self.heartbeat_failures += 1
            self._registered.clear()
            now = time.monotonic()
            delay = self._retry_delay_s
            self._next_retry_at = now + delay
            self._retry_delay_s = min(self._retry_max_delay_s, delay * 2)

    def _reset_retry(self) -> None:
        with self._connection_lock:
            self._next_retry_at = 0.0
            self._retry_delay_s = self._retry_initial_delay_s

    def _is_closed(self) -> bool:
        with self._connection_lock:
            return self._closed

    def _request_with_optional_timeout(
        self, path: str, payload: dict[str, Any], *, timeout_s: float | None
    ) -> dict[str, Any]:
        if timeout_s is None:
            return self._request(path, payload)
        return self._request(path, payload, timeout_s=timeout_s)

    def _request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > MAX_STREAM_REQUEST_BYTES:
            raise ValueError(
                "stream request exceeds the "
                f"{MAX_STREAM_REQUEST_BYTES}-byte limit"
            )
        request = urllib.request.Request(
            f"http://{self.host}:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = self._request_timeout_s if timeout_s is None else float(timeout_s)
        if timeout <= 0:
            raise ValueError("stream request timeout must be greater than zero")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError("stream server returned a non-object response")
        return decoded


def _bounded_error_text(error: BaseException | None) -> str | None:
    if error is None:
        return None
    text = f"{type(error).__name__}: {error}"
    return text[:512]


def _safe_source_health_count(value: object) -> int | None:
    """Discard a malformed local diagnostic rather than fail delivery."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > (2**53) - 1:
        return None
    return value
