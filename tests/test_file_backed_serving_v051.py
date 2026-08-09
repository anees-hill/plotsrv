from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plotsrv import config, store
from plotsrv.app import app
from plotsrv.runtime import (
    FileBackedLoadBusyError,
    WatchConfig,
    _FILE_BACKED_LOADS,
    file_backed_load_slot,
    read_file_backed_csv_preview,
    register_watch_views,
)


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    store.reset()
    _FILE_BACKED_LOADS.reset_for_tests()
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    monkeypatch.setattr(config, "get_internal_read_local_only", lambda: False)
    monkeypatch.setattr(config, "get_views_local_only", lambda: False)
    yield
    _FILE_BACKED_LOADS.reset_for_tests()
    store.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _register_file_watch(
    path: Path,
    *,
    label: str = "data",
    section: str = "watch",
    read_mode: str = "head",
    max_bytes: int | None = 10_000,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    monkeypatch.setattr(
        "plotsrv.runtime.resolve_watch_materialization",
        lambda path, requested=None: "file",
    )
    register_watch_views(
        [
            WatchConfig(
                path=path,
                label=label,
                section=section,
                read_mode=read_mode,  # type: ignore[arg-type]
                max_bytes=max_bytes,
            )
        ],
        activate_first_if_none=True,
    )
    return f"{section}:{label}"


def test_file_backed_csv_head_stops_without_full_file_row_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large.csv"
    path.write_text(
        "a,b\n" + "".join(f"{i},value-{i}\n" for i in range(200_000)),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 2)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 2)

    view_id = _register_file_watch(path, monkeypatch=monkeypatch, max_bytes=None)
    meta = store.get_watched_file_meta(view_id=view_id)

    # The old v0.5.0 implementation first read a raw window and then scanned
    # every line to determine total_rows. The new path stops after its display
    # row window and deliberately leaves the total unknown.
    monkeypatch.setattr(
        "plotsrv.runtime.read_watch_file_bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("raw read")),
    )
    preview = read_file_backed_csv_preview(meta)

    assert preview.total_rows is None
    assert preview.total_rows_known is False
    assert preview.loaded_rows == 2
    assert preview.preview_bytes < path.stat().st_size // 100


def test_file_backed_csv_tail_keeps_newest_bounded_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.csv"
    path.write_text(
        "id,message\n" + "".join(f"{i},event-{i}\n" for i in range(100)),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "get_table_truncate_rows", lambda: 3)
    monkeypatch.setattr(config, "get_table_truncate_columns", lambda: 2)

    view_id = _register_file_watch(
        path,
        read_mode="tail",
        max_bytes=None,
        monkeypatch=monkeypatch,
    )
    preview = read_file_backed_csv_preview(store.get_watched_file_meta(view_id=view_id))

    assert preview.table_df["id"].tolist() == [97, 98, 99]
    assert preview.loaded_rows == 3
    assert preview.truncated is True


def test_raw_watched_source_streams_registered_file_without_read_bytes(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "report.csv"
    path.write_text("a,b\n1,one\n", encoding="utf-8")

    view_id = _register_file_watch(path, monkeypatch=monkeypatch)

    # FileResponse opens/streams the registered path. It must not use the
    # convenience read_bytes() API, which would retain the complete source.
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(AssertionError("read_bytes called")),
    )
    inline = client.get(f"/watched-file/raw?view={view_id}")
    download = client.get(f"/watched-file/raw?view={view_id}&download=1")

    assert inline.status_code == 200
    assert inline.content == b"a,b\n1,one\n"
    assert inline.headers["x-content-type-options"] == "nosniff"
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

    # Source serving is driven by the registered metadata, not a path supplied
    # by a client. A forged view id cannot expose a file.
    missing = client.get("/watched-file/raw?view=../../etc:passwd")
    assert missing.status_code == 404


def test_memory_backed_watched_csv_export_uses_its_live_source(
    client: TestClient,
    tmp_path: Path,
) -> None:
    path = tmp_path / "published.csv"
    path.write_text("a\n1\n2\n", encoding="utf-8")
    view_id = "watch:memory"
    store.register_view(view_id=view_id, section="watch", label="memory", kind="table")
    store.set_table(
        pd.DataFrame({"a": [1, 2]}),
        html_simple=None,
        view_id=view_id,
    )
    store.set_watched_file_meta(
        store.WatchedFileMeta(
            view_id=view_id,
            path=str(path.resolve()),
            file_kind="csv",
            read_mode="head",
            encoding="utf-8",
            materialization="memory",
        )
    )

    response = client.get(f"/table/export?view={view_id}")

    assert response.status_code == 200
    assert response.content == path.read_bytes()


def test_raw_source_routes_respect_internal_read_policy(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "private.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    view_id = _register_file_watch(path, monkeypatch=monkeypatch)
    monkeypatch.setattr(config, "get_internal_read_local_only", lambda: True)

    raw = client.get(f"/watched-file/raw?view={view_id}")
    export = client.get(f"/table/export?view={view_id}")

    assert raw.status_code == 403
    assert export.status_code == 403


def test_file_backed_image_and_unsanitised_html_use_streaming_source_urls(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "chart.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-image")
    html = tmp_path / "report.html"
    html.write_text("<h1>Report</h1><script>window.bad = true</script>", encoding="utf-8")

    image_view = _register_file_watch(image, label="image", monkeypatch=monkeypatch)
    html_view = _register_file_watch(html, label="html", monkeypatch=monkeypatch)
    monkeypatch.setattr(config, "get_html_sanitize", lambda: False)

    image_resp = client.get(f"/artifact?view={image_view}")
    html_resp = client.get(f"/artifact?view={html_view}")

    assert image_resp.status_code == 200
    assert image_resp.json()["meta"]["source"] == "file_backed_stream"
    assert "/watched-file/raw?" in image_resp.json()["html"]

    html_data = html_resp.json()
    assert html_resp.status_code == 200
    assert html_data["meta"]["mode"] == "file_backed_sandboxed_iframe"
    assert "srcdoc=" not in html_data["html"]
    assert "sandbox=''" in html_data["html"]
    assert "/watched-file/raw?" in html_data["html"]


def test_file_backed_load_controller_returns_503_when_all_slots_busy(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a\n1\n2\n", encoding="utf-8")
    view_id = _register_file_watch(path, monkeypatch=monkeypatch)
    monkeypatch.setattr(config, "get_watch_active_load_max_concurrent", lambda: 1)
    monkeypatch.setattr(config, "get_watch_active_load_wait_timeout_s", lambda: 0.0)

    started = threading.Event()
    release = threading.Event()
    real_preview = read_file_backed_csv_preview

    def blocked_preview(meta):
        started.set()
        assert release.wait(timeout=2.0)
        return real_preview(meta)

    monkeypatch.setattr("plotsrv.app.read_file_backed_csv_preview", blocked_preview)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.get, f"/table/data?view={view_id}")
        assert started.wait(timeout=1.0)
        busy = client.get(f"/table/data?view={view_id}")
        release.set()
        completed = first.result(timeout=2.0)

    assert completed.status_code == 200
    assert busy.status_code == 503
    assert busy.headers["retry-after"] == "1"


def test_file_backed_load_slot_is_bounded_without_retaining_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_watch_active_load_max_concurrent", lambda: 1)
    monkeypatch.setattr(config, "get_watch_active_load_wait_timeout_s", lambda: 0.0)

    with file_backed_load_slot():
        with pytest.raises(FileBackedLoadBusyError):
            with file_backed_load_slot():
                pass
