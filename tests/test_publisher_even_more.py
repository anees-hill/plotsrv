# tests/test_publisher_even_more.py
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
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


def test_publish_view_http_error_swallowed_when_not_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)

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

    # should not raise
    pub.publish_view(pd.DataFrame({"a": [1]}), label="L", kind="table")


def test_publish_view_forced_plot_with_non_plot_obj_swallowed_when_not_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)

    # Should fail inside _to_publish_payload(kind="plot") -> _to_figure TypeError,
    # but publish_view should swallow when not debug.
    pub.publish_view({"not": "a figure"}, label="L", kind="plot")


def test_publish_artifact_pathlike_parse_error_publishes_text_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)

    # Make an invalid JSON file to trigger coerce_file_to_publishable -> json.loads error
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["data"] = req.data
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    pub.publish_artifact(p, label="L", section="S", host="127.0.0.1", port=8000)

    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "artifact"
    # This is the "file read/parse error" fallback branch
    assert payload["artifact_kind"] == "text"
    assert "[plotsrv] file read/parse error" in payload["artifact"]


def test_publish_artifact_infers_table_when_dataframe_and_kind_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_publish_view(obj: Any, **kwargs: Any) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(pub, "publish_view", fake_publish_view)

    df = pd.DataFrame({"a": [1]})
    pub.publish_artifact(df, label="L", section="S", host="127.0.0.1", port=8000)

    assert len(calls) == 1
    assert calls[0]["kind"] == "table"
