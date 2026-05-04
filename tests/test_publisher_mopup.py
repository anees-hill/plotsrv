from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import plotsrv.publisher as pub


class DummyResp:
    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def read(self) -> bytes:
        return b"ok"


def test_to_dataframe_with_pandas() -> None:
    df = pd.DataFrame({"a": [1]})
    out = pub._to_dataframe(df)
    assert out is df


def test_to_dataframe_raises_for_non_dataframe() -> None:
    with pytest.raises(TypeError):
        pub._to_dataframe({"a": 1})


def test_to_figure_none_uses_current_figure() -> None:
    plt = pytest.importorskip("matplotlib.pyplot")
    fig = plt.figure()
    out = pub._to_figure(None)
    assert out is fig
    plt.close(fig)


def test_to_figure_accepts_matplotlib_figure() -> None:
    plt = pytest.importorskip("matplotlib.pyplot")
    fig = plt.figure()
    out = pub._to_figure(fig)
    assert out is fig
    plt.close(fig)


def test_to_figure_rejects_bad_object() -> None:
    with pytest.raises(TypeError):
        pub._to_figure({"no": "plot"})


def test_looks_like_plot_variants() -> None:
    plt = pytest.importorskip("matplotlib.pyplot")
    fig = plt.figure()
    assert pub._looks_like_plot(None) is True
    assert pub._looks_like_plot(fig) is True
    assert pub._looks_like_plot({"x": 1}) is False
    plt.close(fig)


def test_json_safe_primitives_and_fallback_repr() -> None:
    class X:
        def __str__(self) -> str:
            return "X!"

    assert pub._json_safe("a") == "a"
    assert pub._json_safe(1) == 1
    assert pub._json_safe(True) is True
    assert pub._json_safe(date(2020, 1, 1)) == "2020-01-01"
    assert pub._json_safe(datetime(2020, 1, 1, 1, 2, 3)) == "2020-01-01T01:02:03"
    assert pub._json_safe(X()) == "X!"


def test_to_publish_payload_table_contains_table_and_html() -> None:
    df = pd.DataFrame({"a": [1, 2]})
    payload = pub._to_publish_payload(
        df,
        kind="table",
        label="L",
        section="S",
        update_limit_s=10,
        force=True,
    )
    assert payload["kind"] == "table"
    assert payload["label"] == "L"
    assert payload["section"] == "S"
    assert payload["update_limit_s"] == 10
    assert payload["force"] is True
    assert "table" in payload
    assert "table_html_simple" in payload


def test_to_publish_payload_artifact_html_dict() -> None:
    payload = pub._to_publish_payload(
        {"html": "<div>x</div>", "unsafe": True},
        kind="artifact",
        label="L",
        section="S",
        update_limit_s=None,
        force=False,
    )
    assert payload["artifact_kind"] == "html"
    assert payload["artifact"]["html"] == "<div>x</div>"


def test_to_publish_payload_artifact_bytes_defaults_to_python_repr() -> None:
    payload = pub._to_publish_payload(
        b"hello",
        kind="artifact",
        label="L",
        section=None,
        update_limit_s=None,
        force=False,
    )
    assert payload["artifact_kind"] == "python"
    assert payload["artifact"] == repr(b"hello")


def test_to_publish_payload_artifact_json_array_payload_if_numpy_available() -> None:
    np = pytest.importorskip("numpy")
    arr = np.arange(5)
    payload = pub._to_publish_payload(
        arr,
        kind="artifact",
        label="L",
        section=None,
        update_limit_s=None,
        force=False,
    )
    assert payload["artifact_kind"] == "json"
    doc = payload["artifact"]
    assert doc["type"] == "plotsrv_json_document"
    assert doc["source_format"] == "python_object"

    root = doc["root"]
    children = {ch["display_key"]: ch for ch in root["children"]}
    assert children["type"]["full_value"] == "numpy.ndarray"
    assert children["size"]["full_value"] == "5"


def test_to_publish_payload_artifact_python_repr() -> None:
    class X:
        pass

    payload = pub._to_publish_payload(
        X(),
        kind="artifact",
        label="L",
        section=None,
        update_limit_s=None,
        force=False,
    )
    assert payload["artifact_kind"] == "python"
    assert "X object" in payload["artifact"]


def test_publish_artifact_html_string_becomes_html_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    pub.publish_artifact("<div>x</div>", label="L", artifact_kind="html")
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["artifact_kind"] == "html"
    assert payload["artifact"]["html"] == "<div>x</div>"


def test_publish_artifact_pathlike_html_recurses_as_html(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    p = tmp_path / "x.html"
    p.write_text("<div>x</div>", encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    pub.publish_artifact(p, label="L", section="S", artifact_kind="html")
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["artifact_kind"] == "html"
    assert payload["artifact"]["html"] == "<div>x</div>"


def test_publish_artifact_infers_plot_when_kind_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plt = pytest.importorskip("matplotlib.pyplot")
    fig = plt.figure()

    calls: list[dict[str, Any]] = []

    def fake_publish_view(obj: Any, **kwargs: Any) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(pub, "publish_view", fake_publish_view)

    pub.publish_artifact(fig, label="L", section="S")
    assert calls
    assert calls[0]["kind"] == "plot"
    plt.close(fig)


def test_publish_artifact_forced_artifact_kind_overrides_inferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    pub.publish_artifact({"a": 1}, label="L", artifact_kind="python")
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["artifact_kind"] == "python"


def test_publish_artifact_returns_silently_on_json_dump_failure_when_not_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)

    class Bad:
        pass

    monkeypatch.setattr(pub, "_json_safe", lambda x: {"a": {1, 2, 3}})
    pub.publish_artifact(Bad(), label="L")  # no raise


def test_publish_view_returns_silently_on_json_dump_failure_when_not_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)
    monkeypatch.setattr(pub, "_json_safe", lambda x: {"a": {1, 2, 3}})
    pub.publish_view(pd.DataFrame({"a": [1]}), label="L", kind="table")  # no raise


def test_publish_artifact_debug_reraises_json_dump_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")
    monkeypatch.setattr(pub, "_json_safe", lambda x: {"a": {1, 2, 3}})
    with pytest.raises(TypeError):
        pub.publish_artifact({"a": 1}, label="L")


def test_publish_view_debug_reraises_payload_build_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")
    with pytest.raises(TypeError):
        pub.publish_view({"bad": "plot"}, label="L", kind="plot")


def test_plot_launch_delegates_to_publish_view(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_publish_view(obj: Any, **kwargs: Any) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(pub, "publish_view", fake_publish_view)

    pub.plot_launch(
        "OBJ", label="L", section="S", host="h", port=9, update_limit_s=10, force=True
    )
    assert calls == [
        {
            "obj": "OBJ",
            "host": "h",
            "port": 9,
            "label": "L",
            "section": "S",
            "update_limit_s": 10,
            "force": True,
        }
    ]
