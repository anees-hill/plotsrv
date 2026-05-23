from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import pytest
from fastapi import BackgroundTasks, HTTPException

from plotsrv import config, store
import plotsrv.server as srv
from plotsrv.storage.models import LatestMeta, LoadedLatest


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reset store and server globals around each test.
    store.reset()

    srv._SERVER_RUNNING = False
    srv._SERVER_THREAD = None
    srv._SERVER = None
    srv._CURRENT_HOST = "0.0.0.0"
    srv._CURRENT_PORT = 8000

    monkeypatch.setattr(srv, "enqueue_snapshot", lambda **kwargs: False)

    # ensure matplotlib show is unpatched
    if getattr(srv, "_SHOW_PATCHED", False):
        srv._unpatch_matplotlib_show()

    # reset config
    config.set_table_view_mode("simple")

    yield

    store.reset()
    if getattr(srv, "_SHOW_PATCHED", False):
        srv._unpatch_matplotlib_show()


@pytest.fixture
def fake_run_server(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run_server(host: str, port: int, quiet: bool) -> None:
        # pretend server is running then immediately stop
        srv._SERVER_RUNNING = True

    monkeypatch.setattr(srv, "_run_server", _fake_run_server)


def test_refresh_view_with_figure_sets_plot(fake_run_server: None) -> None:
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.plot([1, 2], [3, 4])

    srv.refresh_view(fig)

    assert store.get_kind() == "plot"
    assert store.has_plot() is True
    assert len(store.get_plot()) > 0


def test_refresh_view_with_dataframe_simple(fake_run_server: None) -> None:
    config.set_table_view_mode("simple")
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})

    srv.refresh_view(df)

    assert store.get_kind() == "table"
    assert store.has_table() is True

    out_df = store.get_table_df()
    assert out_df.equals(df)

    html = store.get_table_html_simple()
    assert "<table" in html
    assert "a" in html and "b" in html


def test_refresh_view_with_dataframe_rich(fake_run_server: None) -> None:
    config.set_table_view_mode("rich")
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})

    srv.refresh_view(df)

    assert store.get_kind() == "table"
    assert store.has_table() is True

    out_df = store.get_table_df()
    assert out_df.equals(df)

    # in rich mode, we should not have pre-rendered HTML stored
    with pytest.raises(LookupError):
        store.get_table_html_simple()


def test_refresh_view_generic_object_becomes_python_artifact(
    fake_run_server: None,
) -> None:
    srv.refresh_view(123, label="number", section="debug")

    vid = "debug:number"
    assert store.get_kind(vid) == "artifact"
    art = store.get_artifact(view_id=vid)
    assert art.kind == "python"
    assert art.obj == "123"
    assert art.label == "number"
    assert art.section == "debug"


def test_start_server_sets_defaults_and_patches_show(fake_run_server: None) -> None:
    original_show = plt.show

    srv.start_server(host="127.0.0.1", port=9123, auto_on_show=True, quiet=True)

    assert srv._CURRENT_HOST == "127.0.0.1"
    assert srv._CURRENT_PORT == 9123
    assert srv._SERVER_RUNNING is True
    assert srv._SHOW_PATCHED is True
    assert plt.show is not original_show  # patched


def test_start_server_twice_same_host_port_ok(fake_run_server: None) -> None:
    srv.start_server(host="127.0.0.1", port=9123, auto_on_show=False, quiet=True)
    # second call with same host/port should not raise
    srv.start_server(host="127.0.0.1", port=9123, auto_on_show=False, quiet=True)


def test_start_server_different_port_raises(fake_run_server: None) -> None:
    srv.start_server(host="127.0.0.1", port=9123, auto_on_show=False, quiet=True)
    with pytest.raises(RuntimeError):
        srv.start_server(host="127.0.0.1", port=9999, auto_on_show=False, quiet=True)


def test_stop_server_unpatches_show(fake_run_server: None) -> None:
    srv.start_server(host="127.0.0.1", port=9123, auto_on_show=True, quiet=True)
    patched_show = plt.show

    srv.stop_server(join=False)

    assert srv._SHOW_PATCHED is False
    assert plt.show is not patched_show


def test_object_is_dataframe_with_pandas() -> None:
    df = pd.DataFrame({"a": [1]})
    assert srv._object_is_dataframe(df) is True
    assert srv._object_is_dataframe({"a": [1]}) is False


def test_object_to_dataframe_rejects_non_dataframe() -> None:
    with pytest.raises(TypeError, match="Expected pandas or polars DataFrame"):
        srv._object_to_dataframe({"a": [1]})


def test_refresh_view_with_dataframe_named_view(fake_run_server: None) -> None:
    config.set_table_view_mode("rich")
    df = pd.DataFrame({"a": [1, 2]})

    srv.refresh_view(df, label="rows", section="analysis")

    vid = "analysis:rows"
    assert store.get_kind(vid) == "table"
    assert store.has_table(view_id=vid) is True
    assert store.get_table_df(view_id=vid).equals(df)

    views = {v.view_id: v for v in store.list_views()}
    assert views[vid].label == "rows"
    assert views[vid].section == "analysis"


def test_refresh_view_with_plot_named_view(fake_run_server: None) -> None:
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.plot([1, 2], [3, 4])

    srv.refresh_view(fig, label="plot", section="analysis")

    vid = "analysis:plot"
    assert store.get_kind(vid) == "plot"
    assert store.has_plot(view_id=vid) is True
    assert len(store.get_plot(view_id=vid)) > 0

    views = {v.view_id: v for v in store.list_views()}
    assert views[vid].label == "plot"
    assert views[vid].section == "analysis"


def test_object_to_figure_none_uses_current_figure() -> None:
    fig = plt.figure()
    try:
        out = srv._object_to_figure(None, force_plotnine=False)
        assert out is fig
    finally:
        plt.close(fig)


def test_object_to_figure_accepts_matplotlib_figure() -> None:
    fig = plt.figure()
    try:
        out = srv._object_to_figure(fig, force_plotnine=False)
        assert out is fig
    finally:
        plt.close(fig)


def test_object_to_figure_force_plotnine_requires_draw() -> None:
    with pytest.raises(TypeError, match="force_plotnine=True"):
        srv._object_to_figure(object(), force_plotnine=True)


def test_object_to_figure_force_plotnine_draws_object() -> None:
    fig = plt.figure()

    class FakePlotnine:
        def draw(self):
            return fig

    try:
        out = srv._object_to_figure(FakePlotnine(), force_plotnine=True)
        assert out is fig
    finally:
        plt.close(fig)


def test_patch_matplotlib_show_idempotent() -> None:
    original = plt.show

    try:
        srv._patch_matplotlib_show()
        first = plt.show
        srv._patch_matplotlib_show()
        second = plt.show

        assert first is second
        assert srv._SHOW_PATCHED is True
    finally:
        srv._unpatch_matplotlib_show()

    assert plt.show is original


def test_unpatch_matplotlib_show_idempotent() -> None:
    original = plt.show

    srv._unpatch_matplotlib_show()
    srv._unpatch_matplotlib_show()

    assert plt.show is original
    assert srv._SHOW_PATCHED is False


def test_stop_server_sets_should_exit_and_joins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeServer:
        should_exit = False

    class FakeThread:
        def __init__(self) -> None:
            self.join_called = False
            self.timeout = None

        def join(self, timeout: float | None = None) -> None:
            self.join_called = True
            self.timeout = timeout

    fake_server = FakeServer()
    fake_thread = FakeThread()

    srv._SERVER = fake_server  # type: ignore[assignment]
    srv._SERVER_THREAD = fake_thread  # type: ignore[assignment]

    monkeypatch.setattr("plotsrv.server.stop_storage_worker", lambda join=False: None)

    srv.stop_server(join=True, timeout=2.5)

    assert fake_server.should_exit is True
    assert fake_thread.join_called is True
    assert fake_thread.timeout == 2.5


def test_plot_session_starts_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_start_server(**kwargs: Any) -> None:
        calls.append(("start", kwargs))

    def fake_stop_server(**kwargs: Any) -> None:
        calls.append(("stop", kwargs))

    monkeypatch.setattr(srv, "start_server", fake_start_server)
    monkeypatch.setattr(srv, "stop_server", fake_stop_server)

    with srv.plot_session(host="h", port=123, auto_on_show=False, quiet=False):
        calls.append(("inside", {}))

    assert calls[0] == (
        "start",
        {
            "host": "h",
            "port": 123,
            "auto_on_show": False,
            "quiet": False,
            "config": None,
            "name": None,
            "truncate": None,
            "no_truncate": False,
            "watches": None,
            "restore_latest": True,
        },
    )
    assert calls[1] == ("inside", {})
    assert calls[2] == ("stop", {"join": False})


def test_shutdown_disabled_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv.config, "get_shutdown_enabled", lambda: False)

    with pytest.raises(HTTPException) as e:
        srv.shutdown(BackgroundTasks(), request=object())

    assert e.value.status_code == 404


def test_shutdown_schedules_background_task_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(srv.config, "get_shutdown_enabled", lambda: True)
    monkeypatch.setattr(srv.config, "get_control_local_only", lambda: False)

    tasks = BackgroundTasks()

    out = srv.shutdown(tasks, request=object())

    assert out == {"status": "shutting_down"}
    assert len(tasks.tasks) == 1


def test_start_server_applies_runtime_options(monkeypatch, tmp_path):
    import plotsrv.server as srv

    calls = []

    def fake_apply_runtime_options(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "plotsrv.runtime.apply_runtime_options",
        fake_apply_runtime_options,
    )
    monkeypatch.setattr(srv, "_ensure_server_running", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_patch_matplotlib_show", lambda: None)
    monkeypatch.setattr(srv, "restore_latest_views_from_storage", lambda: 0)

    cfg = tmp_path / "plotsrv.yml"
    cfg.write_text("{}", encoding="utf-8")

    srv.start_server(
        host="127.0.0.1",
        port=8123,
        auto_on_show=True,
        quiet=True,
        config=cfg,
        name="demo",
        truncate=60_000,
        no_truncate=False,
    )

    assert calls == [
        {
            "config": cfg,
            "name": "demo",
            "truncate": 60_000,
            "no_truncate": False,
        }
    ]


def test_start_server_starts_watch_threads(monkeypatch):
    import plotsrv.server as srv

    watch_calls = []

    monkeypatch.setattr(
        "plotsrv.runtime.apply_runtime_options",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(srv, "_ensure_server_running", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_patch_matplotlib_show", lambda: None)
    monkeypatch.setattr(srv, "restore_latest_views_from_storage", lambda: 0)

    def fake_start_watch_threads(watches, *, host, port):
        watch_calls.append({"watches": watches, "host": host, "port": port})
        return []

    monkeypatch.setattr(
        "plotsrv.runtime.start_watch_threads",
        fake_start_watch_threads,
    )

    watches = [{"path": "README.md", "label": "readme"}]
    srv.start_server(host="0.0.0.0", port=8123, watches=watches)

    assert watch_calls == [
        {
            "watches": watches,
            "host": "0.0.0.0",
            "port": 8123,
        }
    ]


def test_plot_session_passes_runtime_options(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_start_server(**kwargs: Any) -> None:
        calls.append(("start", kwargs))

    def fake_stop_server(**kwargs: Any) -> None:
        calls.append(("stop", kwargs))

    monkeypatch.setattr(srv, "start_server", fake_start_server)
    monkeypatch.setattr(srv, "stop_server", fake_stop_server)

    watches = [{"path": "README.md", "label": "readme"}]

    with srv.plot_session(
        port=8123,
        config="plotsrv.yml",
        name="demo",
        truncate=60_000,
        no_truncate=False,
        watches=watches,
    ):
        pass

    assert calls[0] == (
        "start",
        {
            "host": "127.0.0.1",
            "port": 8123,
            "auto_on_show": True,
            "quiet": True,
            "config": "plotsrv.yml",
            "name": "demo",
            "truncate": 60_000,
            "no_truncate": False,
            "watches": watches,
            "restore_latest": True,
        },
    )


def test_refresh_view_string_becomes_text_artifact(fake_run_server: None) -> None:
    srv.refresh_view("hello", label="message", section="debug")

    vid = "debug:message"
    assert store.get_kind(vid) == "artifact"
    art = store.get_artifact(view_id=vid)
    assert art.kind == "text"
    assert art.obj == "hello"


def test_refresh_view_dict_becomes_json_artifact(fake_run_server: None) -> None:
    srv.refresh_view({"status": "ok"}, label="status", section="debug")

    vid = "debug:status"
    assert store.get_kind(vid) == "artifact"
    art = store.get_artifact(view_id=vid)
    assert art.kind == "json"
    assert isinstance(art.obj, dict)
    assert art.obj["type"] == "plotsrv_json_document"
    assert art.obj["source_format"] == "python_object"


def test_refresh_view_pathlike_text_file(fake_run_server: None, tmp_path) -> None:
    p = tmp_path / "app.log"
    p.write_text("line one\nline two\n", encoding="utf-8")

    srv.refresh_view(p, label="log", section="files")

    vid = "files:log"
    assert store.get_kind(vid) == "artifact"
    art = store.get_artifact(view_id=vid)
    assert art.kind == "text"
    assert "line one" in art.obj


def test_refresh_view_invalid_forced_kind_raises(fake_run_server: None) -> None:
    with pytest.raises(ValueError):
        srv.refresh_view({"x": 1}, kind="bad")


def test_refresh_view_enqueues_persistence_for_named_table(
    fake_run_server: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        srv, "enqueue_snapshot", lambda **kwargs: calls.append(kwargs) or True
    )

    df = pd.DataFrame({"a": [1, 2]})
    srv.refresh_view(df, label="rows", section="analysis")

    assert calls
    assert calls[0]["view_id"] == "analysis:rows"
    assert calls[0]["kind"] == "table"
    assert calls[0]["section"] == "analysis"
    assert calls[0]["label"] == "rows"


def _latest_meta(
    *,
    view_id: str = "demo:message",
    kind: str = "text",
    section: str | None = "demo",
    label: str | None = "message",
) -> LatestMeta:
    return LatestMeta(
        view_id=view_id,
        section=section,
        label=label,
        kind=kind,
        updated_at="2026-01-01T00:00:00+00:00",
        payload_filename="latest__payload.txt",
        payload_format="text",
        size_bytes=5,
        path_payload="/tmp/latest__payload.txt",
        path_meta="/tmp/latest__meta.json",
        payload_exists=True,
        extra=None,
    )


def test_restore_latest_views_from_storage_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: False,
    )

    assert srv.restore_latest_views_from_storage() == 0


def test_restore_latest_views_from_storage_restores_text_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    meta = _latest_meta()

    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            assert root_dir == tmp_path

        def list_latest(self):
            return [meta]

        def load_latest(self, *, view_id: str):
            assert view_id == "demo:message"
            return LoadedLatest(meta=meta, obj="hello")

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "discovered",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    restored = srv.restore_latest_views_from_storage()

    assert restored == 1
    assert store.get_kind("demo:message") == "artifact"

    art = store.get_artifact(view_id="demo:message")
    assert art.kind == "text"
    assert art.obj == "hello"
    assert art.label == "message"
    assert art.section == "demo"

    status = store.get_status(view_id="demo:message")
    assert status["last_updated"] == "2026-01-01T00:00:00+00:00"
    assert status["restored_from_storage"] is True
    assert status["restore_source"] == "latest"
    assert status["restored_at"] is not None


def test_restore_latest_views_from_storage_restores_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    df = pd.DataFrame({"a": [1, 2]})
    meta = _latest_meta(
        view_id="etl:table",
        kind="table",
        section="etl",
        label="table",
    )

    meta = LatestMeta(
        view_id=meta.view_id,
        section=meta.section,
        label=meta.label,
        kind=meta.kind,
        updated_at=meta.updated_at,
        payload_filename="latest__payload.csv",
        payload_format="csv",
        size_bytes=10,
        path_payload="/tmp/latest__payload.csv",
        path_meta="/tmp/latest__meta.json",
        payload_exists=True,
        extra={"total_rows": 99, "returned_rows": 2},
    )

    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            pass

        def list_latest(self):
            return [meta]

        def load_latest(self, *, view_id: str):
            return LoadedLatest(meta=meta, obj=df)

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "discovered",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    restored = srv.restore_latest_views_from_storage()

    assert restored == 1
    assert store.get_kind("etl:table") == "table"
    assert store.get_table_df(view_id="etl:table").equals(df)
    assert store.get_table_counts(view_id="etl:table") == (99, 2)
    assert store.get_status(view_id="etl:table")["last_updated"] == meta.updated_at


def test_restore_latest_views_from_storage_restores_plot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    png = b"\x89PNG\r\n\x1a\nfake"
    meta = _latest_meta(
        view_id="plots:one",
        kind="plot",
        section="plots",
        label="one",
    )

    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            pass

        def list_latest(self):
            return [meta]

        def load_latest(self, *, view_id: str):
            return LoadedLatest(meta=meta, obj=png)

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "discovered",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    restored = srv.restore_latest_views_from_storage()

    assert restored == 1
    assert store.get_kind("plots:one") == "plot"
    assert store.get_plot(view_id="plots:one") == png
    assert store.get_status(view_id="plots:one")["last_updated"] == meta.updated_at


def test_restore_latest_views_from_storage_skips_bad_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    good = _latest_meta(view_id="demo:good", label="good")
    bad = _latest_meta(view_id="demo:bad", label="bad")

    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            pass

        def list_latest(self):
            return [bad, good]

        def load_latest(self, *, view_id: str):
            if view_id == "demo:bad":
                raise LookupError("missing")
            return LoadedLatest(meta=good, obj="ok")

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "discovered",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    restored = srv.restore_latest_views_from_storage()

    assert restored == 1
    assert store.has_artifact(view_id="demo:good") is True
    assert store.has_artifact(view_id="demo:bad") is False


def test_restore_latest_views_discovered_scope_skips_unregistered_latest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store.register_view(
        view_id="demo:live",
        section="demo",
        label="live",
        kind="none",
        activate_if_first=False,
    )

    meta = _latest_meta(view_id="demo:other", label="other")

    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            pass

        def list_latest(self):
            return [meta]

        def load_latest(self, *, view_id: str):
            raise AssertionError("should not load unregistered latest record")

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "discovered",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    assert srv.restore_latest_views_from_storage() == 0
    assert store.has_artifact(view_id="demo:other") is False


def test_restore_latest_views_discovered_scope_restores_registered_latest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store.register_view(
        view_id="demo:message",
        section="demo",
        label="message",
        kind="none",
        activate_if_first=False,
    )

    meta = _latest_meta(view_id="demo:message", label="message")

    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            pass

        def list_latest(self):
            return [meta]

        def load_latest(self, *, view_id: str):
            assert view_id == "demo:message"
            return LoadedLatest(meta=meta, obj="hello")

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "discovered",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    assert srv.restore_latest_views_from_storage() == 1
    assert store.get_artifact(view_id="demo:message").obj == "hello"


def test_restore_latest_views_all_scope_restores_unregistered_latest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store.register_view(
        view_id="demo:registered",
        section="demo",
        label="registered",
        kind="none",
        activate_if_first=False,
    )

    meta = _latest_meta(view_id="demo:other", label="other")

    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            pass

        def list_latest(self):
            return [meta]

        def load_latest(self, *, view_id: str):
            return LoadedLatest(meta=meta, obj="hello")

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "all",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    assert srv.restore_latest_views_from_storage() == 1
    assert store.get_artifact(view_id="demo:other").obj == "hello"


def test_restore_latest_views_none_scope_restores_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeLatestBackend:
        def __init__(self, *, root_dir):
            raise AssertionError("should not construct backend")

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "none",
    )
    monkeypatch.setattr(srv, "FileLatestStateBackend", FakeLatestBackend)

    assert srv.restore_latest_views_from_storage() == 0


def test_restore_latest_views_from_real_file_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from plotsrv.storage.latest import FileLatestStateBackend

    latest_backend = FileLatestStateBackend(root_dir=tmp_path)
    latest_backend.write_latest(
        view_id="demo:message",
        kind="text",
        obj="hello from disk",
        section="demo",
        label="message",
    )

    monkeypatch.setattr(
        srv.config,
        "get_storage_restore_latest_on_startup",
        lambda: True,
    )
    monkeypatch.setattr(
        srv.config,
        "get_storage_latest_restore_scope",
        lambda: "discovered",
    )
    monkeypatch.setattr(srv.config, "get_storage_root_dir", lambda: tmp_path)

    restored = srv.restore_latest_views_from_storage()

    assert restored == 1
    assert store.get_artifact(view_id="demo:message").obj == "hello from disk"
