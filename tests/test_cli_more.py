# tests/test_cli_more.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import plotsrv.cli as cli_mod


# ----------------------------
# Project root detection
# ----------------------------


def test_find_project_root_pyproject(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    sub = root / "a" / "b"
    sub.mkdir(parents=True)

    assert cli_mod._find_project_root(sub) == root.resolve()


def test_find_project_root_git(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()

    sub = root / "a"
    sub.mkdir()

    assert cli_mod._find_project_root(sub) == root.resolve()


def test_default_run_target_raises_when_no_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # empty dir, no markers
    with pytest.raises(ValueError):
        _ = cli_mod._default_run_target()


def test_default_run_target_uses_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    sub = root / "x" / "y"
    sub.mkdir(parents=True)

    monkeypatch.chdir(sub)
    assert cli_mod._default_run_target() == str(root.resolve())


# ----------------------------
# Importable target resolution
# ----------------------------


@dataclass
class _FakeSpec:
    origin: str | None = None
    submodule_search_locations: list[str] | None = None


def test_resolve_target_to_path_if_importable_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    modfile = tmp_path / "m.py"
    modfile.write_text("x=1\n", encoding="utf-8")

    def fake_find_spec(name: str) -> Any:
        assert name == "pkg.mod"
        return _FakeSpec(origin=str(modfile), submodule_search_locations=None)

    monkeypatch.setattr(cli_mod.importlib.util, "find_spec", fake_find_spec)

    assert cli_mod._resolve_target_to_path_if_importable("pkg.mod") == str(
        modfile.resolve()
    )


def test_resolve_target_to_path_if_importable_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pkgdir = tmp_path / "pkg"
    pkgdir.mkdir()

    def fake_find_spec(name: str) -> Any:
        assert name == "pkg"
        return _FakeSpec(origin=None, submodule_search_locations=[str(pkgdir)])

    monkeypatch.setattr(cli_mod.importlib.util, "find_spec", fake_find_spec)

    assert cli_mod._resolve_target_to_path_if_importable("pkg") == str(pkgdir.resolve())


def test_resolve_target_to_path_if_importable_ignores_module_fn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If ":" present, function returns None without calling find_spec
    called = {"n": 0}

    def fake_find_spec(_name: str) -> Any:
        called["n"] += 1
        return None

    monkeypatch.setattr(cli_mod.importlib.util, "find_spec", fake_find_spec)
    assert cli_mod._resolve_target_to_path_if_importable("pkg.mod:fn") is None
    assert called["n"] == 0


# ----------------------------
# Scan root resolution
# ----------------------------


def test_resolve_scan_root_for_passive_prefers_existing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "src"
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    assert cli_mod._resolve_scan_root_for_passive("src") == str(root.resolve())


def test_resolve_scan_root_for_passive_importable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # not a path -> uses importable resolution
    modfile = tmp_path / "m.py"
    modfile.write_text("x=1\n", encoding="utf-8")

    monkeypatch.setattr(
        cli_mod,
        "_resolve_target_to_path_if_importable",
        lambda _t: str(modfile.resolve()),
    )
    monkeypatch.setattr(cli_mod, "_resolve_module_part", lambda t: t)  # keep stable

    assert cli_mod._resolve_scan_root_for_passive("pkg.mod") == str(modfile.resolve())


def test_resolve_scan_root_for_passive_falls_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli_mod, "_resolve_target_to_path_if_importable", lambda _t: None
    )
    # ensure it thinks it isn't a path
    assert cli_mod._resolve_scan_root_for_passive("def-not-a-path") == str(
        tmp_path.resolve()
    )


# ----------------------------
# Subprocess helpers (no real processes)
# ----------------------------


class _FakePopen:
    def __init__(self, cmd: list[str]) -> None:
        self.cmd = cmd
        self._poll = None
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self) -> int | None:
        return self._poll

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self._poll = 9

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        self._poll = 0
        return 0


def test_run_subprocess_as_main_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "x.py"
    f.write_text("print('x')\n", encoding="utf-8")

    popens: list[_FakePopen] = []

    def fake_popen(cmd: list[str]) -> _FakePopen:
        p = _FakePopen(cmd)
        popens.append(p)
        return p

    monkeypatch.setattr(cli_mod.subprocess, "Popen", fake_popen)

    p = cli_mod._run_subprocess_as_main(str(f))
    assert isinstance(p, _FakePopen)
    assert popens[0].cmd[:2] == [cli_mod.sys.executable, str(f)]


def test_run_subprocess_as_main_module(monkeypatch: pytest.MonkeyPatch) -> None:
    popens: list[_FakePopen] = []

    def fake_popen(cmd: list[str]) -> _FakePopen:
        p = _FakePopen(cmd)
        popens.append(p)
        return p

    monkeypatch.setattr(cli_mod.subprocess, "Popen", fake_popen)

    p = cli_mod._run_subprocess_as_main("pkg.mod")
    assert isinstance(p, _FakePopen)
    assert popens[0].cmd[:3] == [cli_mod.sys.executable, "-m", "pkg.mod"]


def test_run_subprocess_call_importpath_builds_python_c(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popens: list[_FakePopen] = []

    def fake_popen(cmd: list[str]) -> _FakePopen:
        p = _FakePopen(cmd)
        popens.append(p)
        return p

    monkeypatch.setattr(cli_mod.subprocess, "Popen", fake_popen)

    _ = cli_mod._run_subprocess_call_importpath(
        "pkg.mod:fn", host="127.0.0.1", port=8000
    )
    cmd = popens[0].cmd

    assert cmd[0] == cli_mod.sys.executable
    assert cmd[1] == "-c"
    # sanity: embedded script should mention publish_traceback
    assert "publish_traceback" in cmd[2]
    assert cmd[-3:] == ["pkg.mod:fn", "127.0.0.1", "8000"]


# ----------------------------
# Callable loop control flow (fast)
# ----------------------------


def test_callable_loop_runs_once_and_clears_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make _run_subprocess_as_main return a proc that completes immediately.
    proc = _FakePopen([cli_mod.sys.executable, "-m", "x"])
    proc._poll = 0  # already finished

    monkeypatch.setattr(cli_mod, "_run_subprocess_as_main", lambda _t: proc)
    monkeypatch.setattr(
        cli_mod, "_run_subprocess_call_importpath", lambda *a, **k: proc
    )

    # Spy service info calls
    calls: list[tuple[bool, str | None, int | None]] = []

    def fake_set_service_info(
        *, service_mode: bool, target: str | None, refresh_rate_s: int | None
    ) -> None:
        calls.append((service_mode, target, refresh_rate_s))

    monkeypatch.setattr(cli_mod.store, "set_service_info", fake_set_service_info)
    monkeypatch.setattr(cli_mod.store, "set_service_stop_hook", lambda _fn: None)

    stop = cli_mod.threading.Event()
    cli_mod._callable_loop(
        target="pkg.mod",
        host="127.0.0.1",
        port=8000,
        call_every=None,
        keep_alive=False,
        stop_event=stop,
    )

    # Should set service on then off
    assert calls[0][0] is True
    assert calls[-1] == (False, None, None)
