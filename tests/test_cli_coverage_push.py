# tests/test_cli_coverage_push.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import plotsrv.cli as cli_mod


class _FakePopen:
    def __init__(self) -> None:
        self._poll: int | None = None
        self.terminated = False
        self.killed = False
        self.wait_calls: int = 0

    def poll(self) -> int | None:
        return self._poll

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self._poll = 9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        # Simulate "didn't exit in time"
        raise TimeoutError("nope")


# ---------------------------------------------------------------------
# _callable_loop: periodic schedule + stop hook terminates current child
# ---------------------------------------------------------------------


def test_callable_loop_periodic_no_overlap_and_stop_hook_kills_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakePopen()

    # spawn returns a running proc (poll None)
    def fake_run_as_main(_target: str) -> _FakePopen:
        proc._poll = None
        return proc

    monkeypatch.setattr(cli_mod, "_run_subprocess_as_main", fake_run_as_main)
    monkeypatch.setattr(
        cli_mod, "_run_subprocess_call_importpath", lambda *a, **k: proc
    )

    # Capture the stop hook that callable loop registers
    stop_hook_box: dict[str, Any] = {}

    def fake_set_service_stop_hook(fn) -> None:
        stop_hook_box["fn"] = fn

    monkeypatch.setattr(
        cli_mod.store, "set_service_stop_hook", fake_set_service_stop_hook
    )

    # Avoid store side effects
    monkeypatch.setattr(cli_mod.store, "set_service_info", lambda **kwargs: None)

    # Make time advance so loop will attempt to spawn multiple times,
    # but we keep proc "running" so no-overlap prevents respawn.
    t = {"now": 1000.0}

    def fake_time() -> float:
        t["now"] += 1.0
        return t["now"]

    monkeypatch.setattr(cli_mod.time, "time", fake_time)

    # Make stop_event.wait() stop quickly after a few iterations
    stop_event = cli_mod.threading.Event()

    waits = {"n": 0}

    def fake_wait(timeout: float | None = None) -> bool:
        waits["n"] += 1
        if waits["n"] >= 5:
            stop_event.set()
        return stop_event.is_set()

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    # Run periodic loop briefly
    cli_mod._callable_loop(
        target="pkg.mod",
        host="127.0.0.1",
        port=8000,
        call_every=0.25,
        keep_alive=False,
        stop_event=stop_event,
    )

    # Ensure stop hook exists and works: it should terminate and then kill (due to wait timeout)
    assert "fn" in stop_hook_box
    proc._poll = None  # still running
    stop_hook_box["fn"]()
    assert proc.terminated is True
    assert proc.killed is True


# ---------------------------------------------------------------------
# _run_watch_mode: force a single loop then KeyboardInterrupt
# ---------------------------------------------------------------------


def test_run_watch_mode_text_path_publishes_then_keyboardinterrupt_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p = tmp_path / "x.txt"
    p.write_text("hello", encoding="utf-8")

    # Don't start real server
    monkeypatch.setattr(cli_mod, "publish_artifact", lambda *a, **k: None)

    # Patch server start/stop imported inside function
    monkeypatch.setitem(
        cli_mod.__dict__,
        "server",
        None,
    )

    # Monkeypatch the imported names via module attribute lookup inside function:
    # _run_watch_mode does: from .server import start_server, stop_server
    # so we patch plotsrv.cli.start_server/stop_server after import is resolved by Python
    monkeypatch.setattr(cli_mod, "start_server", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(cli_mod, "stop_server", lambda **kwargs: None, raising=False)

    # Force the loop to raise KeyboardInterrupt after first sleep
    def fake_sleep(_s: float) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli_mod.time, "sleep", fake_sleep)

    # Run
    rc = cli_mod._run_watch_mode(
        str(p),
        host="127.0.0.1",
        port=8000,
        every=0.01,
        kind="text",
        section="watch",
        label=None,
        view_id=None,
        max_bytes=200_000,
        encoding="utf-8",
        update_limit_s=None,
        force=False,
        quiet=True,
        read_mode="head",
    )
    assert rc == 0


def test_run_watch_mode_json_parse_error_publishes_text_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p = tmp_path / "x.json"
    p.write_text("{not json", encoding="utf-8")

    calls: list[dict[str, Any]] = []

    def fake_publish_artifact(obj: Any, **kwargs: Any) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(cli_mod, "publish_artifact", fake_publish_artifact)

    # Make json.loads always fail to guarantee JSON parse error path
    monkeypatch.setattr(
        cli_mod.json, "loads", lambda _s: (_ for _ in ()).throw(ValueError("boom"))
    )

    # Stop after one iteration
    monkeypatch.setattr(
        cli_mod.time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    # Patch server hooks
    monkeypatch.setattr(cli_mod, "start_server", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(cli_mod, "stop_server", lambda **kwargs: None, raising=False)

    rc = cli_mod._run_watch_mode(
        str(p),
        host="127.0.0.1",
        port=8000,
        every=0.01,
        kind="json",
        section="watch",
        label="L",
        view_id=None,
        max_bytes=200_000,
        encoding="utf-8",
        update_limit_s=10,
        force=True,
        quiet=True,
        read_mode="head",
    )
    assert rc == 0
    assert calls, "expected publish_artifact to be called"
    # should publish text error
    assert calls[0]["artifact_kind"] == "text"
    assert "JSON parse error" in str(calls[0]["obj"])


def test_run_watch_mode_auto_parse_error_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p = tmp_path / "x.whatever"
    p.write_text("hi", encoding="utf-8")

    calls: list[dict[str, Any]] = []

    def fake_publish_artifact(obj: Any, **kwargs: Any) -> None:
        calls.append({"obj": obj, **kwargs})

    monkeypatch.setattr(cli_mod, "publish_artifact", fake_publish_artifact)

    # Ensure auto mode uses coercer and coercer fails
    monkeypatch.setattr(
        cli_mod,
        "coerce_file_to_publishable",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")),
    )

    monkeypatch.setattr(
        cli_mod.time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    monkeypatch.setattr(cli_mod, "start_server", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(cli_mod, "stop_server", lambda **kwargs: None, raising=False)

    rc = cli_mod._run_watch_mode(
        str(p),
        host="127.0.0.1",
        port=8000,
        every=0.01,
        kind="auto",
        section="watch",
        label="L",
        view_id=None,
        max_bytes=200_000,
        encoding="utf-8",
        update_limit_s=None,
        force=False,
        quiet=True,
        read_mode="head",
    )
    assert rc == 0
    assert calls
    assert calls[0]["artifact_kind"] == "text"
    assert "parse error" in str(calls[0]["obj"])
