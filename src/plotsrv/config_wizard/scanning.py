"""One cooperative scan, one replaceable progress slot, no UI message backlog."""

from __future__ import annotations

from threading import Event, Lock, Thread

from ..discovery import scan_sources


class ScanJob:
    def __init__(self, setup):
        self.setup = setup
        self.cancelled = Event()
        self.done = Event()
        self.lock = Lock()
        self.progress = None
        self.result = None
        self.error = None
        self.thread = Thread(
            target=self._run, name="plotsrv-config-discovery", daemon=True
        )

    def start(self):
        self.thread.start()

    def update(self, progress):
        with self.lock:
            self.progress = progress

    def take_progress(self):
        with self.lock:
            progress, self.progress = self.progress, None
            return progress

    def _run(self):
        try:
            if self.cancelled.is_set():
                return
            if self.setup.target is None:
                from ..source_targets import default_source_target

                root = self.setup.scan_root(default_source_target())
            else:
                root = self.setup.scan_root()
            if not self.cancelled.is_set():
                self.result = scan_sources(
                    root,
                    on_progress=self.update,
                    cancelled=self.cancelled,
                    include_pruned=self.setup.include_pruned,
                )
        except Exception:
            self.error = "Discovery could not read this scope. Choose an existing package/path, or continue without discovery."
        finally:
            self.done.set()

    def cancel(self):
        self.cancelled.set()

    def close(self):
        self.cancel()
        if self.thread.ident is not None:
            self.thread.join(timeout=0.05)
