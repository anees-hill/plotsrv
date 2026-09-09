import asyncio
from dataclasses import replace
import json
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv import checks, config, ingestion, settings, store
from plotsrv.app import app, get_artifact
from plotsrv.checks_config import parse_checks
from plotsrv.checks_evidence import Budget, select
from plotsrv.observations.receiver import receive_observation
from plotsrv.streams.models import StreamAppend, StreamRegistration
from plotsrv.streams.server_state import StreamRegistry
from tests.test_checks import isolated, spec
from tests.test_observation_presentation import summary


def setup(monkeypatch, **kwargs):
    rules = parse_checks({"rules": [spec(**kwargs)]})
    monkeypatch.setattr(config, "get_check_rules", lambda: rules)
    ingestion.reset_ingestion()
    ingestion.setup_ingestion()
    return checks.current()


def test_local_http_receipt_once_and_snapshots_read_only(monkeypatch, tmp_path):
    engine = setup(monkeypatch)
    store.set_artifact(obj={"duration": 1}, kind="json", view_id="metrics")
    assert engine.flush(1)
    assert engine.snapshot()["states"][0]["state"] == "ok"
    from plotsrv.storage.backend import write_snapshot

    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    old = write_snapshot(
        root_dir=tmp_path, view_id="metrics", kind="json", obj={"duration": 1}
    )
    client = TestClient(app, client=("127.0.0.1", 12345))
    result = client.post(
        "/publish",
        json=dict(
            kind="artifact",
            artifact_kind="json",
            view_id="metrics",
            artifact={"duration": 12},
            force=True,
        ),
    )
    assert result.status_code == 200, result.text
    assert engine.flush(1)
    assert [e["event_type"] for e in engine.snapshot()["events"]] == ["triggered"]
    before = engine.snapshot()
    get_artifact(view="metrics", snapshot=old.snapshot_id)
    assert engine.snapshot() == before
    data = client.get("/checks", params={"view": "metrics"}).json()
    assert data["states"][0]["state"] == "triggered"
    assert (
        client.get("/status", params={"view": "metrics"}).json()["checks"]["cursor"]
        == data["cursor"]
    )
    assert client.get("/checks?after=-1").status_code == 422


def test_restored_and_unsupported_content_do_not_invent_recovery(monkeypatch):
    engine = setup(monkeypatch)
    store.set_artifact(
        obj={"duration": 12}, kind="json", view_id="metrics", record_arrival=False
    )
    assert engine.snapshot()["states"][0]["reason"] == "awaiting_live_data"
    assert not engine.snapshot()["events"]
    store.set_artifact(obj={"duration": 12}, kind="json", view_id="metrics")
    assert engine.flush(1)
    store.set_table(pd.DataFrame({"duration": [1]}), None, view_id="metrics")
    assert engine.flush(1)
    data = engine.snapshot()
    assert data["states"][0]["state"] == "unknown"
    assert [e["event_type"] for e in data["events"]] == ["unavailable"]


def test_stream_retry_dedup_and_raw_eviction(monkeypatch):
    engine = setup(monkeypatch, kind="event")
    registry = StreamRegistry(max_recent_records=1)
    registry.register(
        StreamRegistration("metrics", "Metrics", "test", "client", "session")
    )
    batch = StreamAppend(
        "metrics",
        "client",
        "session",
        "batch",
        0,
        tuple({"duration": i} for i in [11, 12, 13]),
    )
    result = registry.append(batch)
    assert result.accepted_records == 3
    assert registry.append(batch).duplicate
    assert engine.flush(1)
    events = engine.snapshot()["events"]
    assert len(events) == 3
    assert [e["context"]["batch_position"] for e in events] == [0, 1, 2]
    assert [e["context"]["source_revision"] for e in events] == [1, 2, 3]
    assert all(e["context"]["session_id"] == "session" for e in events)


def test_restart_changes_generation_and_has_no_startup_events(monkeypatch):
    engine = setup(monkeypatch)
    store.set_artifact(obj={"duration": 20}, kind="json", view_id="metrics")
    assert engine.flush(1)
    before = engine.generation
    checks.shutdown()
    assert engine._thread is not None and not engine._thread.is_alive()
    ingestion.setup_ingestion()
    assert checks.current().generation != before
    assert checks.current().snapshot()["states"][0]["state"] == "unknown"
    assert not checks.current().snapshot()["events"]


@pytest.mark.parametrize(
    "source,options",
    [
        ({"duration": 20}, dict(metric="value", scope="supplied_value")),
        (
            pd.DataFrame({"duration": np.arange(1000)}),
            dict(metric="mean", scope="base_sample"),
        ),
        (
            pd.DataFrame({"duration": [None] * 1000}),
            dict(metric="missing_fraction", scope="base_sample"),
        ),
    ],
)
def test_observation_explicit_scope_and_field_identity(source, options):
    value = summary(source)
    rule = parse_checks({"rules": [spec(input="observation", **options)]})[0]
    result = select(rule, value, Budget())
    assert result.reason is None
    assert result.scope == options["scope"]
    wrong = replace(rule, scope="complete_small_inspection")
    assert select(wrong, value, Budget()).reason == "incompatible_coverage"
    renamed = replace(rule, path=("other",))
    assert select(renamed, value, Budget()).reason == "field_unavailable"
    generic = replace(rule, input="json", path=("fields", 0, "missingness", "fraction"))
    assert (
        select(generic, value, Budget()).reason == "observation_requires_explicit_scope"
    )


def test_observation_metadata_and_selected_scope(monkeypatch):
    rule = parse_checks(
        {
            "rules": [
                spec(
                    input="observation",
                    path=[],
                    metric="rows",
                    scope="source_metadata",
                    value=100,
                )
            ]
        }
    )[0]
    value = summary(pd.DataFrame({"duration": np.arange(1000)}))
    assert select(rule, value, Budget()).value == 1000
    value["provenance"]["selection"]["path"] = ["other"]
    assert select(rule, value, Budget()).reason == "incompatible_source_scope"


def test_observation_receiver_checks_without_original_or_storage(monkeypatch):
    engine = setup(
        monkeypatch, input="observation", metric="value", scope="supplied_value"
    )
    for at, duration in [(1, 1), (2, 20)]:
        value = summary({"duration": duration}, at=at)
        value["view_id"] = "metrics"
        receive_observation(
            dict(
                kind="artifact",
                artifact_kind="json",
                view_id="metrics",
                observation=value,
                force=True,
            )
        )
        assert engine.flush(1)
    data = engine.snapshot()
    assert data["states"][0]["state"] == "triggered", data
    assert data["events"][0]["evidence_scope"] == "supplied_value"
    assert data["events"][0]["context"]["captured_at_unix_s"] == 2


def test_sse_check_notices_do_not_discard_pending_data():
    from plotsrv.browser_updates import BrowserUpdateHub

    async def run():
        hub = BrowserUpdateHub()
        sub = hub.subscribe(view_id="metrics", since=0, loop=asyncio.get_running_loop())
        data = hub.publish(view_id="metrics", change_type="ordinary")
        check = hub.publish(view_id="metrics", change_type="checks")
        await asyncio.sleep(0)
        assert list(sub.queue._queue) == [data, check]
        hub.unsubscribe(sub)

    asyncio.run(run())


def test_public_local_publish_uses_same_hook(monkeypatch):
    from plotsrv import publish_view
    from plotsrv import server

    engine = setup(monkeypatch)
    monkeypatch.setattr(server, "start_server", lambda **kw: None)
    for duration in (1, 20):
        publish_view(
            {"duration": duration},
            view_id="metrics",
            mode="local",
            kind="artifact",
            artifact_kind="json",
            async_=False,
            force=True,
        )
        assert engine.flush(1)
    assert [x["event_type"] for x in engine.snapshot()["events"]] == ["triggered"]


def test_authenticated_stream_http_dedup_and_rejection(monkeypatch, tmp_path):
    from plotsrv.streams.models import STREAM_PROTOCOL_VERSION

    (tmp_path / "plotsrv.yml").write_text(
        "server-settings:\n  ingestion:\n    bearer_token_env: CHECK_TEST_KEY\n"
    )
    monkeypatch.setenv("CHECK_TEST_KEY", "private-test-secret")
    engine = setup(monkeypatch, kind="event")
    client = TestClient(app, client=("127.0.0.1", 12345))
    identity = dict(
        protocol_version=STREAM_PROTOCOL_VERSION,
        view_id="metrics",
        client_id="client",
        session_id="session",
    )
    registration = identity | dict(label="Metrics", section="test")
    assert client.post("/stream/register", json=registration).status_code == 401
    assert engine.snapshot()["cursor"] == 0
    headers = {"Authorization": "Bearer private-test-secret"}
    assert (
        client.post("/stream/register", json=registration, headers=headers).status_code
        == 200
    )
    batch = identity | dict(
        batch_id="batch", batch_sequence=0, records=[{"duration": 12}]
    )
    assert client.post("/stream/append", json=batch, headers=headers).status_code == 200
    assert client.post("/stream/append", json=batch, headers=headers).json()[
        "duplicate"
    ]
    assert engine.flush(1)
    data = engine.snapshot()
    assert len(data["events"]) == 1
    assert "private-test-secret" not in json.dumps(data)


def test_restored_stream_history_does_not_evaluate(monkeypatch, tmp_path):
    from tests.test_stream_storage import (
        _configure_stream_storage,
        _write_completed_compact_session,
    )
    from plotsrv import server

    root = _configure_stream_storage(tmp_path)
    _write_completed_compact_session(root)
    engine = setup(monkeypatch, source="logs:restored", kind="event", path=["value"])
    registry = StreamRegistry()
    monkeypatch.setattr(server, "stream_registry", registry)
    assert server.restore_streams_from_storage() == 1
    registry.data(view_id="logs:restored")
    registry.summary(view_id="logs:restored")
    assert engine.snapshot()["cursor"] == 0
    assert engine.snapshot()["states"][0]["reason"] == "awaiting_live_data"


def test_invalid_setup_fails_before_service_and_unknown_sources_are_not_registered(
    tmp_path,
):
    (tmp_path / "plotsrv.yml").write_text("checks-settings:\n  rules:\n    - id: bad\n")
    with pytest.raises(ValueError, match="required"):
        ingestion.setup_ingestion()
    assert not store._VIEWS
