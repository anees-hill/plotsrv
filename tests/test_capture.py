# tests/test_capture.py
from __future__ import annotations

import pytest

import plotsrv.capture as cap_mod


def test_capture_exceptions_reraises_and_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    def fake_publish_traceback(exc: Exception, **kwargs: object) -> None:
        called["exc_type"] = type(exc).__name__
        called["kwargs"] = dict(kwargs)

    monkeypatch.setattr(cap_mod, "publish_traceback", fake_publish_traceback)

    with pytest.raises(RuntimeError):
        with cap_mod.capture_exceptions(
            label="L",
            section="S",
            view_id="S:L",
            host="127.0.0.1",
            port=8000,
            update_limit_s=5,
            force=True,
            reraise=True,
            options=None,
        ):
            raise RuntimeError("boom")

    assert called["exc_type"] == "RuntimeError"
    kwargs = called["kwargs"]
    assert kwargs["label"] == "L"
    assert kwargs["section"] == "S"
    assert kwargs["view_id"] == "S:L"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert kwargs["update_limit_s"] == 5
    assert kwargs["force"] is True
    assert kwargs["options"] is None


def test_capture_exceptions_no_reraise_still_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_publish_traceback(exc: Exception, **kwargs: object) -> None:
        calls.append(type(exc).__name__)

    monkeypatch.setattr(cap_mod, "publish_traceback", fake_publish_traceback)

    # should NOT raise
    with cap_mod.capture_exceptions(reraise=False):
        raise ValueError("nope")

    assert calls == ["ValueError"]
