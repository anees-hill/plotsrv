# tests/test_publisher_more.py
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

import plotsrv.publisher as pub


class DummyResp:
    def __enter__(self):  # noqa: D401
        return self

    def __exit__(self, *args: Any) -> bool:  # noqa: D401
        return False

    def read(self) -> bytes:
        return b"ok"


def test_is_na_scalar_vs_container() -> None:
    assert pub._is_na(float("nan")) is True
    assert pub._is_na(None) is True  # pandas treats None as NA
    # container must not be treated as scalar NA
    assert pub._is_na([1, 2, 3]) is False
    assert pub._is_na({"a": 1}) is False


def test_json_safe_handles_nested_dates_and_nans() -> None:
    x = {
        "a": float("nan"),
        "b": float("inf"),
        "c": -float("inf"),
        "d": datetime(2020, 1, 2, 3, 4, 5),
        "e": date(2020, 1, 2),
        "f": [1, 2, float("nan")],
        "g": {"h": "ok"},
    }

    out = pub._json_safe(x)
    assert out["a"] is None
    assert out["b"] is None
    assert out["c"] is None
    assert out["d"] == "2020-01-02T03:04:05"
    assert out["e"] == "2020-01-02"
    assert out["f"] == [1, 2, None]
    assert out["g"]["h"] == "ok"


def test_try_array_payload_numpy_if_available() -> None:
    np = pytest.importorskip("numpy")
    arr = np.arange(6).reshape(2, 3)
    payload = pub._try_array_payload(arr)
    assert payload is not None
    assert payload["type"] == "numpy.ndarray"
    assert payload["shape"] == [2, 3]
    assert payload["ndim"] == 2
    assert payload["truncated"] is False
    assert payload["data"] == arr.tolist()


def test_infer_artifact_kind_prefers_json_for_dict() -> None:
    assert pub._infer_artifact_kind({"a": 1}) == "json"
    assert pub._infer_artifact_kind("hello") == "text"
    assert pub._infer_artifact_kind(object()) == "python"


def test_publish_artifact_pathlike_json_file_posts_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    p = tmp_path / "x.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    pub.publish_artifact(p, label="L", section="S", host="127.0.0.1", port=8000)

    assert captured["url"] == "http://127.0.0.1:8000/publish"
    payload = json.loads(captured["data"].decode("utf-8"))

    assert payload["kind"] == "artifact"
    # json file should end up as artifact_kind json, artifact a dict
    assert payload["artifact_kind"] == "json"
    assert payload["artifact"] == {"a": 1}
    assert payload["label"] == "L"
    assert payload["section"] == "S"


def test_publish_artifact_pathlike_csv_routes_to_publish_view_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a\n1\n2\n", encoding="utf-8")

    calls: list[dict[str, Any]] = []

    def fake_publish_view(obj: Any, **kwargs: Any) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(pub, "publish_view", fake_publish_view)

    # no HTTP needed; should route to publish_view(kind="table")
    pub.publish_artifact(p, label="L", section="S", host="127.0.0.1", port=8000)

    assert len(calls) == 1
    assert calls[0]["kind"] == "table"
    assert calls[0]["label"] == "L"
    assert calls[0]["section"] == "S"
    df = calls[0]["obj"]
    assert list(df.columns) == ["a"]
    assert len(df) == 2


def test_publish_artifact_http_error_raises_in_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")

    class _FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                url="http://127.0.0.1:8000/publish",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=None,
            )

        def read(self) -> bytes:
            return b"bad payload"

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        raise _FakeHTTPError()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as e:
        pub.publish_artifact({"a": 1}, label="L", host="127.0.0.1", port=8000)

    assert "400" in str(e.value)
    assert "bad payload" in str(e.value)


def test_publish_view_http_error_raises_in_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")

    class _FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                url="http://127.0.0.1:8000/publish",
                code=500,
                msg="Server Error",
                hdrs=None,
                fp=None,
            )

        def read(self) -> bytes:
            return b"nope"

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        raise _FakeHTTPError()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # Use artifact publishing route via publish_view -> kind inferred as plot/table.
    # Simplest: pass a tiny DataFrame without pulling matplotlib.
    import pandas as pd

    with pytest.raises(RuntimeError) as e:
        pub.publish_view(
            pd.DataFrame({"a": [1]}),
            label="L",
            host="127.0.0.1",
            port=8000,
            kind="table",
        )

    assert "500" in str(e.value)
    assert "nope" in str(e.value)
