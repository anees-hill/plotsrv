from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
import yaml

from plotsrv import config, settings, store
from plotsrv.cli_parser import build_parser
from plotsrv.publishing.models import PublishTarget
from plotsrv.publishing import transport


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


def test_serve_parser_has_no_target_or_execution_flags():
    args = build_parser().parse_args(["serve", "--port", "8765"])
    assert args.host is None and args.port == 8765
    for extra in [["app.py"], ["--call"], ["--watch", "data.csv"]]:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["serve", *extra])


@pytest.mark.parametrize("locked", [False, True, "allowlist"])
def test_server_only_restores_logical_metadata_without_discovery(
    tmp_path, monkeypatch, locked
):
    import uvicorn
    from plotsrv import discovery, runtime
    from plotsrv.standalone import serve
    from plotsrv.storage.latest import FileLatestStateBackend

    FileLatestStateBackend(root_dir=tmp_path).write_latest(
        view_id="stored", kind="text", obj="previous", label="Stored", section="History"
    )
    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_storage_restore_latest_on_startup", lambda: True)
    monkeypatch.setattr(
        config, "get_storage_latest_restore_scope", lambda: "discovered"
    )
    (tmp_path / "plotsrv.yml").write_text(
        yaml.safe_dump(
            {
                "server-settings": {
                    "bind": {"host": "127.0.0.1", "port": 8765},
                    "admission": {"mode": "catalogue-locked" if locked else "dynamic"},
                }
            }
        )
    )

    if locked == "allowlist":
        path = tmp_path / "plotsrv.yml"
        cfg = yaml.safe_load(path.read_text())
        cfg["server-settings"]["admission"]["allowed_ids"] = ["stored"]
        path.write_text(yaml.safe_dump(cfg))

    def forbidden(*args, **kwargs):
        raise AssertionError("application source/discovery was reached")

    monkeypatch.setattr(discovery, "discover_views", forbidden)
    monkeypatch.setattr(runtime, "start_watch_threads", forbidden)

    def run(server):
        assert server.config.port == 8765
        if locked is True:
            assert not store.list_views()
        else:
            assert store.get_artifact(view_id="stored").obj == "previous"
            assert store.get_status(view_id="stored")["restored_from_storage"] is True
            assert store.get_data_activity(view_id="stored")["event_count"] == 0

    monkeypatch.setattr(uvicorn.Server, "run", run)
    assert serve(quiet=True) == 0
    assert config.get_storage_latest_restore_scope() == "discovered"


@pytest.mark.parametrize("quiet,verbose,level,access", [
    (False, False, "info", False),
    (True, False, "warning", False),
    (False, True, "info", True),
])
def test_standalone_server_log_modes(monkeypatch, quiet, verbose, level, access, capsys):
    import uvicorn
    from plotsrv.app import app
    from plotsrv.request_logging import FailureRequestLogger
    from plotsrv.standalone import serve

    captured = {}

    def fake_run(self):
        captured["config"] = self.config

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    assert serve(quiet=quiet, verbose=verbose) == 0
    cfg = captured["config"]
    assert cfg.log_level == level
    assert cfg.access_log is access
    assert (cfg.app is app) is verbose
    assert isinstance(cfg.app, FailureRequestLogger) is (not verbose)
    assert ("Waiting for a publisher" in capsys.readouterr().out) is (not quiet)


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


SERVER_SCRIPT = """
import os, sys
blocked = os.environ['BLOCKED_PROJECT']
def audit(event, args):
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        if os.fsdecode(args[0]).startswith(blocked):
            raise AssertionError('server tried to read publisher project')
sys.addaudithook(audit)
from plotsrv import discovery, runtime
from plotsrv.cli import main
def forbidden(*args, **kwargs):
    raise AssertionError('standalone discovery or watch was invoked')
discovery.discover_views = forbidden
runtime.start_watch_threads = forbidden
raise SystemExit(main(['serve', '--config', 'server.yml', '--quiet']))
"""


class ServerProcess:
    def __init__(self, root, *, key, locked=False):
        self.server_dir = root / "server"
        self.publisher_dir = root / "publisher"
        self.server_dir.mkdir(exist_ok=True)
        self.publisher_dir.mkdir(exist_ok=True)
        self.port = unused_port()
        self.env = {
            **os.environ,
            "BLOCKED_PROJECT": str(self.publisher_dir),
            "REMOTE_TEST_KEY": "integration-test-key",
        }
        self.env.pop("PLOTSRV_CONFIG", None)
        self.env.pop("PLOTSRV_NAME", None)
        cfg = {
            "server-settings": {
                "bind": {"host": "127.0.0.1", "port": self.port},
                "admission": {"mode": "catalogue-locked" if locked else "dynamic"},
            }
        }
        if key:
            cfg["server-settings"]["ingestion"] = {
                "bearer_token_env": "REMOTE_TEST_KEY"
            }
        (self.server_dir / "server.yml").write_text(yaml.safe_dump(cfg))
        destination = {"url": f"http://127.0.0.1:{self.port}"}
        if key:
            destination["bearer_token_env"] = "REMOTE_TEST_KEY"
        (self.publisher_dir / "plotsrv.yml").write_text(
            yaml.safe_dump({"publisher-settings": {"destination": destination}})
        )
        self.log = (self.server_dir / "server.log").open("w+")
        self.process = None

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, "-c", SERVER_SCRIPT],
            cwd=self.server_dir,
            env=self.env,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.log.flush()
                raise AssertionError((self.server_dir / "server.log").read_text())
            try:
                self.get("/views")
                return
            except OSError:
                time.sleep(0.05)
        raise AssertionError("standalone server did not start")

    def get(self, path):
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}", timeout=0.5
        ) as response:
            return json.loads(response.read())

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process = None

    def close(self):
        self.stop()
        self.log.close()


PUBLISHER_SCRIPT = """
import json, time
from pathlib import Path
import pandas as pd
from plotsrv import publish_view, stream_view, view
@view(view_id='decorated', label='Decorated')
def calculate():
    return 'original result'
assert calculate() == 'original result'
publish_view(pd.DataFrame({'a':[1,2]}), view_id='table', force=True)
publish_view('ready', view_id='artifact', force=True)
path=Path('application.jsonl')
path.write_text('')
handle=stream_view(source=path, view_id='stream', label='Events')
with path.open('a') as f:
    f.write(json.dumps({'event':'one'})+'\\n')
deadline=time.monotonic()+10
while time.monotonic()<deadline and handle.health['delivery']['delivery_acknowledgements']<1:
    time.sleep(0.05)
health=handle.health
handle.stop(timeout=1)
assert health['delivery']['delivery_acknowledgements']==1, health
print(json.dumps({'ok':True, 'session':handle.session_id}))
"""


@pytest.mark.parametrize("key", [False, True])
def test_independent_server_and_direct_publisher_processes(tmp_path, key):
    server = ServerProcess(tmp_path, key=key)
    try:
        server.start()
        assert server.get("/views") == []
        result = subprocess.run(
            [sys.executable, "-c", PUBLISHER_SCRIPT],
            cwd=server.publisher_dir,
            env=server.env,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        ids = {v["view_id"] for v in server.get("/views")}
        assert {"table", "artifact", "stream", "decorated"} <= ids
        assert len(server.get("/stream/data?view=stream")["records"]) == 1
        assert "integration-test-key" not in result.stdout + result.stderr
        assert not (server.server_dir / "application.jsonl").exists()
    finally:
        server.close()


def test_real_restart_recovers_stream_and_locked_server_rejects(tmp_path, monkeypatch):
    from plotsrv.streams.client import StreamClient
    from plotsrv.streams.models import StreamRegistration
    from plotsrv.streams.file_source import JsonlBatch, JsonlRecord

    monkeypatch.setenv("REMOTE_TEST_KEY", "integration-test-key")
    server = ServerProcess(tmp_path, key=True)
    target = PublishTarget(
        "remote",
        base_url=f"http://127.0.0.1:{server.port}",
        bearer_token_env="REMOTE_TEST_KEY",
    )
    producer = StreamClient(
        destination=target,
        registration=StreamRegistration(
            "events", "Events", "Logs", "client", "original"
        ),
    )

    def batch(n):
        return JsonlBatch(
            f"batch-{n}",
            (JsonlRecord({"n": n}, n, n + 1, datetime.now(UTC)),),
            n,
            n + 1,
        )

    try:
        server.start()
        first_generation = transport.handshake(
            target, feature="stream-v4"
        ).server_generation
        assert producer.append_batch(batch(1))
        server.stop()
        server.start()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if producer.append_batch(batch(2)):
                break
            time.sleep(0.1)
        assert producer.health()["delivery_acknowledgements"] == 2, producer.health()
        assert producer.registration.session_id != "original"
        assert transport.health(target)["server_generation"] != first_generation
        assert len(server.get("/stream/data?view=events")["records"]) == 1
        assert producer.close(drain_completed=True, timeout_s=0.5)
        server.stop()
        config_path = server.server_dir / "server.yml"
        cfg = yaml.safe_load(config_path.read_text())
        cfg["server-settings"]["admission"] = {"mode": "catalogue-locked"}
        config_path.write_text(yaml.safe_dump(cfg))
        server.start()
        with pytest.raises(
            transport.TransportError, match="catalogue_awaiting_bootstrap"
        ):
            transport.request_json(
                target,
                "/publish",
                {"view_id": "new", "kind": "artifact", "artifact": "x"},
                feature="publish",
            )
        assert server.get("/views") == []
    finally:
        server.close()
