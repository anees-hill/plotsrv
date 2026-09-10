"""Compare capture/availability never mutates publication or reads history bodies."""

import json
from pathlib import Path

import pandas as pd
import pytest

from plotsrv import app as app_mod, compare, store
from plotsrv.storage import navigation
from tests.test_snapshot_navigation import client, seed


def publish(obj="one", kind="text"):
    store.set_artifact(obj=obj, kind=kind, view_id="ops:log")


def test_latest_pairs_revision_content_and_receipt_without_mutation(client):
    publish()
    revision = store.get_render_revision(view_id="ops:log")
    status = store.get_status(view_id="ops:log")
    activity = store.get_data_activity(view_id="ops:log")
    data = client.get("/compare/latest?view=ops:log").json()
    assert data["revision"] == revision
    assert (
        data["created_at"]
        == store.get_view_state("ops:log").artifact.created_at.isoformat()
    )
    assert "one" in data["artifact"]["html"]
    assert store.get_status(view_id="ops:log") == status
    assert store.get_data_activity(view_id="ops:log") == activity
    publish("two")
    assert "one" in data["artifact"]["html"]
    assert (
        "two" in client.get("/compare/latest?view=ops:log").json()["artifact"]["html"]
    )


def test_concurrent_publish_cannot_mislabel_body(client, monkeypatch):
    publish()
    render = app_mod._render_artifact_response

    def racing(**kwargs):
        result = render(**kwargs)
        publish("replacement")
        return result

    monkeypatch.setattr(app_mod, "_render_artifact_response", racing)
    response = client.get("/compare/latest?view=ops:log")
    assert response.status_code == 409
    assert "changed" in response.json()["detail"]


def test_capture_work_does_not_hold_publication_lock(client, monkeypatch):
    import threading

    publish()
    render = app_mod._render_artifact_response

    def independent(**kwargs):
        done = threading.Event()
        t = threading.Thread(target=lambda: (publish("new"), done.set()))
        t.start()
        assert done.wait(1), "Capture blocked publication"
        t.join()
        return render(**kwargs)

    monkeypatch.setattr(app_mod, "_render_artifact_response", independent)
    assert client.get("/compare/latest?view=ops:log").status_code == 409


def test_input_bounds_before_renderer_and_unknown_values_do_not_execute(
    client, monkeypatch
):
    class Dangerous:
        def __repr__(self):
            raise AssertionError("repr executed")

        def __iter__(self):
            raise AssertionError("iter executed")

    monkeypatch.setattr(
        app_mod,
        "_render_artifact_response",
        lambda **kw: pytest.fail("Rendered rejected input"),
    )
    for obj in (
        "x" * (compare.MAX_STRING + 1),
        [None] * (compare.MAX_NODES + 1),
        Dangerous(),
        {"a": Dangerous()},
    ):
        publish(obj, "json")
        assert client.get("/compare/latest?view=ops:log").status_code == 413
    nested = None
    for _ in range(20):
        nested = [nested]
    publish(nested, "json")
    assert client.get("/compare/latest?view=ops:log").status_code == 413


def test_table_preview_bounded_and_detached_before_serialization(client):
    store.set_table(pd.DataFrame({"value": range(100_000)}), None, view_id="ops:log")
    response = client.get("/compare/latest?view=ops:log")
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["table"]["rows"]) == compare.MAX_ROWS
    assert data["table"]["total_rows"] == 100_000
    assert "preview" in data["scope"]
    assert len(response.content) < compare.MAX_BYTES
    store.set_table(pd.DataFrame([[1] * 65]), None, view_id="ops:log")
    assert client.get("/compare/latest?view=ops:log").status_code == 413
    store.set_table(
        pd.DataFrame({"a": pd.Series([1], dtype="Int64")}), None, view_id="ops:log"
    )
    assert client.get("/compare/latest?view=ops:log").status_code == 413


def test_capture_concurrency_and_response_limits_release_slots(client, monkeypatch):
    publish()
    assert compare._READERS.acquire(False) and compare._READERS.acquire(False)
    try:
        assert client.get("/compare/latest?view=ops:log").status_code == 503
    finally:
        compare._READERS.release()
        compare._READERS.release()
    monkeypatch.setattr(compare, "MAX_BYTES", 10)
    assert client.get("/compare/latest?view=ops:log").status_code == 413
    monkeypatch.setattr(compare, "MAX_BYTES", 4 * 1024 * 1024)
    assert client.get("/compare/latest?view=ops:log").status_code == 200


def test_month_marks_all_pages_and_only_requested_month(client, tmp_path, monkeypatch):
    for i in range(220):
        seed(tmp_path, f"s{i:03}", "2026-09-09T12:00:00Z")
    seed(tmp_path, "boundary", "2026-10-01T00:30:00+01:00")
    seed(tmp_path, "october", "2026-10-01T00:00:00Z")
    original = Path.open

    def no_body(path, *a, **kw):
        assert path.name.endswith("__meta.json")
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "open", no_body)
    data = client.get("/history/month?view=ops:log&month=2026-09").json()
    assert data["timezone"] == "UTC"
    assert data["days"] == {"2026-09-09": 220, "2026-09-30": 1}
    assert client.get("/history/month?view=ops:log&month=2026-08").json()["days"] == {}
    assert client.get("/history/month?view=ops:log&month=invalid").status_code == 400
    with pytest.raises(ValueError):
        navigation.navigation_page(
            root_dir=tmp_path,
            view_id="ops:log",
            days=True,
            start="2026-01-01",
            end="2027-01-01",
        )


def test_utc_boundaries_repeated_local_times_are_distinct(client, tmp_path):
    seed(tmp_path, "first", "2026-10-25T01:30:00+01:00")
    seed(tmp_path, "second", "2026-10-25T01:30:00+00:00")
    data = client.get(
        "/history/navigation?view=ops:log&start=2026-10-25T00:00:00Z&end=2026-10-26T00:00:00Z"
    ).json()
    assert [row["snapshot_id"] for row in data["snapshots"]] == ["second", "first"]
    assert len({r["created_at"] for r in data["snapshots"]}) == 2


def test_compare_permission_and_storage_capability(client, monkeypatch):
    from plotsrv import config

    publish()
    monkeypatch.setattr(config, "get_storage_enabled", lambda: False)
    assert client.get("/compare/latest?view=ops:log").status_code == 409
    assert (
        client.get("/history/month?view=ops:log&month=2026-09").json()["capability"][
            "enabled"
        ]
        is False
    )


def test_plot_artifact_and_table_capture_paths(client):
    store.set_plot(b"\x89PNG\r\n\x1a\n", view_id="ops:log")
    assert client.get("/compare/latest?view=ops:log").json()["plot"] == "iVBORw0KGgo="
    publish({"items": [1, 2, 3]}, "json")
    response = client.get("/compare/latest?view=ops:log")
    assert response.status_code == 200
    assert response.json()["artifact"]["kind"] == "json"
    store.set_table(
        pd.DataFrame({"date": pd.date_range("2026-09-01", periods=2)}),
        None,
        view_id="ops:log",
    )
    response = client.get("/compare/latest?view=ops:log")
    assert response.status_code == 200, response.text
    assert response.json()["table"]["rows"][0]["date"].startswith("2026-09-01")


def test_direct_file_latest_refuses_before_opening_source(client, monkeypatch):
    from plotsrv.store import WatchedFileMeta
    import inspect

    publish()
    fields = inspect.signature(WatchedFileMeta).parameters
    values = {
        "view_id": "ops:log",
        "path": "/never-read/secret.csv",
        "file_kind": "csv",
        "materialization": "file",
    }
    # Construct only required fixture fields; source contents must never be accessed.
    for name, parameter in fields.items():
        if parameter.default is inspect.Parameter.empty and name not in values:
            values[name] = None
    store.set_watched_file_meta(WatchedFileMeta(**values))
    monkeypatch.setattr(
        Path, "open", lambda *a, **kw: pytest.fail("Read mutable source")
    )
    result = client.get("/compare/latest?view=ops:log")
    assert result.status_code == 409
    assert "unavailable" in result.json()["detail"]
    with pytest.raises(Exception, match="stored snapshot"):
        compare.capture_latest("ops:log")
    assert "secret" not in result.text


def test_new_read_endpoints_preserve_remote_permissions(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from plotsrv import config

    monkeypatch.setattr(config, "get_history_local_only", lambda: True)
    with TestClient(app_mod.app, client=("203.0.113.1", 50000)) as remote:
        assert remote.get("/compare/latest?view=ops:log").status_code == 403
        assert (
            remote.get("/history/month?view=ops:log&month=2026-09").status_code == 403
        )


def test_latest_budget_measurement_does_not_follow_large_row_count(client):
    import time
    import tracemalloc

    measurements = []
    for count in (1000, 100_000):
        store.set_table(
            pd.DataFrame({"value": range(count), "label": ["bounded"] * count}),
            None,
            view_id="ops:log",
        )
        tracemalloc.start()
        start = time.perf_counter()
        response = compare.capture_latest("ops:log")
        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result = json.loads(response.body)
        assert len(result["table"]["rows"]) <= compare.MAX_ROWS
        assert len(response.body) <= compare.MAX_BYTES
        measurements.append(
            {
                "hosted_rows": count,
                "wall_seconds_traced": elapsed,
                "peak_bytes": peak,
                "wire_bytes": len(response.body),
            }
        )
    print("Compare capture measurements:", measurements)


def test_capture_timestamp_tracks_content_not_subsequent_status(client):
    publish()
    original = client.get("/compare/latest?view=ops:log").json()
    store.mark_error("later publication failed", view_id="ops:log")
    assert client.get("/compare/latest?view=ops:log").json() == original
    store.mark_success(duration_s=1, view_id="ops:log")
    assert client.get("/compare/latest?view=ops:log").json() == original
    store.mark_restored(view_id="ops:log", last_updated="2025-01-02T03:04:05+00:00")
    restored = client.get("/compare/latest?view=ops:log").json()
    assert restored["created_at"] == "2025-01-02T03:04:05+00:00"
    store.mark_error("failed after restart", view_id="ops:log")
    assert client.get("/compare/latest?view=ops:log").json() == restored
    publish("new content")
    newer = client.get("/compare/latest?view=ops:log").json()
    assert newer["revision"] != original["revision"]
    assert newer["created_at"] != restored["created_at"]


@pytest.mark.parametrize("value", [float("inf"), -float("inf"), float("nan")])
@pytest.mark.parametrize("table", [False, True])
def test_nonfinite_capture_refuses_without_changing_the_live_value(
    client, value, table
):
    import math

    if table:
        store.set_table(pd.DataFrame({"value": [value]}), None, view_id="ops:log")
    else:
        publish({"value": value}, "json")
    status = store.get_status(view_id="ops:log")
    response = client.get("/compare/latest?view=ops:log")
    assert response.status_code == 413
    assert "non-finite" in response.json()["detail"]
    obj = store.get_view_state("ops:log").artifact.obj
    retained = obj.iloc[0, 0] if table else obj["value"]
    assert math.isnan(retained) if math.isnan(value) else retained == value
    assert store.get_status(view_id="ops:log") == status
    publish("recovered")
    assert client.get("/compare/latest?view=ops:log").status_code == 200


def test_datetime_timezone_hooks_are_rejected_without_execution(client):
    from datetime import datetime, timedelta, timezone, tzinfo
    from zoneinfo import ZoneInfo

    class DangerousTimezone(tzinfo):
        def utcoffset(self, dt):
            pytest.fail("Executed application timezone callback")

    value = datetime(2026, 1, 1, tzinfo=DangerousTimezone())
    publish({"date": value}, "json")
    result = client.get("/compare/latest?view=ops:log")
    assert result.status_code == 413
    assert "timezone" in result.json()["detail"]
    for zone in (
        None,
        timezone.utc,
        timezone(timedelta(hours=2)),
        ZoneInfo("Europe/London"),
    ):
        value = datetime(2026, 1, 1, tzinfo=zone)
        assert compare.Budget().copy(value) == value.isoformat()


def test_observation_capture_preserves_revision_context_and_refuses_congestion(
    client, monkeypatch
):
    from plotsrv.observations import history
    from tests.test_observation_presentation import summary, accept

    accept(summary({"count": 10}, at=1))
    accept(summary({"count": 12}, at=2))
    live = app_mod.get_artifact(view="test")
    before = history.stats()
    captured = client.get("/compare/latest?view=test")
    assert captured.status_code == 200, captured.text
    assert captured.json()["artifact"] == live
    assert "No compatible prior observation is retained." not in captured.text
    assert history.stats() == before
    with history._LOCK:
        assert client.get("/compare/latest?view=test").status_code == 409
    assert client.get("/compare/latest?view=test").status_code == 200

    read = history.read

    def racing(*args, **kwargs):
        result = read(*args, **kwargs)
        accept(summary({"count": 14}, at=3))
        return result

    monkeypatch.setattr(history, "read", racing)
    assert client.get("/compare/latest?view=test").status_code == 409
    assert captured.json()["artifact"] == live


def test_broad_json_refused_before_expensive_renderer(client, monkeypatch):
    publish({str(i): list(range(100)) for i in range(100)}, "json")
    monkeypatch.setattr(
        app_mod,
        "_render_artifact_response",
        lambda **kw: pytest.fail("Rendered oversized JSON"),
    )
    response = client.get("/compare/latest?view=ops:log")
    assert response.status_code == 413
    assert "rendering budget" in response.json()["detail"]


def test_two_near_limit_captures_leave_publication_independent(client, monkeypatch):
    import threading
    import time
    import tracemalloc
    from concurrent.futures import ThreadPoolExecutor

    for vid in ("capture:a", "capture:b"):
        store.set_artifact(obj="x" * compare.MAX_STRING, kind="text", view_id=vid)
    entered = threading.Barrier(3)
    resume = threading.Event()
    render = app_mod._render_artifact_response

    def paused(**kwargs):
        entered.wait(timeout=5)
        assert resume.wait(5)
        return render(**kwargs)

    monkeypatch.setattr(app_mod, "_render_artifact_response", paused)
    with ThreadPoolExecutor(max_workers=3) as workers:
        tracemalloc.start()
        try:
            captures = [
                workers.submit(compare.capture_latest, vid)
                for vid in ("capture:a", "capture:b")
            ]
            entered.wait(timeout=5)
            start = time.perf_counter()
            workers.submit(publish, "independent publication").result(timeout=1)
            publication_time = time.perf_counter() - start
            with pytest.raises(Exception) as busy:
                compare.capture_latest("capture:a")
            assert busy.value.status_code == 503
            resume.set()
            responses = [future.result(timeout=5) for future in captures]
            _, peak = tracemalloc.get_traced_memory()
        finally:
            resume.set()
            tracemalloc.stop()
    assert all(
        response.status_code == 200 and len(response.body) <= compare.MAX_BYTES
        for response in responses
    )
    print(
        "Concurrent capture measurement:",
        {
            "peak_bytes": peak,
            "publication_seconds": publication_time,
            "wire_bytes": [len(r.body) for r in responses],
        },
    )
