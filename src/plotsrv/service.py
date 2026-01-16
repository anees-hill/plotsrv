# src/plotsrv/service.py
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .loader import load_callable
from .runner import run_once, RunResult
from .server import start_server, stop_server, refresh_view
from . import store


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    target: str
    host: str
    port: int
    refresh_rate: int
    once: bool
    keep_alive: bool
    quiet: bool


class RunnerService:
    """
    Run a callable on a schedule and publish its output into plotsrv.

    v0.2.0 Part 1:
      - target is importable as "module:function"
      - callable must be zero-arg (or only optional args with defaults)
    """

    def __init__(self, cfg: ServiceConfig) -> None:
        self.cfg = cfg
        self.func: Callable[..., Any] = load_callable(cfg.target)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def _publish_result(self, res: RunResult) -> None:
        """
        Push result into existing plotsrv pipeline.

        We set update_status=False here because this CLI service owns the
        "duration + last error" status bookkeeping.
        """
        refresh_view(res.value, update_status=False)

    def run_cycle_once(self) -> None:
        """
        Runs one job cycle with overlap protection.

        - If already running, skip.
        - On success: updates last_updated/duration and clears last_error.
        - On error: sets last_error but keeps last good plot/table.
        """
        if not self._lock.acquire(blocking=False):
            return

        start = time.perf_counter()
        try:
            res = run_once(self.func)
            self._publish_result(res)
            duration = time.perf_counter() - start
            store.mark_success(duration_s=duration)
        except Exception as e:
            store.mark_error(f"{type(e).__name__}: {e}")
        finally:
            self._lock.release()

    def run(self) -> None:
        """
        Start server and run once or periodically.
        """
        start_server(
            host=self.cfg.host,
            port=self.cfg.port,
            auto_on_show=False,
            quiet=self.cfg.quiet,
        )

        # Tell the UI we are running in service mode
        store.set_service_info(
            service_mode=True,
            target=self.cfg.target,
            refresh_rate_s=(self.cfg.refresh_rate if not self.cfg.once else None),
        )

        # Allow /shutdown to stop the service loop cleanly
        store.set_service_stop_hook(self.stop)

        # Always do an initial run so the page has content quickly
        self.run_cycle_once()

        # --once mode
        if self.cfg.once:
            if not self.cfg.keep_alive:
                # Shut down server and exit immediately
                stop_server()
                store.set_service_info(
                    service_mode=False, target=None, refresh_rate_s=None
                )
                return

            # Keep the server alive until stopped (Ctrl+C or /shutdown)
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=0.2)

            store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)
            return

        # periodic mode
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.cfg.refresh_rate):
                break
            self.run_cycle_once()

        store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)

    def stop(self) -> None:
        self._stop_event.set()
        store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)
        stop_server()
