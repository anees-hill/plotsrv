from __future__ import annotations

import io
import os
from pathlib import Path
import threading

import pytest
import yaml

from plotsrv import cli, config_writer, settings, store
from plotsrv.cli_parser import WatchSpec
from plotsrv.discovery import scan_sources, discover_views, DiscoveryProgress
from plotsrv.discovery_progress import TerminalProgress
from plotsrv.source_setup import resolve_source_setup, build_manifest
from plotsrv.source_targets import resolve_source_target


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    store.reset()
    yield
    store.reset()


def configure(tmp_path, monkeypatch, *, discovery=None, watches=None):
    directory = tmp_path / "config"
    directory.mkdir(exist_ok=True)
    path = directory / "custom.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "publisher-settings": {
                    "discovery": discovery or {},
                    "watch": watches or [],
                }
            }
        )
    )
    monkeypatch.setenv("PLOTSRV_CONFIG", str(path))
    settings._CONFIG_CACHE.clear()
    return directory


def test_independent_config_cli_empty_watch_and_selection_precedence(
    tmp_path, monkeypatch
):
    base = configure(
        tmp_path,
        monkeypatch,
        discovery={"target": "./src", "selection": ["etl"]},
        watches=[
            {
                "path": "events.log",
                "view_id": "exact:id",
                "label": "Log",
                "section": "Logs",
                "read_mode": "head",
                "materialization": "file",
            }
        ],
    )
    (base / "src").mkdir()
    configured = resolve_source_setup()
    assert configured.scan_root() == base / "src"
    assert configured.watches[0].path == str(base / "events.log")
    assert configured.watches[0].view_id == "exact:id"
    assert configured.watches[0].read_mode == "head"
    assert configured.watches[0].materialization == "file"
    (tmp_path / "other").mkdir()
    target_only = resolve_source_setup(target="other")
    assert target_only.scan_root() == tmp_path / "other"
    assert target_only.watches == configured.watches
    assert len(target_only.messages) == 1
    watch_only = resolve_source_setup(watches=[WatchSpec("relative.log")])
    assert watch_only.scan_root() == base / "src"
    assert watch_only.watches[0].path == "relative.log"
    assert watch_only.selection == ("etl",)
    assert resolve_source_setup(watches=[]).watches == ()
    assert resolve_source_setup(selection=[]).selection == ()


def test_run_uses_config_and_explicit_watch_replaces_without_merge(
    tmp_path, monkeypatch, capsys
):
    base = configure(
        tmp_path,
        monkeypatch,
        discovery={"target": "./src", "selection": ["keep"]},
        watches=[
            {
                "path": "configured.log",
                "view_id": "log",
                "label": "Config log",
                "read_mode": "head",
            }
        ],
    )
    (base / "src").mkdir()
    calls = []
    monkeypatch.setattr(
        cli,
        "_run_passive_server_forever",
        lambda root, **kwargs: calls.append((root, kwargs)) or 0,
    )
    assert cli.main(["run"]) == 0
    assert calls[-1][0] == str(base / "src")
    assert calls[-1][1]["watch_specs"][0].label == "Config log"
    assert calls[-1][1]["includes"] == {"keep"}
    assert cli.main(["run", "--watch", "explicit.log"]) == 0
    assert len(calls[-1][1]["watch_specs"]) == 1
    assert calls[-1][1]["watch_specs"][0].path == "explicit.log"
    assert cli.main(["run", "--no-watch"]) == 0
    assert calls[-1][1]["watch_specs"] == []
    assert "explicit watch set" in capsys.readouterr().err
    (tmp_path / "override").mkdir()
    assert cli.main(["run", "override", "--quiet"]) == 0
    assert calls[-1][0] == str(tmp_path / "override")
    assert calls[-1][1]["watch_specs"][0].view_id == "log"
    assert capsys.readouterr().err == ""
    with pytest.raises(SystemExit):
        cli.main(["run", "--no-watch", "--watch", "x"])


def test_empty_config_preserves_project_default(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("")
    calls = []
    monkeypatch.setattr(
        cli,
        "_run_passive_server_forever",
        lambda root, **kwargs: calls.append(root) or 0,
    )
    assert cli.main(["run"]) == 0
    assert calls == [str(tmp_path)]


def test_module_resolution_never_imports_parent_or_consults_hooks(
    tmp_path, monkeypatch
):
    import importlib.util

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("raise AssertionError('package was executed')")
    module = package / "child.py"
    module.write_text(
        'from plotsrv import view\n@view(view_id="exact:child")\ndef work(): pass\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    def forbidden(*args, **kwargs):
        raise AssertionError("import hook consulted")

    monkeypatch.setattr(importlib.util, "find_spec", forbidden)
    assert resolve_source_target("pkg.child:work") == module
    assert cli._resolve_scan_root_for_passive("pkg.child:work") == str(module)
    assert discover_views("pkg.child:work")[0].view_id == "exact:child"
    assert config_writer.discover_view_ids("pkg.child:work") == ["exact:child"]
    assert "pkg" not in __import__("sys").modules


def test_aliases_docstrings_literal_streams_and_dynamic_review(tmp_path):
    source = tmp_path / "app.py"
    source.write_text('''
import plotsrv as ps
from plotsrv import view as panel, publish_view as send
@panel(view_id=" é:订单:daily ", label=" Label ", section=" Section ")
def report():
    """First line of a summary.

    Longer explanation, excluded from the summary.
    """
    return None
send(None, view_id="inline:id", label="Inline", kind="table")
ps.stream_view(source="events.jsonl", view_id="logs:events", label="Events")
ps.publish_view(None, view_id=dynamic, label="Never guess this ID")
@ps.view(label=dynamic_label)
def dynamic_function(): pass
unrelated.publish_view(None, view_id="false-positive")
''')
    result = scan_sources(source)
    assert {v.view_id for v in result.views} == {
        " é:订单:daily ",
        "inline:id",
        "logs:events",
    }
    decorated = next(v for v in result.views if v.label == " Label ")
    assert decorated.section == " Section "
    assert decorated.description == "First line of a summary."
    assert next(v for v in result.views if v.view_id == "logs:events").kind == "stream"
    assert result.issue_count == 3
    with pytest.raises(ValueError, match="Review"):
        build_manifest(result)
    body = build_manifest(
        result,
        reviewed=True,
        added_ids=["reviewed:dynamic"],
        watches=[WatchSpec("status.log", view_id="watch:id")],
    )
    assert len(body["views"]) == 5
    assert body["protocol_version"] == 1
    assert not store.list_views()


@pytest.mark.parametrize(
    "binding",
    [
        "from other import view",
        "view = something",
        "from other import *",
        "def inside():\n    from plotsrv import view",
    ],
)
def test_shadowed_or_nested_imports_never_authorise_candidates(tmp_path, binding):
    path = tmp_path / "shadowed.py"
    path.write_text(
        "from plotsrv import view\n"
        + binding
        + '\n@view(view_id="unsafe")\ndef f(): pass\n'
    )
    result = scan_sources(path)
    assert not result.views
    assert result.issue_count


def test_manifest_selection_duplicate_conflicts_and_no_partial_registration(tmp_path):
    path = tmp_path / "app.py"
    path.write_text(
        'from plotsrv import publish_view\npublish_view(None, view_id="keep", label="Keep")\npublish_view(None,view_id="drop",label="Drop")'
    )
    result = scan_sources(path)
    body = build_manifest(
        result,
        selection=["Keep"],
        watches=[WatchSpec("events.log", view_id="watch")],
        added_ids=["dynamic"],
    )
    assert {v["view_id"] for v in body["views"]} == {"keep", "watch", "dynamic"}
    with pytest.raises(ValueError, match="duplicate"):
        build_manifest(result, added_ids=["keep"])
    with pytest.raises(ValueError):
        cli._passive_register_views(
            str(path),
            includes=set(),
            excludes=set(),
            watch_specs=[WatchSpec("x", view_id="keep")],
            quiet=True,
        )
    assert not store.list_views()


@pytest.mark.parametrize("config_style", ["global", "default", "instance"])
def test_population_uses_exact_ids_and_config_selection(
    tmp_path, monkeypatch, config_style
):
    source = tmp_path / "app.py"
    source.write_text(
        'from plotsrv import view\n@view(view_id="exact:custom:id",label="Different")\ndef f(): pass\n@view(label="Excluded")\ndef g(): pass\n'
    )
    config_path = tmp_path / "custom.yaml"
    selected = {"discovery": {"selection": ["exact:custom:id"]}}
    publisher = selected
    if config_style == "default":
        publisher = {"default": selected}
    elif config_style == "instance":
        publisher = {
            "discovery": {"selection": ["Excluded"]},
            "instances": {"chosen": selected},
        }
        monkeypatch.setenv("PLOTSRV_NAME", "chosen")
    config_path.write_text(yaml.safe_dump({"publisher-settings": publisher}))
    config_writer.populate_limits(
        path=config_path,
        target=source,
        mode="merge",
        text="123",
        html=None,
        markdown=None,
    )
    written = yaml.safe_load(config_path.read_text())
    assert set(written["limits"]["views"]) == {"exact:custom:id"}


def test_progress_cancellation_and_partial_manifest_guard(tmp_path):
    for i in range(4):
        (tmp_path / f"{i}.py").write_text(
            f'from plotsrv import view\n@view(view_id="id:{i}")\ndef f(): pass\n'
        )
    events = []
    stop = threading.Event()

    def progress(event):
        events.append(event)
        if event.phase == "scanning" and event.processed == 1:
            stop.set()

    result = scan_sources(tmp_path, on_progress=progress, cancelled=stop)
    assert events[0].phase == "enumerating" and events[0].total is None
    assert any(
        e.phase == "scanning" and e.total == 4 and e.processed == 0 for e in events
    )
    assert result.cancelled and result.processed == 1
    assert events[-1].phase == "cancelled"
    with pytest.raises(ValueError, match="cancelled"):
        build_manifest(result, reviewed=True)
    stop.set()
    cancelled = scan_sources(tmp_path, cancelled=stop)
    assert cancelled.cancelled and cancelled.processed == 0


def test_large_tree_pruning_source_bounds_syntax_unreadable_and_symlink_loop(
    tmp_path, monkeypatch
):
    from plotsrv import discovery

    for i in range(200):
        (tmp_path / f"{i}.py").write_text("x=1\n")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "hidden.py").write_text(
        "from plotsrv import view\n@view()\ndef hidden(): pass\n"
    )
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "bad.py").write_text("def bad(:")
    (tmp_path / "big.py").write_text(" " * 300)
    unreadable = tmp_path / "unreadable.py"
    unreadable.write_text("x=1")
    original = os.open

    def guarded(path, *args, **kwargs):
        if Path(path) == unreadable:
            raise PermissionError("test unreadable source")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    monkeypatch.setattr(discovery, "MAX_SOURCE_BYTES", 200)
    events = []
    result = scan_sources(tmp_path, on_progress=events.append)
    assert result.total == 203 and result.processed == 203
    assert not result.views
    assert {issue.reason for issue in result.issues} == {
        "invalid_python",
        "source_byte_limit",
        "unreadable_source",
    }
    assert len([e for e in events if e.phase == "enumerating"]) >= 2
    assert [v.label for v in scan_sources(tmp_path, include_pruned=True).views] == [
        "hidden"
    ]
    monkeypatch.setattr(discovery, "MAX_SCAN_FILES", 10)
    partial = scan_sources(tmp_path)
    assert partial.limited and partial.total == 10
    with pytest.raises(ValueError):
        build_manifest(partial, reviewed=True)


def test_issue_storage_and_plain_progress_are_bounded(tmp_path, monkeypatch):
    from plotsrv import discovery

    monkeypatch.setattr(discovery, "MAX_SCAN_ISSUES", 3)
    for i in range(8):
        (tmp_path / f"{i}.py").write_text("bad syntax ???")
    result = scan_sources(tmp_path)
    assert result.issue_count == 8 and len(result.issues) == 3
    output = io.StringIO()
    progress = TerminalProgress(stream=output, unscoped=True)
    progress(DiscoveryProgress("enumerating", 0, None, 0, 0, 0))
    for i in range(50):
        progress(DiscoveryProgress("enumerating", 0, None, i, 0, 0.1))
    progress(DiscoveryProgress("scanning", 0, 1200, 1200, 0, 0.2))
    progress(DiscoveryProgress("complete", 1200, 1200, 1200, 0, 1))
    text = output.getvalue()
    assert "total not yet known" in text and "1200/1200" in text
    assert "\r" not in text and "\x1b" not in text
    assert text.count("Tip:") == 1 and len(text.splitlines()) <= 6
    quiet = io.StringIO()
    TerminalProgress(stream=quiet, quiet=True)(
        DiscoveryProgress("complete", 0, 0, 0, 0, 0)
    )
    assert quiet.getvalue() == ""


def test_configured_callable_keeps_import_name_and_child_context(tmp_path, monkeypatch):
    base = configure(tmp_path, monkeypatch, discovery={"target": "pkg.child:work"})
    package = base / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "raise AssertionError('discovery imported project')"
    )
    (package / "child.py").write_text("def work(): return 1")
    setup = resolve_source_setup()
    assert setup.target == "pkg.child:work"
    assert setup.scan_root() == package / "child.py"
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs))
    )
    cli._run_subprocess_call_importpath(
        setup.target, host="127.0.0.1", port=8000, source_base=setup.target_base
    )
    assert calls[0][1]["cwd"] == str(base)
    assert str(base / "src") in calls[0][1]["env"]["PYTHONPATH"]
    assert calls[0][0][-3] == "pkg.child:work"


def test_manifest_rejects_excess_added_ids_without_consuming_infinite_input():
    from plotsrv.contracts import MAX_CATALOGUE_VIEWS

    consumed = 0

    def ids():
        nonlocal consumed
        while True:
            consumed += 1
            yield f"dynamic:{consumed}"

    with pytest.raises(ValueError, match="count"):
        build_manifest([], added_ids=ids())
    assert consumed == MAX_CATALOGUE_VIEWS + 1


def test_enumeration_cancellation_has_unknown_total_and_no_reads(tmp_path, monkeypatch):
    stop = threading.Event()
    events = []

    def progress(event):
        events.append(event)
        if event.phase == "enumerating":
            stop.set()

    result = scan_sources(tmp_path, on_progress=progress, cancelled=stop)
    assert events[0].total is None
    assert result.cancelled and result.bytes_read == 0


def test_scan_total_bytes_and_entry_count_are_hard_bounds(tmp_path, monkeypatch):
    from plotsrv import discovery

    for i in range(4):
        (tmp_path / f"{i}.py").write_text("x=1\n" * 20)
    monkeypatch.setattr(discovery, "MAX_SCAN_BYTES", 100)
    result = scan_sources(tmp_path)
    assert result.limited and result.bytes_read <= 101
    assert any(i.reason == "scan_byte_limit" for i in result.issues)
    monkeypatch.setattr(discovery, "MAX_SCAN_ENTRIES", 2)
    result = scan_sources(tmp_path)
    assert result.limited and result.bytes_read == 0
    assert any(i.reason == "entry_limit" for i in result.issues)


def test_configured_package_remains_a_module_for_explicit_execution(
    tmp_path, monkeypatch
):
    base = configure(tmp_path, monkeypatch, discovery={"target": "package"})
    package = base / "package"
    package.mkdir()
    (package / "__init__.py").write_text("raise AssertionError('must not import')")
    setup = resolve_source_setup()
    assert setup.target == "package"
    assert setup.scan_root() == package
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs))
    )
    cli._run_subprocess_as_main(setup.target, source_base=setup.target_base)
    assert calls[0][0][-2:] == ["-m", "package"]
    assert calls[0][1]["cwd"] == str(base)
