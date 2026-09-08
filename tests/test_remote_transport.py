from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time

import pytest

from plotsrv.publishing.models import PublishTarget
from plotsrv.publishing import transport


@contextmanager
def endpoint():
    state = {"requests": [], "generation": "first", "status": 200, "version": 1}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["requests"].append((self.path, dict(self.headers), body))
            status = state["status"]
            data = {"ok": True}
            if self.path.endswith("/capabilities"):
                data = {
                    "protocol_version": state["version"],
                    "stream_protocol_version": 4,
                    "server_generation": state["generation"],
                    "dashboard_scope": "scope",
                    "capabilities": ["publish", "stream-v4"],
                }
            if status == 403:
                data = {"detail": {"reason": "catalogue_awaiting_bootstrap"}}
            raw = state.get("raw", json.dumps(data).encode())
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            if 300 <= status < 400:
                self.send_header("Location", "/leaked")
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield PublishTarget(
            "remote", base_url=f"http://127.0.0.1:{server.server_port}/team/"
        ), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_prefix_handshake_cache_generation_and_resource_cleanup():
    with endpoint() as (target, state):
        transport.request_json(target, "/publish", {"value": 1}, feature="publish")
        descriptors_before = (
            len(os.listdir("/proc/self/fd")) if Path("/proc/self/fd").exists() else None
        )
        threads_before = {
            t.ident for t in threading.enumerate() if not t.name.startswith("Thread-")
        }
        for i in range(20):
            transport.request_json(target, "/publish", {"value": i}, feature="publish")
        assert [r[0] for r in state["requests"]].count("/team/capabilities") == 1
        assert all(
            path in ("/team/capabilities", "/team/publish")
            for path, _, _ in state["requests"]
        )
        state["generation"] = "second"
        transport.invalidate(target)
        assert (
            transport.handshake(target, feature="publish").server_generation == "second"
        )
        assert transport.health(target)["server_generation"] == "second"
        assert not any(
            t.name.startswith("plotsrv") and t.ident not in threads_before
            for t in threading.enumerate()
        )
        # The server may still be closing its final accepted socket; allow that
        # one transient descriptor, but no per-publication retained connections.
        if descriptors_before is not None:
            assert len(os.listdir("/proc/self/fd")) <= descriptors_before + 2


@pytest.mark.parametrize(
    "status,category",
    [
        (401, "unauthorised_publisher"),
        (307, "redirect_refused"),
        (503, "server_unavailable"),
    ],
)
def test_failures_are_cached_redacted_and_do_not_retry_without_auth(
    monkeypatch, caplog, status, category
):
    monkeypatch.setenv("TRANSPORT_TEST_KEY", "private-test-token")
    with endpoint() as (anonymous, state):
        target = PublishTarget(
            "remote", base_url=anonymous.base_url, bearer_token_env="TRANSPORT_TEST_KEY"
        )
        state["status"] = status
        state["raw"] = b"private-test-token"
        for _ in range(10):
            with pytest.raises(transport.TransportError, match=category):
                transport.request_json(target, "/publish", {}, feature="publish")
        assert len(state["requests"]) == 1
        path, headers, body = state["requests"][0]
        assert headers["Authorization"] == "Bearer private-test-token"
        assert "private-test-token" not in path and b"private-test-token" not in body
        assert "private-test-token" not in caplog.text
        assert len(caplog.records) == 1
        # Another security context gets its own negotiation and failure state.
        state["status"] = 200
        del state["raw"]
        assert transport.request_json(anonymous, "/publish", {}, feature="publish")[
            "ok"
        ]


def test_incompatible_protocol_and_unimplemented_features_fail_closed():
    with endpoint() as (target, state):
        state["version"] = 900
        with pytest.raises(transport.TransportError, match="incompatible_protocol"):
            transport.request_json(target, "/publish", {}, feature="publish")
        assert len(state["requests"]) == 1
        transport.reset_transport()
        state["version"] = 1
        with pytest.raises(transport.TransportError, match="incompatible_protocol"):
            transport.handshake(target, feature="future-watch")
        assert len(state["requests"]) == 2


def test_response_bounds_and_clear_bootstrap_reason():
    with endpoint() as (target, state):
        state["raw"] = b" " * (transport.MAX_RESPONSE_BYTES + 1)
        with pytest.raises(transport.TransportError, match="oversize_response"):
            transport.handshake(target, feature="publish")
        transport.reset_transport()
        del state["raw"]
        transport.handshake(target, feature="publish")
        state["status"] = 403
        with pytest.raises(
            transport.TransportError, match="catalogue_awaiting_bootstrap"
        ):
            transport.request_json(target, "/publish", {}, feature="publish")


def test_bad_target_does_not_capture_or_block_good_target(monkeypatch):
    from plotsrv import publisher

    with endpoint() as (bad, bad_state), endpoint() as (good, good_state):
        bad_state["status"] = 401
        calls = []
        original = publisher._to_publish_payload

        def capture(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(publisher, "_to_publish_payload", capture)
        for _ in range(4):
            publisher.publish_view("data", destination=bad)
        assert not calls
        publisher.publish_view("data", destination=good)
        assert len(calls) == 1
        assert len(bad_state["requests"]) == 1
        assert good_state["requests"][-1][0].endswith("/publish")


def test_cache_count_and_credentials_are_bounded(monkeypatch):
    for port in range(10000, 10000 + transport.MAX_TARGETS + 10):
        transport.health(PublishTarget("remote", port=port))
    assert len(transport._contexts) == transport.MAX_TARGETS
    monkeypatch.setenv("TRANSPORT_TEST_KEY", "first-key")
    target = PublishTarget("remote", bearer_token_env="TRANSPORT_TEST_KEY")
    monkeypatch.setenv("TRANSPORT_TEST_KEY", "second-key")
    with pytest.raises(transport.TransportError, match="invalid_credential"):
        transport.handshake(target, feature="publish")
    assert "first-key" not in str(transport._contexts) and "second-key" not in str(
        transport._contexts
    )


def test_tls_verification_and_timeout_budget(monkeypatch):
    import ssl

    handlers = []
    original = transport.urllib.request.build_opener

    def build(*args):
        opener = original(*args)
        handlers.extend(opener.handlers)
        return opener

    monkeypatch.setattr(transport.urllib.request, "build_opener", build)
    # Inspect the real opener without an external HTTPS request.
    build(transport._NoRedirect())
    https = next(
        h for h in handlers if isinstance(h, transport.urllib.request.HTTPSHandler)
    )
    context = https._context or ssl.create_default_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    target = PublishTarget("remote", base_url="https://example.test/base/")
    calls = []

    def exchange(target, path, payload, timeout):
        calls.append((path, timeout))
        if path == "/capabilities":
            time.sleep(0.01)
            return {
                "protocol_version": 1,
                "stream_protocol_version": 4,
                "server_generation": "g",
                "dashboard_scope": "s",
                "capabilities": ["publish"],
            }
        return {"ok": True}

    monkeypatch.setattr(transport, "_exchange", exchange)
    transport.request_json(target, "/publish", {}, feature="publish", timeout_s=0.2)
    assert 0 < calls[1][1] < calls[0][1] <= 0.2


def test_missing_key_is_best_effort_with_bounded_setup_diagnostics(
    tmp_path, monkeypatch, caplog
):
    from plotsrv import publisher, settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_MISSING_TEST_KEY", raising=False)
    (tmp_path / "plotsrv.yml").write_text(
        "publisher-settings:\n  destination:\n    url: https://example.test\n    bearer_token_env: PLOTSRV_MISSING_TEST_KEY\n"
    )
    for _ in range(10):
        assert publisher.publish_view("data") is None
    assert len(caplog.records) == 1
    assert "credential configuration" in caplog.text
    assert "PLOTSRV_MISSING_TEST_KEY" not in caplog.text


def test_stream_permanent_failure_and_final_close_do_not_busy_loop(monkeypatch):
    from plotsrv.streams.client import StreamClient
    from plotsrv.streams.models import StreamRegistration
    from tests.test_stream_restart import batch

    with endpoint() as (target, state):
        state["status"] = 401
        producer = StreamClient(
            destination=target,
            registration=StreamRegistration("v", "V", "S", "client", "session"),
        )
        for _ in range(10):
            assert producer.append_batch(batch(1)) is False
            assert producer.heartbeat_once() is False
        assert len(state["requests"]) == 1
        assert producer.retry_delay_s > 0
        start = time.monotonic()
        assert producer.close(drain_completed=False, timeout_s=0.05) is False
        assert time.monotonic() - start < 0.5
        assert len(state["requests"]) == 1


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), -1, 0])
def test_transport_rejects_unbounded_timeouts(timeout):
    with pytest.raises(transport.TransportError, match="request_timeout"):
        transport.request_json(
            PublishTarget("remote"),
            "/publish",
            {},
            feature="publish",
            timeout_s=timeout,
        )


def test_remote_failure_preserves_decorated_output_and_original_exception(
    tmp_path, monkeypatch
):
    from plotsrv import settings, view, config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.setattr(config, "get_tracebacks_enabled", lambda: True)
    with endpoint() as (target, state):
        (tmp_path / "plotsrv.yml").write_text(
            "publisher-settings:\n  destination:\n    url: " + target.base_url + "\n"
        )
        state["status"] = 401
        original = ValueError("original application failure")

        @view(view_id="result")
        def calculate():
            return 42

        @view(view_id="failure", on_error="publish_and_raise")
        def fail():
            raise original

        assert calculate() == 42
        with pytest.raises(ValueError) as caught:
            fail()
        assert caught.value is original
        assert len(state["requests"]) == 1


def test_remote_traceback_keeps_explicit_identity(tmp_path, monkeypatch):
    from plotsrv import settings, view, config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.setattr(config, "get_tracebacks_enabled", lambda: True)
    with endpoint() as (target, state):
        (tmp_path / "plotsrv.yml").write_text(
            "publisher-settings:\n  destination:\n    url: " + target.base_url + "\n"
        )

        @view(view_id="etl:custom:id", label="Different", on_error="publish_and_raise")
        def fail():
            raise ValueError("application failure")

        with pytest.raises(ValueError):
            fail()
        path, _, body = state["requests"][-1]
        assert path == "/team/publish"
        assert json.loads(body)["view_id"] == "etl:custom:id"
