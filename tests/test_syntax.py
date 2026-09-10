"""Bounded source syntax, local/remote routing and immutable version hints."""

from html.parser import HTMLParser
from pathlib import Path
import sys
import subprocess
import tracemalloc

import pytest

from plotsrv import runtime, store, config, source_info
from plotsrv.renderers import register_default_renderers
from plotsrv.renderers.registry import render_any
from plotsrv.renderers import syntax
from tests.test_remote_watch import isolated, client, register, envelope, post


class Text(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.value = ""
        self.feed(markup)

    def handle_data(self, data):
        self.value += data


@pytest.mark.parametrize(
    "name,source,kind,language",
    [
        ("script.py", 'print("<script>danger</script>")\n', "python", "python"),
        ("types.pyi", "def work(x: int) -> str: ...\n", "python", "python"),
        ("analysis.R", "x <- 42\n", "text", "r"),
        ("query.sql", "SELECT * FROM orders;\n", "text", "sql"),
        ("run.sh", 'echo "$HOME"\n', "text", "bash"),
        ("file.unknown", "plain source\n", "text", None),
    ],
)
def test_local_and_remote_watch_routing(client, tmp_path, name, source, kind, language):
    register_default_renderers()
    path = tmp_path / name
    # Deliberately no file: supplied bytes and basename must be sufficient.
    prepared = runtime.build_watch_publish_payload(
        path=path,
        raw=source.encode(),
        watch_config=runtime.WatchConfig(path=path),
        read_mode="head",
        max_bytes=4096,
    )
    assert prepared.artifact_kind == kind
    local = render_any(
        prepared.artifact, view_id="v", kind_hint=kind, source_info=prepared.source_info
    )
    session = register(client)
    post(client, envelope(session, source.encode(), name=name))
    remote = client.get("/artifact", params={"view": "watch:exact:é"}).json()
    assert remote["kind"] == local.kind == kind
    assert remote["meta"]["source_info"]["basename"] == name
    assert not path.exists()
    if language:
        assert "ps-code-token--" in local.html and "ps-code-token--" in remote["html"]
    else:
        assert "ps-code-token--" not in remote["html"]
    assert "<script>danger" not in remote["html"]


def test_explicit_text_and_language_choices(client, tmp_path):
    path = tmp_path / "script.py"
    raw = b"SELECT count(*) FROM orders;\n"
    prepared = runtime.build_watch_publish_payload(
        path=path,
        raw=raw,
        watch_config=runtime.WatchConfig(path=path, kind="text"),
        read_mode="head",
        max_bytes=4096,
    )
    assert prepared.artifact_kind == "text"
    (tmp_path / "plotsrv.yml").write_text(
        "code-settings:\n  language: sql\n  style: plain\n"
    )
    register_default_renderers()
    result = render_any(
        prepared.artifact,
        view_id="v",
        kind_hint="text",
        source_info=prepared.source_info,
    )
    assert 'data-plotsrv-style-default="plain"' in result.html
    assert syntax.presentation("v", prepared.source_info) == ("sql", "plain")


def test_multiline_tokens_remain_balanced_and_preserve_source():
    raw = 'x = """first\n<script>still a string</script>\nlast"""\r\n# tail\n'
    result = syntax.highlight(raw, "python")
    assert result.html is not None and Text(result.html).value == raw
    for line in result.html.split("\n"):
        assert line.count("<span") == line.count("</span>")
    assert 'ps-code-token--string">&lt;script&gt;' in result.html
    assert syntax.highlight(raw, "python", partial_tail=True).html is None


def test_limits_precede_lexer_work_and_bound_expansion(monkeypatch):
    import pygments.lexers

    original = pygments.lexers.get_lexer_by_name
    monkeypatch.setattr(
        pygments.lexers,
        "get_lexer_by_name",
        lambda *a, **kw: pytest.fail("Lexer before admission"),
    )
    raw = "x" * 10_000_000
    tracemalloc.start()
    assert syntax.highlight(raw, "python").html is None
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 20_000
    assert syntax.highlight("small", "/tmp/lexer.py").html is None
    monkeypatch.setattr(pygments.lexers, "get_lexer_by_name", original)
    monkeypatch.setattr(syntax, "MAX_TOKENS", 2)
    assert syntax.highlight("x = 1 + 2 + 3", "python").html is None
    monkeypatch.setattr(syntax, "MAX_TOKENS", 4096)
    monkeypatch.setattr(syntax, "MAX_OUTPUT_BYTES", 24)
    assert syntax.highlight('x = "<script>"', "python").html is None


def test_busy_and_failed_lexer_fall_back_without_leaking_slots(monkeypatch):
    import pygments.lexers

    syntax._SLOTS.acquire()
    syntax._SLOTS.acquire()
    try:
        assert syntax.highlight("x=1", "python").html is None
    finally:
        syntax._SLOTS.release()
        syntax._SLOTS.release()

    def fail(*a, **kw):
        raise RuntimeError("Bad lexer")

    monkeypatch.setattr(pygments.lexers, "get_lexer_by_name", fail)
    for _ in range(3):
        assert syntax.highlight("x=1", "python").html is None
    assert syntax._SLOTS.acquire(False)
    syntax._SLOTS.release()


def test_plain_pipeline_import_does_not_import_pygments():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import plotsrv, sys; assert 'pygments' not in sys.modules",
        ],
        check=True,
    )


def test_python_preview_bounds_before_lexing_even_with_display_limits_off(monkeypatch):
    from plotsrv.renderers.python import PythonRenderer

    monkeypatch.setattr(config, "get_truncation_max_chars", lambda *a, **kw: None)
    result = PythonRenderer().render("x\n" * 1_000_000, view_id="v")
    assert result.truncation.truncated
    assert len(result.html) < 100_000


@pytest.mark.parametrize(
    "name,raw",
    [
        ("config.yaml", 'title: "<script>"\nvalue: 42\n'),
        ("config.toml", 'title = "<script>"\nvalue = 42\n'),
        ("config.ini", "[main]\ntitle = <script>\nvalue = 42\n"),
        ("config.json", '{"title": "<script>", "value": 42}\n'),
    ],
)
def test_structured_modes_keep_raw_syntax(tmp_path, name, raw):
    from plotsrv.file_kinds import coerce_file_to_publishable

    register_default_renderers()
    result = coerce_file_to_publishable(tmp_path / name, raw=raw.encode())
    assert result.artifact_kind == "json"
    rendered = render_any(result.obj, view_id="v", kind_hint="json")
    assert 'data-json-panel="json"' in rendered.html
    assert 'data-json-text-view="1" data-plotsrv-syntax="1"' in rendered.html
    assert "<script>" not in rendered.html


def test_metadata_roundtrips_snapshot_and_restored_latest(
    client, tmp_path, monkeypatch
):
    from plotsrv.storage.backend import write_snapshot
    from plotsrv.storage.latest import FileLatestStateBackend
    from plotsrv import server

    info = source_info.for_file("report.sql")
    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_storage_enabled", lambda: True)
    monkeypatch.setattr(config, "get_storage_view_enabled", lambda *a, **kw: True)
    raw = "SELECT count(*) FROM orders;\n"
    snapshot = write_snapshot(
        root_dir=tmp_path,
        view_id="v",
        kind="text",
        obj=raw,
        extra={"source_info": info},
    )
    reply = client.get(
        "/artifact", params={"view": "v", "snapshot": snapshot.snapshot_id}
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["meta"]["source_info"] == info
    assert "ps-code-token--keyword" in reply.json()["html"]
    backend = FileLatestStateBackend(root_dir=tmp_path)
    backend.write_latest(view_id="v", kind="text", obj=raw, extra={"source_info": info})
    server._restore_latest_loaded_view(backend.load_latest(view_id="v"))
    assert store.get_artifact(view_id="v").source_info == info


def test_metadata_rejects_paths_before_visible_mutation(client):
    result = client.post(
        "/publish",
        json=dict(
            view_id="bad",
            kind="artifact",
            artifact_kind="text",
            artifact="text",
            source_info={"basename": "/private/lexer.py"},
        ),
    )
    assert result.status_code == 422
    assert "bad" not in {v.view_id for v in store.list_views()}


def test_same_revision_reuses_highlighting(client, monkeypatch):
    session = register(client)
    post(client, envelope(session, b"x = 42\n", name="source.py"))
    assert client.get("/artifact", params={"view": "watch:exact:é"}).status_code == 200

    import pygments.lexers

    monkeypatch.setattr(
        pygments.lexers,
        "get_lexer_by_name",
        lambda *a, **kw: pytest.fail("Repeated lexer work"),
    )
    assert client.get("/artifact", params={"view": "watch:exact:é"}).status_code == 200


@pytest.mark.parametrize("requested,expected", [("auto", "python"), ("text", "text")])
def test_file_backed_python_respects_explicit_text_override(
    client, tmp_path, monkeypatch, requested, expected
):
    path = tmp_path / "source.pyi"
    path.write_text("def work(x: int) -> str: ...\n")
    monkeypatch.setattr(
        runtime, "resolve_watch_materialization", lambda *a, **kw: "file"
    )
    runtime.register_watch_views(
        [runtime.WatchConfig(path=path, kind=requested, label="code", section="watch")],
        activate_first_if_none=True,
    )
    reply = client.get("/artifact", params={"view": "watch:code"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["kind"] == expected
    assert reply.json()["meta"]["source_info"]["language"] == "python"
    assert (
        next(v for v in store.list_views() if v.view_id == "watch:code").icon_key
        == expected
    )


def test_trimmed_tail_cannot_claim_complete_lexical_context(client, tmp_path):
    path = tmp_path / "source.py"
    path.write_text('value = """\n' + "still inside a string\n" * 100 + 'end"""\n')
    spec = runtime.WatchConfig(path=path, read_mode="tail", max_bytes=100)
    raw = runtime.read_watch_file_bytes(
        path, read_mode="tail", max_bytes=100, watch_config=spec
    )
    assert len(raw) < 100  # First partial line was dropped.
    result = runtime.build_watch_publish_payload(
        path=path,
        raw=raw,
        watch_config=spec,
        read_mode="tail",
        max_bytes=100,
        source_size_bytes=path.stat().st_size,
    )
    assert result.source_info["partial"]
    rendered = render_any(
        result.artifact,
        view_id="v",
        kind_hint=result.artifact_kind,
        source_info=result.source_info,
    )
    assert "ps-code-token--" not in rendered.html
    session = register(client)
    body = envelope(session, raw, name="source.py", complete=False)
    body["source"]["read_scope"] = "tail"
    post(client, body)
    reply = client.get("/artifact", params={"view": "watch:exact:é"}).json()
    assert "ps-code-token--" not in reply["html"]


def test_watch_metadata_is_given_to_existing_storage_queue(client, monkeypatch):
    from plotsrv import app as app_mod

    tasks = []
    monkeypatch.setattr(app_mod, "enqueue_snapshot", lambda **kw: tasks.append(kw))
    session = register(client)
    post(client, envelope(session, b"SELECT 1;", name="query.sql"))
    assert tasks[0]["extra"]["source_info"]["language"] == "sql"
    assert tasks[0]["obj"] == "SELECT 1;"
