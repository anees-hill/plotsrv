"""Public source-registration API for append-only plotsrv streams."""

from __future__ import annotations

import atexit
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import threading
import time
from uuid import uuid4

from .. import config
from .client import StreamClient
from .file_source import JsonlFollower, resolve_jsonl_source
from .models import StreamRegistration


@dataclass(slots=True)
class StreamHandle:
    """A lightweight reference to the local background JSONL observer.

    ``stop()`` stops the local observer, attempts a bounded final delivery,
    then sends an explicit ended or incomplete close outcome.  It reports only
    observation state; it never claims anything about application shutdown.
    """

    source: Path
    label: str
    section: str
    host: str
    port: int
    view_id: str
    client_id: str
    session_id: str
    observation_started_at: datetime
    source_existed_at_start: bool
    initial_offset: int
    _follower: JsonlFollower = field(repr=False)
    _client: StreamClient = field(repr=False)
    _stop_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)

    @property
    def is_observing(self) -> bool:
        """Whether this handle's daemon JSONL follower is alive."""
        return self._follower.is_running

    @property
    def acknowledged_source_offset(self) -> int:
        """Last source byte accepted by the stream server."""
        return self._follower.acknowledged_source_offset

    @property
    def candidate_source_offset(self) -> int:
        """End of the one retained source batch awaiting acknowledgement."""
        return self._follower.candidate_source_offset

    @property
    def accounted_source_offset(self) -> int:
        """Source progress including completed malformed or oversized lines."""
        return self._follower.accounted_source_offset

    @property
    def health(self) -> dict[str, object]:
        """Bounded source and transport counters for this stream observer."""
        return {
            **self._follower.health(),
            "delivery": self._client.health(),
            "stopped": self._stopped,
        }

    def stop(self, *, timeout: float | None = None) -> None:
        """Perform one bounded final drain and explicit close attempt.

        A failed worker join, pending source batch, unfinished source line, or
        failed delivery becomes an explicit ``incomplete`` close if the server
        accepts it.  A failed close is left for heartbeat expiry to report as
        disconnected or incomplete; this method never fabricates ``ended``.
        """
        budget_s = (
            config.get_stream_shutdown_drain_timeout_s() if timeout is None else timeout
        )
        if isinstance(budget_s, bool) or not isinstance(budget_s, (int, float)):
            raise ValueError("timeout must be a positive number of seconds")
        if budget_s <= 0:
            raise ValueError("timeout must be greater than zero")
        deadline = time.monotonic() + float(budget_s)
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
            follower_stopped = False
            try:
                self._client.begin_shutdown()
                self._client.stop_heartbeats(
                    timeout_s=min(0.05, self._remaining(deadline))
                )

                # Reserve a small positive request window for close even if a
                # daemon source worker is stuck in a previous bounded HTTP call.
                close_reserve_s = 0.001
                follower_stopped = self._follower.stop(
                    timeout=max(0.0, self._remaining(deadline) - close_reserve_s)
                )
                drain_completed = False
                if follower_stopped:
                    drain_completed = self._follower.drain(
                        timeout_s=max(
                            0.0, self._remaining(deadline) - close_reserve_s
                        ),
                        on_batch=lambda batch: self._client.append_batch(
                            batch,
                            timeout_s=max(close_reserve_s, self._remaining(deadline)),
                            force=True,
                        ),
                    )
                self._client.close(
                    drain_completed=follower_stopped and drain_completed,
                    timeout_s=max(close_reserve_s, self._remaining(deadline)),
                )
            finally:
                if follower_stopped:
                    close_follower = getattr(self._follower, "close", None)
                    if callable(close_follower):
                        try:
                            close_follower()
                        except Exception:
                            pass
                _stream_exit_cleanup_manager.unregister(self)

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())


class _StreamExitCleanupManager:
    """One atexit-only owner for bounded best-effort stream cleanup.

    This manager deliberately uses no signal APIs.  Hosts retain complete
    ownership of application signal handlers and decide their own signal
    policy; normal interpreter exit merely gets a short final-drain attempt.
    """

    def __init__(self) -> None:
        self._handles: dict[int, StreamHandle] = {}
        self._lock = threading.Lock()

    def register(self, handle: StreamHandle) -> None:
        with self._lock:
            self._handles[id(handle)] = handle

    def unregister(self, handle: StreamHandle) -> None:
        with self._lock:
            self._handles.pop(id(handle), None)

    def cleanup(self) -> None:
        """Spend one finite process-wide budget across registered handles."""
        try:
            deadline = time.monotonic() + config.get_stream_process_exit_cleanup_timeout_s()
            with self._lock:
                handles = tuple(self._handles.values())
                self._handles.clear()
            for handle in handles:
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    break
                try:
                    handle.stop(timeout=remaining)
                except Exception:
                    # Never turn interpreter shutdown into a user-script
                    # exception while optional modules may be tearing down.
                    continue
        except Exception:
            return


_stream_exit_cleanup_manager = _StreamExitCleanupManager()
atexit.register(_stream_exit_cleanup_manager.cleanup)


def stream_view(
    *,
    source: str | Path,
    label: str | None = None,
    section: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    view_id: str | None = None,
    client_id: str | None = None,
    session_id: str | None = None,
) -> StreamHandle:
    """Observe newly appended JSON objects from a JSONL or NDJSON source.

    Existing sources begin at their registration EOF.  A missing source is
    accepted and begins at byte zero once it appears.  The ongoing observation
    always runs in a daemon worker; it does not use plotsrv's snapshot
    ``PublishWorker`` or consult ordinary snapshot async configuration.

    ``client_id`` is a stable producer-client identity when callers need to
    relate distinct sessions.  ``session_id`` is the ownership epoch for this
    particular stream registration.  Omitting either creates a fresh opaque
    ID; pass both again only when intentionally retrying the same session.
    """
    source_path = resolve_jsonl_source(source)
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host must be a non-empty string")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("port must be an integer from 1 through 65535")

    stream_label = (label or source_path.stem).strip() or source_path.stem
    stream_section = (section or "stream").strip() or "stream"
    stream_view_id = view_id or f"{stream_section}:{stream_label}"
    stream_client_id = _resolve_identity(client_id, "client_id")
    stream_session_id = _resolve_identity(session_id, "session_id")
    registration = StreamRegistration(
        view_id=stream_view_id,
        label=stream_label,
        section=stream_section,
        client_id=stream_client_id,
        session_id=stream_session_id,
    )
    client = StreamClient(
        host=host,
        port=port,
        registration=registration,
        request_timeout_s=config.get_stream_request_timeout_s(),
        retry_initial_delay_s=config.get_stream_retry_initial_delay_s(),
        retry_max_delay_s=config.get_stream_retry_max_delay_s(),
        heartbeat_interval_s=config.get_stream_heartbeat_interval_s(),
    )
    publish_source_status = getattr(client, "publish_source_status", None)
    follower = JsonlFollower(
        source_path,
        on_batch=client.append_batch,
        on_source_status=(
            publish_source_status if callable(publish_source_status) else None
        ),
        retry_delay=lambda: getattr(client, "retry_delay_s", 0.0),
        poll_interval_s=config.get_stream_poll_interval_s(),
    )
    set_source_status_provider = getattr(client, "set_source_status_provider", None)
    if callable(set_source_status_provider):
        set_source_status_provider(follower.source_status)
    set_source_health_provider = getattr(client, "set_source_health_provider", None)
    if callable(set_source_health_provider):
        set_source_health_provider(follower.health)
    handle = StreamHandle(
        source=source_path,
        label=stream_label,
        section=stream_section,
        host=host,
        port=port,
        view_id=stream_view_id,
        client_id=registration.client_id,
        session_id=registration.session_id,
        observation_started_at=follower.observation_started_at,
        source_existed_at_start=follower.source_existed_at_start,
        initial_offset=follower.initial_offset,
        _follower=follower,
        _client=client,
    )
    client.start()
    follower.start()
    _stream_exit_cleanup_manager.register(handle)
    return handle


def _resolve_identity(value: str | None, field: str) -> str:
    """Use a caller-supplied stable ID or create a fresh producer identity."""
    if value is None:
        return uuid4().hex
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()
