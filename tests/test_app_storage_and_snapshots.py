from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import plotsrv.app as app_mod
from plotsrv import config, store
from plotsrv.storage.backend import write_snapshot


@pytest.fixture(autouse=True)
def reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store.reset()
    config.set_table_view_mode("simple")
    monkeypatch.setattr(app_mod.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(app_mod.config, "get_control_local_only", lambda: False)
    monkeypatch.setattr(app_mod.config, "get_internal_read_local_only", lambda: False)
    yield
    store.reset()
    config.set_table_view_mode("simple")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app_mod.app)


def test_storage_root_helper_uses_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_mod.config, "get_storage_root_dir", lambda: tmp_path / "abc"
    )
    assert app_mod._storage_root() == (tmp_path / "abc")


def test_snapshot_summary_dict_maps_fields() -> None:
    snap = write_snapshot(
        root_dir=Path.cwd() / ".pytest_tmp_dontcare",
        view_id="ops:log",
        kind="text",
        obj="hello",
        section="ops",
        label="log",
        extra={"x": 1},
    )
    d = app_mod._snapshot_summary_dict(snap)
    assert d["snapshot_id"] == snap.snapshot_id
    assert d["view_id"] == "ops:log"
    assert d["section"] == "ops"
    assert d["label"] == "log"
    assert d["kind"] == "text"
    assert d["payload_exists"] is True
    assert d["extra"] == {"x": 1}


def test_load_snapshot_or_404_raises_http_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_mod.config, "get_storage_root_dir", lambda: tmp_path)
    with pytest.raises(app_mod.HTTPException) as e:
        app_mod._load_snapshot_or_404(view_id="missing", snapshot_id="nope")
    assert e.value.status_code == 404


def test_render_plot_snapshot_html_structure() -> None:
    out = app_mod._render_plot_snapshot_html(view_id="v1", snapshot_id="s1")
    assert out["kind"] == "plot"
    assert "/plot?view=v1&snapshot=s1" in out["html"]
    assert out["meta"]["src"] == "/plot?view=v1&snapshot=s1"
    assert out["meta"]["snapshot"] is True


def test_render_table_snapshot_html_structure() -> None:
    out = app_mod._render_table_snapshot_html(view_id="v1", snapshot_id="s1")
    assert out["kind"] == "table"
    assert 'id="table-grid"' in out["html"]
    assert out["meta"]["data_src"] == "/table/data?view=v1&snapshot=s1"
    assert out["meta"]["snapshot"] is True


def test_history_returns_empty_when_no_snapshots(client: TestClient) -> None:
    r = client.get("/history?view=v1")
    assert r.status_code == 200
    data = r.json()
    assert data["view_id"] == "v1"
    assert data["count"] == 0
    assert data["snapshots"] == []


def test_history_returns_written_snapshots(client: TestClient, tmp_path: Path) -> None:
    snap = write_snapshot(
        root_dir=tmp_path,
        view_id="ops:log",
        kind="text",
        obj="hello",
        section="ops",
        label="log",
    )
    r = client.get("/history?view=ops:log")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["snapshots"][0]["snapshot_id"] == snap.snapshot_id
    assert data["snapshots"][0]["kind"] == "text"


def test_get_plot_snapshot_400_when_snapshot_is_not_plot(
    client: TestClient, tmp_path: Path
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        kind="text",
        obj="hello",
    )
    r = client.get(f"/plot?view=v1&snapshot={snap.snapshot_id}")
    assert r.status_code == 400
    assert "is not a plot snapshot" in r.text


def test_get_plot_snapshot_500_when_payload_not_bytes(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        kind="plot",
        obj=b"\x89PNGfake",
    )

    class Loaded:
        def __init__(self, meta: Any) -> None:
            self.meta = meta
            self.obj = "not-bytes"

    monkeypatch.setattr(app_mod, "_load_snapshot_or_404", lambda **kwargs: Loaded(snap))
    r = client.get(f"/plot?view=v1&snapshot={snap.snapshot_id}")
    assert r.status_code == 500
    assert "not valid PNG bytes" in r.text


def test_get_plot_snapshot_download_sets_snapshot_filename(
    client: TestClient, tmp_path: Path
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        kind="plot",
        obj=b"\x89PNGfake",
    )
    r = client.get(f"/plot?view=v1&snapshot={snap.snapshot_id}&download=true")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert snap.snapshot_id in cd
    assert "attachment" in cd.lower()


def test_table_data_snapshot_400_when_not_table(
    client: TestClient, tmp_path: Path
) -> None:
    snap = write_snapshot(root_dir=tmp_path, view_id="v1", kind="text", obj="x")
    r = client.get(f"/table/data?view=v1&snapshot={snap.snapshot_id}")
    assert r.status_code == 400
    assert "is not a table snapshot" in r.text


def test_table_data_snapshot_500_when_payload_not_dataframe(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path, view_id="v1", kind="table", obj=pd.DataFrame({"a": [1]})
    )

    class Loaded:
        def __init__(self, meta: Any) -> None:
            self.meta = meta
            self.obj = {"not": "df"}

    monkeypatch.setattr(app_mod, "_load_snapshot_or_404", lambda **kwargs: Loaded(snap))
    r = client.get(f"/table/data?view=v1&snapshot={snap.snapshot_id}")
    assert r.status_code == 500
    assert "was not a DataFrame" in r.text


def test_table_data_snapshot_uses_meta_extra_counts(
    client: TestClient, tmp_path: Path
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        kind="table",
        obj=pd.DataFrame({"a": [1, 2, 3]}),
        extra={"total_rows": 99, "returned_rows": 77},
    )
    r = client.get(f"/table/data?view=v1&snapshot={snap.snapshot_id}&limit=2")
    assert r.status_code == 200
    data = r.json()
    assert data["total_rows"] == 99
    assert data["returned_rows"] == 77
    assert data["snapshot_id"] == snap.snapshot_id


def test_export_table_snapshot_400_when_not_table(
    client: TestClient, tmp_path: Path
) -> None:
    snap = write_snapshot(root_dir=tmp_path, view_id="v1", kind="text", obj="x")
    r = client.get(f"/table/export?view=v1&snapshot={snap.snapshot_id}")
    assert r.status_code == 400
    assert "is not a table snapshot" in r.text


def test_export_table_snapshot_500_when_payload_not_dataframe(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path, view_id="v1", kind="table", obj=pd.DataFrame({"a": [1]})
    )

    class Loaded:
        def __init__(self, meta: Any) -> None:
            self.meta = meta
            self.obj = "bad"

    monkeypatch.setattr(app_mod, "_load_snapshot_or_404", lambda **kwargs: Loaded(snap))
    r = client.get(f"/table/export?view=v1&snapshot={snap.snapshot_id}")
    assert r.status_code == 500
    assert "was not a DataFrame" in r.text


def test_export_table_snapshot_csv_attachment_name(
    client: TestClient, tmp_path: Path
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path,
        view_id="v1",
        kind="table",
        obj=pd.DataFrame({"a": [1, 2]}),
    )
    r = client.get(f"/table/export?view=v1&snapshot={snap.snapshot_id}")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert snap.snapshot_id in cd
    assert "plotsrv_table_" in cd


def test_publish_artifact_branch_enqueues_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_enqueue_snapshot(**kwargs: Any) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr(app_mod, "enqueue_snapshot", fake_enqueue_snapshot)

    payload = {
        "kind": "artifact",
        "section": "ops",
        "label": "log",
        "artifact_kind": "json",
        "artifact": {"a": 1},
        "publish_source": "watch",
        "force": True,
    }
    r = client.post("/publish", json=payload)
    assert r.status_code == 200
    assert calls
    assert calls[0]["view_id"] == "ops:log"
    assert calls[0]["kind"] == "json"
    assert calls[0]["obj"] == {"a": 1}
    assert calls[0]["source"] == "watch"


def test_publish_table_non_string_html_simple_becomes_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, Any]] = []

    orig_set_table = app_mod.store.set_table

    def fake_set_table(
        df: pd.DataFrame,
        html_simple: str | None,
        *,
        view_id: str | None = None,
        total_rows: int | None = None,
        returned_rows: int | None = None,
    ) -> None:
        captured.append(
            {
                "df": df,
                "html_simple": html_simple,
                "view_id": view_id,
                "total_rows": total_rows,
                "returned_rows": returned_rows,
            }
        )
        orig_set_table(
            df,
            html_simple,
            view_id=view_id,
            total_rows=total_rows,
            returned_rows=returned_rows,
        )

    monkeypatch.setattr(app_mod.store, "set_table", fake_set_table)
    monkeypatch.setattr(app_mod, "enqueue_snapshot", lambda **kwargs: True)

    payload = {
        "kind": "table",
        "section": "etl",
        "label": "import",
        "table": {
            "columns": ["a"],
            "rows": [{"a": 1}],
            "total_rows": "bad",
            "returned_rows": "bad",
        },
        "table_html_simple": {"not": "a string"},
        "force": True,
    }
    r = client.post("/publish", json=payload)
    assert r.status_code == 200
    assert captured
    assert captured[0]["html_simple"] is None
    assert captured[0]["total_rows"] is None
    assert captured[0]["returned_rows"] is None


def test_publish_sets_active_view_when_current_active_unknown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.reset()
    store.set_active_view("missing:view")
    monkeypatch.setattr(app_mod, "enqueue_snapshot", lambda **kwargs: True)

    payload = {
        "kind": "artifact",
        "section": "ops",
        "label": "log",
        "artifact_kind": "text",
        "artifact": "hello",
        "force": True,
    }
    r = client.post("/publish", json=payload)
    assert r.status_code == 200
    assert store.get_active_view_id() == "ops:log"


def test_index_with_view_param_is_request_local_and_does_not_set_active_view(
    client: TestClient,
) -> None:
    vid = store.register_view(section="ops", label="log", kind="none")
    store.set_artifact(
        obj="hello", kind="text", section="ops", label="log", view_id=vid
    )

    store.set_active_view("default")

    r = client.get(f"/?view={vid}")
    assert r.status_code == 200
    assert store.get_active_view_id() == "default"


def test_index_table_simple_lookuperror_falls_back_to_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.set_table_view_mode("simple")
    vid = store.register_view(section="etl", label="import", kind="table")
    store.set_active_view(vid)
    store.get_view_state(vid).table_df = pd.DataFrame({"a": [1]})

    monkeypatch.setattr(app_mod.store, "has_table", lambda **kwargs: True)
    monkeypatch.setattr(
        app_mod.store,
        "get_table_html_simple",
        lambda **kwargs: (_ for _ in ()).throw(LookupError("no html")),
    )

    r = client.get("/")
    assert r.status_code == 200


def test_get_artifact_snapshot_plot_and_table_shortcuts(
    client: TestClient, tmp_path: Path
) -> None:
    plot_snap = write_snapshot(
        root_dir=tmp_path, view_id="vplot", kind="plot", obj=b"\x89PNGfake"
    )
    table_snap = write_snapshot(
        root_dir=tmp_path,
        view_id="vtable",
        kind="table",
        obj=pd.DataFrame({"a": [1]}),
    )

    r1 = client.get(f"/artifact?view=vplot&snapshot={plot_snap.snapshot_id}")
    r2 = client.get(f"/artifact?view=vtable&snapshot={table_snap.snapshot_id}")

    assert r1.status_code == 200
    assert r1.json()["kind"] == "plot"
    assert r2.status_code == 200
    assert r2.json()["kind"] == "table"


def test_get_artifact_snapshot_non_plot_non_table_includes_snapshot_meta(
    client: TestClient, tmp_path: Path
) -> None:
    snap = write_snapshot(
        root_dir=tmp_path,
        view_id="ops:log",
        kind="text",
        obj="hello <b>x</b>",
        section="ops",
        label="log",
    )
    r = client.get(f"/artifact?view=ops:log&snapshot={snap.snapshot_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["snapshot_id"] == snap.snapshot_id
    assert data["meta"]["snapshot"] is True
    assert data["meta"]["snapshot_meta"]["snapshot_id"] == snap.snapshot_id


def test_get_artifact_live_returns_meta_and_truncation(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    vid = store.register_view(section="ops", label="log", kind="artifact")
    store.set_artifact(
        obj="hello", kind="text", section="ops", label="log", view_id=vid
    )

    r = client.get(f"/artifact?view={vid}")
    assert r.status_code == 200
    data = r.json()
    assert data["view_id"] == vid
    assert data["kind"] == "text"
    assert "meta" in data


def test_ensure_assets_mount_mounts_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UI:
        def __init__(self, assets_dir: Path) -> None:
            self.assets_dir = assets_dir

    assets = tmp_path / "assets"
    assets.mkdir()

    monkeypatch.setattr(app_mod, "get_ui_settings", lambda: UI(assets))

    before = len(app_mod.app.router.routes)
    app_mod._ensure_assets_mount()
    mid = len(app_mod.app.router.routes)
    app_mod._ensure_assets_mount()
    after = len(app_mod.app.router.routes)

    assert mid >= before
    assert after == mid


def test_ensure_assets_mount_noop_when_missing_assets_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UI:
        def __init__(self, assets_dir: Path | None) -> None:
            self.assets_dir = assets_dir

    monkeypatch.setattr(app_mod, "get_ui_settings", lambda: UI(tmp_path / "missing"))
    before = len(app_mod.app.router.routes)
    app_mod._ensure_assets_mount()
    after = len(app_mod.app.router.routes)
    assert after == before
