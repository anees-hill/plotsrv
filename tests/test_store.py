from __future__ import annotations

import pandas as pd
import pytest

from plotsrv import store


@pytest.fixture(autouse=True)
def reset_store() -> None:
    # ensure clean state around each test
    store.reset()
    yield
    store.reset()


def test_set_plot_sets_kind_and_bytes() -> None:
    png = b"fake-bytes"
    store.set_plot(png)
    assert store.get_kind() == "plot"
    assert store.has_plot() is True
    assert store.get_plot() == png
    assert store.has_table() is False


def test_get_plot_raises_if_none() -> None:
    with pytest.raises(LookupError):
        store.get_plot()


def test_set_table_sets_kind_and_dataframe_and_html() -> None:
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    html = "<table>hi</table>"

    store.set_table(df, html)

    assert store.get_kind() == "table"
    assert store.has_table() is True
    assert store.has_plot() is False

    out_df = store.get_table_df()
    assert out_df.equals(df)

    assert store.get_table_html_simple() == html


def test_get_table_df_raises_if_none() -> None:
    with pytest.raises(LookupError):
        store.get_table_df()


def test_get_table_html_simple_raises_if_none() -> None:
    df = pd.DataFrame({"x": [1]})
    store.set_table(df, html_simple=None)

    with pytest.raises(LookupError):
        store.get_table_html_simple()


def test_reset_clears_all_state() -> None:
    df = pd.DataFrame({"x": [1]})
    store.set_plot(b"abc")
    store.set_table(df, "<table></table>")

    store.reset()
    assert store.get_kind() == "none"
    assert store.has_plot() is False
    assert store.has_table() is False


def test_register_view_creates_meta_and_list_views_sorted() -> None:
    store.register_view(section="b", label="z")
    store.register_view(section="a", label="m")
    store.register_view(section="a", label="a")

    metas = store.list_views()
    assert [m.section for m in metas] == ["a", "a", "b"]
    assert [m.label for m in metas] == ["a", "m", "z"]


def test_views_are_isolated_by_view_id() -> None:
    v1 = store.register_view(section="etl", label="import")
    v2 = store.register_view(section="etl", label="metrics")

    store.set_plot(b"plot1", view_id=v1)
    store.set_plot(b"plot2", view_id=v2)

    assert store.get_plot(view_id=v1) == b"plot1"
    assert store.get_plot(view_id=v2) == b"plot2"


def test_set_active_view_affects_backcompat_calls() -> None:
    v1 = store.register_view(section="s", label="a")
    v2 = store.register_view(section="s", label="b")

    store.set_active_view(v1)
    store.set_plot(b"one")
    store.set_active_view(v2)
    store.set_plot(b"two")

    assert store.get_plot(view_id=v1) == b"one"
    assert store.get_plot(view_id=v2) == b"two"


def test_should_accept_publish_throttles_when_limit_set() -> None:
    vid = store.register_view(section="s", label="x")
    assert (
        store.should_accept_publish(view_id=vid, update_limit_s=10, now_s=100.0) is True
    )
    # immediately again -> reject
    assert (
        store.should_accept_publish(view_id=vid, update_limit_s=10, now_s=105.0)
        is False
    )
    # after window -> accept
    assert (
        store.should_accept_publish(view_id=vid, update_limit_s=10, now_s=110.0) is True
    )


def test_should_accept_publish_accepts_when_no_limit() -> None:
    vid = store.register_view(section="s", label="x")
    assert (
        store.should_accept_publish(view_id=vid, update_limit_s=None, now_s=0.0) is True
    )
    assert (
        store.should_accept_publish(view_id=vid, update_limit_s=None, now_s=0.1) is True
    )


def test_traceback_artifact_uses_traceback_icon_key() -> None:
    store.set_artifact(
        obj={"type": "traceback", "frames": []},
        kind="traceback",
        label="err",
        section="ops",
        view_id="ops:err",
    )

    art = store.get_artifact(view_id="ops:err")
    assert art.kind == "traceback"

    views = {v.view_id: v for v in store.list_views()}
    assert views["ops:err"].icon_key == "traceback"


def test_exception_artifact_alias_uses_traceback_icon_key() -> None:
    store.set_artifact(
        obj={"type": "traceback", "frames": []},
        kind="exception",
        label="err",
        section="ops",
        view_id="ops:err",
    )

    art = store.get_artifact(view_id="ops:err")
    assert art.kind == "exception"

    views = {v.view_id: v for v in store.list_views()}
    assert views["ops:err"].icon_key == "traceback"


def test_mark_restored_sets_restored_status() -> None:
    store.set_artifact(
        obj="hello",
        kind="text",
        section="demo",
        label="message",
        view_id="demo:message",
    )

    store.mark_restored(
        view_id="demo:message",
        last_updated="2026-01-01T00:00:00+00:00",
        restored_at="2026-01-02T00:00:00+00:00",
        source="latest",
    )

    status = store.get_status(view_id="demo:message")

    assert status["last_updated"] == "2026-01-01T00:00:00+00:00"
    assert status["last_error"] is None
    assert status["restored_from_storage"] is True
    assert status["restored_at"] == "2026-01-02T00:00:00+00:00"
    assert status["restore_source"] == "latest"


def test_fresh_publish_clears_restored_status() -> None:
    store.set_artifact(
        obj="hello",
        kind="text",
        section="demo",
        label="message",
        view_id="demo:message",
    )

    store.mark_restored(
        view_id="demo:message",
        last_updated="2026-01-01T00:00:00+00:00",
        restored_at="2026-01-02T00:00:00+00:00",
        source="latest",
    )

    store.set_artifact(
        obj="fresh",
        kind="text",
        section="demo",
        label="message",
        view_id="demo:message",
    )

    status = store.get_status(view_id="demo:message")

    assert status["restored_from_storage"] is False
    assert status["restored_at"] is None
    assert status["restore_source"] is None
