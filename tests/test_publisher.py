from __future__ import annotations

import json
import urllib.request
import pandas as pd
import pytest
import matplotlib.pyplot as plt

from plotsrv.publisher import publish_view

class DummyResp:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return b"ok"

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
    publish_view(fig, label="metrics")

    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["kind"] == "plot"
    assert payload["label"] == "metrics"
    assert "plot_png_b64" in payload


def test_publish_view_swallows_errors(monkeypatch) -> None:
    def fake_urlopen(*args, **kwargs):
        raise RuntimeError("no server")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # should not raise
    publish_view(pd.DataFrame({"a": [1]}), label="x")
