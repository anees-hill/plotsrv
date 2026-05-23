from __future__ import annotations

from typing import Any

import pytest

from plotsrv.storage.latest import LatestStateBackend
from plotsrv.storage.models import LatestMeta, LoadedLatest


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
