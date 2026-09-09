from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
import yaml

from plotsrv import cli, settings, store
from plotsrv import publisher_agent as agent
from plotsrv.cli_parser import build_parser
from tests.test_standalone import ServerProcess


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    store.reset()
    yield
    store.reset()


def test_publish_catalogue_only_static_discovery_no_server_execution(
    tmp_path, monkeypatch
):
    source = tmp_path / "package"
    source.mkdir()
    (source / "__init__.py").write_text("raise AssertionError('must not import')")
    (source / "child.py").write_text(
        'from plotsrv import view\n@view(view_id="exact:id")\ndef run(): pass\n'
    )
    calls = []
    monkeypatch.setattr(
        agent,
        "request_json",
        lambda target, route, payload, **kw: calls.append((route, payload))
        or {"ok": True},
    )
    monkeypatch.setattr(
        cli,
        "_run_passive_server_forever",
        lambda *a, **k: pytest.fail("started server"),
    )
    assert (
        cli.main(
            [
                "publish",
                "package.child:run",
                "--destination",
                "http://localhost:8000",
                "--quiet",
            ]
        )
        == 0
    )
    assert calls[0][0] == "/catalogue/register"
    assert calls[0][1]["views"][0]["view_id"] == "exact:id"
    assert not store.list_views()


def test_config_watch_paths_manifest_union_explicit_seal_and_review(
    tmp_path, monkeypatch
):
    base = tmp_path / "config"
    base.mkdir()
    source = base / "app.py"
    source.write_text(
        "from plotsrv import view\n@view(view_id=dynamic())\ndef f(): pass\n"
    )
    path = base / "custom.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "publisher-settings": {
                    "discovery": {"target": "./app.py"},
                    "watch": [
                        {
                            "path": "local.log",
                            "view_id": "exact:watch",
                            "materialization": "file",
                        }
                    ],
                }
            }
        )
    )
    calls, watches = [], []
    monkeypatch.setattr(
        agent,
        "request_json",
        lambda target, route, payload, **kw: calls.append((route, payload))
        or {"ok": True},
    )
    monkeypatch.setattr(
        agent, "foreground", lambda watcher: watches.extend(watcher.states) or 0
    )
    args = [
        "publish",
        "--config",
        str(path),
        "--seal-catalogue",
        "--add-id",
        "runtime:id",
        "--quiet",
    ]
    assert cli.main(args) == 2
    assert calls == []
    assert cli.main([*args, "--reviewed"]) == 0
    assert calls[0][0] == "/catalogue/bootstrap"
    assert {v["view_id"] for v in calls[0][1]["views"]} == {"exact:watch", "runtime:id"}
    assert watches[0].spec.path == str(base / "local.log")
    assert (
        watches[0].spec.materialization == "file"
    )  # Remote never registers a local path.


def test_watch_legacy_local_and_explicit_remote_destination(tmp_path, monkeypatch):
    local, remote = [], []
    monkeypatch.setattr(
        cli, "_run_watch_mode", lambda *a, **kw: local.append((a, kw)) or 0
    )
    monkeypatch.setattr(
        agent, "foreground", lambda watcher: remote.append(watcher) or 0
    )
    assert (
        cli.main(["watch", "source.txt", "--host", "127.0.0.1", "--port", "8002"]) == 0
    )
    assert len(local) == 1 and not remote
    assert (
        cli.main(["watch", "source.txt", "--destination", "http://localhost:8003"]) == 0
    )
    assert len(remote) == 1 and len(local) == 1
    assert remote[0].target.base_url == "http://localhost:8003/"
    assert (
        cli.main(
            [
                "watch",
                "source.txt",
                "--destination",
                "http://localhost:8003",
                "--port",
                "8002",
            ]
        )
        == 2
    )


def wait_for(server, check, *, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, KeyError):
            pass
        time.sleep(0.05)
    raise AssertionError("watch process did not reach expected state")


@pytest.mark.parametrize("key", [False, True])
def test_disjoint_server_publisher_cli_restart_and_shutdown(tmp_path, key):
    server = ServerProcess(tmp_path, key=key)
    producer = None
    try:
        path = server.publisher_dir / "publisher-only.txt"
        path.write_text("first")
        cfg_path = server.publisher_dir / "plotsrv.yml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["publisher-settings"]["watch"] = [
            {"path": path.name, "view_id": "remote:log", "label": "Remote log"}
        ]
        cfg_path.write_text(yaml.safe_dump(cfg))
        server.start()
        script = """
import sys
from plotsrv import publishing
from plotsrv.publishing import transport
transport.CAPABILITY_TTL_S = 0.2
from plotsrv.cli import main
raise SystemExit(main(['publish', '--every', '0.1', '--quiet']))
"""
        producer = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=server.publisher_dir,
            env=server.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        artifact = lambda: server.get("/artifact?view=remote%3Alog")
        wait_for(server, lambda: "first" in artifact()["html"])
        assert str(server.publisher_dir) not in json.dumps(artifact())
        path.write_text("second")
        wait_for(server, lambda: "second" in artifact()["html"])
        path.unlink()
        wait_for(server, lambda: artifact()["meta"]["status"] == "missing")
        assert "second" in artifact()["html"]
        path.write_text("after rotation")
        wait_for(server, lambda: "after rotation" in artifact()["html"])
        server.stop()
        server.start()
        wait_for(server, lambda: "after rotation" in artifact()["html"])
        producer.send_signal(signal.SIGINT)
        stdout, stderr = producer.communicate(timeout=7)
        assert producer.returncode == 0, (stdout, stderr)
        assert artifact()["meta"]["status"] == "stopped"
        assert path.read_text() == "after rotation"
    finally:
        if producer is not None and producer.poll() is None:
            producer.kill()
            producer.communicate(timeout=3)
        server.close()


def test_explicit_local_watch_overrides_unused_remote_credential(tmp_path, monkeypatch):
    cfg = tmp_path / "publisher.yml"
    cfg.write_text(
        "publisher-settings:\n  destination:\n    url: https://example.test\n    bearer_token_env: MISSING_WATCH_KEY\n"
    )
    monkeypatch.delenv("MISSING_WATCH_KEY", raising=False)
    calls = []
    monkeypatch.setattr(cli, "_run_watch_mode", lambda *a, **kw: calls.append(kw) or 0)
    assert (
        cli.main(
            [
                "watch",
                "source.txt",
                "--config",
                str(cfg),
                "--host",
                "127.0.0.1",
                "--port",
                "8002",
            ]
        )
        == 0
    )
    assert calls[0]["port"] == 8002


def test_sigint_during_trickling_handshake_exits_without_workers(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    entered, stopped = threading.Event(), threading.Event()

    class Slow(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            entered.set()
            try:
                while not stopped.wait(0.025):
                    self.wfile.write(b" ")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = """
import sys
from plotsrv.publisher_agent import RemoteWatcher, foreground
from plotsrv.runtime import WatchConfig
from plotsrv.publishing.models import PublishTarget
watcher = RemoteWatcher([WatchConfig(path='unused.txt')], PublishTarget(
    'remote', base_url=sys.argv[1], request_timeout_s=0.3), every=0.1)
raise SystemExit(foreground(watcher))
"""
    producer = subprocess.Popen(
        [sys.executable, "-c", script, f"http://127.0.0.1:{server.server_port}"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert entered.wait(8)
        start = time.monotonic()
        producer.send_signal(signal.SIGINT)
        out, err = producer.communicate(timeout=2)
        assert producer.returncode == 0, (out, err)
        assert time.monotonic() - start < 1.5
        assert not (tmp_path / "unused.txt").exists()
    finally:
        if producer.poll() is None:
            producer.kill()
            producer.communicate(timeout=3)
        stopped.set()
        server.shutdown()
        server.server_close()
        thread.join(2)
