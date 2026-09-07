from __future__ import annotations

import pandas as pd
import pytest
from datetime import datetime, timedelta, timezone
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


def test_watched_file_meta_round_trip() -> None:
    meta = store.WatchedFileMeta(
        view_id="watch:app.log",
        path="/tmp/app.log",
        file_kind="text",
        read_mode="tail",
        encoding="utf-8",
        materialization="file",
        size_bytes=123,
        mtime_ns=456,
        max_bytes=100,
        last_checked_at="2026-01-01T00:00:00+00:00",
        last_read_at=None,
        last_error=None,
    )

    store.register_view(
        view_id="watch:app.log",
        section="watch",
        label="app.log",
        kind="artifact",
    )

    assert store.has_watched_file_meta(view_id="watch:app.log") is False

    store.set_watched_file_meta(meta)

    assert store.has_watched_file_meta(view_id="watch:app.log") is True
    assert store.get_watched_file_meta(view_id="watch:app.log") == meta


def test_get_watched_file_meta_raises_when_missing() -> None:
    store.register_view(
        view_id="watch:missing.log",
        section="watch",
        label="missing.log",
        kind="artifact",
    )

    with pytest.raises(LookupError):
        store.get_watched_file_meta(view_id="watch:missing.log")


def test_clear_watched_file_meta() -> None:
    meta = store.WatchedFileMeta(
        view_id="watch:app.log",
        path="/tmp/app.log",
        file_kind="text",
        read_mode="tail",
        encoding="utf-8",
        materialization="file",
    )

    store.set_watched_file_meta(meta)

    assert store.has_watched_file_meta(view_id="watch:app.log") is True

    store.clear_watched_file_meta(view_id="watch:app.log")

    assert store.has_watched_file_meta(view_id="watch:app.log") is False


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


def test_plain_watch_error_uses_exception_icon() -> None:
    store.set_artifact(obj="Could not read file", kind="watch_error", view_id="ops:watch-error")
    views = {v.view_id: v for v in store.list_views()}
    assert views["ops:watch-error"].icon_key == "exception"


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


def _make_old_last_updated(seconds_ago: int = 120) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def test_freshness_global_applies_to_normal_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store.config, "get_freshness_enabled", lambda: True)
    monkeypatch.setattr(
        store.config, "get_freshness_view_enabled", lambda view_id: True
    )
    monkeypatch.setattr(
        store.config, "has_freshness_view_config", lambda view_id: False
    )
    monkeypatch.setattr(
        store.config, "get_freshness_expected_every_s", lambda view_id=None: 1
    )
    monkeypatch.setattr(
        store.config, "get_freshness_warn_after_s", lambda view_id=None: 1
    )
    monkeypatch.setattr(
        store.config, "get_freshness_overdue_after_s", lambda view_id=None: 2
    )

    vid = "normal:view"
    store.set_artifact(
        obj="hello",
        kind="text",
        section="normal",
        label="view",
        view_id=vid,
    )
    store.get_view_state(vid).status["last_updated"] = _make_old_last_updated(120)

    out = store.get_freshness(view_id=vid)

    assert out["enabled"] is True
    assert out["state"] == "error"
    assert out["publish_source"] == "normal"
    assert out["source_disabled"] is False


def test_freshness_global_does_not_apply_to_watch_publish_without_view_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store.config, "get_freshness_enabled", lambda: True)
    monkeypatch.setattr(
        store.config, "get_freshness_view_enabled", lambda view_id: True
    )
    monkeypatch.setattr(
        store.config, "has_freshness_view_config", lambda view_id: False
    )
    monkeypatch.setattr(
        store.config, "get_freshness_expected_every_s", lambda view_id=None: 1
    )
    monkeypatch.setattr(
        store.config, "get_freshness_warn_after_s", lambda view_id=None: 1
    )
    monkeypatch.setattr(
        store.config, "get_freshness_overdue_after_s", lambda view_id=None: 2
    )

    vid = "watch:log"
    store.set_artifact(
        obj="hello",
        kind="text",
        section="watch",
        label="log",
        view_id=vid,
        publish_source="watch",
    )
    store.get_view_state(vid).status["last_updated"] = _make_old_last_updated(120)

    out = store.get_freshness(view_id=vid)

    assert out["enabled"] is False
    assert out["state"] == "disabled"
    assert out["publish_source"] == "watch"
    assert out["source_disabled"] is True
    assert out["reason"] == "watch_source_without_view_freshness"


def test_freshness_view_config_opts_watch_publish_into_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store.config, "get_freshness_enabled", lambda: True)
    monkeypatch.setattr(
        store.config, "get_freshness_view_enabled", lambda view_id: True
    )
    monkeypatch.setattr(store.config, "has_freshness_view_config", lambda view_id: True)
    monkeypatch.setattr(
        store.config, "get_freshness_expected_every_s", lambda view_id=None: 1
    )
    monkeypatch.setattr(
        store.config, "get_freshness_warn_after_s", lambda view_id=None: 1
    )
    monkeypatch.setattr(
        store.config, "get_freshness_overdue_after_s", lambda view_id=None: 2
    )

    vid = "watch:log"
    store.set_artifact(
        obj="hello",
        kind="text",
        section="watch",
        label="log",
        view_id=vid,
        publish_source="watch",
    )
    store.get_view_state(vid).status["last_updated"] = _make_old_last_updated(120)

    out = store.get_freshness(view_id=vid)

    assert out["enabled"] is True
    assert out["state"] == "error"
    assert out["publish_source"] == "watch"
    assert out["source_disabled"] is False


def test_publish_source_is_normalised_on_status() -> None:
    vid = "watch:source"
    store.set_artifact(
        obj="hello",
        kind="text",
        section="watch",
        label="source",
        view_id=vid,
        publish_source=" WATCH ",
    )

    status = store.get_status(view_id=vid)

    assert status["publish_source"] == "watch"
