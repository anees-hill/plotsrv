# tests/test_tracebacks.py
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import plotsrv.tracebacks as tb_mod


class DummyResp:
    def __enter__(self):  # noqa: D401
        return self

    def __exit__(self, *args: Any) -> bool:  # noqa: D401
        return False

    def read(self) -> bytes:
        return b"ok"


def _raise_here() -> None:
    # Keep this as a real source line for linecache context checks.
    x = 1  # noqa: F841
    raise ValueError("boom")


def test_build_traceback_payload_includes_frames_and_context() -> None:
    try:
        _raise_here()
    except Exception as e:
        payload = tb_mod._build_traceback_payload(
            e, options=tb_mod.TracebackPublishOptions(context_lines=1, max_frames=50)
        )

    assert payload["type"] == "traceback"
    assert payload["exc_type"] == "ValueError"
    assert "boom" in payload["exc_msg"]

    frames = payload["frames"]
    assert isinstance(frames, list)
    assert len(frames) >= 1

    top = frames[-1]  # last frame should be where raise occurred
    assert "filename" in top and "lineno" in top and "function" in top
    assert isinstance(top["context_before"], list)
    assert isinstance(top["context_after"], list)
    # context_lines=1 -> at most 1 each side
    assert len(top["context_before"]) <= 1
    assert len(top["context_after"]) <= 1


def test_publish_traceback_remote_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["headers"] = dict(req.headers)
        return DummyResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    try:
        _raise_here()
    except Exception as e:
        tb_mod.publish_traceback(
            e,
            host="127.0.0.1",
            port=8000,
            label="L",
            section="S",
            view_id="S:L",
            update_limit_s=3,
            force=True,
            options=tb_mod.TracebackPublishOptions(context_lines=0, max_frames=1),
        )

    assert captured["url"] == "http://127.0.0.1:8000/publish"
    post = json.loads(captured["data"].decode("utf-8"))
    assert post["kind"] == "artifact"
    assert post["artifact_kind"] == "traceback"
    assert post["label"] == "L"
    assert post["section"] == "S"
    assert post["view_id"] == "S:L"
    assert post["update_limit_s"] == 3
    assert post["force"] is True
    assert post["artifact"]["type"] == "traceback"
    # max_frames=1
    assert len(post["artifact"]["frames"]) <= 1


def test_publish_traceback_inprocess_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def fake_set_artifact(
        *,
        obj: Any,
        kind: str,
        label: str | None,
        section: str | None,
        view_id: str | None,
        truncation: Any,
    ):
        calls["set_artifact"] = {
            "obj": obj,
            "kind": kind,
            "label": label,
            "section": section,
            "view_id": view_id,
        }

    def fake_mark_error(msg: str, *, view_id: str | None = None) -> None:
        calls["mark_error"] = {"msg": msg, "view_id": view_id}

    monkeypatch.setattr(tb_mod.store, "set_artifact", fake_set_artifact)
    monkeypatch.setattr(tb_mod.store, "mark_error", fake_mark_error)

    try:
        _raise_here()
    except Exception as e:
        tb_mod.publish_traceback(e, label="L", section="S", view_id="S:L")

    assert calls["set_artifact"]["kind"] == "traceback"
    assert calls["set_artifact"]["label"] == "L"
    assert calls["set_artifact"]["section"] == "S"
    assert calls["set_artifact"]["view_id"] == "S:L"
    assert calls["mark_error"]["view_id"] == "S:L"
    assert "ValueError" in calls["mark_error"]["msg"]
