from __future__ import annotations

import base64

import pandas as pd
import pytest

import plotsrv.storage.policy as policy
from plotsrv.storage.models import SnapshotMeta


def _snap(snapshot_id: str) -> SnapshotMeta:
    return SnapshotMeta(
        snapshot_id=snapshot_id,
        view_id="v1",
        section="sec",
        label="lab",
        kind="text",
        created_at="2026-01-01T00:00:00+00:00",
        payload_filename=f"{snapshot_id}__payload.txt",
        payload_format="text",
        size_bytes=10,
        path_payload="/tmp/payload.txt",
        path_meta="/tmp/meta.json",
        payload_exists=True,
        extra=None,
    )


def test_should_store_snapshot_rejects_when_storage_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy.config, "get_storage_keep_last", lambda _v: 2)
    monkeypatch.setattr(
        policy.config, "get_storage_min_store_interval_s", lambda _v: None
    )
    monkeypatch.setattr(
        policy.config, "get_storage_max_snapshot_size_bytes", lambda _v: 1000
    )
    monkeypatch.setattr(
        policy.config,
        "get_storage_view_enabled",
        lambda _v, source=None: False,
    )

    dec = policy.should_store_snapshot(
        view_id="v1",
        payload_size_bytes=10,
        existing_snapshots=[],
        source="watch",
    )
    assert dec.accepted is False
    assert dec.reason == "storage_disabled"
    assert dec.keep_last == 2
    assert dec.max_snapshot_size_bytes == 1000


def test_should_store_snapshot_rejects_when_payload_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy.config, "get_storage_keep_last", lambda _v: 3)
    monkeypatch.setattr(
        policy.config, "get_storage_min_store_interval_s", lambda _v: None
    )
    monkeypatch.setattr(
        policy.config, "get_storage_max_snapshot_size_bytes", lambda _v: 5
    )
    monkeypatch.setattr(
        policy.config,
        "get_storage_view_enabled",
        lambda _v, source=None: True,
    )

    dec = policy.should_store_snapshot(
        view_id="v1",
        payload_size_bytes=6,
        existing_snapshots=[],
    )
    assert dec.accepted is False
    assert dec.reason == "payload_too_large"


def test_should_store_snapshot_rejects_on_min_store_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy.config, "get_storage_keep_last", lambda _v: 2)
    monkeypatch.setattr(
        policy.config, "get_storage_min_store_interval_s", lambda _v: 60
    )
    monkeypatch.setattr(
        policy.config, "get_storage_max_snapshot_size_bytes", lambda _v: 1000
    )
    monkeypatch.setattr(
        policy.config,
        "get_storage_view_enabled",
        lambda _v, source=None: True,
    )
    monkeypatch.setattr(
        policy, "_new_snapshot_id_like_now", lambda: "20260101T000030.000000Z"
    )

    dec = policy.should_store_snapshot(
        view_id="v1",
        payload_size_bytes=10,
        existing_snapshots=[_snap("20260101T000000.000000Z")],
    )
    assert dec.accepted is False
    assert dec.reason == "min_store_interval"


def test_should_store_snapshot_accepts_when_checks_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy.config, "get_storage_keep_last", lambda _v: None)
    monkeypatch.setattr(
        policy.config, "get_storage_min_store_interval_s", lambda _v: 60
    )
    monkeypatch.setattr(
        policy.config, "get_storage_max_snapshot_size_bytes", lambda _v: 1000
    )
    monkeypatch.setattr(
        policy.config,
        "get_storage_view_enabled",
        lambda _v, source=None: True,
    )
    monkeypatch.setattr(
        policy, "_new_snapshot_id_like_now", lambda: "20260101T000200.000000Z"
    )

    dec = policy.should_store_snapshot(
        view_id="v1",
        payload_size_bytes=100,
        existing_snapshots=[_snap("20260101T000000.000000Z")],
    )
    assert dec.accepted is True
    assert dec.reason == "accepted"
    assert dec.keep_last is None


def test_should_store_snapshot_accepts_when_snapshot_id_parse_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy.config, "get_storage_keep_last", lambda _v: 2)
    monkeypatch.setattr(
        policy.config, "get_storage_min_store_interval_s", lambda _v: 60
    )
    monkeypatch.setattr(
        policy.config, "get_storage_max_snapshot_size_bytes", lambda _v: 1000
    )
    monkeypatch.setattr(
        policy.config,
        "get_storage_view_enabled",
        lambda _v, source=None: True,
    )
    monkeypatch.setattr(policy, "_new_snapshot_id_like_now", lambda: "bad-id-too")

    dec = policy.should_store_snapshot(
        view_id="v1",
        payload_size_bytes=10,
        existing_snapshots=[_snap("bad-id-one")],
    )
    assert dec.accepted is True
    assert dec.reason == "accepted"


def test_snapshots_to_prune_respects_keep_last(monkeypatch: pytest.MonkeyPatch) -> None:
    snaps = [
        _snap("20260101T000001.000000Z"),
        _snap("20260101T000003.000000Z"),
        _snap("20260101T000002.000000Z"),
    ]

    monkeypatch.setattr(policy.config, "get_storage_keep_last", lambda _v: 2)
    pruned = policy.snapshots_to_prune(view_id="v1", snapshots=snaps)

    assert [s.snapshot_id for s in pruned] == ["20260101T000001.000000Z"]


def test_snapshots_to_prune_with_infinite_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy.config, "get_storage_keep_last", lambda _v: None)
    assert policy.snapshots_to_prune(view_id="v1", snapshots=[_snap("x")]) == []


def test_estimate_payload_size_bytes_for_plot_table_json_image_and_fallbacks() -> None:
    assert policy.estimate_payload_size_bytes(kind="plot", obj=b"abcdef") == 6

    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    assert policy.estimate_payload_size_bytes(kind="table", obj=df) > 0

    j = {"a": 1, "b": [1, 2]}
    assert policy.estimate_payload_size_bytes(kind="json", obj=j) > 0

    raw = b"abcdef"
    obj = {"data_b64": base64.b64encode(raw).decode("ascii")}
    est = policy.estimate_payload_size_bytes(kind="image", obj=obj)
    assert est >= 1

    assert policy.estimate_payload_size_bytes(kind="text", obj=b"xyz") == 3
    assert policy.estimate_payload_size_bytes(kind="text", obj="hello") == len(
        "hello".encode("utf-8")
    )


def test_estimate_payload_size_bytes_json_and_table_fallback_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BadStr:
        def __str__(self) -> str:
            return "fallback"

    class BoomDF:
        def to_csv(self, index: bool = False) -> str:
            raise RuntimeError("boom")

    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))

    size_json = policy.estimate_payload_size_bytes(kind="json", obj=set([1, 2]))
    assert size_json > 0

    # non-DataFrame table object falls back to str length
    size_table = policy.estimate_payload_size_bytes(kind="table", obj=BoomDF())
    assert size_table == len(str(BoomDF()).encode("utf-8"))

    assert policy._len_str_fallback(BadStr()) == len("fallback".encode("utf-8"))


def test_latest_snapshot_and_seconds_between_ids_helpers() -> None:
    s1 = _snap("20260101T000001.000000Z")
    s2 = _snap("20260101T000010.000000Z")
    assert policy._latest_snapshot([s1, s2]) == s2
    assert policy._latest_snapshot([]) is None

    assert (
        policy._seconds_between_snapshot_ids(
            "20260101T000001.000000Z",
            "20260101T000011.000000Z",
        )
        == 10
    )

    assert (
        policy._seconds_between_snapshot_ids("bad", "20260101T000011.000000Z") is None
    )
    assert policy._parse_snapshot_id("bad") is None
    assert isinstance(policy._new_snapshot_id_like_now(), str)
