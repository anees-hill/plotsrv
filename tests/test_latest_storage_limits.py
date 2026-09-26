from types import SimpleNamespace

import pytest

from plotsrv import config
from plotsrv.storage import worker
from plotsrv.storage.latest import FileLatestStateBackend, LatestPayloadTooLarge


def test_latest_size_limit_preserves_previous_state(tmp_path):
    backend = FileLatestStateBackend(root_dir=tmp_path)
    backend.write_latest(view_id="v", kind="text", obj="old")
    with pytest.raises(LatestPayloadTooLarge):
        backend.write_latest(view_id="v", kind="text", obj="longer value", max_payload_bytes=5)
    assert backend.load_latest(view_id="v").obj == "old"


def test_latest_limits_are_separate_from_snapshot_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_storage_latest_enabled", lambda: True)
    monkeypatch.setattr(config, "get_storage_latest_max_bytes", lambda: 10)
    monkeypatch.setattr(config, "get_storage_latest_min_interval_s", lambda: 5.0)
    monkeypatch.setattr(config, "get_storage_latest_view_enabled", lambda vid: vid != "excluded")
    monkeypatch.setattr(worker, "should_store_snapshot", lambda **kw: SimpleNamespace(accepted=False))
    clock = [10.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    process = worker.StorageWorker()
    latest = FileLatestStateBackend(root_dir=tmp_path)
    def persist(value, view="v"):
        process._process_task(worker.StorageTask(view_id=view, kind="text", obj=value))
    persist("first")
    clock[0] = 11.0
    persist("second")
    assert latest.load_latest(view_id="v").obj == "first"
    clock[0] = 16.0
    persist("third")
    assert latest.load_latest(view_id="v").obj == "third"
    clock[0] = 22.0
    persist("x" * 11)
    persist("hidden", view="excluded")
    assert latest.load_latest(view_id="v").obj == "third"
    with pytest.raises(LookupError):
        latest.load_latest(view_id="excluded")
    assert process.stats()["latest_skipped"] == 3


def test_queue_estimate_counts_nested_data_and_handles_cycles():
    payload = {"rows": [{"text": "x" * 1000}]}
    assert worker._estimate_storage_task_bytes(payload, limit=100) > 100
    recursive = []
    recursive.append(recursive)
    assert 0 < worker._estimate_storage_task_bytes(recursive) < 1000
