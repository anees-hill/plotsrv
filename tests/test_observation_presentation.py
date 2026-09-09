from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv import ingestion, settings, store
from plotsrv.app import app, get_artifact
from plotsrv.observations.capture import capture_detached
from plotsrv.observations.models import ObservationBudget, ObservationOptions
from plotsrv.observations.summary import build_summary
from plotsrv.observations import history
from plotsrv.observations.presentation import changes, project, compatibility
from plotsrv.observations.receiver import receive_observation
from plotsrv.observations.rendering import render_observation, MAX_BROWSER_BYTES

BUDGET = ObservationBudget(capture_ms=50)


def summary(source, *, at=1.0, session="test", options=ObservationOptions()):
    value = build_summary(
        capture_detached(source, view_id="test", budget=BUDGET, options=options),
        budget=BUDGET,
        publisher_session=session,
    )
    value["captured_at_unix_s"] = at
    return value


def accept(value):
    return receive_observation(
        dict(
            kind="artifact",
            artifact_kind="json",
            observation=value,
            view_id="test",
            label="Test",
            force=True,
        )
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    store.reset()
    yield
    store.reset()


@pytest.mark.parametrize(
    "source",
    [
        pd.DataFrame({"x": np.arange(10000), "empty": [None] * 10000}),
        np.arange(10000),
        {"metrics": {"rows": 123, "seconds": 1.5}},
        {"empty": None},
        object(),
    ],
)
def test_useful_scoped_overview_reuses_explorer_and_no_raw_json(source):
    value = summary(source)
    accept(value)
    result = get_artifact(view="test")
    assert result["meta"]["observation"] is True
    assert "Observation overview" in result["html"]
    assert 'id="table-save-view-btn"' in result["html"]
    assert "Capture details and provenance" in result["html"]
    assert "data-plotsrv-json" not in result["html"]
    assert "Examples / sample" not in result["html"]
    assert history.stats()["entries"] == 1
    assert set(store._VIEWS) == {"test"}
    assert (
        get_artifact(view="test") == result
    )  # cached read cannot accept another observation
    assert history.stats()["entries"] == 1


def test_all_null_and_unknown_are_distinct_without_empty_charts():
    value = summary(
        pd.DataFrame({"null": [None] * 10000, "unknown": [object()] * 10000})
    )
    result = render_observation(value, view_id="test")
    data = project(value)
    assert data["distributions"] == 0
    assert "only missing values" in result.html
    assert "No suitable observed distribution" in result.html
    null, unknown = data["rows"]
    assert null["inspected"] > 0 and null["missing_fraction"] == 1
    assert unknown["not_inspected"] > 0 and unknown["missing_fraction"] is None


def test_examples_require_permission_and_are_not_stored_in_recent_history():
    value = summary(np.arange(100), options=ObservationOptions(include_examples=True))
    assert "Examples / sample" in render_observation(value, view_id="test").html
    accept(value)
    entries, _ = history.read(
        "test", revision=store.get_render_revision(view_id="test")
    )
    raw = json.dumps(entries)
    assert "examples" not in raw and "histogram" not in raw
    assert len(project(value)["examples"]) <= 16


def test_compatible_exact_metrics_and_shape_changes_no_cumulative_sum():
    old, new = summary({"rows": 100}, at=1), summary({"rows": 125}, at=2)
    message, rows = changes(history.compact(new), history.compact(old))
    assert rows[0][1:3] == ("100", "125")
    assert rows[0][3] == "Supplied metric change: 25"
    accept(old)
    accept(new)
    entries, _ = history.read(
        "test", revision=store.get_render_revision(view_id="test")
    )
    data = project(new, entries)
    trend = [r for r in data["rows"] if r["surface"] == "Scalar history"]
    column = next(c for c in data["columns"] if c.startswith("metric_"))
    assert [r[column] for r in trend] == [100, 125]
    assert any(r["presentation"]["plot"]["type"] == "scatter" for r in data["recipes"])
    old, new = summary(np.arange(100), at=1), summary(np.arange(200), at=2)
    assert (
        changes(history.compact(new), history.compact(old))[1][0][0]
        == "Known shape/length"
    )


@pytest.mark.parametrize(
    "change",
    [
        "session",
        "selection",
        "unknown_scope",
        "recipe",
        "policy",
        "out_of_order",
        "schema",
        "unit",
    ],
)
def test_incompatible_states_do_not_produce_scalar_trend(change):
    old, new = summary({"rows": 10}, at=1), summary({"rows": 20}, at=2)
    if change == "session":
        new["provenance"]["publisher_session"] = "other"
    elif change == "selection":
        new["provenance"]["selection"]["path"] = ["other"]
    elif change == "unknown_scope":
        old["provenance"].pop("selection")
    elif change == "recipe":
        new["recipe_version"] = 2
    elif change == "policy":
        new["sampling"]["limits"]["max_rows"] = 4
    elif change == "out_of_order":
        new["captured_at_unix_s"] = 1
    elif change == "schema":
        new["fields"][0]["path"][0]["value"] = "other"
    elif change == "unit":
        new["fields"][0]["value"]["unit"] = "seconds"
    message, rows = changes(history.compact(new), history.compact(old))
    assert "unavailable" in message or "start again" in message
    entries = [
        dict(history.compact(v), received_at=at) for at, v in [(1, old), (2, new)]
    ]
    assert not any(
        r["name"].startswith("Recent") for r in project(new, entries)["recipes"]
    )


def test_same_named_fields_in_different_branches_have_different_provenance():
    root = {"left": {"x": 1}, "right": {"x": 2}}
    old = summary(root, at=1, options=ObservationOptions(path=("left",)))
    new = summary(root, at=2, options=ObservationOptions(path=("right",)))
    assert compatibility(new, old).startswith("Selected source scope")


def test_big_integer_delta_is_exact_but_not_silently_plotted():
    old, new = summary({"n": 2**63}, at=1), summary({"n": 2**63 + 1}, at=2)
    _, rows = changes(history.compact(new), history.compact(old))
    assert rows[0][3] == "Supplied metric change: 1"
    assert not any(column.startswith("metric_") for column in project(new)["columns"])


def test_recent_history_bounded_globally_and_per_source(monkeypatch):
    monkeypatch.setattr(history, "MAX_SOURCES", 4)
    monkeypatch.setattr(history, "MAX_TOTAL_BYTES", 20000)
    value = summary({"n": 1})
    for source in range(30):
        for revision in range(30):
            assert history.append(
                str(source),
                value,
                revision=revision + 1,
                previous_revision=revision,
                received_at=revision,
            )
            assert history.stats()["bytes"] <= 20000
            assert history.stats()["sources"] <= 4
    entries, pruned = history.read("29", revision=30)
    assert len(entries) <= 16 and pruned
    history.clear()
    assert history.stats() == {"sources": 0, "entries": 0, "bytes": 0}


def test_history_gap_on_content_replacement_or_busy_admission():
    accept(summary({"n": 1}))
    store.set_artifact(obj="ordinary", kind="text", view_id="test")
    accept(summary({"n": 2}, at=2))
    assert history.stats()["entries"] == 1
    with history._LOCK:
        assert (
            history.append(
                "test", summary(3), revision=5, previous_revision=4, received_at=1
            )
            is False
        )


def test_drops_are_process_scoped_and_history_reads_are_nonmutating():
    value = summary(1)
    value["delivery"] = dict(skipped=100, coalesced=12, failed=3, best_effort=True)
    accept(value)
    result = get_artifact(view="test")
    assert "all its views, best effort" in result["html"]
    assert "Gaps are not filled" in result["html"]
    assert history.stats()["entries"] == 1
    historical = render_observation(value, view_id="test", snapshot=True)
    assert "fixed historical evidence" in historical.html
    assert "Return to Latest explicitly" in historical.html
    assert historical.meta["recent_count"] == 0
    assert history.stats()["entries"] == 1


def test_unknown_locked_view_does_not_enter_history(tmp_path):
    (tmp_path / "plotsrv.yml").write_text(
        "server-settings:\n  admission:\n    mode: catalogue-locked\n    allowed_ids: [known]\n"
    )
    ingestion.reset_ingestion()
    with pytest.raises(ingestion.IngestionError):
        accept(summary(1))
    assert history.stats()["entries"] == 0


def test_shared_json_renderer_unchanged_for_custom_objects():
    store.set_artifact(obj={"custom": 3}, kind="json", view_id="ordinary")
    result = get_artifact(view="ordinary")
    assert "data-plotsrv-json" in result["html"]
    assert "data-plotsrv-observation" not in result["html"]


def test_renamed_columns_and_selected_branches_change_presentation_bindings():
    old, new = project(summary(pd.DataFrame({"revenue": [1, 2]}))), project(
        summary(pd.DataFrame({"latency": [1, 2]}))
    )
    old_marker = next(c for c in old["columns"] if c.startswith("evidence_"))
    assert old_marker not in new["columns"]
    left = summary({"a": {"n": 1}}, options=ObservationOptions(path=("a",)))
    right = summary({"b": {"n": 1}}, options=ObservationOptions(path=("b",)))
    old_metric = next(c for c in project(left)["columns"] if c.startswith("metric_"))
    assert old_metric not in project(right)["columns"]


def test_selection_provenance_obeys_the_lowest_output_budget():
    options = ObservationOptions(fields=tuple("😀" * 120 + str(i) for i in range(32)))
    budget = replace(BUDGET, max_output_bytes=4096)
    envelope = capture_detached({}, budget=budget, options=options)
    assert len(envelope.payload) <= 4096
    assert envelope.document()["selection"] is None


def test_duplicate_field_names_do_not_merge_automatic_missingness_bars():
    data = project(summary(pd.DataFrame([[1, None], [2, None]], columns=["x", "x"])))
    rows = [r for r in data["rows"] if r["surface"] == "Fields"]
    assert len({r["field"] for r in rows}) == 2


def test_snapshot_storage_uses_existing_policy_and_browsing_is_read_only(
    tmp_path, monkeypatch
):
    from plotsrv import config
    from plotsrv.storage.backend import write_snapshot

    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    value = summary({"count": 10})
    accept(value)
    snapshot = write_snapshot(root_dir=tmp_path, view_id="test", kind="json", obj=value)
    count = history.stats()["entries"]
    stored = get_artifact(view="test", snapshot=snapshot.snapshot_id)
    assert stored["meta"]["snapshot"] is True
    assert "fixed historical evidence" in stored["html"]
    assert history.stats()["entries"] == count
    assert "Snapshot storage has not been enabled" in get_artifact(view="test")["html"]


def test_exploratory_non_null_examples_remain_separate():
    value = summary([None] * 100, options=ObservationOptions(include_examples=True))
    value["exploration"] = dict(
        positions_captured=1, useful_values=1, included_in_base_statistics=False
    )
    value["exploratory_examples"] = [
        {"position": 75, "value": {"type": "integer", "value": 123}}
    ]
    result = render_observation(value, view_id="test")
    assert "Exploratory probes found 1 useful" in result.html
    assert any(
        r[2] == "123" and r[3].startswith("Exploratory")
        for r in project(value)["examples"]
    )
    assert all(
        r[3].startswith("Base") or r[3].startswith("Exploratory")
        for r in project(value)["examples"]
    )


def test_authenticated_remote_observations_use_same_recent_evidence(
    tmp_path, monkeypatch
):
    (tmp_path / "plotsrv.yml").write_text(
        "server-settings:\n  ingestion:\n    bearer_token_env: OBSERVATION_TEST_KEY\n"
    )
    monkeypatch.setenv("OBSERVATION_TEST_KEY", "private-test-key")
    ingestion.reset_ingestion()
    client = TestClient(app, client=("127.0.0.1", 50000))
    for at, count in [(1, 10), (2, 12)]:
        response = client.post(
            "/publish",
            json=dict(
                kind="artifact",
                artifact_kind="json",
                view_id="test",
                observation=summary({"count": count}, at=at),
                force=True,
            ),
            headers={"Authorization": "Bearer private-test-key"},
        )
        assert response.status_code == 200
    result = client.get("/artifact", params={"view": "test"}).json()
    assert result["meta"]["recent_count"] == 2
    assert "Supplied metric change: 2" in result["html"]
    assert "private-test-key" not in result["html"]


def test_wide_unicode_evidence_and_maximum_history_stay_bounded():
    source = pd.DataFrame(
        {("名字" * 85) + str(i): ["值" * 500] * 128 for i in range(32)}
    )
    budget = replace(
        BUDGET,
        max_fields=32,
        max_rows=128,
        max_elements=4096,
        max_nodes=4096,
        max_value_bytes=1024,
        max_capture_bytes=1024 * 1024,
    )
    value = build_summary(
        capture_detached(
            source,
            view_id="test",
            budget=budget,
            options=ObservationOptions(include_examples=True),
        ),
        budget=budget,
        publisher_session="test",
    )
    for revision in range(1, 33):
        history.append(
            "test",
            value,
            revision=revision,
            previous_revision=revision - 1,
            received_at=revision,
        )
    entries, pruned = history.read("test", revision=32)
    assert pruned and len(entries) <= 16
    assert history.stats()["bytes"] <= history.MAX_SOURCE_BYTES
    result = render_observation(value, view_id="test", entries=entries)
    from html import unescape

    payload = unescape(
        result.html.split('data-observation-data="1">')[1].split("</div>")[0]
    )
    assert len(payload.encode()) <= MAX_BROWSER_BYTES
    data = json.loads(payload)
    assert len(data["rows"]) <= 256 and len(data["columns"]) <= 32


def test_omitted_compact_evidence_cannot_become_baseline(monkeypatch):
    value = summary(pd.DataFrame({str(i): np.arange(100) for i in range(16)}))
    monkeypatch.setattr(history, "MAX_ENTRY_BYTES", 1800)
    assert history.append("test", value, revision=1, previous_revision=0, received_at=1)
    entries, _ = history.read("test", revision=1)
    assert entries[0]["history_evidence_omitted"]
    assert "omitted" in compatibility(history.compact(value), entries[0])


@pytest.mark.parametrize(
    "old_source,new_source",
    [
        (np.arange(100), np.arange(100, dtype=float)),
        ({"values": [1, 2]}, {"values": ["a", "b"]}),
    ],
)
def test_array_dtype_and_observed_container_types_fence_comparisons(
    old_source, new_source
):
    old, new = summary(old_source, at=1), summary(new_source, at=2)
    message, rows = changes(history.compact(new), history.compact(old))
    assert "schema" in message and "unavailable" in message
    old_key = next(c for c in project(old)["columns"] if c.startswith("evidence_"))
    assert old_key not in project(new)["columns"]


def test_unfamiliar_bounded_metadata_degrades_without_raw_data_or_server_error():
    value = summary(pd.DataFrame({"x": [1, 2]}))
    value["metadata"]["fields"] = ["unfamiliar"]
    result = render_observation(value, view_id="test")
    assert "format is unavailable" in result.html
    assert "unfamiliar" not in result.html


@pytest.mark.parametrize("enabled", [False, True])
def test_receiver_reuses_optional_snapshot_worker(enabled, tmp_path, monkeypatch):
    from plotsrv import config
    from plotsrv.storage import worker as storage_worker
    from plotsrv.storage.backend import list_snapshots

    monkeypatch.setattr(config, "get_storage_enabled", lambda: enabled)
    monkeypatch.setattr(config, "get_storage_latest_enabled", lambda: False)
    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_storage_view_enabled", lambda *a, **kw: enabled)
    worker = storage_worker.StorageWorker()
    monkeypatch.setattr(storage_worker, "_WORKER", worker)
    try:
        accept(summary({"count": 10}))
        deadline = time.monotonic() + 2
        while (
            enabled and worker.stats()["processed"] < 1 and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert worker.stats()["failed"] == 0
        assert worker.stats()["running"] is enabled
        snapshots = list_snapshots(root_dir=tmp_path, view_id="test")
        assert bool(snapshots) is enabled
        if enabled:
            before = history.stats()
            result = get_artifact(view="test", snapshot=snapshots[0].snapshot_id)
            assert result["meta"]["history_scope"] == "snapshot"
            assert history.stats() == before
    finally:
        worker.stop(join=True, timeout=2)
