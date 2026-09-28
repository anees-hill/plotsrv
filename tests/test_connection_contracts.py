from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import urllib.error

import pytest

from plotsrv import settings
from plotsrv.connection_config import (
    get_publisher_sources,
    get_server_connection_config,
    resolve_publish_target,
)
from plotsrv.contracts import (
    ErrorCategory,
    ProtocolCapabilities,
    SourceMetadata,
    ViewDescriptor,
    dashboard_scope,
    normalise_base_url,
    validate_catalogue,
)
from plotsrv.publishing.models import PublishTarget, PublishTask


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)
    monkeypatch.delenv("TEST_PUBLISH_KEY", raising=False)


def config_file(tmp_path, text):
    path = tmp_path / "plotsrv.yml"
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    "kwargs,kind",
    [
        ({}, "local"),
        ({"host": "127.0.0.1"}, "remote"),
        ({"port": 8000}, "remote"),
        ({"mode": "remote"}, "remote"),
        ({"mode": "local", "port": 8123}, "local"),
        ({"mode": "remote", "launch_server": True}, "local"),
        ({"mode": "local", "launch_server": False}, "remote"),
    ],
)
def test_legacy_resolution(kwargs, kind):
    assert resolve_publish_target(**kwargs).kind == kind


def test_config_precedence_and_role_separation(tmp_path, monkeypatch):
    config_file(
        tmp_path,
        """publisher-settings:
  default:
    destination:
      url: https://dashboard.example/proxy/
      request_timeout_s: 3
  instances:
    batch:
      destination:
        request_timeout_s: 4
server-settings:
  bind: {host: '::', port: 9000}
  admission: {mode: catalogue-locked, allowed_ids: ['é:订单:α']}
storage-settings:
  enabled: true
""",
    )
    monkeypatch.setenv("PLOTSRV_NAME", "batch")
    target = resolve_publish_target()
    assert target.kind == "remote"
    assert target.request_timeout_s == 4
    assert target.url_for("/publish") == "https://dashboard.example/proxy/publish"
    assert resolve_publish_target(launch_server=False) == target
    assert resolve_publish_target(port=8000).base_url is None
    assert resolve_publish_target(mode="local").kind == "local"
    assert (
        resolve_publish_target(destination="https://other.example").host
        == "other.example"
    )
    server = get_server_connection_config()
    assert (server.bind_host, server.bind_port) == ("::", 9000)
    assert server.allowed_ids == ("é:订单:α",)
    from plotsrv import config

    assert config.get_storage_enabled() is True


def test_publisher_only_and_server_only(tmp_path):
    p = config_file(
        tmp_path,
        "publisher-settings:\n  destination: {url: 'https://example.test/p'}\n",
    )
    assert get_server_connection_config().bind_port == 8000
    p.write_text("server-settings:\n  bind: {port: 9001}\n")
    settings._CONFIG_CACHE.clear()
    assert resolve_publish_target().kind == "local"
    assert get_publisher_sources().watch == ()
    assert get_server_connection_config().bind_port == 9001


def test_config_selection_preserves_yml_then_yaml_and_explicit_env(
    tmp_path, monkeypatch
):
    first = config_file(
        tmp_path, "publisher-settings: {destination: {url: 'https://first.test'}}"
    )
    second = tmp_path / "plotsrv.yaml"
    second.write_text("publisher-settings: {destination: {url: 'https://second.test'}}")
    assert settings.get_runtime_config_path() == first
    monkeypatch.setenv("PLOTSRV_CONFIG", str(second))
    assert resolve_publish_target().host == "second.test"
    settings.set_runtime_context(config_path=first)
    assert resolve_publish_target().host == "first.test"


@pytest.mark.parametrize(
    "kwargs",
    [{"host": "localhost"}, {"port": 8000}, {"mode": "local"}, {"launch_server": True}],
)
def test_explicit_url_conflicts(kwargs):
    with pytest.raises(ValueError, match="conflicts"):
        resolve_publish_target(destination="https://example.test", **kwargs)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("HTTPS://EXAMPLE.COM:443/app", "https://example.com/app/"),
        ("http://[::1]:8000/prefix/", "http://[::1]:8000/prefix/"),
        ("http://example.com:80/", "http://example.com/"),
        ("https://example.com/a/b///", "https://example.com/a/b/"),
    ],
)
def test_url_prefix_ipv6_normalisation(url, expected):
    target = resolve_publish_target(destination=url)
    assert target.base_url == expected
    assert target.url_for("/publish") == expected + "publish"
    assert target.url_for("streams/register") == expected + "streams/register"
    assert (
        resolve_publish_target(host="::1").url_for("/publish")
        == "http://[::1]:8000/publish"
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host/p",
        "http://user:secret@host",
        "https://host/p?secret=x",
        "https://host/#secret",
        "https://host:99999",
        "https://host:0",
        "https://host/a/../b",
        "https://host/a/%2e%2e/b",
        "https://host/\nsecret",
        "https://host\\secret",
        "relative/path",
    ],
)
def test_invalid_urls_redact_input(url):
    with pytest.raises(ValueError) as exc:
        normalise_base_url(url)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 301])
def test_bounded_timeouts(timeout):
    with pytest.raises(ValueError):
        PublishTarget("remote", request_timeout_s=timeout)


def test_credentials_missing_redaction_and_rotation(monkeypatch):
    with pytest.raises(ValueError, match="missing"):
        PublishTarget(
            "remote",
            base_url="https://example.test",
            bearer_token_env="TEST_PUBLISH_KEY",
        )
    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret-one")
    first = PublishTarget(
        "remote", base_url="https://example.test", bearer_token_env="TEST_PUBLISH_KEY"
    )
    assert first.authorization_headers() == {"Authorization": "Bearer secret-one"}
    assert "secret-one" not in repr(first) + json.dumps(asdict(first)) + first.key
    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret-two")
    second = PublishTarget(
        "remote", base_url="https://example.test", bearer_token_env="TEST_PUBLISH_KEY"
    )
    assert first.key != second.key
    assert (
        PublishTask(None, first, "é:a:b").coalesce_key
        != PublishTask(None, second, "é:a:b").coalesce_key
    )
    with pytest.raises(ValueError, match="changed"):
        first.authorization_headers()
    monkeypatch.setenv("TEST_PUBLISH_KEY", "bad\nsecret")
    with pytest.raises(ValueError) as exc:
        second.authorization_headers()
    assert "bad" not in str(exc.value) and "secret" not in str(exc.value)


def test_bearer_transport_requires_tls_except_loopback(monkeypatch):
    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        PublishTarget("remote", host="192.168.1.2", bearer_token_env="TEST_PUBLISH_KEY")
    assert PublishTarget("remote", host="::1", bearer_token_env="TEST_PUBLISH_KEY")


def test_server_key_missing_and_admission_validation(tmp_path):
    p = config_file(
        tmp_path, "server-settings:\n  ingestion: {bearer_token_env: TEST_PUBLISH_KEY}"
    )
    with pytest.raises(ValueError, match="missing"):
        get_server_connection_config()
    p.write_text("server-settings:\n  admission: {mode: dynamic, allowed_ids: ['x']}")
    settings._CONFIG_CACHE.clear()
    with pytest.raises(ValueError, match="catalogue-locked"):
        get_server_connection_config()


def test_config_sources_do_not_open_publisher_files(tmp_path, monkeypatch):
    p = config_file(
        tmp_path,
        """publisher-settings:
  discovery: {target: ./missing.py, selection: ['é:订单:α']}
  watch:
    - {path: data/missing.csv, view_id: 'é:订单:α', label: Orders, read_mode: tail}
""",
    )
    settings.set_runtime_context(config_path=p)
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.chdir(server_dir)
    sources = get_publisher_sources()
    assert sources.discovery_target == str(tmp_path / "missing.py")
    assert sources.watch[0].path == str(tmp_path / "data/missing.csv")
    assert sources.watch[0].view_id == "é:订单:α"


@pytest.mark.parametrize("view_id", ["é:订单:α", "  é:a:b  ", "no-colon"])
def test_exact_descriptor_round_trip(view_id):
    descriptor = ViewDescriptor(
        view_id, "Label", "Section", source=SourceMetadata("file.py", "python")
    )
    assert ViewDescriptor.from_dict(json.loads(descriptor.to_json())) == descriptor
    assert json.loads(descriptor.to_json())["view_id"] == view_id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"view_id": "x" * 513},
        {"label": "x" * 513},
        {"description": "x" * 2049},
        {"view_id": "\ud800"},
        {"capabilities": ("table",)},
        {"kind": "made-up"},
        {"metadata_version": True},
        {"metadata_version": 2},
    ],
)
def test_descriptor_rejects_bad_metadata(kwargs):
    with pytest.raises(ValueError):
        ViewDescriptor(**{"view_id": "a", "label": "a", **kwargs})


def test_aggregate_metadata_and_catalogue_bounds():
    with pytest.raises(ValueError, match="oversize_data"):
        ViewDescriptor(
            "😀" * 512,
            "😀" * 512,
            "😀" * 512,
            kind="table",
            description="😀" * 2048,
            capabilities=("😀" * 64,) * 32,
        )
    view = ViewDescriptor("id", "Label")
    with pytest.raises(ValueError, match="duplicate"):
        validate_catalogue([view, view])
    with pytest.raises(ValueError, match="oversize"):
        validate_catalogue([view] * 1025)
    with pytest.raises(ValueError, match="path"):
        SourceMetadata("/secret/server/file")
    with pytest.raises(TypeError):
        ViewDescriptor.from_dict(
            {"view_id": "a", "label": "a", "server_path": "/etc/passwd"}
        )


def test_protocol_and_dashboard_identity():
    scope = dashboard_scope("https://HOST:443/team/", "batch")
    assert scope == dashboard_scope("https://host/team", "batch")
    assert scope != dashboard_scope("https://host/other", "batch")
    assert scope != dashboard_scope("https://host/team", "other")
    first = ProtocolCapabilities("generation-1", scope)
    second = ProtocolCapabilities("generation-2", scope)
    assert first.dashboard_scope == second.dashboard_scope
    assert first.to_dict()["stream_protocol_version"] == 4
    assert ProtocolCapabilities(**first.to_dict()) == first
    with pytest.raises(ValueError, match="incompatible_protocol"):
        ProtocolCapabilities("generation", scope, stream_protocol_version=3)
    assert {c.value for c in ErrorCategory} == {
        "incompatible_protocol",
        "unauthorised_publisher",
        "inadmissible_view",
        "oversize_data",
        "invalid_request",
        "ingestion_busy",
    }


def test_cli_defaults_keep_explicitness():
    from plotsrv.cli_parser import build_parser

    parser = build_parser()
    omitted = parser.parse_args(["run"])
    explicit = parser.parse_args(["run", "--host", "127.0.0.1", "--port", "8000"])
    assert (omitted.host, omitted.port) == (explicit.host, explicit.port)
    assert not omitted.host_supplied and not omitted.port_supplied
    assert explicit.host_supplied and explicit.port_supplied


def test_discovery_runtime_exact_ids(tmp_path):
    from plotsrv import cli, store
    from plotsrv.discovery import discover_views

    path = tmp_path / "app.py"
    path.write_text(
        'from plotsrv import publish_view\npublish_view(None, view_id="é:a:b", label="Different", section="Other")'
    )
    discovered = discover_views(path)[0]
    assert discovered.descriptor().view_id == "é:a:b"
    assert discovered.descriptor().kind == "unknown"
    assert discovered.descriptor().capabilities == ()
    try:
        cli._passive_register_views(str(path), includes={"é:a:b"}, excludes=set())
        assert store.get_active_view_id() == "é:a:b"
        assert any(meta.view_id == "é:a:b" for meta in store.list_views())
    finally:
        store.reset()


def test_decorator_and_watch_preserve_ids(monkeypatch, tmp_path):
    from plotsrv import decorators
    from plotsrv.runtime import (
        WatchConfig,
        _watch_view_from_config,
        coerce_watch_config,
    )

    received = []
    monkeypatch.setattr(
        decorators, "publish_view", lambda obj, **kw: received.append(kw)
    )

    @decorators.view(view_id="é:a:b", label="Other", port=8000)
    def data():
        return 42

    assert data() == 42
    assert received[0]["view_id"] == "é:a:b"
    spec = coerce_watch_config({"path": tmp_path / "a.csv", "view_id": "é:a:b"})
    assert _watch_view_from_config(spec).view_id == "é:a:b"


def test_import_and_parser_startup_do_not_scan_or_connect():
    script = """import socket, pathlib, sys
attempted = []

def forbidden(*args, **kwargs):
    attempted.append(True)
    raise AssertionError("unexpected startup IO")
socket.socket.connect = forbidden
socket.create_connection = forbidden
pathlib.Path.rglob = forbidden
import plotsrv
from plotsrv import publish_view
from plotsrv.cli_parser import build_parser
assert not attempted
assert build_parser().parse_args(["run"]).target is None
assert "plotsrv.discovery" not in sys.modules
assert "plotsrv.discovery" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=20)


@pytest.mark.parametrize("pathlike", [False, True])
def test_configured_destination_delivers_prefix_and_id(tmp_path, monkeypatch, pathlike):
    from plotsrv import publisher

    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret-one")
    config_file(
        tmp_path,
        """publisher-settings:
  destination:
    url: https://example.test/dashboard
    bearer_token_env: TEST_PUBLISH_KEY
    request_timeout_s: 3
""",
    )
    received = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == 65537
            return json.dumps({"ok": True, "protocol_version": 1, "stream_protocol_version": 4,
                               "server_generation": "test", "dashboard_scope": "test",
                               "capabilities": ["publish"]}).encode()

    class Opener:
        def open(self, req, timeout):
            received.append((req, timeout))
            return Response()

    monkeypatch.setattr(
        __import__("urllib.request", fromlist=["build_opener"]), "build_opener", lambda *args: Opener()
    )
    value = "hello"
    if pathlike:
        value = tmp_path / "input.txt"
        value.write_text("hello")
    publisher.publish_view(value, view_id="é:a:b", label="Display")
    assert len(received) == 2
    assert received[0][0].full_url.endswith("/capabilities")
    req, timeout = received[-1]
    assert req.full_url == "https://example.test/dashboard/publish"
    assert req.get_header("Authorization") == "Bearer secret-one"
    assert 0 < timeout <= 3
    payload = json.loads(req.data)
    assert payload["view_id"] == "é:a:b"
    assert "secret-one" not in json.dumps(payload)


def test_remote_failure_never_launches_and_redacts_errors(monkeypatch):
    from plotsrv import publisher, server

    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret-one")
    target = PublishTarget(
        "remote", base_url="https://example.test", bearer_token_env="TEST_PUBLISH_KEY"
    )

    class Opener:
        def open(self, req, timeout):
            raise OSError("secret-one")

    monkeypatch.setattr(
        __import__("urllib.request", fromlist=["build_opener"]), "build_opener", lambda *args: Opener()
    )

    def forbidden(**kwargs):
        raise AssertionError("local fallback")

    monkeypatch.setattr(server, "start_server", forbidden)
    publisher.publish_view("hello", destination=target)
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")
    with pytest.raises(RuntimeError) as exc:
        publisher.publish_view("hello", destination=target)
    assert "secret-one" not in str(exc.value)


def test_explicit_target_redirect_does_not_forward_bearer(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from plotsrv import publisher

    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            received.append(self.path)
            self.send_response(307)
            self.send_header("Location", "/leak")
            self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret-one")
    target = PublishTarget(
        "remote",
        base_url=f"http://127.0.0.1:{httpd.server_port}/prefix/",
        bearer_token_env="TEST_PUBLISH_KEY",
    )
    try:
        assert (
            publisher._post_publish_payload(
                payload={},
                host=target.host,
                port=target.port,
                target=target,
                debug=False,
            )
            is False
        )
        assert received == ["/prefix/capabilities"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(2)


def test_async_target_is_resolved_before_queueing(monkeypatch):
    from plotsrv import publisher

    received = []

    class Worker:
        def submit(self, task):
            received.append(task)

    monkeypatch.setattr(publisher, "get_publish_worker", lambda: Worker())
    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret-one")
    target = PublishTarget(
        "remote", base_url="https://example.test/p", bearer_token_env="TEST_PUBLISH_KEY"
    )
    publisher.publish_view("hello", destination=target, view_id="é:a:b", async_=True)
    assert received[0].target is target
    assert received[0].coalesce_view_id == "é:a:b"
    monkeypatch.setenv("TEST_PUBLISH_KEY", "secret-two")
    assert publisher._run_publish_task(received[0]) is False


def test_json_decode_is_bounded_and_kind_literals_are_preserved():
    from plotsrv.discovery import _extract_publish_view_discovery
    import ast

    descriptor = ViewDescriptor("é:a:b", "Label")
    assert ViewDescriptor.from_json(descriptor.to_json()) == descriptor
    with pytest.raises(ValueError, match="oversize_data"):
        ViewDescriptor.from_json(b" " * 16385)
    with pytest.raises(ValueError):
        ViewDescriptor.from_json("[" * 8000 + "]" * 8000)
    call = ast.parse('publish_view(x, view_id="é:a:b", kind="table")').body[0].value
    assert _extract_publish_view_discovery(call).descriptor().kind == "table"


@pytest.mark.parametrize(
    "value", ["https://remote.test", "{default: invalid}", "{instances: invalid}"]
)
def test_malformed_publisher_config_cannot_select_local(tmp_path, value):
    config_file(tmp_path, "publisher-settings: " + value)
    with pytest.raises(ValueError):
        resolve_publish_target()
