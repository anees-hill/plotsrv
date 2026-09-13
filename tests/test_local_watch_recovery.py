"""Local watches retain delivery intent, never a queue of source payloads."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import pytest

from plotsrv import runtime
from plotsrv.publishing import transport


@pytest.fixture(params=[False, True], ids=["threads", "coalesced"])
def probe(tmp_path, monkeypatch, request):
    path = tmp_path / "source.txt"
    path.write_text("initial")
    clock = [0.0]
    waits = []
    events = []
    hook = [lambda: None]

    class Event:
        stopped = False

        def __init__(self):
            events.append(self)

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, delay):
            waits.append(delay)
            clock[0] += delay
            hook[0]()
            if len(waits) >= 8:
                self.set()
            return self.stopped

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(runtime.threading, "Thread", Thread)
    monkeypatch.setattr(runtime.threading, "Event", Event)
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime.random, "uniform", lambda *args: 0.5)
    monkeypatch.setattr(runtime, "_local_watch_ready", lambda *args: None)
    monkeypatch.setattr(
        runtime, "resolve_watch_materialization", lambda *args, **kwargs: "memory"
    )
    reads = []
    original = runtime.read_watch_file_bytes

    def read(*args, **kwargs):
        reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "read_watch_file_bytes", read)

    def run():
        runtime.start_watch_threads(
            [runtime.WatchConfig(path=path, label="probe", section="test")],
            host="127.0.0.1",
            port=1,
            register_views=False,
            coalesce=request.param,
        )

    return path, waits, reads, hook, run


def test_rejected_unchanged_file_recovers_then_rests(probe, monkeypatch):
    path, waits, reads, hook, run = probe
    sent = []

    def publish(**kwargs):
        sent.append(
            kwargs["payload"].artifact.removeprefix("\ufeffPLOTSRV_ANCHOR=tail\n")
        )
        return len(sent) > 1

    monkeypatch.setattr(runtime, "publish_prepared_watch_payload", publish)
    run()
    assert sent == ["initial", "initial"]
    assert len(reads) == 2
    assert waits == [2.5] + [1.0] * 7


def test_outage_skips_reads_coalesces_changes_and_bounds_logs(
    probe, monkeypatch, caplog
):
    path, waits, reads, hook, run = probe
    sent = []

    def ready(*args):
        if len(waits) < 6:
            raise transport.TransportError("server_unavailable")

    hook[0] = lambda: (
        path.write_text(f"latest-{len(waits)}") if len(waits) <= 6 else None
    )
    monkeypatch.setattr(runtime, "_local_watch_ready", ready)
    monkeypatch.setattr(
        runtime,
        "publish_prepared_watch_payload",
        lambda **kw: sent.append(
            kw["payload"].artifact.removeprefix("\ufeffPLOTSRV_ANCHOR=tail\n")
        )
        or True,
    )
    run()
    assert sent == ["latest-6"]
    assert len(reads) == 1
    assert max(waits) <= 30
    assert len(caplog.records) < 6


def test_busy_slot_does_no_preparation(probe, monkeypatch):
    path, waits, reads, hook, run = probe
    monkeypatch.setattr(runtime, "publish_prepared_watch_payload", lambda **kw: True)
    with runtime._LOCAL_WATCH_SLOT:
        run()
    assert not reads
    assert waits == [1.0] * 8


def test_replacement_during_read_is_not_acknowledged(probe, monkeypatch):
    path, waits, reads, hook, run = probe
    sent = []
    original = runtime.read_watch_file_bytes

    def read(*args, **kwargs):
        raw = original(*args, **kwargs)
        if len(reads) == 1:
            replacement = path.with_suffix(".new")
            replacement.write_text("replacement")
            replacement.replace(path)
        return raw

    monkeypatch.setattr(runtime, "read_watch_file_bytes", read)
    monkeypatch.setattr(
        runtime,
        "publish_prepared_watch_payload",
        lambda **kw: sent.append(
            kw["payload"].artifact.removeprefix("\ufeffPLOTSRV_ANCHOR=tail\n")
        )
        or True,
    )
    run()
    assert sent == ["replacement"]
    assert len(reads) == 2


def test_shutdown_during_preparation_prevents_publication(probe, monkeypatch):
    path, waits, reads, hook, run = probe
    original = runtime.read_watch_file_bytes

    def read(*args, **kwargs):
        raw = original(*args, **kwargs)
        runtime.stop_watch_threads()
        return raw

    def forbidden(**kwargs):
        pytest.fail("published after shutdown")

    monkeypatch.setattr(runtime, "read_watch_file_bytes", read)
    monkeypatch.setattr(runtime, "publish_prepared_watch_payload", forbidden)
    run()
    assert len(reads) == 1


@pytest.mark.parametrize("coalesce", [False, True])
def test_fifteen_watch_startup_recovers_over_http_and_stops(
    tmp_path, monkeypatch, coalesce
):
    received = {}
    requests = []
    active = [0, 0]
    guard = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.reply(
                200,
                dict(
                    protocol_version=1,
                    stream_protocol_version=4,
                    server_generation="probe",
                    dashboard_scope="probe",
                    capabilities=["publish"],
                ),
            )

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with guard:
                requests.append(payload["label"])
                active[0] += 1
                active[1] = max(active)
                reject = len(requests) <= 2
            time.sleep(0.01)
            try:
                if reject:
                    self.reply(429, {"error": "ingestion_busy"})
                else:
                    received[payload["label"]] = payload["artifact"].removeprefix(
                        "\ufeffPLOTSRV_ANCHOR=tail\n"
                    )
                    self.reply(200, {"ok": True})
            finally:
                with guard:
                    active[0] -= 1

    monkeypatch.setattr(transport, "FAILURE_COOLDOWN_S", 0.05)
    monkeypatch.setattr(
        runtime, "resolve_watch_materialization", lambda *args, **kwargs: "memory"
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    runner = threading.Thread(target=server.serve_forever, daemon=True)
    runner.start()
    specs = []
    for i in range(15):
        path = tmp_path / f"source-{i}.txt"
        path.write_text(f"content-{i}")
        specs.append(runtime.WatchConfig(path=path, label=str(i), section="test"))
    workers = []
    try:
        workers = runtime.start_watch_threads(
            specs,
            host="127.0.0.1",
            port=server.server_port,
            register_views=False,
            coalesce=coalesce,
        )
        assert len(workers) == (1 if coalesce else 15)
        deadline = time.monotonic() + 30
        while len(received) < 15 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert received == {str(i): f"content-{i}" for i in range(15)}
        assert active[1] == 1
        assert len(requests) == 17
        previous = len(requests)
        time.sleep(1.1)
        assert len(requests) == previous
        runtime.stop_watch_threads()
        for worker in workers:
            worker.join(0.5)
        assert not any(worker.is_alive() for worker in workers)
        # A fresh batch is not stopped by the previous batch's cancellation.
        workers = runtime.start_watch_threads(
            specs[:1],
            host="127.0.0.1",
            port=server.server_port,
            register_views=False,
            coalesce=coalesce,
        )
        deadline = time.monotonic() + 3
        while len(requests) == previous and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(requests) == previous + 1
    finally:
        runtime.stop_watch_threads()
        for worker in workers:
            worker.join(1)
        server.shutdown()
        server.server_close()
        runner.join(1)


def test_missing_file_error_notice_does_not_prevent_recovery(probe, monkeypatch):
    path, waits, reads, hook, run = probe
    path.unlink()
    notices = []
    sent = []
    hook[0] = lambda: path.write_text("restored") if len(waits) == 3 else None
    monkeypatch.setattr(
        runtime,
        "publish_watch_payload",
        lambda **kw: notices.append(kw["artifact_kind"]) or True,
    )
    monkeypatch.setattr(
        runtime,
        "publish_prepared_watch_payload",
        lambda **kw: sent.append(kw["payload"].artifact) or True,
    )
    run()
    assert notices == ["watch_error"] * 3
    assert len(sent) == 1 and sent[0].endswith("restored")
    assert len(reads) == 4


def test_equal_size_replacement_with_preserved_mtime_is_published(probe, monkeypatch):
    import os

    path, waits, reads, hook, run = probe
    original_stat = path.stat()
    sent = []

    def replace():
        if len(waits) == 1:
            replacement = path.with_suffix(".new")
            replacement.write_text("changed")
            os.utime(
                replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns)
            )
            replacement.replace(path)

    hook[0] = replace
    monkeypatch.setattr(
        runtime,
        "publish_prepared_watch_payload",
        lambda **kw: sent.append(kw["payload"].artifact) or True,
    )
    run()
    assert len(sent) == 2
    assert sent[0].endswith("initial") and sent[1].endswith("changed")
    assert len(reads) == 2
