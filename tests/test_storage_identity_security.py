import json
from pathlib import Path

import pytest

from plotsrv.storage import backend
from plotsrv.storage.latest import FileLatestStateBackend
from plotsrv.storage.navigation import navigation_page


def test_colliding_view_names_have_independent_snapshots_latest_and_pruning(tmp_path):
    latest = FileLatestStateBackend(root_dir=tmp_path)
    ids = ["a:b", "a/b", "a__b", ".a:b."]
    for view in ids:
        backend.write_snapshot(root_dir=tmp_path, view_id=view, kind="text", obj=view)
        latest.write_latest(view_id=view, kind="text", obj=view)
    for view in ids:
        snapshots = backend.list_snapshots(root_dir=tmp_path, view_id=view)
        assert [s.view_id for s in snapshots] == [view]
        assert latest.load_latest(view_id=view).obj == view
    backend.delete_all_snapshots_for_view(root_dir=tmp_path, view_id=ids[0])
    latest.delete_latest(view_id=ids[0])
    for view in ids[1:]:
        assert backend.list_snapshots(root_dir=tmp_path, view_id=view)
        assert latest.load_latest(view_id=view).obj == view


def test_legacy_collision_remains_readable_without_cross_view_deletion(tmp_path):
    legacy = tmp_path / backend._slug_view_id("a:b")
    legacy.mkdir()
    snapshots = {}
    for view in ["a:b", "a/b"]:
        snap = backend.write_snapshot(root_dir=tmp_path, view_id=view, kind="text", obj=view)
        snapshots[view] = snap
        for path in Path(snap.path_meta).parent.iterdir():
            path.rename(legacy / path.name)
    for view, snap in snapshots.items():
        assert backend.load_snapshot(root_dir=tmp_path, view_id=view, snapshot_id=snap.snapshot_id).obj == view
        assert navigation_page(root_dir=tmp_path, view_id=view)["count"] == 1
    backend.delete_all_snapshots_for_view(root_dir=tmp_path, view_id="a:b")
    other = snapshots["a/b"]
    assert backend.load_snapshot(root_dir=tmp_path, view_id="a/b", snapshot_id=other.snapshot_id).obj == "a/b"


def test_legacy_latest_requires_exact_identity_and_new_write_wins(tmp_path):
    latest = FileLatestStateBackend(root_dir=tmp_path)
    meta = latest.write_latest(view_id="a:b", kind="text", obj="old")
    Path(meta.path_meta).parent.rename(latest.latest_root / backend._slug_view_id("a:b"))
    assert latest.load_latest(view_id="a:b").obj == "old"
    with pytest.raises(LookupError):
        latest.load_latest(view_id="a/b")
    assert latest.delete_latest(view_id="a/b") is False
    latest.write_latest(view_id="a:b", kind="text", obj="new")
    assert latest.load_latest(view_id="a:b").obj == "new"
    assert len(latest.list_latest()) == 1
    assert latest.delete_latest(view_id="a:b") is True
    with pytest.raises(LookupError):
        latest.load_latest(view_id="a:b")


@pytest.mark.parametrize("tamper_filename", [False, True])
def test_metadata_cannot_redirect_payload_reads_or_deletions(tmp_path, tamper_filename):
    private = tmp_path / "private.txt"
    private.write_text("private fixture")
    snap = backend.write_snapshot(root_dir=tmp_path, view_id="v", kind="text", obj="public fixture")
    metadata = Path(snap.path_meta)
    raw = json.loads(metadata.read_text())
    raw["path_payload"] = str(private)
    raw["path_meta"] = str(private)
    if tamper_filename:
        raw["payload_filename"] = "../private.txt"
    metadata.write_text(json.dumps(raw))
    if tamper_filename:
        with pytest.raises(LookupError):
            backend.load_snapshot(root_dir=tmp_path, view_id="v", snapshot_id=snap.snapshot_id)
    else:
        assert backend.load_snapshot(root_dir=tmp_path, view_id="v", snapshot_id=snap.snapshot_id).obj == "public fixture"
    backend.delete_snapshot(root_dir=tmp_path, view_id="v", snapshot_id=snap.snapshot_id)
    assert private.read_text() == "private fixture"
