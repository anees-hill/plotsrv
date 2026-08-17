from __future__ import annotations

import base64
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv.app import app
from plotsrv import store, config
from plotsrv.runtime import WatchConfig, register_watch_views


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    store.reset()
    config.set_table_view_mode("simple")
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    monkeypatch.setattr(config, "get_internal_read_local_only", lambda: False)
    monkeypatch.setattr(config, "get_views_local_only", lambda: False)
    yield
    store.reset()
    config.set_table_view_mode("simple")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_plot_404_when_none(client: TestClient) -> None:
    resp = client.get("/plot")
    assert resp.status_code == 404


def test_get_plot_returns_png_when_set(client: TestClient) -> None:
    vid = _mk_view("etl", "metrics")
    store.set_plot(b"\x89PNGfake", view_id=vid)

    resp = client.get(f"/plot?view={vid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_get_plot_download_sets_content_disposition(client: TestClient) -> None:
    store.set_plot(b"\x89PNGfake")

    resp = client.get("/plot?download=true")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "").lower()


def test_table_data_404_when_none(client: TestClient) -> None:
    resp = client.get("/table/data")
    assert resp.status_code == 404


def test_table_data_returns_json_sample(client: TestClient) -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    store.set_table(df, html_simple="<table>dummy</table>")

    resp = client.get("/table/data?limit=2")
    assert resp.status_code == 200

    data = resp.json()
    assert data["columns"] == ["a", "b"]
    assert data["total_rows"] == 3
    assert data["total_rows_known"] is True
    assert data["loaded_rows"] == 3
    assert data["returned_rows"] == 2
    assert len(data["rows"]) == 2


def test_index_none_shows_empty_state(client: TestClient) -> None:
    store.reset()
    resp = client.get("/")
    text = resp.text

    assert "Waiting for content" in text
    assert "plotsrv is running" in text
    assert "Python outputs" in text
    assert "watched file updates" in text


def test_index_plot_embeds_image(client: TestClient) -> None:
    store.set_plot(b"\x89PNGfake")
    resp = client.get("/")
    text = resp.text
    assert '<img id="plot"' in text
    assert "/plot" in text


def test_index_table_simple_embeds_table_html(client: TestClient) -> None:
    config.set_table_view_mode("simple")
    store.set_table(
        pd.DataFrame({"a": [1]}),
        html_simple="<table><tr><td>SIMPLE</td></tr></table>",
    )

    resp = client.get("/")
    text = resp.text
    assert "SIMPLE" in text

    # Don't look for "table-grid" substring
    assert 'id="table-grid"' not in text
    assert "/static/vendor/tabulator/5.5.0/tabulator.min.js" not in text


def test_index_table_rich_has_table_grid_div(client: TestClient) -> None:
    config.set_table_view_mode("rich")
    store.set_table(pd.DataFrame({"a": [1]}), html_simple=None)

    resp = client.get("/")
    text = resp.text
    assert 'id="table-grid"' in text
    assert "/static/vendor/tabulator/5.5.0/tabulator.min.js" in text


def test_status_includes_service_fields(client: TestClient) -> None:
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "last_updated" in data
    assert "last_duration_s" in data
    assert "last_error" in data

    assert "service_mode" in data
    assert "service_target" in data
    assert "service_refresh_rate_s" in data


def test_status_includes_current_view_menu_revision(client: TestClient) -> None:
    store.register_view(section="demo", label="summary", kind="artifact")

    resp = client.get("/status")

    assert resp.status_code == 200
    assert resp.json()["view_menu_revision"] == store.get_view_menu_revision()


def test_index_seeds_current_view_menu_revision(client: TestClient) -> None:
    store.register_view(section="demo", label="summary", kind="artifact")

    resp = client.get("/")

    assert resp.status_code == 200
    assert f'"view_menu_revision": {store.get_view_menu_revision()}' in resp.text


def test_status_includes_file_backed_watch_metadata(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="api",
                section="logs",
                read_mode="tail",
                max_bytes=123,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/status?view=logs:api")

    assert resp.status_code == 200
    data = resp.json()

    assert data["view_id"] == "logs:api"
    assert data["is_watched_file"] is True
    assert data["materialization"] == "file"

    watched = data["watched_file"]
    assert watched["materialization"] == "file"
    assert watched["path"] == str(p.resolve())
    assert watched["file_kind"] == "unknown"
    assert watched["read_mode"] == "tail"
    assert watched["encoding"] == "utf-8"
    assert watched["size_bytes"] == len("hello\n".encode("utf-8"))
    assert watched["max_bytes"] == 123


def test_status_non_watch_has_no_watched_file_metadata(
    client: TestClient,
) -> None:
    vid = store.register_view(section="demo", label="normal", kind="artifact")
    store.set_artifact(
        obj="hello",
        kind="text",
        section="demo",
        label="normal",
        view_id=vid,
    )

    resp = client.get(f"/status?view={vid}")

    assert resp.status_code == 200
    data = resp.json()

    assert data["is_watched_file"] is False
    assert data["materialization"] is None
    assert data["watched_file"] is None


def test_views_include_file_backed_watch_metadata(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="api",
                section="logs",
                read_mode="tail",
                max_bytes=123,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/views")

    assert resp.status_code == 200
    views = resp.json()

    item = next(v for v in views if v["view_id"] == "logs:api")

    assert item["is_watched_file"] is True
    assert item["materialization"] == "file"
    assert item["watched_file"]["materialization"] == "file"
    assert item["watched_file"]["path"] == str(p.resolve())
    assert item["watched_file"]["read_mode"] == "tail"
    assert item["watched_file"]["size_bytes"] == len("hello\n".encode("utf-8"))


def test_views_include_memory_backed_watch_metadata(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "small.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "memory",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="small",
                section="logs",
                read_mode="tail",
                max_bytes=123,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/views")

    assert resp.status_code == 200
    views = resp.json()

    item = next(v for v in views if v["view_id"] == "logs:small")

    assert item["is_watched_file"] is True
    assert item["materialization"] == "memory"
    assert item["watched_file"]["materialization"] == "memory"
    assert item["watched_file"]["path"] == str(p.resolve())


def _mk_view(section: str = "default", label: str = "titanic") -> str:
    vid = store.register_view(section=section, label=label, kind="none")
    store.set_active_view(vid)
    return vid


def test_publish_plot_creates_view_and_serves_plot(client: TestClient) -> None:
    # Build a tiny png bytes payload (server expects b64 png)
    fig: Figure = plt.figure()
    buf = b"\x89PNGfake"  # you can generate real bytes too; fake is fine if server doesn't validate PNG
    png_b64 = base64.b64encode(buf).decode("utf-8")

    payload = {
        "kind": "plot",
        "label": "metrics",
        "section": "etl-1",
        "update_limit_s": None,
        "force": False,
        "plot_png_b64": png_b64,
    }

    r = client.post("/publish", json=payload)
    assert r.status_code == 200

    vid = store.normalize_view_id(None, section="etl-1", label="metrics")
    r2 = client.get(f"/plot?view={vid}")
    assert r2.status_code == 200
    assert r2.content.startswith(
        b"\x89PNG"
    )  # if you used a real png; if fake, just assert equals buf


def test_publish_table_creates_view_and_serves_table(client: TestClient) -> None:
    payload = {
        "kind": "table",
        "label": "import",
        "section": "etl-1",
        "update_limit_s": None,
        "force": False,
        "table": {
            "columns": ["a"],
            "rows": [{"a": 1}, {"a": 2}],
            "total_rows": 2,
            "returned_rows": 2,
        },
        "table_html_simple": "<table><tr><td>hi</td></tr></table>",
    }

    r = client.post("/publish", json=payload)
    assert r.status_code == 200

    vid = store.normalize_view_id(None, section="etl-1", label="import")
    r2 = client.get(f"/table/data?view={vid}&limit=2")
    assert r2.status_code == 200
    assert r2.json()["columns"] == ["a"]


def test_publish_respects_update_limit(client: TestClient) -> None:
    payload = {
        "kind": "table",
        "label": "import",
        "section": "etl-1",
        "update_limit_s": 600,
        "force": False,
        "table": {
            "columns": ["a"],
            "rows": [{"a": 1}],
            "total_rows": 1,
            "returned_rows": 1,
        },
        "table_html_simple": "<table></table>",
    }

    r1 = client.post("/publish", json=payload)
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["ok"] is True
    assert data1["ignored"] is False

    r2 = client.post("/publish", json=payload)
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["ok"] is True
    assert data2["ignored"] is True
    assert data2["reason"] == "throttled"

    # sanity: it still identifies the view
    assert data2["view_id"] == "etl-1:import"


def test_status_includes_restored_fields(client: TestClient) -> None:
    vid = store.register_view(section="demo", label="message", kind="artifact")
    store.set_artifact(
        obj="hello",
        kind="text",
        section="demo",
        label="message",
        view_id=vid,
    )
    store.mark_restored(
        view_id=vid,
        last_updated="2026-01-01T00:00:00+00:00",
        restored_at="2026-01-02T00:00:00+00:00",
        source="latest",
    )

    resp = client.get(f"/status?view={vid}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["restored_from_storage"] is True
    assert data["restored_at"] == "2026-01-02T00:00:00+00:00"
    assert data["restore_source"] == "latest"


def test_publish_normal_large_text_artifact_still_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_artifact_text_chars", lambda: 5)

    payload = {
        "kind": "artifact",
        "artifact_kind": "text",
        "section": "limits",
        "label": "normal-large-text",
        "artifact": "x" * 20,
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 413
    detail = resp.json()["detail"]
    assert "limits.published_objects.max_artifact_text_chars=5" in detail
    assert "publish_source=normal" in detail


def test_publish_watch_large_text_artifact_bypasses_publish_text_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_artifact_text_chars", lambda: 5)

    payload = {
        "kind": "artifact",
        "artifact_kind": "text",
        "section": "limits",
        "label": "watch-large-text",
        "artifact": "x" * 20,
        "publish_source": "watch",
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["ignored"] is False


def test_publish_watch_source_is_case_and_space_insensitive(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_artifact_text_chars", lambda: 5)

    payload = {
        "kind": "artifact",
        "artifact_kind": "text",
        "section": "limits",
        "label": "watch-source-normalised",
        "artifact": "x" * 20,
        "publish_source": "  WATCH  ",
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_publish_normal_large_json_artifact_still_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_json_container_items", lambda: 2)

    payload = {
        "kind": "artifact",
        "artifact_kind": "json",
        "section": "limits",
        "label": "normal-large-json",
        "artifact": {"a": [1, 2, 3]},
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 413
    detail = resp.json()["detail"]
    assert "limits.published_objects.max_json_container_items=2" in detail
    assert "publish_source=normal" in detail


def test_publish_watch_large_json_artifact_bypasses_publish_json_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_json_container_items", lambda: 2)

    payload = {
        "kind": "artifact",
        "artifact_kind": "json",
        "section": "limits",
        "label": "watch-large-json",
        "artifact": {"a": [1, 2, 3]},
        "publish_source": "watch",
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_publish_normal_large_text_artifact_413_is_actionable(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_artifact_text_chars", lambda: 5)

    resp = client.post(
        "/publish",
        json={
            "kind": "artifact",
            "artifact_kind": "text",
            "section": "limits",
            "label": "normal-large-text",
            "artifact": "x" * 20,
        },
    )

    assert resp.status_code == 413
    detail = resp.json()["detail"]
    assert "20 characters" in detail
    assert "limits.published_objects.max_artifact_text_chars=5" in detail
    assert "publish_source=normal" in detail


def test_publish_table_too_many_rows_413_is_actionable(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_table_rows", lambda: 1)

    resp = client.post(
        "/publish",
        json={
            "kind": "table",
            "section": "limits",
            "label": "too-many-rows",
            "table": {
                "columns": ["a"],
                "rows": [{"a": 1}, {"a": 2}],
            },
        },
    )

    assert resp.status_code == 413
    detail = resp.json()["detail"]
    assert "2 rows" in detail
    assert "limits.published_objects.max_table_rows=1" in detail
    assert "publish_source=normal" in detail


def test_publish_table_too_many_columns_413_is_actionable(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_table_columns", lambda: 1)

    resp = client.post(
        "/publish",
        json={
            "kind": "table",
            "section": "limits",
            "label": "too-many-columns",
            "table": {
                "columns": ["a", "b"],
                "rows": [{"a": 1, "b": 2}],
            },
        },
    )

    assert resp.status_code == 413
    detail = resp.json()["detail"]
    assert "2 columns" in detail
    assert "limits.published_objects.max_table_columns=1" in detail
    assert "publish_source=normal" in detail


def test_table_data_uses_table_truncate_limits(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 2)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 2)

    df = pd.DataFrame(
        {
            "a": [1, 2, 3],
            "b": [4, 5, 6],
            "c": [7, 8, 9],
        }
    )
    store.set_table(df, html_simple="<table>dummy</table>")

    resp = client.get("/table/data")
    assert resp.status_code == 200

    data = resp.json()

    assert data["columns"] == ["a", "b"]
    assert data["rows"] == [
        {"a": 1, "b": 4},
        {"a": 2, "b": 5},
    ]
    assert data["total_rows"] == 3
    assert data["total_rows_known"] is True
    assert data["loaded_rows"] == 3
    assert data["returned_rows"] == 2


def test_table_data_query_limit_can_reduce_below_table_truncate_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 3)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 10)

    df = pd.DataFrame({"a": [1, 2, 3]})
    store.set_table(df, html_simple="<table>dummy</table>")

    resp = client.get("/table/data?limit=1")
    assert resp.status_code == 200

    data = resp.json()

    assert data["rows"] == [{"a": 1}]
    assert data["total_rows"] == 3
    assert data["returned_rows"] == 1


def test_rejected_python_artifact_publish_creates_visible_error_artifact(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_artifact_text_chars", lambda: 5)

    payload = {
        "kind": "artifact",
        "artifact_kind": "text",
        "section": "tests",
        "label": "too-big",
        "artifact": "x" * 20,
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 413

    vid = store.normalize_view_id(None, section="tests", label="too-big")
    art = store.get_artifact(view_id=vid)

    assert art.kind == "publish_error"
    assert "plotsrv publish rejected" in art.obj
    assert "Status: 413" in art.obj
    assert "View: tests:too-big" in art.obj
    assert "Kind: artifact" in art.obj
    assert "limits.published_objects.max_artifact_text_chars=5" in art.obj

    status = store.get_status(view_id=vid)
    assert status["last_error"]


def test_rejected_python_table_publish_creates_visible_error_artifact(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_table_rows", lambda: 1)

    payload = {
        "kind": "table",
        "section": "tests",
        "label": "too-many-rows",
        "table": {
            "columns": ["a"],
            "rows": [{"a": 1}, {"a": 2}],
            "total_rows": 2,
            "returned_rows": 2,
        },
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 413

    vid = store.normalize_view_id(None, section="tests", label="too-many-rows")
    art = store.get_artifact(view_id=vid)

    assert art.kind == "publish_error"
    assert "plotsrv publish rejected" in art.obj
    assert "Status: 413" in art.obj
    assert "Kind: table" in art.obj
    assert "limits.published_objects.max_table_rows=1" in art.obj

    status = store.get_status(view_id=vid)
    assert status["last_error"]


def test_rejected_python_plot_publish_creates_visible_error_artifact(
    client: TestClient,
) -> None:
    payload = {
        "kind": "plot",
        "section": "tests",
        "label": "bad-plot",
        "plot_png_b64": "not valid base64",
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 422

    vid = store.normalize_view_id(None, section="tests", label="bad-plot")
    art = store.get_artifact(view_id=vid)

    assert art.kind == "publish_error"
    assert "plotsrv publish rejected" in art.obj
    assert "Status: 422" in art.obj
    assert "Kind: plot" in art.obj
    assert "plot_png_b64 was not valid base64" in art.obj

    status = store.get_status(view_id=vid)
    assert status["last_error"]


def test_rejected_watch_publish_does_not_create_app_level_error_artifact(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_table_rows", lambda: 1)

    payload = {
        "kind": "table",
        "section": "watch",
        "label": "too-many-rows",
        "publish_source": "watch",
        "table": {
            "columns": ["a"],
            "rows": [{"a": 1}, {"a": 2}],
            "total_rows": 2,
            "returned_rows": 2,
        },
    }

    resp = client.post("/publish", json=payload)

    assert resp.status_code == 413

    vid = store.normalize_view_id(None, section="watch", label="too-many-rows")

    with pytest.raises(LookupError):
        store.get_artifact(view_id=vid)


def test_publish_error_artifact_renders_without_text_truncation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_publish_max_artifact_text_chars", lambda: 5)
    monkeypatch.setattr(
        config, "get_truncation_max_chars", lambda kind, view_id=None: 10
    )

    payload = {
        "kind": "artifact",
        "artifact_kind": "text",
        "section": "tests",
        "label": "too-big-untruncated-error",
        "artifact": "x" * 20,
    }

    resp = client.post("/publish", json=payload)
    assert resp.status_code == 413

    vid = store.normalize_view_id(
        None,
        section="tests",
        label="too-big-untruncated-error",
    )

    rendered = client.get(f"/artifact?view={vid}")
    assert rendered.status_code == 200

    data = rendered.json()
    assert data["kind"] == "publish_error"
    assert data["truncation"]["truncated"] is False
    assert "plotsrv publish rejected" in data["html"]
    assert "limits.published_objects.max_artifact_text_chars=5" in data["html"]


def test_table_data_serves_file_backed_csv_watch(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text(
        "a,b\n" "1,one\n" "2,two\n" "3,three\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 10)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 10)

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=1000,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/table/data?view=watch:data")

    assert resp.status_code == 200
    data = resp.json()

    assert data["columns"] == ["a", "b"]
    assert data["rows"] == [
        {"a": 1, "b": "one"},
        {"a": 2, "b": "two"},
        {"a": 3, "b": "three"},
    ]
    assert data["total_rows"] is None
    assert data["total_rows_known"] is False
    assert data["loaded_rows"] == 3
    assert data["returned_rows"] == 3

    meta = data["meta"]
    assert meta["file_backed"] is True
    assert meta["watch"] is True
    assert meta["materialization"] == "file"
    assert meta["file_kind"] == "csv"
    assert meta["path"] == str(p.resolve())
    assert meta["source"] == "file_backed_csv"
    assert meta["truncated"] is False


def test_table_data_file_backed_csv_respects_query_limit(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text(
        "a,b\n" "1,one\n" "2,two\n" "3,three\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 10)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 10)

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=1000,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/table/data?view=watch:data&limit=2")

    assert resp.status_code == 200
    data = resp.json()

    assert data["rows"] == [
        {"a": 1, "b": "one"},
        {"a": 2, "b": "two"},
    ]
    assert data["total_rows"] is None
    assert data["total_rows_known"] is False
    # The request limit is applied while reading the file-backed source,
    # rather than after constructing a larger in-memory preview.
    assert data["loaded_rows"] == 2
    assert data["returned_rows"] == 2
    assert data["meta"]["file_backed"] is True


def test_table_data_file_backed_csv_tail_mode(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text(
        "a,b\n" "1,one\n" "2,two\n" "3,three\n" "4,four\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 10)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 10)

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="tail",
                max_bytes=12,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/table/data?view=watch:data")

    assert resp.status_code == 200
    data = resp.json()

    assert data["columns"] == ["a", "b"]
    assert {"a": 4, "b": "four"} in data["rows"]
    assert data["total_rows"] is None
    assert data["total_rows_known"] is False
    assert data["meta"]["truncated"] is True
    assert data["meta"]["preview_bytes"] <= p.stat().st_size


def test_table_data_file_backed_csv_without_store_table(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    assert store.has_table(view_id="watch:data") is False

    resp = client.get("/table/data?view=watch:data")

    assert resp.status_code == 200
    assert resp.json()["rows"] == [{"a": 1}]


def test_table_data_file_backed_csv_missing_file_returns_visible_error_row(
    client: TestClient,
    tmp_path,
) -> None:
    import plotsrv.store as store

    p = tmp_path / "missing.csv"

    store.register_view(
        view_id="watch:missing",
        section="watch",
        label="missing",
        kind="table",
        activate_if_first=False,
    )
    store.set_watched_file_meta(
        store.WatchedFileMeta(
            view_id="watch:missing",
            path=str(p.resolve()),
            file_kind="csv",
            read_mode="head",
            encoding="utf-8",
            materialization="file",
            size_bytes=None,
            mtime_ns=None,
            max_bytes=100,
            last_error="FileNotFoundError",
        )
    )

    resp = client.get("/table/data?view=watch:missing")

    assert resp.status_code == 200
    data = resp.json()

    assert data["columns"] == ["plotsrv_error"]
    assert data["total_rows"] == 1
    assert data["returned_rows"] == 1
    assert data["meta"]["error"] is True
    assert data["meta"]["artifact_kind"] == "watch_error"
    assert data["meta"]["status_code"] == 404

    error_text = data["rows"][0]["plotsrv_error"]
    assert "file-backed CSV read failed" in error_text
    assert "FileNotFoundError" in error_text
    assert str(p.resolve()) in error_text

    status = store.get_status(view_id="watch:missing")
    assert status["last_error"]


def test_table_export_file_backed_csv_streams_original_source(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a,b\n1,one\n2,two\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    assert store.has_table(view_id="watch:data") is False

    resp = client.get("/table/export?view=watch:data")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content == p.read_bytes()


def test_table_export_source_does_not_break_file_backed_csv_data(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    export_resp = client.get("/table/export?view=watch:data")
    assert export_resp.status_code == 200
    assert export_resp.content == p.read_bytes()

    data_resp = client.get("/table/data?view=watch:data")
    assert data_resp.status_code == 200
    assert data_resp.json()["rows"] == [{"a": 1}]


def test_table_export_memory_table_still_works(
    client: TestClient,
) -> None:
    df = pd.DataFrame({"a": [1, 2]})
    store.set_table(df, html_simple="<table>dummy</table>")

    resp = client.get("/table/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "").lower()
    assert resp.content.decode("utf-8") == "a\n1\n2\n"


def test_table_export_memory_backed_watch_csv_uses_store_table(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "memory",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    store.set_table(
        pd.DataFrame({"a": [1]}),
        html_simple=None,
        view_id="watch:data",
        total_rows=1,
        returned_rows=1,
        publish_source="watch",
    )

    resp = client.get("/table/export?view=watch:data")

    assert resp.status_code == 200
    assert resp.content.decode("utf-8") == "a\n1\n"


def test_file_backed_csv_error_row_contains_full_actionable_message(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plotsrv.store as store

    p = tmp_path / "missing.csv"

    monkeypatch.setattr(
        config,
        "get_table_truncate_columns",
        lambda: 1,
    )
    monkeypatch.setattr(
        config,
        "get_table_truncate_rows",
        lambda: 1,
    )

    store.register_view(
        view_id="watch:missing",
        section="watch",
        label="missing",
        kind="table",
        activate_if_first=False,
    )
    store.set_watched_file_meta(
        store.WatchedFileMeta(
            view_id="watch:missing",
            path=str(p.resolve()),
            file_kind="csv",
            read_mode="head",
            encoding="utf-8",
            materialization="file",
            size_bytes=None,
            mtime_ns=None,
            max_bytes=100,
            last_error="FileNotFoundError",
        )
    )

    resp = client.get("/table/data?view=watch:missing")

    assert resp.status_code == 200
    data = resp.json()

    error_text = data["rows"][0]["plotsrv_error"]
    assert "Config keys to check" in error_text
    assert "limits.watched_files.max_mb" in error_text
    assert "limits.truncate_after.table_rows" in error_text
    assert "limits.truncate_after.table_columns" in error_text


def test_views_file_backed_csv_watch_uses_table_icon(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="data",
                section="watch",
                read_mode="head",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/views")

    assert resp.status_code == 200
    item = next(v for v in resp.json() if v["view_id"] == "watch:data")

    assert item["is_watched_file"] is True
    assert item["materialization"] == "file"
    assert item["watched_file"]["file_kind"] == "csv"
    assert item["icon_key"] == "table"


def test_views_file_backed_unknown_watch_uses_text_icon(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )

    register_watch_views(
        [
            WatchConfig(
                path=p,
                label="api",
                section="logs",
                read_mode="tail",
                max_bytes=100,
            )
        ],
        activate_first_if_none=True,
    )

    resp = client.get("/views")

    assert resp.status_code == 200
    item = next(v for v in resp.json() if v["view_id"] == "logs:api")

    assert item["is_watched_file"] is True
    assert item["materialization"] == "file"
    assert item["watched_file"]["file_kind"] == "unknown"
    assert item["icon_key"] == "text"


def test_index_includes_file_backed_status_indicator_markup(
    client: TestClient,
) -> None:
    resp = client.get("/")

    assert resp.status_code == 200
    text = resp.text

    assert 'id="status-file-backed"' in text
    assert "/static/logo_on_disk.png" in text
    assert "ps-statusline__disk-icon" in text
