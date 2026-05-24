from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import plotsrv.storage.backend as backend
from plotsrv.storage.models import SnapshotMeta


def test_ensure_storage_root_creates_directory(tmp_path: Path) -> None:
    root = tmp_path / "a" / "b" / "store"
    out = backend.ensure_storage_root(root)
    assert out.exists()
    assert out.is_dir()
    assert out == root.resolve()


def test_write_and_load_plot_snapshot_roundtrip(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\nabc"
    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="sec:plot1",
        kind="plot",
        obj=png,
        section="sec",
        label="plot1",
        extra={"x": 1},
    )

    assert meta.kind == "plot"
    assert meta.payload_format == "png"
    assert meta.payload_exists is True
    assert meta.extra == {"x": 1}

    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="sec:plot1",
        snapshot_id=meta.snapshot_id,
    )
    assert loaded.meta.snapshot_id == meta.snapshot_id
    assert loaded.obj == png


def test_write_and_load_table_snapshot_roundtrip(tmp_path: Path) -> None:
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="etl:table1",
        kind="table",
        obj=df,
        section="etl",
        label="table1",
    )

    assert meta.kind == "table"
    assert meta.payload_format == "csv"

    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="etl:table1",
        snapshot_id=meta.snapshot_id,
    )
    assert isinstance(loaded.obj, pd.DataFrame)
    assert loaded.obj.to_dict(orient="records") == df.to_dict(orient="records")


def test_write_and_load_json_snapshot_roundtrip(tmp_path: Path) -> None:
    obj = {"a": 1, "b": ["x", 2]}

    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="etl:json1",
        kind="json",
        obj=obj,
    )

    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="etl:json1",
        snapshot_id=meta.snapshot_id,
    )
    assert loaded.obj == obj


def test_write_and_load_traceback_snapshot_roundtrip(tmp_path: Path) -> None:
    obj = {
        "type": "traceback",
        "exc_type": "ValueError",
        "exc_msg": "bad",
        "frames": [
            {
                "filename": "a.py",
                "lineno": 10,
                "function": "fn",
                "line": "raise ValueError()",
                "context_before": ["x = 1"],
                "context_after": ["y = 2"],
            }
        ],
    }

    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="ops:error",
        kind="traceback",
        obj=obj,
        section="ops",
        label="error",
    )

    assert meta.kind == "traceback"
    assert meta.payload_format == "json"
    assert meta.payload_filename.endswith("__payload.json")

    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="ops:error",
        snapshot_id=meta.snapshot_id,
    )

    assert loaded.obj == obj


def test_write_and_load_exception_snapshot_alias_roundtrip(tmp_path: Path) -> None:
    obj = {
        "type": "traceback",
        "exc_type": "RuntimeError",
        "exc_msg": "legacy",
        "frames": [],
    }

    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="ops:error",
        kind="exception",
        obj=obj,
    )

    assert meta.kind == "exception"
    assert meta.payload_format == "json"

    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="ops:error",
        snapshot_id=meta.snapshot_id,
    )

    assert loaded.obj == obj


def test_write_and_load_markdown_python_and_text_fallback_roundtrip(
    tmp_path: Path,
) -> None:
    md = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="docs:md1",
        kind="markdown",
        obj="# Hello",
    )
    py = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="code:py1",
        kind="python",
        obj="print('hi')",
    )
    txt = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="misc:text1",
        kind="text",
        obj="plain text",
    )

    assert (
        backend.load_snapshot(
            root_dir=tmp_path, view_id="docs:md1", snapshot_id=md.snapshot_id
        ).obj
        == "# Hello"
    )
    assert (
        backend.load_snapshot(
            root_dir=tmp_path, view_id="code:py1", snapshot_id=py.snapshot_id
        ).obj
        == "print('hi')"
    )
    assert (
        backend.load_snapshot(
            root_dir=tmp_path, view_id="misc:text1", snapshot_id=txt.snapshot_id
        ).obj
        == "plain text"
    )


def test_write_and_load_html_string_roundtrip(tmp_path: Path) -> None:
    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="ui:html1",
        kind="html",
        obj="<div>hello</div>",
    )

    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="ui:html1",
        snapshot_id=meta.snapshot_id,
    )
    assert loaded.obj == "<div>hello</div>"


def test_write_and_load_html_dict_roundtrip(tmp_path: Path) -> None:
    obj = {"html": "<div>hello</div>", "meta": {"x": 1}}

    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="ui:htmljson",
        kind="html",
        obj=obj,
    )

    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="ui:htmljson",
        snapshot_id=meta.snapshot_id,
    )
    assert loaded.obj == obj
    assert meta.payload_format == "json"


def test_write_and_load_image_roundtrip(tmp_path: Path) -> None:
    raw = b"\x89PNG\r\n\x1a\nfake"
    obj = {
        "mime": "image/png",
        "data_b64": base64.b64encode(raw).decode("ascii"),
    }

    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="img:one",
        kind="image",
        obj=obj,
    )
    loaded = backend.load_snapshot(
        root_dir=tmp_path,
        view_id="img:one",
        snapshot_id=meta.snapshot_id,
    )

    assert isinstance(loaded.obj, dict)
    assert loaded.obj["mime"] == "image/png"
    assert base64.b64decode(loaded.obj["data_b64"].encode("ascii")) == raw


def test_write_snapshot_and_prune_keeps_latest_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = iter(
        [
            "20260101T000000.000001Z",
            "20260101T000000.000002Z",
            "20260101T000000.000003Z",
        ]
    )
    monkeypatch.setattr(backend, "_new_snapshot_id", lambda: next(ids))

    written1, pruned1 = backend.write_snapshot_and_prune(
        root_dir=tmp_path,
        view_id="v1",
        kind="text",
        obj="a",
        keep_last=2,
    )
    written2, pruned2 = backend.write_snapshot_and_prune(
        root_dir=tmp_path,
        view_id="v1",
        kind="text",
        obj="b",
        keep_last=2,
    )
    written3, pruned3 = backend.write_snapshot_and_prune(
        root_dir=tmp_path,
        view_id="v1",
        kind="text",
        obj="c",
        keep_last=2,
    )

    assert pruned1 == []
    assert pruned2 == []
    assert [x.snapshot_id for x in pruned3] == [written1.snapshot_id]

    snaps = backend.list_snapshots(root_dir=tmp_path, view_id="v1")
    assert [s.snapshot_id for s in snaps] == [
        written3.snapshot_id,
        written2.snapshot_id,
    ]


def test_list_snapshots_ignores_bad_meta_json(tmp_path: Path) -> None:
    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        kind="text",
        obj="ok",
    )
    view_dir = tmp_path / backend._slug_view_id("v1")
    (view_dir / "bad__meta.json").write_text("{not json", encoding="utf-8")

    snaps = backend.list_snapshots(root_dir=tmp_path, view_id="v1")
    assert [s.snapshot_id for s in snaps] == [meta.snapshot_id]


def test_load_snapshot_missing_meta_raises_lookup_error(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="Snapshot not found"):
        backend.load_snapshot(
            root_dir=tmp_path,
            view_id="v1",
            snapshot_id="20260101T000000.000001Z",
        )


def test_load_snapshot_invalid_meta_raises_lookup_error(tmp_path: Path) -> None:
    view_dir = tmp_path / backend._slug_view_id("v1")
    view_dir.mkdir(parents=True)
    meta_path = view_dir / "20260101T000000.000001Z__meta.json"
    meta_path.write_text("[]", encoding="utf-8")

    with pytest.raises(LookupError, match="Snapshot metadata invalid"):
        backend.load_snapshot(
            root_dir=tmp_path,
            view_id="v1",
            snapshot_id="20260101T000000.000001Z",
        )


def test_load_snapshot_missing_payload_raises_lookup_error(tmp_path: Path) -> None:
    view_dir = tmp_path / backend._slug_view_id("v1")
    view_dir.mkdir(parents=True)

    snap_id = "20260101T000000.000001Z"
    meta_path = view_dir / f"{snap_id}__meta.json"
    raw = {
        "snapshot_id": snap_id,
        "view_id": "v1",
        "section": None,
        "label": None,
        "kind": "text",
        "created_at": "2026-01-01T00:00:00+00:00",
        "payload_filename": f"{snap_id}__payload.txt",
        "payload_format": "text",
        "size_bytes": 0,
        "path_payload": str(view_dir / f"{snap_id}__payload.txt"),
        "path_meta": str(meta_path),
        "payload_exists": False,
        "extra": {},
    }
    meta_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(LookupError, match="Snapshot payload missing"):
        backend.load_snapshot(root_dir=tmp_path, view_id="v1", snapshot_id=snap_id)


def test_delete_snapshot_uses_meta_payload_path(tmp_path: Path) -> None:
    meta = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        kind="text",
        obj="hello",
    )

    removed = backend.delete_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        snapshot_id=meta.snapshot_id,
    )
    assert removed is True

    snaps = backend.list_snapshots(root_dir=tmp_path, view_id="v1")
    assert snaps == []


def test_delete_snapshot_falls_back_to_payload_glob_when_meta_unreadable(
    tmp_path: Path,
) -> None:
    view_id = "v1"
    view_dir = tmp_path / backend._slug_view_id(view_id)
    view_dir.mkdir(parents=True)

    snap_id = "20260101T000000.000001Z"
    payload_path = view_dir / f"{snap_id}__payload.txt"
    meta_path = view_dir / f"{snap_id}__meta.json"
    payload_path.write_text("hello", encoding="utf-8")
    meta_path.write_text("{broken", encoding="utf-8")

    removed = backend.delete_snapshot(
        root_dir=tmp_path,
        view_id=view_id,
        snapshot_id=snap_id,
    )
    assert removed is True
    assert not payload_path.exists()
    assert not meta_path.exists()


def test_delete_all_snapshots_for_view_removes_files_and_directory(
    tmp_path: Path,
) -> None:
    backend.write_snapshot(root_dir=tmp_path, view_id="v1", kind="text", obj="a")
    backend.write_snapshot(root_dir=tmp_path, view_id="v1", kind="text", obj="b")

    removed = backend.delete_all_snapshots_for_view(root_dir=tmp_path, view_id="v1")
    assert removed == 4  # 2 payload + 2 meta

    view_dir = tmp_path / backend._slug_view_id("v1")
    assert not view_dir.exists()


def test_delete_all_snapshots_for_missing_view_returns_zero(tmp_path: Path) -> None:
    assert (
        backend.delete_all_snapshots_for_view(root_dir=tmp_path, view_id="missing") == 0
    )


def test_prune_snapshots_keep_last_none_returns_empty(tmp_path: Path) -> None:
    s1 = backend.write_snapshot(root_dir=tmp_path, view_id="v1", kind="text", obj="a")
    s2 = backend.write_snapshot(root_dir=tmp_path, view_id="v1", kind="text", obj="b")
    snaps = [s1, s2]

    pruned = backend.prune_snapshots(
        root_dir=tmp_path,
        view_id="v1",
        snapshots=snaps,
        keep_last=None,
    )
    assert pruned == []


def test_get_storage_stats_and_list_stored_views(tmp_path: Path) -> None:
    backend.write_snapshot(
        root_dir=tmp_path,
        view_id="etl:one",
        kind="text",
        obj="aaa",
    )
    backend.write_snapshot(
        root_dir=tmp_path,
        view_id="etl:one",
        kind="text",
        obj="bbb",
    )
    backend.write_snapshot(
        root_dir=tmp_path,
        view_id="ops:two",
        kind="json",
        obj={"x": 1},
    )

    orphan_dir = tmp_path / "orphan_dir"
    orphan_dir.mkdir()

    stats = backend.get_storage_stats(root_dir=tmp_path)
    assert stats["view_count"] == 3
    assert stats["snapshot_count"] == 3
    assert stats["total_bytes"] > 0

    views = backend.list_stored_views(root_dir=tmp_path)
    ids = [v["view_id"] for v in views]
    assert "etl:one" in ids
    assert "ops:two" in ids
    assert "orphan_dir" in ids

    etl = next(v for v in views if v["view_id"] == "etl:one")
    assert etl["snapshot_count"] == 2
    assert etl["total_bytes"] > 0


def test_list_stored_views_ignores_malformed_meta_but_keeps_orphan_dir(
    tmp_path: Path,
) -> None:
    child = tmp_path / "weird"
    child.mkdir()
    (child / "broken__meta.json").write_text("{oops", encoding="utf-8")

    views = backend.list_stored_views(root_dir=tmp_path)
    assert views == [
        {
            "view_id": "weird",
            "snapshot_count": 0,
            "total_bytes": 0,
            "last_created_at": None,
        }
    ]


def test_delete_all_snapshots_removes_all_files_for_all_views(tmp_path: Path) -> None:
    backend.write_snapshot(root_dir=tmp_path, view_id="v1", kind="text", obj="a")
    backend.write_snapshot(root_dir=tmp_path, view_id="v2", kind="text", obj="b")

    removed = backend.delete_all_snapshots(root_dir=tmp_path)
    assert removed == 4

    assert backend.list_stored_views(root_dir=tmp_path) == []


def test_internal_helpers_cover_edge_cases() -> None:
    assert backend._slug_view_id(" etl:import / weird ") == "etl__import__weird"
    assert backend._slug_view_id("...") == "default"

    iso = backend._snapshot_id_to_iso("20260101T010203.123456Z")
    assert iso.startswith("2026-01-01T01:02:03.123456+00:00")

    iso_bad = backend._snapshot_id_to_iso("not-a-snapshot-id")
    assert "T" in iso_bad

    assert backend._suffix_from_mime("image/png") == "png"
    assert backend._suffix_from_mime("image/jpeg") == "jpg"
    assert backend._suffix_from_mime("application/x-odd") == "bin"


def test_serialise_payload_type_errors() -> None:
    with pytest.raises(TypeError, match="plot snapshots expect PNG bytes"):
        backend._serialise_payload(kind="plot", obj="not bytes")

    with pytest.raises(TypeError, match="table snapshots expect pandas DataFrame"):
        backend._serialise_payload(kind="table", obj={"a": 1})


def test_write_bytes_atomic_and_write_json_atomic(tmp_path: Path) -> None:
    p1 = tmp_path / "x.bin"
    p2 = tmp_path / "y.json"

    backend._write_bytes_atomic(p1, b"abc")
    backend._write_json_atomic(p2, {"a": 1})

    assert p1.read_bytes() == b"abc"
    assert json.loads(p2.read_text(encoding="utf-8")) == {"a": 1}


def test_meta_from_dict_coerces_defaults() -> None:
    meta = backend._meta_from_dict({"snapshot_id": "s1", "view_id": "v1"})
    assert isinstance(meta, SnapshotMeta)
    assert meta.snapshot_id == "s1"
    assert meta.view_id == "v1"
    assert meta.kind == "artifact"
    assert meta.size_bytes == 0
    assert meta.extra is None


def test_snapshot_backend_roundtrips_all_artifact_kinds(tmp_path: Path) -> None:
    raw = b"\x89PNG\r\n\x1a\nfake"

    cases: list[tuple[str, Any]] = [
        ("text", "hello"),
        ("json", {"a": 1}),
        ("markdown", "# Hello"),
        ("html", {"html": "<div>Hello</div>", "unsafe": True}),
        (
            "image",
            {"mime": "image/png", "data_b64": base64.b64encode(raw).decode("ascii")},
        ),
        ("python", "print('hi')"),
        (
            "traceback",
            {
                "type": "traceback",
                "exc_type": "ValueError",
                "exc_msg": "bad",
                "frames": [],
            },
        ),
    ]

    for kind, obj in cases:
        view_id = f"case:{kind}"
        meta = backend.write_snapshot(
            root_dir=tmp_path,
            view_id=view_id,
            kind=kind,
            obj=obj,
        )
        loaded = backend.load_snapshot(
            root_dir=tmp_path,
            view_id=view_id,
            snapshot_id=meta.snapshot_id,
        )

        if kind == "image":
            assert isinstance(loaded.obj, dict)
            assert loaded.obj["mime"] == "image/png"
        else:
            assert loaded.obj == obj


def test_snapshot_listing_ignores_latest_directory(tmp_path: Path) -> None:
    latest_dir = tmp_path / "latest" / "etl__orders"
    latest_dir.mkdir(parents=True)
    (latest_dir / "latest__meta.json").write_text("{}", encoding="utf-8")

    snap = backend.write_snapshot(
        root_dir=tmp_path,
        view_id="etl:orders",
        kind="text",
        obj="hello",
    )

    snaps = backend.list_snapshots(root_dir=tmp_path, view_id="etl:orders")

    assert [s.snapshot_id for s in snaps] == [snap.snapshot_id]


def test_storage_stats_ignores_latest_directory(tmp_path: Path) -> None:
    latest_dir = tmp_path / "latest" / "etl__orders"
    latest_dir.mkdir(parents=True)
    (latest_dir / "latest__meta.json").write_text("{}", encoding="utf-8")
    (latest_dir / "latest__payload.txt").write_text("hello", encoding="utf-8")

    stats = backend.get_storage_stats(root_dir=tmp_path)
    assert stats["view_count"] == 0
    assert stats["snapshot_count"] == 0
