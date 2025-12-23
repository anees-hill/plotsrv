from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Any

from .loader import load_callable
from .runner import run_once, RunResult
from .server import start_server, stop_server, refresh_view


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    target: str
    host: str
    port: int
    refresh_rate: int
    once: bool
    quiet: bool


class RunnerService:
    """
    Run a callable on a schedule and publish its output into plotsrv's store.

    - The callable must be importable via "module:function".
    - For v0.2.0 Part 1 we assume callable is zero-arg (or optional args only).
    """

    def __init__(self, cfg: ServiceConfig) -> None:
        self.cfg = cfg
        self.func: Callable[..., Any] = load_callable(cfg.target)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def _publish_result(self, res: RunResult) -> None:
        """
        Push result into existing plotsrv pipeline.
        refresh_view() already knows how to deal with:
          - matplotlib/plotnine objects
          - pandas/polars dataframes
        """
        # If you later want to use label, you can store it in store metadata.
        refresh_view(res.value)

    def run_cycle_once(self) -> None:
        """
        Runs one job cycle with overlap protection.
        """
        # If already running, skip
        if not self._lock.acquire(blocking=False):
            return
        try:
            res = run_once(self.func)
            self._publish_result(res)
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

        # Always do one initial run so the page has content quickly
        self.run_cycle_once()

        if self.cfg.once:
            return

        # Periodic loop
        while not self._stop_event.is_set():
            # Wait refresh_rate seconds, but wake early if stopped
            if self._stop_event.wait(timeout=self.cfg.refresh_rate):
                break
            self.run_cycle_once()

    def stop(self) -> None:
        self._stop_event.set()
        stop_server()
