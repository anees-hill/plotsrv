from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import pandas as pd
import pytest
from fastapi import BackgroundTasks, HTTPException

from plotsrv import config, store
import plotsrv.server as srv


@pytest.fixture(autouse=True)
def reset_state() -> None:
    # Reset store and server globals around each test.
    store.reset()

    srv._SERVER_RUNNING = False
    srv._SERVER_THREAD = None
    srv._SERVER = None
    srv._CURRENT_HOST = "0.0.0.0"
    srv._CURRENT_PORT = 8000

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


def test_refresh_view_invalid_type_raises(fake_run_server: None) -> None:
    with pytest.raises(TypeError):
        srv.refresh_view(123)  # type: ignore[arg-type]


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
        {"host": "h", "port": 123, "auto_on_show": False, "quiet": False},
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
