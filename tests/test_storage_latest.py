from __future__ import annotations

from typing import Any

import pytest
from pathlib import Path

import base64
import pandas as pd

from plotsrv.storage.models import LatestMeta, LoadedLatest
from plotsrv.storage.latest import (
    LatestStateBackend,
    FileLatestStateBackend,
    latest_meta_from_dict,
)


def test_latest_meta_holds_latest_state_metadata() -> None:
    meta = LatestMeta(
        view_id="etl:orders",
        section="etl",
        label="orders",
        kind="table",
        updated_at="2026-01-01T00:00:00+00:00",
        payload_filename="latest__payload.csv",
        payload_format="csv",
        size_bytes=123,
        path_payload="/tmp/store/latest/etl__orders/latest__payload.csv",
        path_meta="/tmp/store/latest/etl__orders/latest__meta.json",
        payload_exists=True,
        extra={"total_rows": 10},
    )

    assert meta.view_id == "etl:orders"
    assert meta.section == "etl"
    assert meta.label == "orders"
    assert meta.kind == "table"
    assert meta.updated_at == "2026-01-01T00:00:00+00:00"
    assert meta.payload_exists is True
    assert meta.extra == {"total_rows": 10}


def test_loaded_latest_pairs_meta_and_object() -> None:
    meta = LatestMeta(
        view_id="ops:status",
        section="ops",
        label="status",
        kind="json",
        updated_at="2026-01-01T00:00:00+00:00",
        payload_filename="latest__payload.json",
        payload_format="json",
        size_bytes=20,
        path_payload="/tmp/latest__payload.json",
        path_meta="/tmp/latest__meta.json",
    )

    loaded = LoadedLatest(meta=meta, obj={"status": "ok"})

    assert loaded.meta is meta
    assert loaded.obj == {"status": "ok"}


class FakeLatestBackend:
    def __init__(self) -> None:
        self._items: dict[str, LoadedLatest] = {}

    def write_latest(
        self,
        *,
        view_id: str,
        kind: str,
        obj: Any,
        section: str | None = None,
        label: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> LatestMeta:
        meta = LatestMeta(
            view_id=view_id,
            section=section,
            label=label,
            kind=kind,
            updated_at="2026-01-01T00:00:00+00:00",
            payload_filename="latest__payload.txt",
            payload_format="text",
            size_bytes=len(str(obj).encode("utf-8")),
            path_payload="/tmp/latest__payload.txt",
            path_meta="/tmp/latest__meta.json",
            extra=extra,
        )
        self._items[view_id] = LoadedLatest(meta=meta, obj=obj)
        return meta

    def load_latest(self, *, view_id: str) -> LoadedLatest:
        try:
            return self._items[view_id]
        except KeyError:
            raise LookupError(view_id)

    def list_latest(self) -> list[LatestMeta]:
        return [x.meta for x in self._items.values()]

    def delete_latest(self, *, view_id: str) -> bool:
        return self._items.pop(view_id, None) is not None


def test_latest_state_backend_protocol_shape() -> None:
    backend = FakeLatestBackend()

    assert isinstance(backend, LatestStateBackend)

    meta = backend.write_latest(
        view_id="demo:message",
        kind="text",
        obj="hello",
        section="demo",
        label="message",
    )

    assert meta.view_id == "demo:message"

    loaded = backend.load_latest(view_id="demo:message")
    assert loaded.obj == "hello"

    assert backend.list_latest() == [meta]
    assert backend.delete_latest(view_id="demo:message") is True

    with pytest.raises(LookupError):
        backend.load_latest(view_id="demo:message")


def test_file_latest_backend_writes_under_latest_layout(tmp_path: Path) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    meta = backend.write_latest(
        view_id="etl:orders",
        kind="text",
        obj="hello",
        section="etl",
        label="orders",
        extra={"source": "test"},
    )

    latest_dir = tmp_path / "latest" / "etl__orders"

    assert latest_dir.exists()
    assert (latest_dir / "latest__meta.json").exists()
    assert (latest_dir / "latest__payload.txt").exists()

    assert meta.view_id == "etl:orders"
    assert meta.section == "etl"
    assert meta.label == "orders"
    assert meta.kind == "text"
    assert meta.payload_filename == "latest__payload.txt"
    assert meta.payload_format == "text"
    assert meta.payload_exists is True
    assert meta.extra == {"source": "test"}


def test_file_latest_backend_loads_text_roundtrip(tmp_path: Path) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    meta = backend.write_latest(
        view_id="demo:message",
        kind="text",
        obj="hello",
        section="demo",
        label="message",
    )

    loaded = backend.load_latest(view_id="demo:message")

    assert loaded.meta.view_id == meta.view_id
    assert loaded.meta.updated_at == meta.updated_at
    assert loaded.obj == "hello"


def test_file_latest_backend_overwrites_latest_payload(tmp_path: Path) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    meta1 = backend.write_latest(
        view_id="demo:item",
        kind="text",
        obj="first",
    )
    meta2 = backend.write_latest(
        view_id="demo:item",
        kind="json",
        obj={"value": "second"},
    )

    latest_dir = tmp_path / "latest" / "demo__item"

    assert meta1.updated_at <= meta2.updated_at
    assert not (latest_dir / "latest__payload.txt").exists()
    assert (latest_dir / "latest__payload.json").exists()

    loaded = backend.load_latest(view_id="demo:item")
    assert loaded.meta.kind == "json"
    assert loaded.obj == {"value": "second"}


def test_file_latest_backend_lists_latest_views(tmp_path: Path) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    backend.write_latest(
        view_id="etl:orders",
        kind="text",
        obj="orders",
        section="etl",
        label="orders",
    )
    backend.write_latest(
        view_id="ops:health",
        kind="json",
        obj={"ok": True},
        section="ops",
        label="health",
    )

    latest = backend.list_latest()
    ids = {x.view_id for x in latest}

    assert ids == {"etl:orders", "ops:health"}


def test_file_latest_backend_delete_latest_removes_files_and_dir(
    tmp_path: Path,
) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    backend.write_latest(
        view_id="demo:item",
        kind="text",
        obj="hello",
    )

    view_dir = tmp_path / "latest" / "demo__item"
    assert view_dir.exists()

    assert backend.delete_latest(view_id="demo:item") is True
    assert not view_dir.exists()
    assert backend.delete_latest(view_id="demo:item") is False


def test_file_latest_backend_missing_latest_raises_lookup_error(
    tmp_path: Path,
) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    with pytest.raises(LookupError, match="Latest state not found"):
        backend.load_latest(view_id="missing:view")


def test_file_latest_backend_missing_payload_raises_lookup_error(
    tmp_path: Path,
) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    meta = backend.write_latest(
        view_id="demo:item",
        kind="text",
        obj="hello",
    )

    Path(meta.path_payload).unlink()

    with pytest.raises(LookupError, match="Latest state payload missing"):
        backend.load_latest(view_id="demo:item")


def test_file_latest_backend_list_ignores_bad_meta_json(tmp_path: Path) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    backend.write_latest(view_id="demo:ok", kind="text", obj="hello")

    bad_dir = tmp_path / "latest" / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "latest__meta.json").write_text("{not json", encoding="utf-8")

    latest = backend.list_latest()

    assert [x.view_id for x in latest] == ["demo:ok"]


def test_file_latest_backend_table_roundtrip(tmp_path: Path) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    meta = backend.write_latest(
        view_id="etl:table",
        kind="table",
        obj=df,
        section="etl",
        label="table",
        extra={"total_rows": 2},
    )

    loaded = backend.load_latest(view_id="etl:table")

    assert meta.payload_format == "csv"
    assert isinstance(loaded.obj, pd.DataFrame)
    assert loaded.obj.to_dict(orient="records") == df.to_dict(orient="records")
    assert loaded.meta.extra == {"total_rows": 2}


def test_file_latest_backend_image_roundtrip(tmp_path: Path) -> None:
    backend = FileLatestStateBackend(root_dir=tmp_path)

    raw = b"\x89PNG\r\n\x1a\nfake"
    obj = {
        "mime": "image/png",
        "data_b64": base64.b64encode(raw).decode("ascii"),
    }

    meta = backend.write_latest(
        view_id="img:one",
        kind="image",
        obj=obj,
    )

    loaded = backend.load_latest(view_id="img:one")

    assert meta.payload_format == "binary_image"
    assert isinstance(loaded.obj, dict)
    assert loaded.obj["mime"] == "image/png"
    assert base64.b64decode(loaded.obj["data_b64"].encode("ascii")) == raw


def test_latest_meta_from_dict_coerces_defaults() -> None:
    meta = latest_meta_from_dict({"view_id": "demo:item"})

    assert meta.view_id == "demo:item"
    assert meta.kind == "artifact"
    assert meta.size_bytes == 0
    assert meta.extra is None
