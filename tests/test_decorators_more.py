# tests/test_decorators_more.py
from __future__ import annotations

import os

import pytest

import plotsrv.decorators as dec


def test_escape_repr_truncates() -> None:
    s = "x" * 1100
    out = dec._escape_repr(s, max_chars=1000)
    assert out.startswith("x" * 1000)
    assert out.endswith("…")
    assert len(out) == 1001


def test_on_error_publish_swallows(monkeypatch: pytest.MonkeyPatch) -> None:
    tb_calls: list[str] = []

    def fake_publish_traceback(exc: Exception, **kwargs: object) -> None:
        tb_calls.append(type(exc).__name__)

    monkeypatch.setattr(dec, "publish_traceback", fake_publish_traceback)

    @dec.plot(port=8000, on_error="publish")
    def boom() -> int:
        raise ValueError("x")

    out = boom()
    assert out is None
    assert tb_calls == ["ValueError"]


def test_on_error_publish_and_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    tb_calls: list[str] = []

    def fake_publish_traceback(exc: Exception, **kwargs: object) -> None:
        tb_calls.append(type(exc).__name__)

    monkeypatch.setattr(dec, "publish_traceback", fake_publish_traceback)

    @dec.table(port=8000, on_error="publish_and_raise")
    def boom() -> int:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        boom()

    assert tb_calls == ["RuntimeError"]


def test_debug_env_reraises_publish_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    # If publish_view fails and PLOTSRV_DEBUG=1, wrapper should raise.
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")

    def fake_publish_view(*args: object, **kwargs: object) -> None:
        raise RuntimeError("publish failed")

    monkeypatch.setattr(dec, "publish_view", fake_publish_view)

    @dec.plot(port=8000)
    def ok() -> int:
        return 1

    with pytest.raises(RuntimeError):
        ok()


def test_plotsrv_class_wrap_publishes_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_publish_artifact(obj: object, **kwargs: object) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(dec, "publish_artifact", fake_publish_artifact)

    @dec.plotsrv(port=8000, label="MyCls", section="sec")
    class MyCls:
        def __init__(self, x: int) -> None:
            self.x = x

    inst = MyCls(5)
    assert inst.x == 5

    assert len(calls) == 1
    assert calls[0]["label"] == "MyCls"
    assert calls[0]["section"] == "sec"
    assert calls[0]["artifact_kind"] == "json"
    assert isinstance(calls[0]["obj"], dict)
    assert calls[0]["obj"]["class"] == "MyCls"
