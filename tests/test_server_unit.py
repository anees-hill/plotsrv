from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import pytest

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
