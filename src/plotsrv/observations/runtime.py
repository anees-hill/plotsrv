"""One event-driven consumer of detached observations, independent of raw tasks."""

from __future__ import annotations

from collections import OrderedDict
import logging
import math
import os
import threading
import time
from uuid import uuid4

from .admission import CaptureEngine, get_capture_engine
from .models import CaptureOptions, ObservationRoute
from .summary import build_summary, encode_summary, MAX_OBSERVATION_BYTES

MAX_REQUEST_BYTES = MAX_OBSERVATION_BYTES + 16 * 1024
MAX_TARGETS = 16
_DEFAULT_OPTIONS = CaptureOptions()


def observation_options(observe, async_=None):
    if observe is False:
        return None
    if observe is True:
        options = _DEFAULT_OPTIONS
    elif type(observe) is CaptureOptions:
        options = observe
    else:
        raise ValueError("observe must be True, False, or ObservationOptions")
    if async_ is not None and async_ is not True:
        raise ValueError(
            "observation requires background delivery; async_=False is incompatible"
        )
    return options


def _validate_route_arguments(arguments):
    from ..publishing.models import PublishTarget

    for key, value in arguments.items():
        if value is None:
            continue
        if key == "destination" and type(value) is PublishTarget:
            continue
        if key in ("destination", "host", "mode", "label", "section", "view_id"):
            if type(value) is not str or len(value) > (
                2048 if key == "destination" else 512
            ):
                raise ValueError("invalid observation routing metadata")
        elif key in ("port", "update_limit_s"):
            if type(value) is not int or not 0 <= value <= 86400:
                raise ValueError("invalid observation routing number")
        elif key in ("launch_server", "force") and type(value) is not bool:
            raise ValueError("invalid observation routing option")


class ObservationWorker:
    def __init__(self, engine: CaptureEngine):
        self.engine = engine
        self._pid = os.getpid()
        self._cache_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._targets = OrderedDict()
        self._routes = OrderedDict()
        self._thread = None
        self._running = False
        self._next_warning = 0.0
        self._setup_retry_at = 0.0
        self.last_error = None
        self.session = uuid4().hex

    def start(self):
        if self._pid != os.getpid() or self.engine._closed and self._running:
            return False
        if self._running:
            return True
        if not self._start_lock.acquire(False):
            return False
        try:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self.engine._closed:
                if not self._cache_lock.acquire(False):
                    return False
                try:
                    if not self.engine.reopen():
                        return False
                    self._targets.clear()
                    self._routes.clear()
                    self._setup_retry_at = 0.0
                    self.session = uuid4().hex
                finally:
                    self._cache_lock.release()
            self._running = True
            self._thread = threading.Thread(
                target=self._run, name="plotsrv-observation-worker", daemon=True
            )
            try:
                self._thread.start()
            except Exception:
                self._running = False
                self.engine.close()
                raise
            return True
        finally:
            self._start_lock.release()

    def route(self, **arguments):
        """Cache setup only; warm admission does no config/filesystem/credential IO."""
        from ..connection_config import resolve_publish_target
        from ..contracts import bounded_text
        from ..publishing.models import PublishTarget

        _validate_route_arguments(arguments)
        connection = {
            key: arguments.get(key)
            for key in ("destination", "host", "port", "mode", "launch_server")
        }
        destination = connection["destination"]
        target_key = tuple(
            id(value) if type(value) is PublishTarget else value
            for value in connection.values()
        )
        metadata = tuple(
            arguments.get(key)
            for key in ("label", "section", "view_id", "update_limit_s", "force")
        )
        key = (target_key, metadata)
        if not self._cache_lock.acquire(False):
            return None
        try:
            cached = self._routes.get(key)
            if cached is not None:
                return cached
            target = self._targets.get(target_key)
            if target is None:
                if len(self._targets) >= MAX_TARGETS:
                    return None
                target = resolve_publish_target(**connection)
                self._targets[target_key] = target
            label = arguments.get("label") or "default"
            section = arguments.get("section")
            view_id = arguments.get("view_id")
            if view_id is None:
                view_id = f"{(section or 'default').strip() or 'default'}:{label.strip() or 'default'}"
            bounded_text(view_id, "view_id", 512)
            route = ObservationRoute(
                target,
                label,
                section,
                arguments.get("update_limit_s"),
                arguments.get("force", False),
            )
            if len(self._routes) >= self.engine.budget.max_view_ids:
                self._routes.popitem(last=False)
            self._routes[key] = (view_id, route)
            return view_id, route
        finally:
            self._cache_lock.release()

    def submit(self, source, options, **arguments):
        if time.monotonic() < self._setup_retry_at:
            self.engine._count("skipped")
            return "setup_cooldown"
        if not self.start():
            return "closed"
        try:
            resolved = self.route(**arguments)
            if resolved is None:
                self.engine._count("skipped")
                return "routing_busy_or_full"
            view_id, route = resolved
            return self.engine.submit(view_id, source, options, route=route)
        except Exception:
            self.engine._count("skipped")
            self.last_error = "invalid_observation_setup"
            self._setup_retry_at = time.monotonic() + 30
            return "invalid_setup"

    def _invalidate_target(self, route):
        # Consumer only; retain neither the failed work nor exception.
        with self._cache_lock:
            keys = [
                key for key, target in self._targets.items() if target is route.target
            ]
            for key in keys:
                del self._targets[key]
            for key, (_, cached) in tuple(self._routes.items()):
                if cached.target is route.target:
                    del self._routes[key]

    def _warn(self, code):
        self.last_error = code
        now = time.monotonic()
        if now >= self._next_warning:
            self._next_warning = now + 30
            try:
                logging.getLogger(__name__).warning(
                    "Observation delivery skipped: %s", code
                )
            except Exception:
                pass

    def _run(self):
        try:
            while (work := self.engine.wait_take()) is not None:
                succeeded, pause_s, error = False, 0, None
                route = work.route
                try:
                    if route is None:
                        raise ValueError("missing observation route")
                    summary = build_summary(
                        work.envelope,
                        budget=self.engine.budget,
                        publisher_session=self.session,
                        diagnostics={
                            "scope": "publisher_process",
                            "best_effort": True,
                            **self.engine.stats()["counters"],
                        },
                    )
                    succeeded = self._deliver(summary, work.view_id, route)
                    if not succeeded:
                        error, pause_s = "delivery_rejected", 5
                except Exception as failure:
                    from ..publishing.transport import TransportError

                    error = (
                        failure.category
                        if type(failure) is TransportError
                        else "observation_delivery_failed"
                    )
                    pause_s = (
                        30
                        if error
                        in (
                            "invalid_credential",
                            "unauthorised_publisher",
                            "inadmissible_view",
                            "incompatible_protocol",
                            "invalid_request",
                            "oversize_data",
                            "redirect_refused",
                        )
                        else 5
                    )
                    if error == "invalid_credential" and route is not None:
                        self._invalidate_target(route)
                finally:
                    self.engine.complete(
                        work.token,
                        succeeded=succeeded,
                        pause_target=(
                            route.target_key if route is not None and pause_s else None
                        ),
                        pause_s=pause_s,
                    )
                    # Release every envelope/result before sleeping again.
                    del work
                    if "summary" in locals():
                        del summary
                if error is not None:
                    self._warn(error)
                else:
                    self.last_error = None
                route = None
        finally:
            self.engine.close()
            self._running = False

    def _deliver(self, summary, view_id, route):
        if self.engine._closed:
            return False
        payload = {
            "kind": "artifact",
            "artifact_kind": "json",
            "observation": summary,
            "view_id": view_id,
            "label": route.label,
            "section": route.section,
            "update_limit_s": route.update_limit_s,
            "force": route.force,
        }
        if len(encode_summary(payload)) > MAX_REQUEST_BYTES:
            raise ValueError("observation request budget")
        if route.target.kind == "remote":
            from ..publishing.transport import request_json

            response = request_json(
                route.target,
                "/publish",
                payload,
                feature="observation-v1",
                timeout_s=min(2.0, route.target.request_timeout_s),
            )
        else:
            from .. import server
            from .receiver import receive_observation

            with server._SERVER_LOCK:
                active = (
                    server._SERVER_RUNNING
                    or server._SERVER_STARTING
                    or server._SERVER_THREAD is not None
                    and server._SERVER_THREAD.is_alive()
                )
            if active:
                server._ensure_server_running(
                    route.target.host, route.target.port, quiet=True
                )
            else:
                server.start_server(
                    host=route.target.host,
                    port=route.target.port,
                    auto_on_show=False,
                    quiet=True,
                    announce=False,
                    restore_latest=False,
                )
            if self.engine._closed:
                return False
            response = receive_observation(payload)
        return response.get("ok") is True

    def stop(self, *, timeout=0.0):
        if self._pid != os.getpid():
            return
        self.engine.close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, timeout))


_WORKER = None
_LOCK = threading.Lock()
_SETUP_ERROR = None
_SETUP_RETRY_AT = 0.0


def _after_fork():
    global _WORKER, _LOCK, _SETUP_ERROR, _SETUP_RETRY_AT
    _WORKER, _LOCK, _SETUP_ERROR, _SETUP_RETRY_AT = None, threading.Lock(), None, 0.0


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def get_observation_worker():
    global _WORKER
    if _WORKER is not None:
        return _WORKER
    if not _LOCK.acquire(False):
        return None
    try:
        if _WORKER is None:
            _WORKER = ObservationWorker(get_capture_engine())
        return _WORKER
    finally:
        _LOCK.release()


def submit_observation(source, options, **arguments):
    global _SETUP_ERROR, _SETUP_RETRY_AT
    if time.monotonic() < _SETUP_RETRY_AT:
        return
    try:
        worker = get_observation_worker()
        if worker is not None:
            worker.submit(source, options, **arguments)
    except Exception:
        # No logging callbacks or exception formatting in the observed pipeline.
        _SETUP_ERROR = "invalid_observation_setup"
        _SETUP_RETRY_AT = time.monotonic() + 30


def flush_observations(timeout):
    worker = _WORKER
    if worker is None:
        return True
    if not math.isfinite(timeout):
        raise ValueError("observation flush requires a finite timeout")
    return worker.engine.flush(max(0.0, timeout))


def stop_observations(*, timeout=0.0):
    worker = _WORKER
    if worker is not None:
        worker.stop(timeout=timeout)


def get_observation_stats():
    worker = _WORKER
    if worker is None:
        return {
            "running": False,
            "last_error": _SETUP_ERROR,
            "pending": 0,
            "reserved": 0,
        }
    return {
        **worker.engine.stats(),
        "running": worker._running,
        "last_error": worker.last_error,
        "targets": len(worker._targets),
        "routes": len(worker._routes),
    }
