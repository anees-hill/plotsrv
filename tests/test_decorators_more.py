# tests/test_decorators_more.py
from __future__ import annotations

from typing import Any

import pytest

import plotsrv.decorators as dec


def test_escape_repr_truncates() -> None:
    s = "x" * 1100
    out = dec._escape_repr(s, max_chars=1000)

    assert out.startswith("x" * 1000)
    assert out.endswith("…")
    assert len(out) == 1001


def test_on_error_publish_swallows_when_port_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tb_calls: list[dict[str, Any]] = []

    def fake_publish_traceback(exc: Exception, **kwargs: Any) -> None:
        tb_calls.append({"exc_type": type(exc).__name__, **kwargs})

    monkeypatch.setattr(dec, "publish_traceback", fake_publish_traceback)

    @dec.view(port=8000, on_error="publish")
    def boom() -> int:
        raise ValueError("x")

    out = boom()

    assert out is None
    assert tb_calls == [
        {
            "exc_type": "ValueError",
            "label": "boom",
            "section": None,
            "host": "127.0.0.1",
            "port": 8000,
        }
    ]


def test_on_error_publish_swallows_when_launch_server_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tb_calls: list[dict[str, Any]] = []

    def fake_publish_traceback(exc: Exception, **kwargs: Any) -> None:
        tb_calls.append({"exc_type": type(exc).__name__, **kwargs})

    monkeypatch.setattr(dec, "publish_traceback", fake_publish_traceback)

    @dec.view(launch_server=True, on_error="publish")
    def boom() -> int:
        raise ValueError("x")

    out = boom()

    assert out is None
    assert tb_calls == [
        {
            "exc_type": "ValueError",
            "label": "boom",
            "section": None,
            "host": "127.0.0.1",
            "port": 8000,
        }
    ]


def test_on_error_publish_and_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    tb_calls: list[str] = []

    def fake_publish_traceback(exc: Exception, **kwargs: object) -> None:
        tb_calls.append(type(exc).__name__)

    monkeypatch.setattr(dec, "publish_traceback", fake_publish_traceback)

    @dec.view(port=8000, on_error="publish_and_raise")
    def boom() -> int:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        boom()

    assert tb_calls == ["RuntimeError"]


def test_on_error_raise_does_not_publish_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tb_calls: list[str] = []

    def fake_publish_traceback(exc: Exception, **kwargs: object) -> None:
        tb_calls.append(type(exc).__name__)

    monkeypatch.setattr(dec, "publish_traceback", fake_publish_traceback)

    @dec.view(port=8000, on_error="raise")
    def boom() -> int:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        boom()

    assert tb_calls == []


def test_debug_env_reraises_publish_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLOTSRV_DEBUG", "1")

    def fake_publish_view(*args: object, **kwargs: object) -> None:
        raise RuntimeError("publish failed")

    monkeypatch.setattr(dec, "publish_view", fake_publish_view)

    @dec.view(launch_server=True)
    def ok() -> int:
        return 1

    with pytest.raises(RuntimeError, match="publish failed"):
        ok()


def test_publish_failures_are_swallowed_when_not_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLOTSRV_DEBUG", raising=False)

    def fake_publish_view(*args: object, **kwargs: object) -> None:
        raise RuntimeError("publish failed")

    monkeypatch.setattr(dec, "publish_view", fake_publish_view)

    @dec.view(launch_server=True)
    def ok() -> int:
        return 1

    assert ok() == 1


def test_view_class_wrap_publishes_json_when_port_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_publish_view(obj: object, **kwargs: object) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(dec, "publish_view", fake_publish_view)

    @dec.view(port=8000, label="MyCls", section="sec")
    class MyCls:
        def __init__(self, x: int) -> None:
            self.x = x

    inst = MyCls(5)

    assert inst.x == 5
    assert len(calls) == 1
    assert calls[0]["label"] == "MyCls"
    assert calls[0]["section"] == "sec"
    assert calls[0]["host"] is None
    assert calls[0]["port"] == 8000
    assert calls[0]["launch_server"] is False
    assert calls[0]["artifact_kind"] == "json"
    assert isinstance(calls[0]["obj"], dict)
    assert calls[0]["obj"]["class"] == "MyCls"


def test_view_class_wrap_publishes_json_when_launch_server_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_publish_view(obj: object, **kwargs: object) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(dec, "publish_view", fake_publish_view)

    @dec.view(launch_server=True, label="MyCls", section="sec")
    class MyCls:
        def __init__(self, x: int) -> None:
            self.x = x

    inst = MyCls(5)

    assert inst.x == 5
    assert len(calls) == 1
    assert calls[0]["label"] == "MyCls"
    assert calls[0]["section"] == "sec"
    assert calls[0]["host"] is None
    assert calls[0]["port"] is None
    assert calls[0]["launch_server"] is True
    assert calls[0]["artifact_kind"] == "json"
    assert isinstance(calls[0]["obj"], dict)
    assert calls[0]["obj"]["class"] == "MyCls"


def test_view_class_does_not_wrap_when_passive_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_publish_view(obj: object, **kwargs: object) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(dec, "publish_view", fake_publish_view)

    @dec.view(label="MyCls", section="sec")
    class MyCls:
        def __init__(self, x: int) -> None:
            self.x = x

    inst = MyCls(5)

    assert inst.x == 5
    assert calls == []


def test_inspect_instance_limits_attrs() -> None:
    class ManyAttrs:
        pass

    obj = ManyAttrs()
    for i in range(205):
        setattr(obj, f"x{i}", i)

    out = dec._inspect_instance(obj)

    assert out["kind"] == "instance"
    assert out["class"] == "ManyAttrs"
    assert isinstance(out["attrs"], dict)
    assert "…" in out["attrs"]
