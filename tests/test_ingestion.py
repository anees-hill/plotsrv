from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from plotsrv import config, settings, store
from plotsrv.app import app
from plotsrv import ingestion
from plotsrv.contracts import ViewDescriptor
from plotsrv.streams.models import (
    StreamRegistration,
    StreamAppend,
    StreamHeartbeat,
    StreamClose,
)
from plotsrv.streams.server_state import stream_registry


@pytest.fixture(autouse=True)
def isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    monkeypatch.delenv("TEST_INGEST_KEY", raising=False)
    store.reset()
    yield
    store.reset()


def configure(
    tmp_path, monkeypatch, *, key=True, mode="dynamic", ids=None, remote=False
):
    import yaml

    if key:
        monkeypatch.setenv("TEST_INGEST_KEY", "test-only-secret")
    admission = {"mode": mode}
    if ids is not None:
        admission["allowed_ids"] = ids
    path = tmp_path / "plotsrv.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "server-settings": {
                    "ingestion": {
                        "bearer_token_env": "TEST_INGEST_KEY" if key else None,
                        "allow_remote_without_key": remote,
                    },
                    "admission": admission,
                }
            }
        )
    )
    settings._CONFIG_CACHE.clear()
    ingestion.reset_ingestion()


def client(*, local=False, key=True):
    return TestClient(
        app,
        client=("127.0.0.1" if local else "198.51.100.10", 50000),
        headers={"Authorization": "Bearer test-only-secret"} if key else {},
    )


def descriptor(vid="é:订单:daily", kind="unknown"):
    return ViewDescriptor(vid, "Daily orders", "Imports", kind=kind)


def manifest(vid="é:订单:daily", kind="unknown"):
    return {"protocol_version": 1, "views": [descriptor(vid, kind).to_dict()]}


def publication(vid="é:订单:daily"):
    return {
        "kind": "artifact",
        "artifact_kind": "text",
        "artifact": "working",
        "view_id": vid,
    }


def registration(vid="é:订单:daily"):
    return {
        "protocol_version": 4,
        "view_id": vid,
        "label": "Daily orders",
        "section": "Imports",
        "client_id": "producer",
        "session_id": "session",
    }


@pytest.mark.parametrize("route", sorted(ingestion.INGESTION_PATHS))
@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong", "Basic test-only-secret"]
)
def test_auth_all_routes_before_body_and_without_mutation(
    tmp_path, monkeypatch, route, authorization
):
    configure(tmp_path, monkeypatch)
    headers = {"Authorization": authorization} if authorization else {}
    http = client(key=False)
    response = http.request(
        "GET" if route == "/capabilities" else "POST",
        route,
        content=b"not json",
        headers=headers,
    )
    assert response.status_code == 401
    assert response.json()["detail"]["category"] == "unauthorised_publisher"
    assert "test-only-secret" not in response.text
    assert not store._VIEW_META and not store._VIEWS


def test_key_no_key_and_exposure_modes(tmp_path, monkeypatch, caplog):
    assert (
        client(local=True, key=False).post("/publish", json=publication()).status_code
        == 200
    )
    assert (
        client(key=False).post("/publish", json=publication("other")).status_code == 403
    )
    # Disabling administration locality cannot authorise remote ingestion.
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    assert client(key=False).get("/capabilities").status_code == 403
    configure(tmp_path, monkeypatch, key=False, remote=True)
    assert (
        client(key=False).post("/publish", json=publication("remote")).status_code
        == 200
    )
    assert "without a key" in caplog.text
    assert client(key=True).get("/capabilities").status_code == 401


def test_missing_key_fails_service_setup(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.delenv("TEST_INGEST_KEY")
    with pytest.raises(ValueError, match="missing"):
        with client():
            pass
    assert not store._VIEW_META


def test_publish_and_capabilities_do_not_grant_admin(tmp_path, monkeypatch):
    import plotsrv.server  # registers the existing shutdown route

    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "get_shutdown_enabled", lambda: True)
    http = client()
    assert http.post("/publish", json=publication()).status_code == 200
    capabilities = http.get("/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["stream_protocol_version"] == 4
    assert "test-only-secret" not in capabilities.text
    assert http.get("/views").status_code == 403
    assert http.post("/shutdown").status_code == 403
    assert client(local=True).post("/shutdown").status_code == 403
    assert (
        client(local=True, key=False)
        .post("/shutdown", headers={"X-Forwarded-For": "198.51.100.2"})
        .status_code
        == 403
    )


def test_browser_cannot_use_publisher_mutation_even_locally():
    response = client(local=True, key=False).post(
        "/publish", json=publication(), headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert not store._VIEWS


def test_bootstrap_seal_idempotence_metadata_evolution_and_restart(
    tmp_path, monkeypatch
):
    configure(tmp_path, monkeypatch, mode="catalogue-locked")
    http = client()
    generation = http.get("/capabilities").json()["server_generation"]
    assert http.post("/publish", json=publication()).status_code == 403
    assert http.post("/catalogue/register", json=manifest()).status_code == 403
    assert not store._VIEW_META and not store._VIEWS
    first = http.post("/catalogue/bootstrap", json=manifest())
    assert first.status_code == 200
    assert store.get_kind("é:订单:daily") == "none"
    assert store.get_status(view_id="é:订单:daily")["last_updated"] is None
    revision = store.get_view_menu_revision()
    retry = http.post("/catalogue/bootstrap", json=manifest())
    assert retry.json()["idempotent"] is True
    assert store.get_view_menu_revision() == revision
    assert http.post("/publish", json=publication()).status_code == 200
    assert (
        http.post("/catalogue/register", json=manifest(kind="table")).status_code == 200
    )
    before = store.get_status(view_id="é:订单:daily").copy()
    assert http.post("/catalogue/bootstrap", json=manifest("new")).status_code == 409
    assert http.post("/publish", json=publication("new")).status_code == 403
    assert store.get_status(view_id="é:订单:daily") == before
    assert "new" not in store._VIEWS
    store.reset()
    response = http.get("/capabilities").json()
    assert response["server_generation"] != generation
    assert response["admission"]["sealed"] is False


def test_configured_allowlist_empty_and_matching_bootstrap(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, mode="catalogue-locked", ids=["é:订单:daily"])
    http = client()
    assert http.post("/publish", json=publication()).status_code == 200
    assert http.post("/catalogue/bootstrap", json=manifest()).status_code == 200
    assert http.post("/catalogue/bootstrap", json=manifest("other")).status_code == 409
    store.reset()
    configure(tmp_path, monkeypatch, mode="catalogue-locked", ids=[])
    assert client().post("/publish", json=publication()).status_code == 403


def test_racing_bootstrap_transactions_are_atomic(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, mode="catalogue-locked")
    barrier = threading.Barrier(2)

    def seal(vid):
        barrier.wait()
        try:
            return ingestion.register_catalogue([descriptor(vid)], seal=True)
        except ingestion.IngestionError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(seal, ["one", "two"]))
    assert sum(isinstance(x, dict) for x in outcomes) == 1
    assert len(store.list_views()) == 1
    assert frozenset(store._VIEW_META) == ingestion.state().allowed


def test_invalid_manifest_never_partially_registers(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, mode="catalogue-locked")
    bad = manifest()
    bad["views"].append({"view_id": "bad", "label": "Bad", "path": "/etc/passwd"})
    assert client().post("/catalogue/bootstrap", json=bad).status_code == 403
    assert not store._VIEWS and not ingestion.state().sealed
    duplicate = {"protocol_version": 1, "views": [descriptor().to_dict()] * 2}
    assert client().post("/catalogue/bootstrap", json=duplicate).status_code == 403
    assert not store._VIEW_META


def test_locked_in_process_bypasses_and_restoration_are_denied(tmp_path, monkeypatch):
    from plotsrv.server import refresh_view, _restore_latest_loaded_view
    from plotsrv.artifacts import Artifact

    configure(tmp_path, monkeypatch, mode="catalogue-locked", ids=["accepted"])
    actions = [
        lambda: store.register_view(view_id="unexpected"),
        lambda: store.set_artifact(obj="bad", kind="text", view_id="unexpected"),
        lambda: store.set_plot(b"bad", view_id="unexpected"),
        lambda: store.mark_error("bad", view_id="unexpected"),
        lambda: store.mark_success(view_id="unexpected"),
        lambda: store.set_active_view("unexpected"),
        lambda: refresh_view("bad", view_id="unexpected"),
        lambda: stream_registry.register(
            StreamRegistration("unexpected", "Bad", "Section", "client", "session")
        ),
        lambda: stream_registry.append(
            StreamAppend("unexpected", "client", "session", "batch", 0, ({"x": 1},))
        ),
        lambda: stream_registry.heartbeat(
            StreamHeartbeat("unexpected", "client", "session", "live", False)
        ),
        lambda: stream_registry.close(
            StreamClose("unexpected", "client", "session", True)
        ),
        lambda: _restore_latest_loaded_view(
            SimpleNamespace(
                meta=SimpleNamespace(
                    view_id="unexpected", kind="text", section=None, label="Restored"
                )
            )
        ),
    ]
    for action in actions:
        with pytest.raises(ingestion.IngestionError):
            action()
        assert not store._VIEWS and not store._VIEW_META
    store.set_artifact(obj="good", kind="text", view_id="accepted")
    assert store.has_artifact(view_id="accepted")


def test_stream_mutations_preserve_protocol_and_admission(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, mode="catalogue-locked", ids=["stream"])
    http = client()
    assert http.post("/stream/register", json=registration("stream")).status_code == 200
    common = {
        "protocol_version": 4,
        "view_id": "stream",
        "client_id": "producer",
        "session_id": "session",
    }
    bodies = {
        "append": {"records": [{"x": 1}], "batch_id": "b", "batch_sequence": 0},
        "heartbeat": {"delivery_state": "live", "pending_delivery": False},
        "close": {"drain_completed": True},
    }
    for route, fields in bodies.items():
        assert (
            http.post("/stream/" + route, json={**common, **fields}).status_code == 200
        )
        assert (
            http.post(
                "/stream/" + route, json={**common, **fields, "view_id": "unknown"}
            ).status_code
            == 403
        )
    assert "unknown" not in store._VIEWS
    assert http.post("/publish", json=publication("stream")).status_code == 409
    assert (
        http.post(
            "/stream/register", json={**registration("stream"), "protocol_version": 3}
        ).json()["detail"]["category"]
        == "incompatible_protocol"
    )


def test_request_byte_limit_is_before_conversion(tmp_path, monkeypatch):
    import plotsrv.app as app_module

    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "MAX_PUBLISH_REQUEST_BYTES", 100)

    def forbidden(*args, **kwargs):
        raise AssertionError("conversion was reached")

    monkeypatch.setattr(app_module.pd, "DataFrame", forbidden)
    response = client().post("/publish", content=b" " * 101)
    assert response.status_code == 413
    assert not store._VIEWS


@pytest.mark.parametrize("declared", [None, "1"])
def test_chunked_actual_bytes_checked_with_missing_or_false_length(declared):
    async def exercise():
        chunks = iter([b'{"x":"', b"x" * 100, b'"}'])

        async def receive():
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        headers = [] if declared is None else [(b"content-length", declared.encode())]
        req = Request(
            {
                "type": "http",
                "method": "POST",
                "headers": headers,
                "client": ("127.0.0.1", 1),
            },
            receive,
        )
        with pytest.raises(ingestion.IngestionError) as error:
            await ingestion.read_payload(req, 32)
        assert error.value.category == "oversize_data"

    asyncio.run(exercise())
    assert not store._VIEWS


def test_concurrency_rate_and_body_timeout_are_bounded(monkeypatch):
    current = ingestion.state()
    for _ in range(ingestion.MAX_INGESTION_CONCURRENT):
        current.enter()
    try:
        assert client(local=True, key=False).get("/capabilities").status_code == 429
    finally:
        for _ in range(ingestion.MAX_INGESTION_CONCURRENT):
            current.leave()
    current._tokens = 0
    current._last_refill = ingestion.time.monotonic() + 10
    assert client(local=True, key=False).get("/capabilities").status_code == 429
    assert not store._VIEWS
    monkeypatch.setattr(ingestion, "BODY_TIMEOUT_S", 0.001)

    async def exercise():
        async def receive():
            await asyncio.sleep(1)

        req = Request(
            {
                "type": "http",
                "method": "POST",
                "headers": [],
                "client": ("127.0.0.1", 1),
            },
            receive,
        )
        with pytest.raises(ingestion.IngestionError) as error:
            await ingestion.read_payload(req, 100)
        assert error.value.status == 408

    asyncio.run(exercise())


def test_remote_html_markdown_and_table_flags_cannot_grant_trust(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, key=False, remote=True)
    http = client(key=False)
    monkeypatch.setattr(config, "get_html_sanitize", lambda: False)
    monkeypatch.setattr(
        config, "get_html_sandbox", lambda: "allow-scripts allow-same-origin"
    )
    monkeypatch.setattr(config, "get_markdown_sanitize", lambda: False)
    for kind, key in [("html", "html"), ("markdown", "text")]:
        data = {
            **publication(kind),
            "artifact_kind": kind,
            "artifact": {
                key: '<script>window.parent.secret=1</script><img src="x" onerror="alert(1)">',
                "unsafe": True,
                "unsafe_html": True,
                "sandbox": "allow-scripts allow-same-origin",
                "_plotsrv_remote": False,
            },
        }
        assert http.post("/publish", json=data).status_code == 200
        html = http.get("/artifact", params={"view": kind}).json()["html"]
        assert (
            "<script>" not in html
            and "onerror=" not in html
            and "allow-same-origin" not in html
        )
    # The trusted in-process renderer retains its deliberate opt-out.
    from plotsrv.renderers.html import HtmlRenderer

    trusted = HtmlRenderer().render(
        {"html": "<script>1</script>", "unsafe": True}, view_id="trusted"
    )
    assert trusted.meta["mode"] == "unsafe_iframe"
    assert (
        http.post(
            "/publish",
            json={
                **publication("svg"),
                "artifact_kind": "image",
                "artifact": {"mime": "image/svg+xml", "data_b64": "AA=="},
            },
        ).status_code
        == 422
    )
    assert (
        http.post(
            "/publish", json={**publication("path"), "local_path": "/etc/passwd"}
        ).status_code
        == 422
    )


def test_implicit_active_view_cannot_bypass_admission_using_labels(
    tmp_path, monkeypatch
):
    configure(tmp_path, monkeypatch, mode="catalogue-locked", ids=["default:Allowed"])
    with pytest.raises(ingestion.IngestionError):
        store.set_artifact(obj="bad", kind="text", label="Allowed")
    assert not store._VIEWS


def test_unadmitted_restored_stream_has_no_side_effects(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, mode="catalogue-locked", ids=[])
    from plotsrv.streams.server_state import StreamViewState

    restored = StreamViewState(
        registration=StreamRegistration("unknown", "Restored", "s", "c", "session")
    )
    with pytest.raises(ingestion.IngestionError):
        stream_registry._add_historical_state(restored)
    assert not stream_registry._historical_streams
    assert not store._VIEW_META


def test_structure_limit_before_json_expansion(monkeypatch):
    monkeypatch.setattr(ingestion, "MAX_JSON_STRUCTURAL_TOKENS", 10)

    def forbidden(*args, **kwargs):
        raise AssertionError("decoder expanded the data")

    monkeypatch.setattr(ingestion.json, "loads", forbidden)
    with pytest.raises(ingestion.IngestionError, match="json_complexity_limit"):
        ingestion._decode_payload(bytearray(b'{"data":[' + b"{}," * 20 + b"{}]}"))


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-32"])
def test_non_utf8_wire_encoding_cannot_bypass_structure_scan(encoding):
    body = bytearray(
        json.dumps({"text": 'escaped " quote', "data": [{}]}).encode(encoding)
    )
    with pytest.raises(ingestion.IngestionError, match="invalid_json"):
        ingestion._decode_payload(body)


def test_catalogue_capacity_counts_error_state_and_rejections_do_not_accumulate(
    monkeypatch,
):
    monkeypatch.setattr(ingestion, "MAX_CATALOGUE_VIEWS", 2)
    store.register_view(view_id="first")
    store.mark_error("failed", view_id="second")
    for index in range(20):
        view_id = f"rejected:{index}"
        with pytest.raises(ingestion.IngestionError, match="catalogue_capacity"):
            store.mark_error("failed", view_id=view_id)
        store.get_view_state(view_id=view_id)
    assert set(store._VIEWS) == {"first", "second"}
    assert not ingestion.state().descriptors
    with pytest.raises(ingestion.IngestionError, match="catalogue_capacity"):
        ingestion.register_catalogue([descriptor("third")], seal=False)
    assert "third" not in store._VIEW_META
    # Reaching capacity must not prevent updates to an existing admitted ID.
    store.mark_success(duration_s=0.1, view_id="first")


def test_configured_allowlist_does_not_change_with_env_or_reconnect(
    tmp_path, monkeypatch
):
    configure(tmp_path, monkeypatch, mode="catalogue-locked", ids=["accepted"])
    original = ingestion.state()
    monkeypatch.setenv("TEST_INGEST_KEY", "rotated-secret")
    with pytest.raises(ValueError, match="restart"):
        ingestion.setup_ingestion()
    assert ingestion.state() is original
    assert client().post("/publish", json=publication("accepted")).status_code == 200
    assert client().post("/publish", json=publication("unexpected")).status_code == 403


@pytest.mark.parametrize("hint", ["image", "python", "text", "traceback"])
def test_renderer_fallback_cannot_bypass_remote_content_policy(
    tmp_path, monkeypatch, hint
):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "get_tracebacks_enabled", lambda: True)
    monkeypatch.setattr(config, "get_markdown_sanitize", lambda: False)
    http = client()
    response = http.post(
        "/publish",
        json={
            **publication(hint),
            "artifact_kind": hint,
            "artifact": {
                "text": "<script>parent.pwned=1</script>",
                "unsafe_html": True,
                "sandbox": "allow-scripts allow-same-origin",
                "_plotsrv_remote": False,
            },
        },
    )
    assert response.status_code == 200
    html = http.get("/artifact", params={"view": hint}).json()["html"]
    assert "<script>" not in html and "allow-same-origin" not in html


def test_http_html_dictionary_cannot_bypass_text_limit(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "get_publish_max_artifact_text_chars", lambda: 10)
    response = client().post(
        "/publish",
        json={**publication(), "artifact_kind": "html", "artifact": {"html": "x" * 11}},
    )
    assert response.status_code == 413


@pytest.mark.parametrize("local,key,forwarded,trusted", [
    (True, False, False, True),
    (False, True, False, True),
    (False, False, False, False),
    (True, False, True, False),
])
def test_report_trust_comes_from_publisher_authority(tmp_path, monkeypatch, local, key, forwarded, trusted):
    from html.parser import HTMLParser

    configure(tmp_path, monkeypatch, key=key, remote=True)
    monkeypatch.setattr(config, "get_html_sanitize", lambda: False)
    monkeypatch.setattr(config, "get_html_sandbox", lambda: "")
    http = client(local=local, key=key)
    report = '<style>body{background:navy}</style><button onclick="this.textContent=42">Run</button><script>window.reportReady=true</script>'
    response = http.post("/publish", headers={"X-Forwarded-For": "198.51.100.1"} if forwarded else {}, json={
        **publication("report"), "artifact_kind": "html",
        "artifact": {"html": report, "unsafe": True, "_plotsrv_remote": False},
    })
    assert response.status_code == 200
    rendered = http.get("/artifact", params={"view": "report"}).json()
    assert store.get_artifact(view_id="report").obj["_plotsrv_remote"] is not trusted
    if trusted:
        frames = []
        class Frames(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == "iframe":
                    frames.append(dict(attrs))
        Frames().feed(rendered["html"])
        assert len(frames) == 1
        assert frames[0]["srcdoc"] == report
        assert "sandbox" not in frames[0]
        assert rendered["meta"]["display_only"] is False
    else:
        assert "<script>" not in rendered["html"]
        assert "onclick=" not in rendered["html"]


def test_operator_can_explicitly_sanitize_reports(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "get_html_sanitize", lambda: True)
    http = client()
    assert http.post("/publish", json={**publication("report"), "artifact_kind": "html", "artifact": {"html": "<script>1</script><b>Report</b>", "unsafe": True}}).status_code == 200
    assert http.get("/artifact", params={"view": "report"}).json()["meta"]["mode"] == "sanitized"


def test_remote_table_cannot_supply_inline_html(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    response = client().post(
        "/publish",
        json={
            "view_id": "table",
            "kind": "table",
            "table": {"columns": ["x"], "rows": [{"x": 1}]},
            "table_html_simple": "<script>parent.pwned=1</script>",
        },
    )
    assert response.status_code == 200
    assert "<script>" not in store.get_table_html_simple(view_id="table")
    assert "<table" in store.get_table_html_simple(view_id="table")


@pytest.mark.parametrize("kind,field", [("html", "html"), ("markdown", "text")])
def test_remote_content_stays_untrusted_in_persisted_history(
    tmp_path, monkeypatch, kind, field
):
    import plotsrv.app as app_module
    from plotsrv.storage.backend import write_snapshot
    from plotsrv.storage.latest import FileLatestStateBackend

    configure(tmp_path, monkeypatch, key=False, remote=True)
    snapshots = []
    latest = FileLatestStateBackend(root_dir=tmp_path)

    def persist(**kwargs):
        kwargs.pop("source", None)
        snapshots.append(write_snapshot(root_dir=tmp_path, **kwargs))
        latest.write_latest(**kwargs)
        return True

    monkeypatch.setattr(app_module, "enqueue_snapshot", persist)
    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_html_sanitize", lambda: False)
    monkeypatch.setattr(config, "get_markdown_sanitize", lambda: False)
    http = client(key=False)
    assert (
        http.post(
            "/publish",
            json={
                **publication(kind),
                "artifact_kind": kind,
                "artifact": {
                    field: "<script>parent.pwned=1</script><p>Safe content</p>",
                    "unsafe": True,
                    "unsafe_html": True,
                },
            },
        ).status_code
        == 200
    )
    store.reset()
    assert latest.load_latest(view_id=kind).obj["_plotsrv_remote"] is True
    response = http.get(
        "/artifact", params={"view": kind, "snapshot": snapshots[0].snapshot_id}
    )
    assert response.status_code == 200
    assert "<script>" not in response.json()["html"]
    assert "Safe content" in response.json()["html"]
