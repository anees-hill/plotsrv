"""Bounded delivery with a local receiver and deterministic failure injection."""

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from plotsrv import checks, config, ingestion, webhooks
from plotsrv.app import app
from plotsrv.checks import CheckEngine
from plotsrv.checks_config import parse_checks
from plotsrv.webhook_config import Destination, WebhookConfig, parse_webhooks
from plotsrv.webhooks import Outcome, WebhookDispatcher
from tests.test_checks import isolated, spec


def rule(**kwargs):
    return parse_checks(
        {"rules": [spec(notify=["ops"], **kwargs)]}, destinations=("ops",)
    )[0]


def event(n=1, **kwargs):
    return dict(
        version=1,
        event_id=f"gen:{n}",
        generation="gen",
        cursor=n,
        view_id="metrics",
        check_id="latency",
        kind="state",
        event_type="triggered",
        previous_state="ok",
        state="triggered",
        severity="warning",
        observed_value=20,
        threshold=10,
        evidence_scope="supplied_value",
        unit=None,
        inspected=None,
        not_inspected=None,
        coverage_lost=0,
        context={"received_at": "2026-09-09T12:00:00Z"},
        **kwargs,
    )


def configuration(address="http://127.0.0.1:1/hook"):
    return parse_webhooks(
        {"destinations": {"ops": {"url": address}}, "event_cooldown_s": 1}
    )


@pytest.fixture
def receiver():
    records = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            records.append((self.path, dict(self.headers), body))
            mode = self.path.split("?")[0]
            if mode == "/timeout":
                time.sleep(0.2)
            code = (
                401
                if mode == "/auth"
                else 503 if mode == "/retry" else 302 if mode == "/redirect" else 200
            )
            self.send_response(code)
            if mode == "/retry":
                self.send_header("Retry-After", "999999")
            if mode == "/redirect":
                self.send_header("Location", "/secret-received")
            if mode == "/huge-headers":
                self.send_header("X-Huge", "a" * 40000)
            self.end_headers()
            try:
                if mode == "/huge-body":
                    self.wfile.write(b"x" * (2 * 1024 * 1024))
                else:
                    self.wfile.write(b"ok")
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", records
    server.shutdown()
    server.server_close()
    thread.join(1)


@pytest.mark.parametrize(
    "section",
    [
        {"wrong": 1},
        {"destinations": []},
        {"destinations": {str(i): {"url": "https://x"} for i in range(9)}},
        {"event_cooldown_s": 0},
        {"event_cooldown_s": True},
        {"event_cooldown_s": 10**1000},
        {"destinations": {"ops": {"url": "file:///etc/passwd"}}},
        {"destinations": {"ops": {"url": "https://user:secret@example.test"}}},
        {"destinations": {"ops": {"url": "https://example.test/#fragment"}}},
        {"destinations": {"ops": {"url": "https://example.test/\n"}}},
        {
            "destinations": {
                "ops": {
                    "url": "https://example.test",
                    "headers": {"Authorization": "literal"},
                }
            }
        },
        {
            "destinations": {
                "ops": {"url": "https://example.test", "headers_env": {"Host": "ENV"}}
            }
        },
        {"dashboard_url": "https://dashboard.test/?token=secret"},
    ],
)
def test_reject_invalid_setup_without_echoing_secrets(section):
    with pytest.raises(ValueError) as error:
        parse_webhooks(section)
    assert (
        "secret" not in str(error.value)
        or str(error.value) == "webhook header secret is missing or invalid"
    )
    assert "example.test" not in str(error.value)


def test_missing_secret_values_header_injection_and_repr(monkeypatch):
    section = {
        "destinations": {
            "ops": {
                "url": "https://example.test/?token=urlsecret",
                "headers_env": {"Authorization": "HOOK_AUTH"},
            }
        }
    }
    monkeypatch.delenv("HOOK_AUTH", raising=False)
    with pytest.raises(ValueError, match="missing or invalid"):
        parse_webhooks(section)
    monkeypatch.setenv("HOOK_AUTH", "Bearer not-a-real-secret")
    parsed = parse_webhooks(section)
    assert parsed.destinations[0].headers == (
        ("Authorization", "Bearer not-a-real-secret"),
    )
    assert "not-a-real-secret" not in repr(parsed) and "urlsecret" not in repr(parsed)
    monkeypatch.setenv("HOOK_AUTH", "bad\r\nInjected: secret")
    with pytest.raises(ValueError):
        parse_webhooks(section)
    monkeypatch.setenv("HOOK_AUTH", "Bearer secret")
    section["destinations"]["ops"]["url"] = "http://private.internal/hook"
    with pytest.raises(ValueError, match="HTTPS"):
        parse_webhooks(section)
    section["destinations"]["ops"].pop("headers_env")
    assert parse_webhooks(section).destinations[0].url == "http://private.internal/hook"


@pytest.mark.parametrize(
    "path,category,status,retryable",
    [
        ("/ok", "delivered", 200, False),
        ("/huge-body", "delivered", 200, False),
        ("/auth", "http_permanent", 401, False),
        ("/retry", "http_retryable", 503, True),
        ("/redirect", "redirect_refused", 302, False),
        ("/huge-headers", "response_or_configuration_limit", None, False),
    ],
)
def test_local_post_result_bounds_redirects_and_headers(
    receiver, monkeypatch, path, category, status, retryable
):
    base, records = receiver
    monkeypatch.setenv("HOOK_AUTH", "Bearer test-secret")
    cfg = parse_webhooks(
        {
            "destinations": {
                "ops": {
                    "url": base + path + "?hidden=token",
                    "headers_env": {"Authorization": "HOOK_AUTH"},
                }
            }
        }
    )
    result = webhooks.post(cfg.destinations[0], b'{"hello":1}', "gen:1")
    assert (result.category, result.status, result.retryable) == (
        category,
        status,
        retryable,
    )
    assert len(records) == 1
    assert records[0][1]["Authorization"] == "Bearer test-secret"
    assert records[0][1]["Idempotency-Key"] == "gen:1"
    assert "test-secret" not in repr(result) and "token" not in repr(result)
    if path == "/retry":
        assert result.retry_after == 30


def test_timeout_after_receipt_preserves_duplicate_identity(receiver, monkeypatch):
    base, records = receiver
    monkeypatch.setattr(webhooks, "REQUEST_TIMEOUT", 0.04)
    destination = configuration(base + "/timeout").destinations[0]
    for _ in range(2):
        assert webhooks.post(destination, b"{}", "same:1").category == "timeout"
    assert len(records) == 2
    assert {r[1]["Idempotency-Key"] for r in records} == {"same:1"}


def test_unavailable_network():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    result = webhooks.post(
        Destination("ops", f"http://127.0.0.1:{port}"), b"{}", "gen:1"
    )
    assert result.category == "network_unavailable" and result.retryable


def test_retry_order_payload_and_limit(monkeypatch):
    attempts = []

    def sender(destination, body, event_id):
        attempts.append((body, event_id))
        return (
            Outcome("http_retryable", 503, True)
            if len(attempts) < 3
            else Outcome("delivered", 204)
        )

    d = WebhookDispatcher(configuration(), [rule()], sender=sender)
    try:
        d.submit(rule(), event())
        assert d.flush(5)
        assert len(attempts) == 3
        assert len(set(attempts)) == 1
        body = json.loads(attempts[0][0])
        assert body["previous_state"] == "ok" and body["current_state"] == "triggered"
        assert body["version"] == 1 and body["coverage"]["lost"] == 0
        assert d.snapshot("latency")[0]["delivered"] == 1
    finally:
        assert d.close(1)


def test_permanent_pause_drops_backlog_and_future_events():
    sent = []

    def sender(*args):
        sent.append(1)
        return Outcome("http_permanent", 401)

    d = WebhookDispatcher(configuration(), [rule()], sender=sender)
    try:
        d.submit(rule(), event())
        assert d.flush(1)
        for i in range(2, 102):
            d.submit(rule(), event(i))
        row = d.snapshot("latency")[0]
        assert len(sent) == 1 and row["state"] == "paused"
        assert row["dropped"] == 100 and row["paused_for_s"] > 0
        assert "http_permanent" == row["last_failure"]
    finally:
        assert d.close(1)


def test_cooldown_suppression_dedup_and_next_eligible_summary(monkeypatch):
    monkeypatch.setattr(webhooks, "MIN_SPACING", 0)
    r = rule(kind="event")
    delivered = []
    d = WebhookDispatcher(
        configuration(),
        [r],
        sender=lambda _, body, eid: delivered.append(json.loads(body))
        or Outcome("delivered", 200),
    )
    try:
        d.submit(r, event())
        assert d.flush(1)
        for n in range(2, 11):
            d.submit(r, event(n))
        d.submit(r, event(10))
        assert len(delivered) == 1
        row = d.snapshot(r.id)[0]
        assert row["suppressed"] == 9 and row["duplicates"] == 1
        with d._condition:
            d._cooldown[(r.id, "ops")] = 0
        d.submit(r, event(11))
        assert d.flush(1)
        assert delivered[-1]["suppressed_since_previous"] == 9
        assert d.snapshot(r.id)[0]["suppressed"] == 9
    finally:
        assert d.close(1)


def test_queue_bytes_items_shutdown_and_stuck_worker_no_replacement(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def sender(*args):
        entered.set()
        release.wait(5)
        return Outcome("delivered", 200)

    d = WebhookDispatcher(configuration(), [rule()], sender=sender)
    try:
        d.submit(rule(), event())
        assert entered.wait(1)
        for n in range(2, 1002):
            d.submit(rule(), event(n))
        assert len(d._queue) <= webhooks.MAX_ITEMS and d._bytes <= webhooks.MAX_BYTES
        assert d.snapshot("latency")[0]["dropped"] > 900
        before = time.monotonic()
        assert not d.close(0.03)
        assert time.monotonic() - before < 0.5
        assert len(d._queue) == 1 and d._bytes == len(d._inflight.body)
    finally:
        release.set()
        assert d.close(1)
    assert not d._queue and d._bytes == 0


def test_slow_delivery_does_not_block_ingestion_or_check_recovery(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    # Dispatcher sender default is injected explicitly after creation, before jobs.
    monkeypatch.setattr(config, "get_check_rules", lambda: (rule(),))
    monkeypatch.setattr(config, "get_webhook_config", configuration)
    ingestion.reset_ingestion()
    ingestion.setup_ingestion()
    engine = checks.current()

    def sender(*args):
        entered.set()
        release.wait(5)
        return Outcome("delivered", 200)

    engine.notifications._sender = sender
    client = TestClient(app, client=("127.0.0.1", 1234))

    def publish(value):
        result = client.post(
            "/publish",
            json={
                "kind": "artifact",
                "artifact_kind": "json",
                "view_id": "metrics",
                "artifact": {"duration": value},
                "force": True,
            },
        )
        assert result.status_code == 200
        assert engine.flush(1)

    try:
        publish(1)
        publish(20)
        assert entered.wait(1)
        publish(2)
        body = client.get("/checks?view=metrics").json()
        assert [e["event_type"] for e in body["events"]] == ["triggered", "recovered"]
        assert body["states"][0]["state"] == "ok"
        assert body["states"][0]["notifications"][0]["queued"] == 2
        assert not release.is_set()
    finally:
        release.set()
        engine.close(1)


def test_no_worker_without_referenced_enabled_rules():
    d = WebhookDispatcher(
        configuration(), [], sender=lambda *args: pytest.fail("unexpected network")
    )
    assert d._thread is None and d.close(0)
    engine = CheckEngine((replace(rule(), enabled=False),), webhooks=configuration())
    assert engine.notifications is None
    assert engine.close(0)


def test_payload_bounds_before_queue_admission_and_no_raw_context():
    r = rule()
    payload = webhooks.encode(r, event(), 7, "https://dashboard.test/base/")
    decoded = json.loads(payload)
    assert decoded["dashboard_url"] == "https://dashboard.test/base/?view=metrics"
    assert decoded["suppressed_since_previous"] == 7
    item = event()
    item["context"]["raw_row"] = {"secret": "do not send"}
    assert b"do not send" not in webhooks.encode(r, item, 0, None)
    assert webhooks.encode(replace(r, name="x" * 9000), item, 0, None) is None


def test_failed_attempts_stop_at_three_and_fifo_before_recovery():
    attempts = []

    def sender(_, body, eid):
        attempts.append(eid)
        return (
            Outcome("network_unavailable", retryable=True)
            if eid == "gen:1"
            else Outcome("delivered", 200)
        )

    d = WebhookDispatcher(configuration(), [rule()], sender=sender)
    try:
        d.submit(rule(), event(1))
        recovery = event(2)
        recovery.update(event_type="recovered", state="ok", previous_state="triggered")
        d.submit(rule(), recovery)
        assert d.flush(9)
        assert attempts == ["gen:1", "gen:1", "gen:1", "gen:2"]
        row = d.snapshot("latency")[0]
        assert row["failures"] == 3 and row["delivered"] == 1
    finally:
        assert d.close(1)


def test_retry_after_wait_and_close_have_no_background_probe():
    entered = threading.Event()

    def sender(*args):
        entered.set()
        return Outcome("http_retryable", 429, True, 30)

    d = WebhookDispatcher(configuration(), [rule()], sender=sender)
    try:
        d.submit(rule(), event())
        assert entered.wait(1)
        deadline = time.monotonic() + 1
        while (
            d.snapshot("latency")[0]["state"] != "retrying"
            and time.monotonic() < deadline
        ):
            time.sleep(0.001)
        with d._condition:
            assert 29 < d._queue[0].due - time.monotonic() <= 30
        assert d.close(0.03)
        assert d.snapshot("latency")[0]["dropped"] == 1
    finally:
        d.close(1)


def test_restart_refuses_stuck_network_then_new_generation_has_no_initial_alert(
    monkeypatch,
):
    entered, release = threading.Event(), threading.Event()
    engine = CheckEngine((rule(),), generation="old", webhooks=configuration())
    monkeypatch.setattr(checks, "_ENGINE", engine)
    sent = []

    def sender(_, body, eid):
        sent.append(eid)
        entered.set()
        release.wait(5)
        return Outcome("delivered", 200)

    engine.notifications._sender = sender

    def accept(value):
        engine.submit(
            "metrics",
            "state",
            [
                (
                    {"duration": value},
                    {"source_revision": value, "received_at": "2026-09-09T12:00:00Z"},
                )
            ],
        )
        assert engine.flush(1)

    try:
        accept(1)
        accept(20)
        assert entered.wait(1)
        assert not engine.close(0.01)
        with pytest.raises(ValueError, match="still stopping"):
            checks.configure((rule(),), "new", webhooks=configuration())
        assert checks.current() is engine
    finally:
        release.set()
        assert engine.close(1)
    checks.configure((rule(),), "new", webhooks=configuration())
    newer = checks.current()
    try:
        newer.notifications._sender = lambda *args: pytest.fail(
            "initial state must not replay a failure"
        )
        newer.submit(
            "metrics",
            "state",
            [
                (
                    {"duration": 20},
                    {"source_revision": 1, "received_at": "2026-09-09T12:00:00Z"},
                )
            ],
        )
        assert newer.flush(1)
        assert newer.snapshot()["events"] == []
        assert newer.snapshot()["states"][0]["state"] == "triggered"
        assert newer.notifications.flush(1)
        assert sent == ["old:1"]
    finally:
        newer.close(1)


def test_literal_header_references_duplicates_limits_and_safe_dashboard_url(
    monkeypatch,
):
    for names in (["missing"], ["ops", "ops"], ["ops"] * 3):
        with pytest.raises(ValueError):
            parse_checks({"rules": [spec(notify=names)]}, destinations=("ops",))
    with pytest.raises(ValueError):
        CheckEngine((rule(),))
    for address in (
        "http://127.0.0.1:0",
        "http://host:99999",
        "https:///path",
        "https://x/\x7f",
    ):
        with pytest.raises(ValueError):
            configuration(address)
    monkeypatch.setenv("HOOK_AUTH", "x" * 4096)
    with pytest.raises(ValueError, match="aggregate"):
        parse_webhooks(
            {
                "destinations": {
                    "ops": {
                        "url": "https://example.test",
                        "headers_env": {"X-One": "HOOK_AUTH", "X-Two": "HOOK_AUTH"},
                    }
                }
            }
        )


def test_tls_verification_and_proxies_are_independent_of_publisher(monkeypatch):
    import ssl
    import urllib.request

    handlers = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeOpener:
        def open(self, *args, **kwargs):
            return FakeResponse()

    def build(*items):
        handlers.extend(items)
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    destination = Destination("ops", "https://example.test/hook")
    assert webhooks.post(destination, b"{}", "gen:1").category == "delivered"
    proxies = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert len(proxies) == 1 and proxies[0].proxies == {}
    https = next(h for h in handlers if isinstance(h, urllib.request.HTTPSHandler))
    context = https._context or ssl.create_default_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    redirect = next(
        h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)
    )
    assert (
        redirect.redirect_request(None, None, 302, None, None, "https://elsewhere.test")
        is None
    )
    monkeypatch.setattr(
        webhooks,
        "open_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ssl.SSLCertVerificationError("sensitive URL omitted")
        ),
    )
    assert webhooks.post(destination, b"{}", "gen:1").category == "tls_failure"


def test_actual_server_config_resolves_named_destinations(tmp_path, monkeypatch):
    from plotsrv import settings

    monkeypatch.setenv("HOOK_AUTH", "Bearer example-placeholder")
    path = tmp_path / "plotsrv.yml"
    path.write_text("""webhook-settings:
  destinations:
    ops:
      url: https://receiver.example.test/hooks/plotsrv
      headers_env:
        Authorization: HOOK_AUTH
checks-settings:
  rules:
    - id: latency
      source: metrics
      kind: state
      path: [duration]
      op: gt
      value: 10
      notify: [ops]
""")
    settings._CONFIG_CACHE.clear()
    rules = config.get_check_rules()
    assert rules[0].notify == ("ops",)
    assert config.get_webhook_config().destinations[0].headers == (
        ("Authorization", "Bearer example-placeholder"),
    )


def test_live_http_publication_delivers_real_trigger_and_recovery(
    receiver, monkeypatch
):
    base, records = receiver
    cfg = configuration(base + "/ok")
    monkeypatch.setattr(config, "get_check_rules", lambda: (rule(),))
    monkeypatch.setattr(config, "get_webhook_config", lambda: cfg)
    ingestion.reset_ingestion()
    ingestion.setup_ingestion()
    engine = checks.current()
    client = TestClient(app, client=("127.0.0.1", 1234))
    try:
        for value in (1, 20, 2):
            response = client.post(
                "/publish",
                json=dict(
                    kind="artifact",
                    artifact_kind="json",
                    view_id="metrics",
                    artifact={"duration": value},
                    force=True,
                ),
            )
            assert response.status_code == 200
            assert engine.flush(1)
        assert engine.notifications.flush(2)
        assert engine.flush(1)
        bodies = [json.loads(row[2]) for row in records]
        assert [b["event_type"] for b in bodies] == ["triggered", "recovered"]
        assert [(b["previous_state"], b["current_state"]) for b in bodies] == [
            ("ok", "triggered"),
            ("triggered", "ok"),
        ]
        assert all(len(row[2]) <= webhooks.MAX_PAYLOAD for row in records)
        assert bodies[0]["generation"] == engine.generation
        assert (
            client.get("/status?view=metrics").json()["checks"]["states"][0][
                "notifications"
            ][0]["delivered"]
            == 2
        )
    finally:
        engine.close(1)


def test_notification_failure_does_not_change_check_state_or_add_check_events():
    engine = CheckEngine((rule(),), webhooks=configuration())
    engine.notifications._sender = lambda *args: Outcome("http_permanent", 401)
    try:
        for value in (1, 20):
            engine.submit(
                "metrics",
                "state",
                [
                    (
                        {"duration": value},
                        {
                            "source_revision": value,
                            "received_at": "2026-09-09T12:00:00Z",
                        },
                    )
                ],
            )
            assert engine.flush(1)
        assert engine.notifications.flush(1)
        assert engine.flush(1)
        result = engine.snapshot()
        assert [e["event_type"] for e in result["events"]] == ["triggered"]
        assert result["states"][0]["state"] == "triggered"
        assert result["states"][0]["notifications"][0]["state"] == "paused"
    finally:
        engine.close(1)


def test_expired_queue_item_is_disclosed_without_sending():
    entered, release = threading.Event(), threading.Event()
    sent = []

    def sender(_, body, eid):
        sent.append(eid)
        entered.set()
        release.wait(5)
        return Outcome("delivered", 200)

    d = WebhookDispatcher(configuration(), [rule()], sender=sender)
    try:
        d.submit(rule(), event(1))
        assert entered.wait(1)
        d.submit(rule(), event(2))
        with d._condition:
            d._queue[-1].created = time.monotonic() - webhooks.MAX_AGE - 1
        release.set()
        assert d.flush(1)
        assert sent == ["gen:1"]
        row = d.snapshot("latency")[0]
        assert row["dropped"] == 1 and row["last_failure"] == "expired"
    finally:
        release.set()
        d.close(1)


def test_closed_engine_releases_without_waiting_for_cyclic_gc():
    import gc
    import weakref

    engine = CheckEngine((rule(),), webhooks=configuration())
    ref = weakref.ref(engine)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        assert engine.close(1)
        del engine
        assert ref() is None
    finally:
        if was_enabled:
            gc.enable()
