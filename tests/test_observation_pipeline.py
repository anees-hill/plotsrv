from __future__ import annotations

import asyncio
from dataclasses import replace
import gc
import inspect
import json
import threading
import time
import weakref

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv import config, ingestion, publisher, settings, store
from plotsrv.app import app
from plotsrv.decorators import view
from plotsrv.observations import admission, runtime
from plotsrv.observations.admission import CaptureEngine
from plotsrv.observations.models import (
    ObservationBudget,
    ObservationOptions,
    ObservationRoute,
)
from plotsrv.observations.runtime import ObservationWorker
from plotsrv.publishing.models import PublishTarget
from plotsrv.publishing.transport import TransportError


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    engine = CaptureEngine(replace(ObservationBudget(), capture_ms=50))
    worker = ObservationWorker(engine)
    monkeypatch.setattr(runtime, "_WORKER", worker)
    monkeypatch.setattr(runtime, "_SETUP_RETRY_AT", 0.0)
    monkeypatch.setattr(admission, "_ENGINE", engine)
    store.reset()
    ingestion.reset_ingestion()
    yield worker
    worker.stop(timeout=2)
    assert worker._thread is None or not worker._thread.is_alive()
    store.reset()
    ingestion.reset_ingestion()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: pd.DataFrame({"x": np.arange(10000)}),
        lambda: np.arange(10000)[::2],
        lambda: {"n": 2**63, "counts": [1, 2, 3]},
    ],
)
@pytest.mark.parametrize("decorated", [False, True])
@pytest.mark.parametrize("remote", [False, True])
def test_public_entrypoints_to_common_receiver(
    worker, monkeypatch, factory, decorated, remote
):
    from plotsrv import server
    from plotsrv.publishing import transport

    calls = []
    main_thread = threading.get_ident()
    client = TestClient(app, client=("127.0.0.1", 50000))

    def start(**kwargs):
        assert threading.get_ident() != main_thread
        assert kwargs["restore_latest"] is False
        calls.append("start")

    monkeypatch.setattr(server, "start_server", start)
    monkeypatch.setattr(server, "_SERVER_RUNNING", False)
    monkeypatch.setattr(server, "_SERVER_STARTING", False)
    monkeypatch.setattr(server, "_SERVER_THREAD", None)

    def request(target, path, payload, **kwargs):
        assert threading.get_ident() != main_thread
        assert kwargs["feature"] == "observation-v1"
        assert kwargs["timeout_s"] <= 2
        assert len(json.dumps(payload).encode()) < 80 * 1024
        assert "base_sample" not in payload["observation"]
        calls.append("http")
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(transport, "request_json", request)
    monkeypatch.setattr(
        publisher, "_estimate_publish_task_bytes", lambda _: pytest.fail("raw estimate")
    )
    monkeypatch.setattr(
        publisher,
        "_resolve_async_publish",
        lambda _: pytest.fail("ordinary async default"),
    )
    source = factory()
    kwargs = {"host": "127.0.0.1", "port": 8912} if remote else {}
    if decorated:

        @view(observe=True, view_id="metrics", **kwargs)
        def pipeline(value):
            """Original documentation."""
            return value

        assert str(inspect.signature(pipeline)) == "(value)"
        assert pipeline.__doc__ == "Original documentation."
        assert pipeline(source) is source
    else:
        assert (
            publisher.publish_view(source, observe=True, view_id="metrics", **kwargs)
            is None
        )
    assert publisher.flush_views(timeout=2)
    assert calls == ["http" if remote else "start"]
    assert set(store._VIEWS) == {"metrics"}
    descriptor = ingestion.state().descriptors["metrics"]
    assert "observation-v1" in descriptor.capabilities
    assert worker.engine.stats()["counters"]["processed"] == 1


def test_decorator_original_errors_cancellation_and_runtime_failure(
    worker, monkeypatch
):
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")
    monkeypatch.setattr(
        runtime,
        "submit_observation",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("delivery")),
    )
    value = object()

    @view(observe=True)
    def sync(value):
        return value

    assert sync(value) is value

    @view(observe=True)
    async def asynchronous(value):
        return value

    assert inspect.iscoroutinefunction(asynchronous)
    assert asyncio.run(asynchronous(value)) is value
    for error in (
        RuntimeError("original"),
        asyncio.CancelledError(),
        KeyboardInterrupt(),
    ):

        @view(observe=True)
        def raises():
            raise error

        with pytest.raises(type(error)) as caught:
            raises()
        assert caught.value is error

        @view(observe=True)
        async def async_raises():
            raise error

        with pytest.raises(type(error)) as caught:
            asyncio.run(async_raises())
        assert caught.value is error


@pytest.mark.parametrize("entry", [publisher.publish_view, view])
def test_explicit_sync_is_setup_incompatibility(entry, worker):
    with pytest.raises(ValueError, match="async_=False"):
        if entry is view:
            entry(observe=True, async_=False)
        else:
            entry(object(), observe=True, async_=False)
    assert worker._thread is None


def test_no_source_retained_during_slow_delivery_or_pending_capture(
    worker, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    delivered = []

    def blocked(summary, view_id, route):
        entered.set()
        assert release.wait(2)
        delivered.append(summary)
        return True

    monkeypatch.setattr(worker, "_deliver", blocked)
    source = pd.DataFrame({"x": np.arange(100000)})
    ref = weakref.ref(source)
    publisher.publish_view(source, observe=True, view_id="first")
    assert entered.wait(1)
    other = np.arange(100000)
    other_ref = weakref.ref(other)
    publisher.publish_view(other, observe=True, view_id="pending")
    other[:] = -1
    del source, other
    gc.collect()
    assert ref() is None and other_ref() is None
    try:
        start = time.monotonic()
        for _ in range(1000):
            publisher.publish_view(object(), observe=True, view_id="first")
        assert time.monotonic() - start < 0.5
        assert not publisher.flush_views(timeout=0.01)
        worker.stop(timeout=0.01)
        assert worker._running
        thread = worker._thread
        assert (
            worker.submit(object(), ObservationOptions(), view_id="another") == "closed"
        )
        assert worker._thread is thread
        assert worker.engine.stats()["reserved"] == 1
    finally:
        release.set()
    worker._thread.join(1)
    assert worker.engine.stats()["reserved"] == 0
    assert len(delivered) == 1
    assert worker.start()
    assert worker._thread is not thread


def test_pending_latest_wins_per_target_without_extra_reservations(worker, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(admission.time, "monotonic", lambda: now[0])
    engine = CaptureEngine(ObservationBudget())
    a = ObservationRoute(
        PublishTarget(kind="remote", base_url="http://127.0.0.1:8912"), "x"
    )
    b = ObservationRoute(
        PublishTarget(kind="remote", base_url="http://127.0.0.1:8913"), "x"
    )
    assert engine.submit("x", 1, route=a) == "accepted"
    now[0] += 2
    assert engine.submit("x", 2, route=a) == "accepted"
    assert engine.submit("x", 3, route=b) == "accepted"
    stats = engine.stats()
    assert stats["reserved"] == 2
    assert stats["counters"]["coalesced"] == stats["counters"]["dropped"] == 1
    works = [engine.take(), engine.take()]
    assert [w.envelope.document()["base_sample"][0]["value"] for w in works] == [2, 3]
    now[0] += 2
    assert engine.submit("x", 4, route=a) == "view_pending"
    for work in works:
        engine.complete(work.token, succeeded=True)
    engine.close()


def test_idle_consumer_has_no_poll_timeout_and_close_wakes_it(worker, monkeypatch):
    entered = threading.Event()
    original = worker.engine._condition.wait

    def wait(timeout=None):
        assert timeout is None
        entered.set()
        return original(timeout)

    monkeypatch.setattr(worker.engine._condition, "wait", wait)
    assert worker.start()
    assert entered.wait(1)
    worker.stop(timeout=1)
    assert not worker._running


@pytest.mark.parametrize(
    "code",
    [
        "request_timeout",
        "unauthorised_publisher",
        "inadmissible_view",
        "incompatible_protocol",
        "invalid_credential",
    ],
)
def test_failures_are_nonfatal_rate_limited_and_recover_on_later_call(
    worker, monkeypatch, caplog, code
):
    calls = []

    def fail(*args):
        calls.append(1)
        raise TransportError(code)

    monkeypatch.setattr(worker, "_deliver", fail)
    publisher.publish_view([1, 2], observe=True, view_id="x")
    assert publisher.flush_views(timeout=1)
    assert worker.engine.stats()["counters"]["failed"] == 1
    for _ in range(100):
        publisher.publish_view([3], observe=True, view_id="x")
    assert len(calls) == 1
    assert caplog.text.count("Observation delivery skipped") <= 1
    with worker.engine._lock:
        worker.engine._paused.clear()
        worker.engine._views.clear()
    monkeypatch.setattr(worker, "_deliver", lambda *args: True)
    publisher.publish_view([4], observe=True, view_id="x")
    assert publisher.flush_views(timeout=1)
    assert worker.engine.stats()["counters"]["processed"] == 1


def test_routing_is_cached_and_invalid_setup_is_cooled_down(worker, monkeypatch):
    import plotsrv.connection_config as connection

    resolver = connection.resolve_publish_target
    calls = []

    def resolve(**kwargs):
        calls.append(1)
        return resolver(**kwargs)

    monkeypatch.setattr(connection, "resolve_publish_target", resolve)
    monkeypatch.setattr(worker, "_deliver", lambda *args: True)
    for _ in range(100):
        publisher.publish_view(1, observe=True, view_id="x")
    assert len(calls) == 1
    assert publisher.flush_views(timeout=1)

    def invalid(**kwargs):
        calls.append(1)
        raise ValueError("SECRET")

    monkeypatch.setattr(connection, "resolve_publish_target", invalid)
    for _ in range(100):
        publisher.publish_view(
            1, observe=True, destination="https://example.invalid", view_id="x"
        )
    assert len(calls) == 2
    assert worker.last_error == "invalid_observation_setup"


def test_http_negotiation_auth_locked_catalogue_and_recovery(
    worker, tmp_path, monkeypatch, caplog
):
    import io
    import urllib.error
    from plotsrv.publishing import transport

    (tmp_path / "plotsrv.yml").write_text("""server-settings:
  ingestion:
    bearer_token_env: OBSERVATION_TEST_KEY
  admission:
    mode: catalogue-locked
    allowed_ids: [known]
""")
    monkeypatch.setenv("OBSERVATION_TEST_KEY", "private-test-key")
    ingestion.reset_ingestion()
    client = TestClient(app, client=("127.0.0.1", 50000))
    requests = []

    def open_request(request, *, timeout):
        requests.append((request.method, request.full_url, threading.get_ident()))
        response = client.request(
            request.method,
            request.full_url,
            content=request.data,
            headers=dict(request.header_items()),
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                response.status_code,
                "error",
                response.headers,
                io.BytesIO(response.content),
            )
        return io.BytesIO(response.content)

    monkeypatch.setattr(transport, "_open", open_request)
    target = PublishTarget(
        kind="remote",
        base_url="http://127.0.0.1:8912",
        bearer_token_env="OBSERVATION_TEST_KEY",
    )
    publisher.publish_view(
        {"count": 5}, observe=True, destination=target, view_id="known"
    )
    assert publisher.flush_views(timeout=2)
    assert "observation-v1" in ingestion.state().descriptors["known"].capabilities
    assert [r[0] for r in requests] == ["GET", "POST"]
    assert all(r[2] != threading.get_ident() for r in requests)
    publisher.publish_view(
        {"count": 6}, observe=True, destination=target, view_id="unknown"
    )
    assert publisher.flush_views(timeout=2)
    assert set(store._VIEWS) == {"known"}
    assert worker.last_error == "inadmissible_view"
    assert "private-test-key" not in caplog.text
    with worker.engine._lock:
        worker.engine._paused.clear()
        worker.engine._views.clear()
    transport.reset_transport()
    ingestion.reset_ingestion()  # a fresh server generation negotiates again
    publisher.publish_view(
        {"count": 7}, observe=True, destination=target, view_id="known"
    )
    assert publisher.flush_views(timeout=2)
    assert worker.engine.stats()["counters"]["processed"] == 2
    monkeypatch.setenv("OBSERVATION_TEST_KEY", "rotated-private-key")
    with worker.engine._lock:
        worker.engine._views.clear()
    publisher.publish_view(8, observe=True, destination=target, view_id="known")
    assert publisher.flush_views(timeout=2)
    assert worker.last_error == "invalid_credential"
    assert "rotated-private-key" not in caplog.text


def test_receiver_rejections_are_atomic_and_auth_precedes_observation(
    worker, tmp_path, monkeypatch
):
    from plotsrv.observations.capture import capture_detached
    from plotsrv.observations.summary import build_summary

    (tmp_path / "plotsrv.yml").write_text("""server-settings:
  ingestion:
    bearer_token_env: OBSERVATION_TEST_KEY
""")
    monkeypatch.setenv("OBSERVATION_TEST_KEY", "private-test-key")
    ingestion.reset_ingestion()
    client = TestClient(app, client=("127.0.0.1", 50000))
    summary = build_summary(
        capture_detached(1, view_id="x"), budget=ObservationBudget()
    )
    payload = {
        "kind": "artifact",
        "artifact_kind": "json",
        "view_id": "x",
        "observation": summary,
    }
    assert client.post("/publish", json=payload).status_code == 401
    assert not store._VIEWS
    summary["observation_version"] = 999
    assert (
        client.post(
            "/publish",
            json=payload,
            headers={"Authorization": "Bearer private-test-key"},
        ).status_code
        == 422
    )
    assert not store._VIEWS


def test_old_server_fails_closed_before_post(worker, monkeypatch):
    import io
    from plotsrv.contracts import ProtocolCapabilities
    from plotsrv.publishing import transport

    requests = []

    def old(request, *, timeout):
        requests.append(request.method)
        return io.BytesIO(
            json.dumps(
                ProtocolCapabilities(
                    server_generation="old",
                    dashboard_scope="test",
                    capabilities=("publish",),
                ).to_dict()
            ).encode()
        )

    monkeypatch.setattr(transport, "_open", old)
    publisher.publish_view(
        np.arange(10000), observe=True, destination="http://127.0.0.1:8912", view_id="x"
    )
    assert publisher.flush_views(timeout=1)
    assert requests == ["GET"]
    assert worker.last_error == "incompatible_protocol"


def test_decorator_warm_calls_do_not_resolve_configuration(worker, monkeypatch):
    from plotsrv import connection_config

    @view(observe=True, view_id="x")
    def pipeline(value):
        """Bounded pipeline explanation.

        Private implementation details are not published.
        """
        return value

    monkeypatch.setattr(
        connection_config,
        "resolve_publish_target",
        lambda **kwargs: pytest.fail("warm configuration access"),
    )
    monkeypatch.setattr(worker, "_deliver", lambda *args: True)
    from plotsrv import descriptions

    monkeypatch.setattr(
        descriptions,
        "source_description",
        lambda *a, **kw: pytest.fail("warm description setup"),
    )
    value = [1, 2]
    assert pipeline(value) is value
    assert publisher.flush_views(timeout=1)
    assert worker.engine.stats()["counters"]["processed"] == 1


def test_local_existing_server_does_not_repeat_setup(worker, monkeypatch):
    from plotsrv import server

    monkeypatch.setattr(server, "_SERVER_RUNNING", True)
    monkeypatch.setattr(server, "_CURRENT_HOST", "127.0.0.1")
    monkeypatch.setattr(server, "_CURRENT_PORT", 8000)
    monkeypatch.setattr(
        server, "start_server", lambda **kwargs: pytest.fail("repeated server setup")
    )
    publisher.publish_view(1, observe=True, view_id="x")
    assert publisher.flush_views(timeout=1)
    assert worker.engine.stats()["counters"]["processed"] == 1


def test_static_invalid_budget_and_options_are_clear_runtime_variation_safe(
    worker, monkeypatch
):
    with pytest.raises(ValueError, match="on_error"):
        view(observe=True, on_error="publish")
    with pytest.raises(ValueError, match="functions"):
        view(observe=True)(type("C", (), {}))
    with pytest.raises(ValueError, match="format"):
        publisher.publish_view(1, observe=True, artifact_kind="html")
    worker.stop(timeout=1)
    monkeypatch.setattr(runtime, "_WORKER", None)
    monkeypatch.setattr(admission, "_ENGINE", None)

    def invalid():
        raise ValueError("invalid publish-settings.observe configuration")

    monkeypatch.setattr(config, "get_observation_budget", invalid)
    with pytest.raises(ValueError, match="configuration"):
        view(observe=True)
    # Inline runtime setup has a non-fatal, fixed-code cooldown.
    assert publisher.publish_view(1, observe=True) is None
    assert runtime.get_observation_stats()["last_error"] == "invalid_observation_setup"


def test_target_and_route_caches_are_bounded(worker):
    for i in range(10000):
        worker.route(view_id=str(i), label="x", force=False)
    assert len(worker._routes) <= worker.engine.budget.max_view_ids
    for i in range(100):
        worker.route(
            destination=f"http://127.0.0.1:{10000 + i}", view_id="x", force=False
        )
    assert len(worker._targets) == runtime.MAX_TARGETS


def test_ordinary_custom_report_still_uses_ordinary_html_path(worker, monkeypatch):
    from plotsrv.publishing import transport

    payloads = []
    monkeypatch.setattr(
        transport,
        "request_json",
        lambda target, path, payload, **kwargs: payloads.append(payload)
        or {"ok": True},
    )
    monkeypatch.setattr(transport, "handshake", lambda *args, **kwargs: None)
    report = {
        "html": '<html><body style="background:#663399"><h1>Custom pipeline report</h1></body></html>',
        "unsafe": True,
    }

    @view(port=8912, async_=False, label="Custom report")
    def custom_report():
        return report

    assert custom_report() is report
    assert payloads[0]["artifact_kind"] == "html"
    assert "observation" not in payloads[0]
    assert worker._thread is None


def test_restart_refreshes_routing_without_reinitializing_capture_budget(
    worker, monkeypatch
):
    monkeypatch.setattr(worker, "_deliver", lambda *args: True)
    publisher.publish_view(1, observe=True, view_id="x")
    assert publisher.flush_views(timeout=1)
    old_session = worker.session
    budget = worker.engine.budget
    worker.stop(timeout=1)
    assert worker.start()
    assert not worker._targets and not worker._routes
    assert worker.session != old_session
    assert worker.engine.budget is budget


def test_coalescing_failure_releases_old_pending_bytes(worker, monkeypatch):
    from plotsrv.observations import capture

    route = ObservationRoute(
        PublishTarget(kind="remote", base_url="http://127.0.0.1:8912"), "x"
    )
    assert worker.engine.submit("x", [1, 2], route=route) == "accepted"
    worker.engine._views.clear()

    def broken(*args, **kwargs):
        raise MemoryError()

    monkeypatch.setattr(capture, "capture_detached", broken)
    assert worker.engine.submit("x", [3], route=route) == "capture_failed"
    assert worker.engine.stats()["reserved"] == 0
    assert worker.engine.stats()["counters"]["dropped"] == 1


def test_source_change_after_pending_handoff_cannot_change_delivery(
    worker, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    delivered = {}

    def deliver(summary, view_id, route):
        if view_id == "block":
            entered.set()
            assert release.wait(2)
        delivered[view_id] = summary
        return True

    monkeypatch.setattr(worker, "_deliver", deliver)
    publisher.publish_view(0, observe=True, view_id="block")
    assert entered.wait(1)
    source = np.arange(10000)
    publisher.publish_view(source, observe=True, view_id="sample")
    source[:] = -1
    release.set()
    assert publisher.flush_views(timeout=2)
    assert delivered["sample"]["fields"][0]["numeric"]["max"]["value"] == 9999


def test_flush_deadline_is_shared_and_failure_means_drained_not_delivered(
    worker, monkeypatch
):
    limits = []

    def ordinary(*, timeout):
        limits.append(timeout)
        time.sleep(0.01)
        return False

    monkeypatch.setattr(publisher, "flush_publish_views", ordinary)
    monkeypatch.setattr(
        runtime, "flush_observations", lambda timeout: limits.append(timeout) or True
    )
    assert not publisher.flush_views(timeout=0.05)
    assert limits[0] == 0.05 and 0 <= limits[1] < 0.045
    with pytest.raises(ValueError, match="finite"):
        publisher.flush_views(timeout=float("inf"))


@pytest.mark.parametrize("replacement", ["text", "table", "plot"])
def test_observation_capability_tracks_current_content(
    worker, monkeypatch, replacement
):
    from plotsrv import server

    monkeypatch.setattr(server, "_SERVER_RUNNING", True)
    monkeypatch.setattr(server, "_CURRENT_HOST", "127.0.0.1")
    monkeypatch.setattr(server, "_CURRENT_PORT", 8000)
    publisher.publish_view(1, observe=True, view_id="x")
    assert publisher.flush_views(timeout=1)
    assert "observation-v1" in ingestion.state().descriptors["x"].capabilities
    if replacement == "text":
        store.set_artifact(obj="ordinary", kind="text", view_id="x")
    elif replacement == "table":
        store.set_table(pd.DataFrame({"x": [1]}), None, view_id="x")
    else:
        store.set_plot(b"image", view_id="x")
    assert "observation-v1" not in ingestion.state().descriptors["x"].capabilities
    worker.engine._views.clear()
    publisher.publish_view(2, observe=True, view_id="x")
    assert publisher.flush_views(timeout=1)
    assert "observation-v1" in ingestion.state().descriptors["x"].capabilities
