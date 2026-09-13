from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import pytest

from plotsrv import cli, publisher_agent, settings, store
from plotsrv import watch_directory as directory
from plotsrv.runtime import WatchConfig
from plotsrv.source_setup import watch_descriptor


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


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "docs"
    for name in (
        "index.md",
        "reference/setup.md",
        "reference/api/v1.md",
        "reference/api/internal/hidden.md",
        "other/notes.md",
        "events.log",
        "data.csv",
        "image.png",
        "plain.txt",
        "unknown.bin",
        ".secret.md",
        ".private/no.md",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return root


def test_discovery_grouping_order_and_metadata_only(docs, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("discovery read source contents")

    monkeypatch.setattr(Path, "open", forbidden)
    watches = directory.discover_directory(WatchConfig(path=docs))
    assert [(w.section, w.label) for w in watches] == [
        ("docs", "data.csv"),
        ("docs", "events.log"),
        ("docs", "image.png"),
        ("docs", "index.md"),
        ("other", "notes.md"),
        ("docs", "plain.txt"),
        ("reference/api", "v1.md"),
        ("reference", "setup.md"),
    ]
    assert all(str(docs) not in watch_descriptor(w).view_id for w in watches)


def test_depth_patterns_prefix_and_inherited_options(docs):
    spec = WatchConfig(
        path=docs,
        section="Reports",
        read_mode="tail",
        max_bytes=1234,
        encoding="latin-1",
        kind="text",
        materialization="memory",
        force=True,
    )
    watches = directory.discover_directory(spec, max_depth=1, include=["*.md"])
    assert [(w.section, w.label) for w in watches] == [
        ("Reports", "index.md"),
        ("Reports/other", "notes.md"),
        ("Reports/reference", "setup.md"),
    ]
    assert all(
        replace(w, path=docs, section="Reports", label=None) == spec for w in watches
    )
    assert len(directory.discover_directory(spec, max_depth=0, include=["*.md"])) == 1
    assert [
        w.label
        for w in directory.discover_directory(
            spec, include=["reference/api/*.md", "index.md"]
        )
    ] == ["index.md", "v1.md"]


def test_no_following_links_or_special_files(docs, tmp_path):
    (docs / "linked.md").symlink_to(docs / "index.md")
    (docs / "loop").symlink_to(docs, target_is_directory=True)
    (docs / "outside").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(docs / "pipe.log")
    assert len(directory.discover_directory(WatchConfig(path=docs))) == 8


@pytest.mark.parametrize(
    "options",
    [
        {"max_depth": -1},
        {"max_depth": 17},
        {"max_views": 0},
        {"max_views": 65},
        {"include": [""]},
        {"include": ["x" * 513]},
        {"include": ["*.md"] * 33},
    ],
)
def test_invalid_discovery_options(docs, options):
    with pytest.raises(ValueError):
        directory.discover_directory(WatchConfig(path=docs), **options)


def test_view_overflow_rejects_entire_collection(docs):
    with pytest.raises(ValueError, match="Nothing was started"):
        directory.discover_directory(WatchConfig(path=docs), max_views=2)


def test_entry_budget_includes_unsupported_and_hidden_files(tmp_path, monkeypatch):
    for i in range(12):
        (tmp_path / f".{i}.bin").touch()
    monkeypatch.setattr(directory, "MAX_ENTRIES", 10)
    with pytest.raises(ValueError, match="exceeded 10 entries"):
        directory.discover_directory(WatchConfig(path=tmp_path))


def test_depth_does_not_enumerate_excluded_subtrees(docs, monkeypatch):
    scandir = directory.os.scandir
    visited = []

    def scan(path):
        visited.append(path)
        return scandir(path)

    monkeypatch.setattr(directory.os, "scandir", scan)
    directory.discover_directory(WatchConfig(path=docs), max_depth=0)
    assert visited == [docs]


def test_unreadable_directory_aborts_before_partial_result(docs, monkeypatch):
    scandir = directory.os.scandir

    def scan(path):
        if path.name == "reference":
            raise PermissionError("permission denied")
        return scandir(path)

    monkeypatch.setattr(directory.os, "scandir", scan)
    with pytest.raises(ValueError, match="Cannot discover"):
        directory.discover_directory(WatchConfig(path=docs))


def test_empty_and_duplicate_id_rejected(tmp_path):
    with pytest.raises(ValueError, match="No supported files"):
        directory.discover_directory(WatchConfig(path=tmp_path))
    (tmp_path / "index.md").touch()
    child = tmp_path / tmp_path.name
    child.mkdir()
    (child / "index.md").touch()
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        directory.discover_directory(WatchConfig(path=tmp_path))
    # A section prefix also disambiguates root files from identically named subfolders.
    assert (
        len(directory.discover_directory(WatchConfig(path=tmp_path, section="docs")))
        == 2
    )


def test_relocation_retains_ids_and_new_files_need_rediscovery(docs, tmp_path):
    first = directory.discover_directory(WatchConfig(path=docs))
    (docs / "new.md").touch()
    assert all(w.label != "new.md" for w in first)
    moved = tmp_path / "moved" / "docs"
    moved.parent.mkdir()
    docs.rename(moved)
    after = directory.discover_directory(WatchConfig(path=moved))
    assert [watch_descriptor(w).view_id for w in first] == [
        watch_descriptor(w).view_id for w in after if w.label != "new.md"
    ]


def test_cli_local_and_remote_use_same_specs(docs, monkeypatch):
    local, remote = [], []
    monkeypatch.setattr(
        cli,
        "_run_watch_collection",
        lambda watches, **kw: local.append((watches, kw)) or 0,
    )
    monkeypatch.setattr(
        publisher_agent, "foreground", lambda watcher: remote.append(watcher) or 0
    )
    args = ["watch", str(docs), "--include", "*.md", "--every", "2", "--max-mb", "1"]
    assert cli.main(args) == 0
    assert cli.main([*args, "--destination", "http://localhost:9999"]) == 0
    assert local[0][0] == [s.spec for s in remote[0].states]
    assert local[0][1]["every"] == remote[0].every == 2
    assert all(
        w.max_bytes == 1024 * 1024 and w.materialization is None for w in local[0][0]
    )
    assert not store.list_views()  # Remote expansion has no server-side registrations.


@pytest.mark.parametrize(
    "extra",
    [
        ["--label", "all"],
        ["--view-id", "all"],
        ["--max-views", "1"],
        ["--every", "nan"],
        ["--every", "0"],
    ],
)
def test_cli_invalid_directory_never_launches(docs, monkeypatch, extra):
    monkeypatch.setattr(
        publisher_agent,
        "destination_for_cli",
        lambda args: pytest.fail("resolved destination before validation"),
    )
    assert cli.main(["watch", str(docs), *extra]) == 2


@pytest.mark.parametrize(
    "extra", [["--max-depth", "0"], ["--max-views", "32"], ["--include", "*.md"]]
)
def test_directory_options_rejected_for_files(docs, extra):
    assert cli.main(["watch", str(docs / "index.md"), *extra]) == 2


def test_cancel_during_discovery_never_resolves_destination(docs, monkeypatch):
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(directory, "discover_directory", cancel)
    monkeypatch.setattr(
        publisher_agent,
        "destination_for_cli",
        lambda args: pytest.fail("resolved destination after cancellation"),
    )
    assert cli.main(["watch", str(docs)]) == 130
    assert not store.list_views()


def test_local_startup_failure_stops_server_without_starting_watchers(
    docs, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        cli,
        "_get_server_hooks",
        lambda: (
            lambda **kw: calls.append("start"),
            lambda **kw: calls.append("stop"),
        ),
    )
    monkeypatch.setattr(cli, "_get_restore_streams_hook", lambda: lambda: None)
    monkeypatch.setattr(cli, "_wait_for_server", lambda *args, **kw: False)
    monkeypatch.setattr(
        cli,
        "start_watch_threads",
        lambda *args, **kw: pytest.fail("started watchers before readiness"),
    )
    watches = directory.discover_directory(WatchConfig(path=docs))
    assert (
        cli._run_watch_collection(
            watches, host="127.0.0.1", port=8000, every=1, quiet=True
        )
        == 2
    )
    assert calls == ["start", "stop"]


def test_explicit_section_is_prefix_even_when_named_watch(docs, monkeypatch):
    captured = []
    monkeypatch.setattr(
        cli, "_run_watch_collection", lambda specs, **kw: captured.extend(specs) or 0
    )
    assert (
        cli.main(["watch", str(docs), "--section", "watch", "--include", "*.md"]) == 0
    )
    assert {w.section for w in captured} == {
        "watch",
        "watch/other",
        "watch/reference",
        "watch/reference/api",
    }


@pytest.mark.parametrize("materialization", ["memory", "file"])
def test_maximum_collection_uses_one_worker_and_retains_no_prepared_payloads(
    tmp_path, monkeypatch, materialization
):
    import weakref
    from plotsrv import runtime

    specs = []
    for i in range(64):
        path = tmp_path / f"{i}.txt"
        path.write_text("source")
        specs.append(WatchConfig(path=path, materialization=materialization))
    clock, waits, refs, reads, changes, threads = [0.0], [], [], [], [], []

    class Event:
        stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, delay):
            # Scheduler suspension must retain neither raw captures nor prepared objects.
            assert all(ref() is None for ref in refs)
            waits.append(delay)
            clock[0] += delay
            self.stopped = len(waits) == 3

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target = target
            threads.append(self)

        def start(self):
            self.target()

    class Payload:
        pass

    def prepare(**kwargs):
        clock[0] += 0.01  # Different preparation times must not stagger idle wakeups.
        value = Payload()
        refs.append(weakref.ref(value))
        return value

    monkeypatch.setattr(runtime.threading, "Event", Event)
    monkeypatch.setattr(runtime.threading, "Thread", Thread)
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime, "_local_watch_ready", lambda *args: None)
    monkeypatch.setattr(
        runtime,
        "read_watch_file_bytes",
        lambda path, **kw: reads.append(path) or b"source",
    )
    monkeypatch.setattr(runtime, "build_watch_publish_payload", prepare)
    monkeypatch.setattr(runtime, "publish_prepared_watch_payload", lambda **kw: True)
    monkeypatch.setattr(
        runtime,
        "note_file_backed_watch_change",
        lambda **kw: changes.append(kw["registered"].view_id),
    )
    runtime.start_watch_threads(
        specs,
        host="127.0.0.1",
        port=8000,
        register_views=False,
        coalesce=True,
        every=2.0,
    )
    assert len(threads) == 1
    assert waits == pytest.approx([2.0] * 3)
    assert len(reads) == (64 if materialization == "memory" else 0)
    assert len(changes) == (64 if materialization == "file" else 0)
    assert len(refs) == len(reads)


@pytest.mark.parametrize("mode", ["local", "local-file", "remote"])
def test_real_directory_launch_update_and_shutdown(tmp_path, mode):
    import json
    import signal
    import subprocess
    import sys
    from urllib.parse import quote

    from tests.test_standalone import ServerProcess
    from tests.test_publisher_agent import wait_for

    server = ServerProcess(tmp_path, key=True)
    producer = None
    root = server.publisher_dir / "docs"
    (root / "reference").mkdir(parents=True)
    (root / "index.md").write_text("# Welcome")
    path = root / "reference" / "setup.md"
    path.write_text("# Initial guide")
    args = ["watch", "docs", "--every", "0.1", "--quiet"]
    try:
        if mode == "remote":
            server.start()
        else:
            # Explicit local bind must override even a configured authenticated destination.
            args.extend(["--host", "127.0.0.1", "--port", str(server.port)])
            if mode == "local-file":
                args.extend(["--materialization", "file"])
        producer = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from plotsrv.cli import main; raise SystemExit(main())",
                *args,
            ],
            cwd=server.publisher_dir,
            env=server.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        artifact = lambda: server.get("/artifact?view=" + quote("reference:setup.md"))
        wait_for(server, lambda: "Initial guide" in artifact()["html"])
        assert len(server.get("/views")) == 2
        (root / "new.md").write_text("Not in startup selection")
        replacement = root / "replacement.tmp"
        replacement.write_text("# Replacement guide")
        replacement.replace(path)
        wait_for(server, lambda: "Replacement guide" in artifact()["html"])
        path.write_text("# Short")  # Truncation continues to update the same view.
        wait_for(server, lambda: "Short" in artifact()["html"])
        assert len(server.get("/views")) == 2
        if mode == "remote":
            assert str(root) not in json.dumps(artifact())
        producer.send_signal(signal.SIGINT)
        stdout, stderr = producer.communicate(timeout=7)
        assert producer.returncode == 0, (stdout, stderr)
        assert "integration-test-key" not in stdout + stderr
    finally:
        if producer is not None and producer.poll() is None:
            producer.kill()
            producer.communicate(timeout=3)
        server.close()
