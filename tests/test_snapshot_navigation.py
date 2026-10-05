"""Metadata ordering and budgets are independent of snapshot payload size."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plotsrv import app as app_mod, config, store
from plotsrv.storage import navigation as nav
from plotsrv.storage.backend import write_snapshot


@pytest.fixture
def client(tmp_path, monkeypatch):
    store.reset()
    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_storage_enabled", lambda: True)
    monkeypatch.setattr(config, "get_storage_view_enabled", lambda *a, **kw: True)
    monkeypatch.setattr(config, "get_history_local_only", lambda: True)
    with TestClient(app_mod.app, client=("127.0.0.1", 50000)) as client:
        yield client
    store.reset()


def seed(root, sid, created="2026-09-09T12:00:00Z", view="ops:log"):
    directory = nav._view_dir(root, view)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sid + "__meta.json")
    path.write_text(
        json.dumps(dict(snapshot_id=sid, view_id=view, kind="text", created_at=created))
    )
    # Intentionally no payload. Metadata-only ordering must work without bodies.
    return path


def test_order_time_then_id_latest_is_separate_and_no_body_reads(tmp_path, monkeypatch):
    seed(tmp_path, "z", "2026-09-09T12:00:00Z")
    seed(tmp_path, "a", "2026-09-10T12:00:00Z")
    seed(tmp_path, "b", "2026-09-10T13:00:00+01:00")
    seed(tmp_path, "c", "2026-09-10T12:00:00.001Z")
    opened = []
    original = nav.open_regular_file

    def checked(path, *args, **kwargs):
        opened.append(path.name)
        assert path.name.endswith("__meta.json")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(nav, "open_regular_file", checked)
    page = nav.navigation_page(root_dir=tmp_path, view_id="ops:log", limit=2)
    assert [s["snapshot_id"] for s in page["snapshots"]] == ["c", "b"]
    assert page["older"]["snapshot_id"] == "c"
    assert page["newer"] is None
    assert page["selected_offset"] == 0
    assert not any(s["is_live_equivalent"] for s in page["snapshots"])
    assert all(s["equivalence"] == "unknown" for s in page["snapshots"])
    second = nav.navigation_page(
        root_dir=tmp_path,
        view_id="ops:log",
        before=page["next_cursor"],
        limit=2,
        selected="b",
    )
    assert [s["snapshot_id"] for s in second["snapshots"]] == ["a", "z"]
    assert second["next_cursor"] is None
    assert second["older"]["snapshot_id"] == "a"
    assert second["newer"]["snapshot_id"] == "c"
    assert second["selected"]["snapshot_id"] == "b"
    assert second["selected_offset"] == 2
    newest = nav.navigation_page(root_dir=tmp_path, view_id="ops:log", selected="c")
    assert newest["newer"] is None and newest["can_return_latest"]
    assert newest["selected_offset"] == 1
    oldest = nav.navigation_page(root_dir=tmp_path, view_id="ops:log", selected="z")
    assert oldest["older"] is None
    assert oldest["selected_offset"] == 4
    filtered = nav.navigation_page(root_dir=tmp_path, view_id="ops:log", selected="z",
                                   start="2026-09-10", limit=1)
    assert filtered["selected_offset"] == 4
    assert opened


def test_many_pages_and_date_range_do_not_cache_or_repeat(tmp_path):
    for i in range(137):
        seed(tmp_path, f"{i:04}")
    before = None
    ids = []
    while True:
        page = nav.navigation_page(
            root_dir=tmp_path,
            view_id="ops:log",
            limit=13,
            before=before,
            start="2026-09-09",
            end="2026-09-10",
        )
        assert len(page["snapshots"]) <= 13
        assert page["count"] == 137
        ids.extend(s["snapshot_id"] for s in page["snapshots"])
        before = page["next_cursor"]
        if not before:
            break
    assert ids == [f"{i:04}" for i in reversed(range(137))]
    empty = nav.navigation_page(
        root_dir=tmp_path, view_id="ops:log", start="2026-10-01"
    )
    assert empty["count"] == 0 and empty["snapshots"] == []


def test_empty_missing_and_slug_collision(tmp_path):
    assert nav.navigation_page(root_dir=tmp_path, view_id="ops:log")["older"] is None
    assert not list(tmp_path.iterdir())  # Read never creates storage.
    seed(tmp_path, "other", view="ops/log")
    page = nav.navigation_page(root_dir=tmp_path, view_id="ops:log", selected="other")
    assert page["count"] == 0
    assert page["selection_state"] == "unavailable"
    assert page["selected_offset"] is None
    assert page["can_return_latest"]


@pytest.mark.parametrize(
    "setting,value",
    [
        ("MAX_ENTRIES", 0),
        ("MAX_METADATA_BYTES", 10),
        ("MAX_FILE_BYTES", 10),
        ("MAX_SCAN_SECONDS", 0),
    ],
)
def test_limits_refuse_incomplete_ordering_and_release_reader(
    tmp_path, monkeypatch, setting, value
):
    seed(tmp_path, "one")
    with monkeypatch.context() as patch:
        patch.setattr(nav, setting, value)
        with pytest.raises(nav.NavigationUnavailable):
            nav.navigation_page(root_dir=tmp_path, view_id="ops:log")
    assert nav.navigation_page(root_dir=tmp_path, view_id="ops:log")["count"] == 1


def test_oversized_metadata_is_bounded_before_json(tmp_path, monkeypatch):
    path = seed(tmp_path, "one")
    path.write_bytes(b" " * (nav.MAX_FILE_BYTES + 1))
    monkeypatch.setattr(
        nav.json, "loads", lambda value: pytest.fail("Must reject before parsing")
    )
    with pytest.raises(nav.NavigationUnavailable):
        nav.navigation_page(root_dir=tmp_path, view_id="ops:log")


@pytest.mark.parametrize(
    "content",
    ["[]", "{", '{"view_id":"ops:log"}', '{"view_id":"ops:log","snapshot_id":42}'],
)
def test_corrupt_metadata_never_becomes_an_empty_history(tmp_path, content):
    seed(tmp_path, "one").write_text(content)
    with pytest.raises(nav.NavigationUnavailable):
        nav.navigation_page(root_dir=tmp_path, view_id="ops:log")


def test_concurrency_has_no_wait_queue(tmp_path):
    assert nav._READERS.acquire(False) and nav._READERS.acquire(False)
    try:
        with pytest.raises(nav.NavigationUnavailable):
            nav.navigation_page(root_dir=tmp_path, view_id="ops:log")
    finally:
        nav._READERS.release()
        nav._READERS.release()


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 101},
        {"before": "!"},
        {"selected": "../secret"},
        {"start": "bad"},
        {"start": "2026-09-10", "end": "2026-09-09"},
    ],
)
def test_invalid_queries(client, query):
    assert (
        client.get(
            "/history/navigation", params={"view": "ops:log", **query}
        ).status_code
        == 400
    )


def test_permissions_and_no_live_mutation(client, tmp_path, monkeypatch):
    store.set_artifact(obj="live", kind="text", view_id="ops:log")
    snap = write_snapshot(root_dir=tmp_path, view_id="ops:log", kind="text", obj="old")
    before = store.get_status(view_id="ops:log")
    revision = store.get_render_revision(view_id="ops:log")
    page = client.get("/history/navigation?view=ops:log").json()
    assert page["count"] == 1
    assert (
        client.get(
            "/artifact", params={"view": "ops:log", "snapshot": snap.snapshot_id}
        ).status_code
        == 200
    )
    assert store.get_status(view_id="ops:log") == before
    assert store.get_render_revision(view_id="ops:log") == revision
    with TestClient(app_mod.app, client=("192.0.2.1", 50000)) as remote:
        assert remote.get("/history/navigation?view=ops:log").status_code == 403
    monkeypatch.setattr(config, "get_history_local_only", lambda: False)
    with TestClient(app_mod.app, client=("192.0.2.1", 50000)) as remote:
        assert remote.get("/history/navigation?view=ops:log").status_code == 200


@pytest.mark.parametrize("reason", ["disabled", "not-admitted", "stream"])
def test_unavailable_storage_never_scans(client, monkeypatch, reason):
    if reason == "disabled":
        monkeypatch.setattr(config, "get_storage_enabled", lambda: False)
    elif reason == "not-admitted":
        monkeypatch.setattr(config, "get_storage_view_enabled", lambda *a, **k: False)
    else:
        store.register_view(view_id="ops:log", kind="stream")
    monkeypatch.setattr(
        nav,
        "navigation_page",
        lambda **kw: pytest.fail("Unavailable storage must not scan"),
    )
    data = client.get("/history/navigation?view=ops:log").json()
    assert data["result"] == "unavailable"
    assert not data["capability"]["enabled"]


def test_missing_payload_corrupt_metadata_and_budget_http(
    client, tmp_path, monkeypatch
):
    snap = write_snapshot(root_dir=tmp_path, view_id="ops:log", kind="text", obj="old")
    Path(snap.path_payload).unlink()
    response = client.get(
        "/artifact", params={"view": "ops:log", "snapshot": snap.snapshot_id}
    )
    assert response.status_code == 404
    assert str(tmp_path) not in response.text
    Path(snap.path_meta).write_text("{")
    assert (
        client.get(
            "/artifact", params={"view": "ops:log", "snapshot": snap.snapshot_id}
        ).status_code
        == 404
    )
    assert client.get("/history/navigation?view=ops:log").status_code == 503


def test_snapshot_body_cannot_cross_colliding_logical_view_ids(client, tmp_path):
    snap = write_snapshot(
        root_dir=tmp_path, view_id="ops/log", kind="text", obj="private"
    )
    assert (
        client.get(
            "/artifact", params={"view": "ops:log", "snapshot": snap.snapshot_id}
        ).status_code
        == 404
    )
