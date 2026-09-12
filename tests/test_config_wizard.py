from __future__ import annotations

import asyncio
import builtins
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace

import pytest

from plotsrv import settings
from plotsrv.cli_parser import build_parser
from plotsrv.config_wizard import launch
from plotsrv.config_wizard.draft import Draft, FIELDS, FieldSpec, MAX_CONFIG_BYTES
from plotsrv.config_wizard.scanning import ScanJob
from plotsrv.discovery import DiscoveryProgress, scan_sources


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    import urllib.request
    import requests

    def no_network(*args, **kwargs):
        pytest.fail("Wizard must not contact any endpoint")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(requests.Session, "request", no_network)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    (tmp_path / "app.py").write_text(
        "from plotsrv import view\n"
        "raise RuntimeError('never execute this project')\n"
        "@view(label='Alpha', section='A', view_id='exact:A')\n"
        "def one(): pass\n"
        "@view(label='Beta', section='B', view_id='exact:B')\n"
        "def two(): pass\n"
        "@view(label='Gamma', section='B', view_id='exact:C')\n"
        "def three(): pass\n"
    )
    return tmp_path


def ui():
    pytest.importorskip(
        "textual", reason="install plotsrv[config] for keyboard harness tests"
    )
    from plotsrv.config_wizard.tui import ConfigWizard

    return ConfigWizard


async def until(pilot, predicate):
    for _ in range(150):
        if predicate():
            await pilot.pause()
            return
        await pilot.pause(0.02)
    raise AssertionError("Wizard did not reach expected state")


def test_parser_and_non_tty_do_not_load_ui(monkeypatch, capsys):
    args = build_parser().parse_args(["config", "init", "pkg", "--name", "etl"])
    assert args.target == "pkg" and args.name == "etl" and args.config is None
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert launch(args) == 2
    assert "interactive terminal" in capsys.readouterr().err


def test_optional_dependency_absent(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    real_import = builtins.__import__

    def absent(name, *args, **kwargs):
        if name == "tui" or name.startswith("textual"):
            raise ModuleNotFoundError("absent", name="textual")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent)
    assert launch(SimpleNamespace(config=None, name=None, target=None)) == 2
    assert "plotsrv[config]" in capsys.readouterr().err


def test_core_and_cli_have_no_textual_import():
    script = """
import sys
import plotsrv
import plotsrv.cli
import plotsrv.config_wizard
assert not any(k == 'textual' or k.startswith('textual.') for k in sys.modules)
assert 'plotsrv.config_wizard.tui' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=20)


def test_path_precedence_and_instance_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Draft.load().path == tmp_path / "plotsrv.yml"
    yaml = tmp_path / "plotsrv.yaml"
    yaml.write_text("publisher-settings:\n  discovery:\n    target: src\n")
    assert Draft.load().path == yaml
    yml = tmp_path / "plotsrv.yml"
    yml.write_text(
        "publisher-settings:\n  default:\n    destination:\n      url: https://server/base\n  instances:\n    etl:\n      destination:\n        bearer_token_env: MISSING_KEY\n"
    )
    draft = Draft.load(name="etl")
    assert draft.path == yml
    assert draft.value(FIELDS["destination"]) == "https://server/base/"
    assert draft.value(FIELDS["bearer"]) == "MISSING_KEY"
    assert settings._CTX.config_path is None
    monkeypatch.setenv("PLOTSRV_CONFIG", str(yaml))
    assert Draft.load().path == yaml
    assert Draft.load(config=yml).path == yml


@pytest.mark.parametrize(
    "raw",
    [
        b"x: [",
        b"x: 1\nx: 2",
        b"[1,2]",
        b"x: &a [*a]",
        b"x: " + b"[" * 40 + b"]" * 40,
        b"x: !!python/object:foo {}",
        b"1: value",
        b"x" * (MAX_CONFIG_BYTES + 1),
    ],
)
def test_unsafe_yaml_is_refused_without_writes(tmp_path, raw):
    path = tmp_path / "plotsrv.yml"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        Draft.load(config=path)
    assert path.read_bytes() == raw


def test_typed_editor_validation_and_override():
    assert FIELDS["bind_port"].parse("8223") == 8223
    for value in ("nan", "inf", "0", "301"):
        with pytest.raises(ValueError):
            FIELDS["request_timeout"].parse(value)
    with pytest.raises(ValueError):
        FIELDS["bearer"].parse("Bearer secret-value")
    with pytest.raises(ValueError):
        FIELDS["destination"].parse("https://user:SECRET@host/")
    spec = FieldSpec(
        "enabled",
        ("freshness-settings", "enabled"),
        "Freshness",
        "bool",
        False,
        "Check freshness",
        per_view=True,
    )
    draft = Draft(Path("unused.yml"))
    draft.set_override(spec, "exact:id", "true")
    assert draft.edits[("freshness-settings", "views", "exact:id", "enabled")] is True
    with pytest.raises(ValueError):
        draft.set_override(FIELDS["destination"], "exact:id", "https://host")


def test_server_keyboard_path_never_parses_sources_or_scans(tmp_path, monkeypatch):
    app_class = ui()
    draft = Draft(
        tmp_path / "plotsrv.yml",
        config={"publisher-settings": "invalid unused section"},
    )
    monkeypatch.setattr(
        draft, "sources", lambda: pytest.fail("Server must skip publisher setup")
    )

    async def run():
        app = app_class(draft)
        async with app.run_test() as pilot:
            await pilot.press("j", "j", "enter")
            assert app.stage == "server"
            assert app.job is None
            assert not app.screen.query("#target")
            await pilot.press("escape")
            assert app.stage == "role"
            await pilot.press("ctrl+q")
            assert app.screen.__class__.__name__ == "Confirm"
            await pilot.press("escape")
            assert app.stage == "role"
            assert not draft.path.exists()

    asyncio.run(run())


def test_keyboard_discovery_selection_ranges_help_and_resize(project):
    app_class = ui()
    draft = Draft(project / "plotsrv.yml", cli_target=str(project))

    async def run():
        from textual.widgets import Static
        from plotsrv.config_wizard.tui import Views

        app = app_class(draft)
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.press("enter")
            assert app.stage == "sources"
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            await until(pilot, lambda: app.stage == "selection")
            assert draft.selected_ids == {"exact:A", "exact:B", "exact:C"}
            views = app.screen.query_one(Views)
            assert views.option_count == 5  # Two section headings.
            await pilot.press("c")
            assert draft.selected_ids == set()
            await pilot.press("home", "r", "end", "e")
            assert draft.selected_ids == {"exact:A", "exact:B", "exact:C"}
            assert "Range selected" in str(
                app.screen.query_one("#range", Static).content
            )
            await pilot.press("c", "home", "space", "j", "space")
            assert len(draft.selected_ids) == 2
            await pilot.press("a")
            assert len(draft.selected_ids) == 3
            await pilot.press("?")
            assert app.screen.__class__.__name__ == "Help"
            await pilot.press("escape")
            await pilot.resize_terminal(44, 16)
            assert app.screen.query_one("#legend").region.height > 0
            await pilot.press("enter")
            assert app.stage == "storage"
            assert not draft.path.exists()
            await pilot.press("escape", "escape")
            assert app.stage == "sources"
            app.screen.query_one("#next").focus()
            previous_job = app.job
            await pilot.press("enter")
            assert app.stage == "selection" and app.job is previous_job
            app.save_screenshot("/tmp/plotsrv-20-small.svg")

    asyncio.run(run())


def test_text_keys_destination_validation_and_watch(project):
    app_class = ui()
    draft = Draft(project / "plotsrv.yml", cli_target=str(project))

    async def run():
        from textual.widgets import Input, Static

        app = app_class(draft)
        async with app.run_test() as pilot:
            await pilot.press("j", "enter")
            assert draft.role == "publisher"
            app.screen.query_one("#target", Input).focus()
            app.screen.query_one("#target", Input).value = ""
            await pilot.press("j", "k", "q", "space", "?", "backspace", "left")
            assert app.stage == "sources"
            assert app.screen.query_one("#target", Input).value == "jkq "
            await pilot.press("f1")
            assert app.screen.__class__.__name__ == "Help"
            await pilot.press("escape")
            app.screen.query_one("#destination", Input).value = "http://remote.example/"
            app.screen.query_one("#bearer", Input).value = "MISSING_KEY"
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            assert "HTTPS" in str(app.screen.query_one("#error", Static).content)
            app.screen.query_one("#destination", Input).value = (
                "https://remote.example/base/"
            )
            app.screen.query_one("#target", Input).value = str(project)
            app.screen.query_one("#configure-watches").focus()
            await pilot.press("enter")
            app.screen.query_one("#watch-path", Input).value = "missing-file.log"
            app.screen.query_one("#watch-id", Input).value = "logs:stable"
            app.screen.query_one("#add-watch").focus()
            await pilot.press("enter")
            assert draft.sources().watches[0].path == str(project / "missing-file.log")
            app.screen.query_one("#skip").focus()
            await pilot.press("enter")
            assert app.stage == "publisher" and app.job is None
            assert draft.watches()[0].view_id == "logs:stable"
            assert draft.value(FIELDS["bearer"]) == "MISSING_KEY"
            await pilot.press("ctrl+c", "tab", "enter")
        assert not draft.path.exists()

    asyncio.run(run())


def test_existing_selection_duplicates_unresolved_and_no_rewrite(project):
    path = project / "plotsrv.yml"
    raw = b"# preserve comment\npublisher-settings:\n  discovery:\n    target: .\n    selection: [exact:B]\nunrelated:\n  token: SUPER_SECRET\n"
    path.write_bytes(raw)
    with (project / "app.py").open("a") as f:
        f.write(
            "@view(label='Duplicate', view_id='exact:B')\ndef dup(): pass\n@view(label=dynamic)\ndef unresolved(): pass\n"
        )
    draft = Draft.load(config=path)
    setup = draft.sources()
    result = scan_sources(setup.scan_root())
    draft.accept_scan(result, (setup.target, setup.target_base, setup.include_pruned))
    assert draft.selected_ids == {"exact:B"}
    preview = "\n".join(draft.diagnostics())
    assert "Duplicate logical ID" in preview and "unresolved" in preview
    assert "SUPER_SECRET" not in preview
    draft.selected_ids = set()
    with pytest.raises(ValueError, match="duplicate"):
        draft.save_edits()
    assert path.read_bytes() == raw


def test_cancel_coalesces_progress_and_prevents_worker_overlap(project, monkeypatch):
    app_class = ui()
    from plotsrv.config_wizard import scanning

    entered = Event()
    release = Event()
    calls = []

    def blocked(root, *, on_progress, cancelled, **kwargs):
        calls.append(root)
        for i in range(5000):
            on_progress(DiscoveryProgress("scanning", i, 5000, 5000, 0, 0))
        entered.set()
        release.wait(5)
        return scan_sources(project, cancelled=cancelled)

    monkeypatch.setattr(scanning, "scan_sources", blocked)

    async def run():
        app = app_class(Draft(project / "plotsrv.yml", cli_target=str(project)))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            await until(pilot, entered.is_set)
            assert app.job.progress is None or app.job.progress.processed == 4999
            await pilot.press("escape")
            assert app.stage == "sources" and app.job.cancelled.is_set()
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            assert len(calls) == 1 and app.stage == "sources"
            release.set()
            await until(pilot, app.job.done.is_set)
            await until(pilot, lambda: app.poll_timer is None)
            assert app.draft.result is None
        assert not app.job.thread.is_alive()

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_default_scope_detection_does_not_walk_sources(project, monkeypatch):
    from plotsrv.cli import _find_project_root

    (project / "pyproject.toml").unlink()
    (project / "src").mkdir()
    monkeypatch.setattr(
        Path, "rglob", lambda *a, **kw: pytest.fail("No unbounded preliminary scan")
    )
    assert _find_project_root(project) == project


def test_no_target_discovery_and_error_recovery(project, monkeypatch):
    app_class = ui()
    monkeypatch.chdir(project)

    async def run():
        from textual.widgets import Input

        app = app_class(Draft(project / "plotsrv.yml"))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            app.screen.query_one("#target", Input).value = "missing/path"
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            await until(pilot, lambda: app.job.done.is_set())
            await until(pilot, lambda: app.poll_timer is None)
            assert app.stage == "scanning" and app.job.error
            await pilot.press("escape")
            app.screen.query_one("#target", Input).value = ""
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            await until(pilot, lambda: app.stage == "selection")
            assert len(app.draft.selected_ids) == 3

    asyncio.run(run())


def test_quit_during_scan_is_prompt_and_never_applies_late_result(project, monkeypatch):
    app_class = ui()
    from plotsrv.config_wizard import scanning

    release = Event()
    entered = Event()

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(5)
        return scan_sources(project)

    monkeypatch.setattr(scanning, "scan_sources", blocked)

    async def run():
        app = app_class(Draft(project / "plotsrv.yml", cli_target=str(project)))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            await until(pilot, entered.is_set)
            await pilot.press("ctrl+q", "tab", "enter")
        assert app.job.cancelled.is_set()
        assert app.draft.result is None
        release.set()
        app.job.thread.join(2)
        assert not app.job.thread.is_alive()
        assert app.draft.result is None

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_input_draft_survives_back_and_selection_header_cannot_collide(project):
    app_class = ui()

    async def run():
        from textual.widgets import Input
        from plotsrv.config_wizard.tui import Views
        from plotsrv.discovery import DiscoveredView, DiscoveryResult

        app = app_class(Draft(project / "plotsrv.yml", cli_target=str(project)))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            app.screen.query_one("#destination", Input).value = "invalid unfinished URL"
            await pilot.press("escape")
            assert app.stage == "role"
            await pilot.press("enter")
            assert (
                app.screen.query_one("#destination", Input).value
                == "invalid unfinished URL"
            )
            app.draft.result = DiscoveryResult(
                (DiscoveredView("unknown", "label", "section", "header-0"),),
                (),
                0,
                1,
                1,
                1,
                False,
                False,
            )
            app.draft.selected_ids = {"header-0"}
            app.show_stage("selection")
            await pilot.pause()
            await pilot.press("c", "a")
            views = app.screen.query_one(Views)
            assert views.selected == ["header-0"]
            assert app.draft.selected_ids == {"header-0"}

    asyncio.run(run())


def test_config_init_noninteractive_entry_stays_lightweight(tmp_path):
    script = """
import sys
from plotsrv.cli_entry import main
assert main(['config', 'init']) == 2
assert 'plotsrv.cli' not in sys.modules
assert 'textual' not in sys.modules
assert 'plotsrv.config_wizard.draft' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX special-file guard")
def test_config_fifo_is_rejected_before_read(tmp_path):
    path = tmp_path / "plotsrv.yml"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular file"):
        Draft.load(config=path)


def test_entire_navigation_can_use_only_tab_and_enter(project):
    app_class = ui()

    async def run():
        app = app_class(Draft(project / "plotsrv.yml", cli_target=str(project)))
        async with app.run_test(size=(44, 16)) as pilot:
            await pilot.press("enter")
            # Walk actual focus order, including scrolling fields and help.
            for _ in range(25):
                if app.focused and app.focused.id == "next":
                    break
                await pilot.press("tab")
            assert app.focused.id == "next"
            await pilot.press("enter")
            await until(pilot, lambda: app.stage == "selection")
            assert app.screen.query_one("#help-panel").region.height == 3
            await pilot.press("r")
            from textual.widgets import Static

            assert "anchor (set)" in str(
                app.screen.query_one("#legend", Static).content
            )
            await pilot.press("end", "e", "enter")
            assert app.stage == "storage"
            await pilot.press("ctrl+q", "tab", "enter")
        assert not app.draft.path.exists()

    asyncio.run(run())


def test_completed_scan_waits_for_help_without_an_idle_timer(project, monkeypatch):
    app_class = ui()
    from plotsrv.config_wizard import scanning

    entered, release = Event(), Event()

    def paused(*args, **kwargs):
        entered.set()
        release.wait(5)
        return scan_sources(project)

    monkeypatch.setattr(scanning, "scan_sources", paused)

    async def run():
        app = app_class(Draft(project / "plotsrv.yml", cli_target=str(project)))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            await until(pilot, entered.is_set)
            await pilot.press("?")
            release.set()
            await until(pilot, lambda: app.poll_timer is None)
            assert app.screen.__class__.__name__ == "Help"
            await pilot.press("escape")
            await until(pilot, lambda: app.stage == "selection")

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_broad_implicit_scan_shows_narrowing_tip(project, monkeypatch):
    app_class = ui()
    from plotsrv.config_wizard import scanning
    from textual.widgets import Static

    release = Event()
    entered = Event()
    monkeypatch.chdir(project)

    def blocked(root, *, on_progress, **kwargs):
        on_progress(DiscoveryProgress("scanning", 50, 1200, 1200, 0, 6))
        entered.set()
        release.wait(5)
        return scan_sources(project)

    monkeypatch.setattr(scanning, "scan_sources", blocked)

    async def run():
        app = app_class(Draft.load(config=project / "plotsrv.yml"))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            app.screen.query_one("#next").focus()
            await pilot.press("enter")
            await until(pilot, entered.is_set)
            await until(
                pilot,
                lambda: "narrow discovery"
                in str(app.screen.query_one("#progress", Static).content),
            )
            assert app.job.progress is None
            await pilot.press("escape")
            release.set()
            await until(pilot, app.job.done.is_set)

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_existing_exact_empty_selection_is_described(project):
    app_class = ui()
    from textual.widgets import Static

    path = project / "plotsrv.yml"
    path.write_text("publisher-settings:\n  discovery:\n    exact_selection: []\n")

    async def run():
        app = app_class(Draft.load(config=path))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            text = "\n".join(str(widget.content) for widget in app.screen.query(Static))
            assert "exact IDs: []" in text
            assert "all (runtime default)" not in text

    asyncio.run(run())
