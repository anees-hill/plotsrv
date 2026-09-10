"""Optional foreground catalogue/watch publisher. Never starts a server."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import math
from pathlib import Path
import signal
import sys
import threading
import time
from uuid import uuid4

from .connection_config import resolve_publish_target
from .contracts import ViewDescriptor
from .publishing.models import PublishTarget
from .publishing.transport import handshake, request_json, TransportError
from .runtime import WatchConfig, resolve_watch_max_bytes
from .source_setup import build_manifest, resolve_source_setup, watch_descriptor
from .watch_capture import (
    capture,
    prepare,
    signature,
    MAX_WATCHES,
    SESSION_LEASE_S,
    WATCH_FEATURE,
)


@dataclass
class WatchState:
    spec: WatchConfig
    descriptor: ViewDescriptor
    client: str
    session: str | None = None
    server_generation: str | None = None
    observed: tuple | None = None
    accepted: tuple | None = None
    source_generation: str = ""
    inode: tuple | None = None
    revision: int = 0
    status: str = "waiting"
    next_due: float = 0
    fenced: bool = False
    refresh_at: float = 0
    changed_polls: int = 0
    attempted: tuple | None = None


class RemoteWatcher:
    """One synchronous admission slot for all sources; no retained payload queue.

    Work coalesces to the version on disk when the next admitted turn begins.
    One slow source/transport delays other sources instead of spawning workers.
    """

    def __init__(self, watches, target, *, every=1.0, stop=None):
        if not math.isfinite(every) or every < 0.1:
            raise ValueError("watch interval must be finite and at least 0.1 seconds")
        if len(watches) > MAX_WATCHES:
            raise ValueError(f"At most {MAX_WATCHES} remote watches are supported")
        self.target, self.every = target, every
        self.stop = stop if stop is not None else threading.Event()
        self.states = []
        self.bytes_read = self.sent_updates = self.max_in_flight_bytes = 0
        self.timeout = min(target.request_timeout_s, 2.0)
        for spec in watches:
            if spec.encoding not in ("utf-8", "utf-8-sig", "ascii", "latin-1"):
                raise ValueError(
                    "Remote watch encoding must be utf-8, utf-8-sig, ascii or latin-1"
                )
            if spec.kind not in ("auto", "text", "json"):
                raise ValueError("Unsupported watch kind")
            descriptor = watch_descriptor(spec)
            self.states.append(WatchState(spec, descriptor, uuid4().hex))
        build_manifest([], watches=watches)

    def send(self, route, body):
        return request_json(
            self.target, route, body, feature=WATCH_FEATURE, timeout_s=self.timeout
        )

    def tick(self):
        for current in self.states:
            if self.stop.is_set():
                break
            now = time.monotonic()
            if now < current.next_due and (
                current.session is None or now < current.refresh_at
            ):
                continue
            try:
                caps = handshake(
                    self.target, feature=WATCH_FEATURE, timeout_s=self.timeout
                )
                if self.stop.is_set():
                    break
                if current.server_generation != caps.server_generation:
                    current.session = None
                    current.accepted = None
                    current.status = "waiting"
                    current.fenced = False
                    current.attempted = None
                    current.server_generation = caps.server_generation
                if current.fenced:
                    continue
                vid = current.descriptor.view_id
                if current.session is None or now >= current.refresh_at:
                    response = self.send(
                        "/watch/register",
                        dict(
                            protocol_version=1,
                            view_id=vid,
                            client_id=current.client,
                            label=current.descriptor.label,
                            section=current.descriptor.section,
                            **(
                                {"description": current.descriptor.description}
                                if current.descriptor.description is not None
                                and "view-descriptions-v1" in caps.capabilities
                                else {}
                            ),
                        ),
                    )
                    session = response.get("session")
                    if not isinstance(session, str) or not session or len(session) > 64:
                        raise TransportError("invalid_response")
                    if session != current.session:
                        current.accepted = None
                        current.attempted = None
                    current.session = session
                    current.refresh_at = time.monotonic() + SESSION_LEASE_S / 3
                if self.stop.is_set():
                    break
                if now < current.next_due:
                    continue
                current.next_due = now + max(
                    self.every, current.spec.update_limit_s or 0
                )
                path = Path(current.spec.path).expanduser().absolute()
                status = "available"
                sig = None
                try:
                    sig = signature(path.lstat())
                    if sig != current.observed:
                        current.observed = sig
                        current.changed_polls += 1
                        # Prefer a stable poll, but continuous changes must not
                        # starve snapshots. Attempt at least every second poll.
                        if current.changed_polls < 2:
                            continue
                    current.changed_polls = 0
                    if sig == current.accepted and current.status == "available":
                        continue
                    captured = capture(
                        path,
                        maximum=resolve_watch_max_bytes(current.spec, view_id=vid),
                        read_mode=current.spec.read_mode,
                        encoding=current.spec.encoding,
                        kind=current.spec.kind,
                    )
                    self.bytes_read += captured.bytes_read
                    sig = captured.signature
                    current.observed = sig
                    prepare(captured.raw, captured.source)
                    if current.attempted != (sig, status) and (
                        current.inode != sig[:2]
                        or (current.accepted and sig[2] < current.accepted[2])
                    ):
                        current.source_generation = uuid4().hex
                        current.inode = sig[:2]
                    source = dict(captured.source, generation=current.source_generation)
                    data = base64.b64encode(captured.raw).decode()
                    self.max_in_flight_bytes = max(self.max_in_flight_bytes, len(data))
                except FileNotFoundError:
                    status = "missing"
                except BlockingIOError:
                    status = "changing"
                except OSError:
                    status = "unreadable"
                except Exception:
                    status = "unsupported"
                if status != "available" and current.status == status:
                    continue
                if self.stop.is_set():
                    break
                version = (sig, status)
                if current.attempted != version:
                    current.revision += 1
                    current.attempted = version
                body = dict(
                    protocol_version=1,
                    view_id=vid,
                    session=current.session,
                    revision=current.revision,
                    status=status,
                )
                if status == "available":
                    body.update(source=source, data_b64=data, force=current.spec.force)
                response = self.send("/watch/update", body)
                if response.get("ok"):
                    current.status = status
                    if status == "available":
                        current.accepted = sig
                        self.sent_updates += not response.get("ignored", False)
            except TransportError as error:
                if error.reason == "watch_session_conflict":
                    current.fenced = True
                # Ownership conflicts may be orphaned leases: retry after the
                # shared cooldown; an explicitly fenced old session stays stopped.
                from .publishing.transport import (
                    PERMANENT_COOLDOWN_S,
                    FAILURE_COOLDOWN_S,
                )

                delay = (
                    PERMANENT_COOLDOWN_S
                    if error.category
                    in (
                        "invalid_credential",
                        "unauthorised_publisher",
                        "incompatible_protocol",
                        "inadmissible_view",
                        "invalid_request",
                        "oversize_data",
                        "redirect_refused",
                    )
                    else FAILURE_COOLDOWN_S
                )
                current.next_due = time.monotonic() + delay
                current.refresh_at = current.next_due
                # Shared bounded diagnostics/cooldown; never anonymous fallback.
                continue

    def run(self):
        try:
            while not self.stop.is_set():
                self.tick()
                self.stop.wait(min(self.every, 0.25))
        finally:
            self.close()

    def close(self):
        deadline = time.monotonic() + 2.0
        for current in self.states:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if current.session:
                try:
                    request_json(
                        self.target,
                        "/watch/close",
                        dict(
                            protocol_version=1,
                            view_id=current.descriptor.view_id,
                            session=current.session,
                        ),
                        feature=WATCH_FEATURE,
                        timeout_s=min(remaining, self.timeout),
                    )
                except TransportError:
                    pass
                finally:
                    current.session = None


def foreground(watcher):
    # Signals request cooperative stop, including while an HTTP exchange finishes.
    previous = {}

    def stop_or_interrupt(*_):
        if watcher.stop.is_set():
            raise KeyboardInterrupt
        watcher.stop.set()

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop_or_interrupt)
    try:
        watcher.run()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


def destination_for_cli(args):
    destination = getattr(args, "destination", None)
    key = getattr(args, "bearer_token_env", None)
    if key and not destination:
        raise ValueError(
            "--bearer-token-env requires --destination; otherwise use destination config"
        )
    if destination:
        target = PublishTarget(
            kind="remote", base_url=destination, bearer_token_env=key
        )
        return resolve_publish_target(
            destination=target,
            host=args.host if getattr(args, "host_supplied", False) else None,
            port=args.port if getattr(args, "port_supplied", False) else None,
        )
    return resolve_publish_target(
        host=args.host if getattr(args, "host_supplied", False) else None,
        port=args.port if getattr(args, "port_supplied", False) else None,
        launch_server=False,
    )


def publish_command(args):
    setup = resolve_source_setup(
        target=args.target, watches=[] if args.no_watch else None
    )
    if not args.quiet:
        for message in setup.messages:
            print(message, file=sys.stderr)
    target = destination_for_cli(args)
    discovered = []
    if not args.no_discovery and setup.target is not None:
        from .discovery import scan_sources
        from .discovery_progress import TerminalProgress

        progress = TerminalProgress(quiet=args.quiet)
        discovered = scan_sources(
            setup.scan_root(),
            on_progress=progress,
            on_issue=progress.issue,
            include_pruned=setup.include_pruned,
        )
    manifest = build_manifest(
        discovered,
        watches=setup.watches,
        added_ids=args.add_id,
        selection=setup.selection,
        reviewed=args.reviewed,
    )
    specs = [WatchConfig(**vars(spec)) for spec in setup.watches]
    watcher = RemoteWatcher(
        specs, target, every=args.every
    )  # Validate before any remote mutation.
    route = "/catalogue/bootstrap" if args.seal_catalogue else "/catalogue/register"
    if args.seal_catalogue and not args.quiet:
        print(
            "Sealing this complete manifest. Include every project's IDs and reviewed dynamic IDs; later partial catalogues cannot extend it.",
            file=sys.stderr,
        )
    response = request_json(
        target,
        route,
        manifest,
        feature="catalogue-bootstrap" if args.seal_catalogue else "catalogue-register",
    )
    if not args.quiet:
        print(
            f"Registered {len(manifest['views'])} catalogue entries; sealed={response.get('sealed', False)}."
        )
    if not specs:
        return 0
    return foreground(watcher)
