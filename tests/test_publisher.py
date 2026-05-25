from __future__ import annotations

import json
import urllib.request
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from plotsrv.publisher import publish_view


class DummyResp:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b"ok"


def test_publish_view_table_sends_json(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["headers"] = dict(req.headers)
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    df = pd.DataFrame({"a": [1, 2]})
    publish_view(df, host="127.0.0.1", port=8000, label="import", section="etl-1")

    assert captured["url"] == "http://127.0.0.1:8000/publish"
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "table"
    assert payload["label"] == "import"
    assert payload["section"] == "etl-1"
    assert "table" in payload
    assert payload["table"]["columns"] == ["a"]


def test_publish_view_plot_sends_b64_png(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    fig = plt.figure()
    publish_view(fig, label="metrics", host="127.0.0.1", port=8000)

    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "plot"
    assert payload["label"] == "metrics"
    assert "plot_png_b64" in payload


def test_publish_view_dict_sends_json_artifact(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    publish_view(
        {"status": "ok"},
        label="Status",
        section="ops",
        host="127.0.0.1",
        port=8000,
    )

    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "artifact"
    assert payload["artifact_kind"] == "json"
    assert payload["label"] == "Status"
    assert payload["section"] == "ops"

    doc = payload["artifact"]
    assert doc["type"] == "plotsrv_json_document"
    assert doc["source_format"] == "python_object"


def test_publish_view_string_sends_text_artifact(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    publish_view("hello", label="Message", host="127.0.0.1", port=8000)

    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "artifact"
    assert payload["artifact_kind"] == "text"
    assert payload["artifact"] == "hello"
    assert payload["label"] == "Message"


def test_publish_view_pathlike_file_publishes_file_content(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    p = tmp_path / "app.log"
    p.write_text("line one\nline two\n", encoding="utf-8")

    publish_view(p, label="Log", host="127.0.0.1", port=8000)

    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "artifact"
    assert payload["artifact_kind"] == "text"
    assert "line one" in payload["artifact"]


def test_publish_view_swallows_errors(monkeypatch) -> None:
    def fake_urlopen(*args, **kwargs):
        raise RuntimeError("no server")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # should not raise
    publish_view(pd.DataFrame({"a": [1]}), label="x", host="127.0.0.1", port=8000)


def test_publish_view_without_host_port_uses_local_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_start_server(**kwargs: Any) -> None:
        captured["start_server"] = kwargs

    def fake_refresh_view(obj: Any, **kwargs: Any) -> None:
        captured["obj"] = obj
        captured["kwargs"] = kwargs

    import plotsrv.server as srv

    monkeypatch.setattr(srv, "start_server", fake_start_server)
    monkeypatch.setattr(srv, "refresh_view", fake_refresh_view)

    df = pd.DataFrame({"a": [1, 2]})
    publish_view(df, label="Data", section="EDA")

    assert captured["start_server"] == {
        "host": "127.0.0.1",
        "port": 8000,
        "auto_on_show": True,
        "quiet": True,
        "announce": True,
    }
    assert captured["obj"] is df
    assert captured["kwargs"] == {
        "label": "Data",
        "section": "EDA",
        "view_id": None,
        "kind": None,
        "artifact_kind": None,
    }


def test_publish_view_without_label_allowed_in_local_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_start_server(**kwargs: Any) -> None:
        captured["start_server"] = kwargs

    def fake_refresh_view(obj: Any, **kwargs: Any) -> None:
        captured["obj"] = obj
        captured["kwargs"] = kwargs

    import plotsrv.server as srv

    monkeypatch.setattr(srv, "start_server", fake_start_server)
    monkeypatch.setattr(srv, "refresh_view", fake_refresh_view)

    df = pd.DataFrame({"a": [1]})
    publish_view(df)

    assert captured["start_server"] == {
        "host": "127.0.0.1",
        "port": 8000,
        "auto_on_show": True,
        "quiet": True,
        "announce": True,
    }
    assert captured["obj"] is df
    assert captured["kwargs"]["label"] is None
    assert captured["kwargs"]["section"] is None
    assert captured["kwargs"]["view_id"] is None


def test_publish_view_with_host_uses_remote_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    publish_view(
        pd.DataFrame({"a": [1]}),
        label="Remote",
        host="127.0.0.1",
    )

    assert captured["url"] == "http://127.0.0.1:8000/publish"
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["label"] == "Remote"
    assert payload["kind"] == "table"


def test_publish_view_with_port_uses_remote_http_default_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    publish_view(
        pd.DataFrame({"a": [1]}),
        label="Remote",
        port=9999,
    )

    assert captured["url"] == "http://127.0.0.1:9999/publish"


def test_publish_view_mode_local_uses_host_port_as_server_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def fake_start_server(**kwargs: Any) -> None:
        calls["start_server"] = kwargs

    def fake_refresh_view(obj: Any, **kwargs: Any) -> None:
        calls["refresh_view"] = {"obj": obj, **kwargs}

    import plotsrv.server as srv

    monkeypatch.setattr(srv, "start_server", fake_start_server)
    monkeypatch.setattr(srv, "refresh_view", fake_refresh_view)

    df = pd.DataFrame({"a": [1]})

    publish_view(
        df,
        mode="local",
        host="0.0.0.0",
        port=8998,
        label="Data",
        section="EDA",
    )

    assert calls["start_server"] == {
        "host": "0.0.0.0",
        "port": 8998,
        "auto_on_show": True,
        "quiet": True,
        "announce": True,
    }
    assert calls["refresh_view"]["obj"] is df
    assert calls["refresh_view"]["label"] == "Data"
    assert calls["refresh_view"]["section"] == "EDA"


def test_publish_view_mode_remote_without_host_port_uses_default_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    publish_view(
        pd.DataFrame({"a": [1]}),
        mode="remote",
        label="Remote",
    )

    assert captured["url"] == "http://127.0.0.1:8000/publish"
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "table"
    assert payload["label"] == "Remote"


def test_publish_view_invalid_mode_swallowed_when_not_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)

    # Should not raise.
    publish_view(pd.DataFrame({"a": [1]}), mode="bad")


def test_publish_view_invalid_mode_raises_in_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")

    with pytest.raises(ValueError, match="mode must be one of"):
        publish_view(pd.DataFrame({"a": [1]}), mode="bad")


def test_publish_view_launch_server_conflicting_port_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plotsrv.server as srv

    def fake_start_server(**kwargs: Any) -> None:
        raise RuntimeError(
            "plotsrv server already running on 127.0.0.1:8000; "
            "call plotsrv.stop_server() before starting a new one on a different host/port."
        )

    monkeypatch.setattr(srv, "start_server", fake_start_server)

    with pytest.raises(RuntimeError, match="stop_server"):
        publish_view(
            pd.DataFrame({"a": [1]}),
            launch_server=True,
            port=8999,
            label="Data",
        )
