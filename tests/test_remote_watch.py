from __future__ import annotations

import base64
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from plotsrv import config, settings, store, ingestion
from plotsrv.app import app
from plotsrv import remote_watch as receiver
from plotsrv import publisher_agent as agent
from plotsrv.watch_capture import capture, prepare, MAX_SOURCE_BYTES, MAX_ROWS
from plotsrv.runtime import WatchConfig
from plotsrv.publishing.models import PublishTarget
from plotsrv.publishing.transport import TransportError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app, client=("127.0.0.1", 1))


def register(client, vid="watch:exact:é", client_id="owner"):
    result = client.post(
        "/watch/register",
        json=dict(
            protocol_version=1,
            view_id=vid,
            client_id=client_id,
            label="Named source",
            section="Logs",
        ),
    )
    assert result.status_code == 200, result.text
    return result.json()["session"]


def envelope(
    session,
    raw=b"hello",
    *,
    name="source.txt",
    revision=1,
    complete=True,
    vid="watch:exact:é",
):
    return dict(
        protocol_version=1,
        view_id=vid,
        session=session,
        revision=revision,
        data_b64=base64.b64encode(raw).decode(),
        status="available",
        source=dict(
            basename=name,
            source_type="watch",
            generation="rotation-1",
            size_bytes=len(raw) if complete else 10**12,
            mtime_ns=1,
            read_scope="full" if complete else "head",
            complete=complete,
            encoding="utf-8",
            kind="auto",
        ),
    )


def post(client, body):
    result = client.post("/watch/update", json=body)
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize(
    "name,raw,kind",
    [
        ("example.py", b"print('safe')", "code"),
        ("small.json", b'{"a": [1,2]}', "json"),
        ("settings.toml", b"x=1\n", "json"),
        ("config.yml", b"x: 1\n", "json"),
        (
            "page.html",
            b'<script>fetch("/private")</script><img src="local.png">',
            "html",
        ),
        ("table.csv", b"a,b\n1,2\n3,4\n", "table"),
    ],
)
def test_supported_complete_sources_and_hosted_download(client, name, raw, kind):
    session = register(client)
    post(client, envelope(session, raw, name=name))
    assert not store.has_watched_file_meta(view_id="watch:exact:é")
    meta = receiver.public_meta("watch:exact:é")
    assert meta["full_download"] and "path" not in meta
    response = client.get(meta["source_download_url"])
    assert response.content == raw
    assert "attachment" in response.headers["content-disposition"]
    if kind == "table":
        assert client.get("/table/data", params={"view": "watch:exact:é"}).json()[
            "meta"
        ]["complete"]
    else:
        response = client.get("/artifact", params={"view": "watch:exact:é"}).json()
        assert response["kind"] == kind
        assert "Complete source hosted" in response["html"]
        if kind == "html":
            assert store.get_artifact(view_id="watch:exact:é").obj["_plotsrv_remote"] is False


def test_previews_exports_and_parse_limits(client):
    session = register(client)
    post(
        client, envelope(session, b'{"unfinished":', name="large.json", complete=False)
    )
    response = client.get("/artifact", params={"view": "watch:exact:é"}).json()
    assert response["kind"] == "text" and "parsing unavailable" in response["html"]
    assert response["meta"]["source_download_url"] is None
    assert (
        client.get("/watch/source", params={"view": "watch:exact:é"}).status_code == 404
    )
    assert (
        client.get(response["meta"]["preview_download_url"]).headers[
            "x-plotsrv-coverage"
        ]
        == "preview"
    )
    post(
        client,
        envelope(session, b"a,b\n1,2\n", name="large.csv", complete=False, revision=2),
    )
    table = client.get("/table/data", params={"view": "watch:exact:é"}).json()
    assert table["total_rows_known"] is False and table["total_rows"] is None
    exported = client.get("/table/export", params={"view": "watch:exact:é"})
    assert "preview" in exported.headers["content-disposition"]


def test_versions_retries_rotation_status_and_conflicting_owner(client):
    session = register(client)
    assert register(client) == session
    post(client, envelope(session, b"new", revision=3))
    count = store.get_data_activity(view_id="watch:exact:é")["event_count"]
    assert post(client, envelope(session, b"old", revision=2))["ignored"]
    assert post(client, envelope(session, b"new", revision=4))["ignored"]
    post(
        client,
        dict(
            protocol_version=1,
            view_id="watch:exact:é",
            session=session,
            revision=5,
            status="missing",
        ),
    )
    assert store.get_artifact(view_id="watch:exact:é").obj == "new"
    assert store.get_data_activity(view_id="watch:exact:é")["event_count"] == count
    assert receiver.public_meta("watch:exact:é")["status"] == "missing"
    status = client.get("/status", params={"view": "watch:exact:é"}).json()
    assert status["data_source"] == {
        "type": "remote_watch",
        "label": "Remote watched file — missing",
    }
    assert (
        client.post(
            "/watch/register",
            json=dict(protocol_version=1, view_id="watch:exact:é", client_id="other"),
        ).status_code
        == 409
    )
    post(client, envelope(session, b"recovered", revision=6))
    assert receiver.public_meta("watch:exact:é")["status"] == "available"
    client.post(
        "/watch/close",
        json=dict(protocol_version=1, view_id="watch:exact:é", session=session),
    )
    replacement = register(client, client_id="other")
    assert replacement != session
    assert (
        client.post(
            "/watch/update", json=envelope(session, b"late", revision=100)
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "field", ["path", "local_path", "watched_file", "snapshot", "source_download_url"]
)
def test_receiver_rejects_filesystem_or_policy_instructions(
    client, tmp_path, monkeypatch, field
):
    secret = tmp_path / "server-secret.txt"
    secret.write_text("never read")
    session = register(client)
    body = envelope(session)
    body["source"][field] = str(secret)
    monkeypatch.setattr(
        Path, "open", lambda *_a, **_k: pytest.fail("receiver opened a path")
    )
    result = client.post("/watch/update", json=body)
    assert result.status_code == 422
    assert not store.has_artifact(view_id="watch:exact:é")


def test_source_basename_escape_and_symlink_capture(client, tmp_path):
    session = register(client)
    for name in ("../../secret", "/etc/passwd", "..", "a\\secret"):
        assert (
            client.post("/watch/update", json=envelope(session, name=name)).status_code
            == 422
        )
    source = tmp_path / "actual.txt"
    source.write_text("private")
    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(OSError):
        capture(link)


def test_auth_seal_unknown_and_no_snapshots(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WATCH_KEY", "secret")
    (tmp_path / "plotsrv.yml").write_text(
        "server-settings:\n  ingestion:\n    bearer_token_env: WATCH_KEY\n  admission:\n    mode: catalogue-locked\n"
    )
    ingestion.reset_ingestion()
    assert client.post("/watch/register", json={}).status_code == 401
    client.headers["Authorization"] = "Bearer wrong"
    assert client.post("/watch/update", content=b"not json").status_code == 401
    client.headers["Authorization"] = "Bearer secret"
    body = dict(protocol_version=1, views=[dict(view_id="known", label="Known")])
    assert client.post("/catalogue/bootstrap", json=body).status_code == 200
    assert client.post("/catalogue/bootstrap", json=body).json()["idempotent"]
    assert (
        client.post(
            "/watch/register",
            json=dict(protocol_version=1, view_id="unknown", client_id="id"),
        ).status_code
        == 403
    )
    session = register(client, vid="known")
    post(client, envelope(session, vid="known"))
    assert (
        client.get("/history", params={"view": "known"}).json()["capability"]["enabled"]
        is False
    )


def test_image_validation_decoded_size_and_binary_rejection(client):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "PNG")
    session = register(client)
    post(client, envelope(session, buf.getvalue(), name="small.png"))
    assert store.get_artifact(view_id="watch:exact:é").kind == "image"
    big = io.BytesIO()
    Image.new("1", (3000, 3000)).save(big, "PNG")
    for raw, name, complete in [
        (big.getvalue(), "big.png", True),
        (b"cut", "small.png", False),
        (b"\0\0", "binary.dat", True),
        (b"<svg/>", "image.svg", True),
    ]:
        assert (
            client.post(
                "/watch/update",
                json=envelope(session, raw, name=name, complete=complete, revision=2),
            ).status_code
            == 422
        )
    assert store.get_artifact(view_id="watch:exact:é").kind == "image"


def test_sparse_bounds_giant_csv_lines_and_multiline_records(tmp_path):
    source = tmp_path / "large.txt"
    with source.open("wb") as file:
        file.write(b"start")
        file.seek(1024**3)
        file.write(b"end")
    for mode in ("head", "tail"):
        # A larger local/configured read cap cannot expand remote transfer.
        result = capture(source, read_mode=mode, maximum=500 * 1024 * 1024)
        assert result.bytes_read == MAX_SOURCE_BYTES
        assert len(result.raw) == MAX_SOURCE_BYTES
        assert result.source["complete"] is False
    source = tmp_path / "data.csv"
    source.write_bytes(b'a,b\n1,"two\nlines"\n3,four\n')
    result = capture(source)
    payload, _, _ = prepare(result.raw, result.source)
    assert payload["table"]["rows"][0][1] == "two\nlines"
    source.write_bytes(b"a,b\n" + b"x" * (MAX_SOURCE_BYTES * 2))
    result = capture(source, read_mode="tail")
    assert result.bytes_read <= MAX_SOURCE_BYTES
    source.write_bytes(b'"' + b"x" * (MAX_SOURCE_BYTES * 2))
    result = capture(source, read_mode="head")
    payload, limitation, _ = prepare(result.raw, result.source)
    assert payload["kind"] == "artifact" and limitation


def test_csv_rows_columns_and_ambiguous_tail_bounds(tmp_path):
    source = tmp_path / "many.csv"
    source.write_text("a,b\n" + "1,2\n" * (MAX_ROWS + 10))
    result = capture(source)
    payload, limitation, _ = prepare(result.raw, result.source)
    assert len(payload["table"]["rows"]) == MAX_ROWS and limitation
    tail = dict(result.source, complete=False, read_scope="tail")
    payload, limitation, _ = prepare(b'a,b\n"multi\nline",2\n', tail)
    assert payload["kind"] == "artifact" and "ambiguous" in limitation


def connect_watcher(monkeypatch, client, path, **kwargs):
    monkeypatch.setattr(
        agent,
        "handshake",
        lambda *_a, **_k: SimpleNamespace(
            server_generation=ingestion.state().generation
        ),
    )

    def send(_target, route, body, **_kw):
        result = client.post(route, json=body)
        if result.status_code != 200:
            raise TransportError(
                "test", reason=result.json().get("detail", {}).get("reason")
            )
        return result.json()

    monkeypatch.setattr(agent, "request_json", send)
    return agent.RemoteWatcher(
        [WatchConfig(path=path, view_id="watch:exact:é", **kwargs)],
        PublishTarget("remote"),
        every=0.1,
    )


def tick(watcher):
    for current in watcher.states:
        current.next_due = 0
    watcher.tick()


def test_watcher_debounce_coalesces_recovers_restarts_and_closes(
    tmp_path, monkeypatch, client
):
    path = tmp_path / "publisher" / "log.txt"
    path.parent.mkdir()
    path.write_text("first")
    watcher = connect_watcher(monkeypatch, client, path)
    tick(watcher)
    assert watcher.bytes_read == 0
    path.write_text("latest")
    tick(watcher)
    tick(watcher)
    assert store.get_artifact(view_id="watch:exact:é").obj == "latest"
    previous_bytes = watcher.bytes_read
    tick(watcher)
    assert watcher.bytes_read == previous_bytes
    path.unlink()
    tick(watcher)
    assert receiver.public_meta("watch:exact:é")["status"] == "missing"
    path.write_text("replacement")
    tick(watcher)
    tick(watcher)
    assert store.get_artifact(view_id="watch:exact:é").obj == "replacement"
    old = watcher.states[0].session
    store.reset()
    tick(watcher)
    assert watcher.states[0].session != old
    assert store.get_artifact(view_id="watch:exact:é").obj == "replacement"
    watcher.close()
    assert receiver.public_meta("watch:exact:é")["status"] == "stopped"


def test_unavailable_server_never_reads_and_cancel_starts_no_workers(
    tmp_path, monkeypatch
):
    path = tmp_path / "source.txt"
    path.write_text("unchanged")

    def unavailable(*a, **k):
        raise TransportError("unavailable_server")

    monkeypatch.setattr(agent, "handshake", unavailable)
    monkeypatch.setattr(
        agent, "capture", lambda *a, **k: pytest.fail("read before admission")
    )
    watcher = agent.RemoteWatcher([WatchConfig(path=path)], PublishTarget("remote"))
    before = threading.active_count()
    tick(watcher)
    watcher.stop.set()
    watcher.run()
    assert threading.active_count() == before and watcher.bytes_read == 0


def test_mid_read_replacement_keeps_last_good(tmp_path, monkeypatch, client):
    path = tmp_path / "source.txt"
    path.write_text("good")
    watcher = connect_watcher(monkeypatch, client, path)
    tick(watcher)
    tick(watcher)
    path.write_text("writing")
    tick(watcher)
    monkeypatch.setattr(
        agent, "capture", lambda *a, **k: (_ for _ in ()).throw(BlockingIOError())
    )
    tick(watcher)
    assert store.get_artifact(view_id="watch:exact:é").obj == "good"
    assert receiver.public_meta("watch:exact:é")["status"] == "changing"


def test_aggregate_hosted_capacity_rejects_before_mutating_last_good(
    client, monkeypatch
):
    session = register(client)
    post(client, envelope(session, b"good"))
    monkeypatch.setattr(receiver, "MAX_HOSTED_BYTES", 16)
    response = client.post(
        "/watch/update", json=envelope(session, b"larger version", revision=2)
    )
    assert response.status_code == 429
    assert store.get_artifact(view_id="watch:exact:é").obj == "good"
    assert receiver.records()["watch:exact:é"]["revision"] == 1


def test_complete_json_partial_write_preserves_last_good_and_recovers(client):
    session = register(client)
    post(client, envelope(session, b'{"ok": 1}', name="state.json"))
    before = store.get_data_activity(view_id="watch:exact:é")["event_count"]
    post(client, envelope(session, b'{"ok":', name="state.json", revision=2))
    assert receiver.public_meta("watch:exact:é")["status"] == "changing"
    assert store.get_artifact(view_id="watch:exact:é").obj == {"ok": 1}
    assert store.get_data_activity(view_id="watch:exact:é")["event_count"] == before
    post(client, envelope(session, b'{"ok": 2}', name="state.json", revision=3))
    assert store.get_artifact(view_id="watch:exact:é").obj == {"ok": 2}


def test_oversize_wire_deep_json_and_yaml_aliases_are_bounded(client):
    assert (
        client.post("/watch/update", content=b"x" * (384 * 1024 + 1)).status_code == 413
    )
    session = register(client)
    for i, (raw, name) in enumerate(
        [
            (b"[" * 100 + b"0" + b"]" * 100, "nested.json"),
            (b"x: &x [1,2]\ny: *x\n", "alias.yaml"),
        ],
        1,
    ):
        post(client, envelope(session, raw, name=name, revision=i))
        assert store.get_artifact(view_id="watch:exact:é").kind == "text"


def test_real_capture_detects_replacement_after_read(tmp_path, monkeypatch):
    path = tmp_path / "source.txt"
    path.write_text("old")
    original = Path.lstat

    def replace_before_check(current):
        other = tmp_path / "replacement"
        other.write_text("new")
        other.replace(path)
        return original(current)

    monkeypatch.setattr(Path, "lstat", replace_before_check)
    with pytest.raises(BlockingIOError):
        capture(path)


def test_ordinary_publish_invalidates_hosted_source_capabilities(client):
    session = register(client)
    post(client, envelope(session))
    assert (
        client.post(
            "/publish",
            json=dict(
                view_id="watch:exact:é",
                kind="artifact",
                artifact_kind="text",
                artifact="direct",
                force=True,
            ),
        ).status_code
        == 200
    )
    assert (
        client.get("/watch/source", params={"view": "watch:exact:é"}).status_code == 404
    )
    assert receiver.public_meta("watch:exact:é") is None


def test_large_text_preview_survives_default_receiver_limits_and_off_display_limits(
    client, monkeypatch
):
    from plotsrv.watch_capture import MAX_TEXT_CHARS

    monkeypatch.setattr(config, "get_render_text_max_chars", lambda: None)
    session = register(client)
    post(client, envelope(session, b"x" * MAX_SOURCE_BYTES, complete=False))
    assert len(store.get_artifact(view_id="watch:exact:é").obj) <= MAX_TEXT_CHARS
    assert not receiver.public_meta("watch:exact:é")["full_download"]
    assert receiver.public_meta("watch:exact:é")["limitation"]


def test_ini_interpolation_is_literal_and_default_fanout_is_bounded(client, tmp_path):
    # This tiny input used to allocate >127 MiB before the output check.
    raw = b"[section]\na0 = " + b"x" * 100 + b"\n"
    for level in range(1, 6):
        raw += f"a{level} = ".encode() + (f"%(a{level-1})s" * 10).encode() + b"\n"
    path = tmp_path / "source.ini"
    path.write_bytes(raw)
    captured = capture(path)
    prepared, limitation, _ = prepare(captured.raw, captured.source)
    assert limitation is None
    assert len(json.dumps(prepared)) < 30_000
    assert "%(a4)s" in json.dumps(prepared)
    session = register(client)
    post(client, envelope(session, raw, name=path.name))
    assert receiver.public_meta("watch:exact:é")["full_download"]

    raw = b"[DEFAULT]\na=" + b"x" * 4000 + b"\n"
    raw += b"".join(f"[s{i}]\n".encode() for i in range(1000))
    path.write_bytes(raw)
    captured = capture(path)
    prepared, limitation, _ = prepare(captured.raw, captured.source)
    assert prepared["artifact_kind"] == "text"
    assert limitation
    assert len(json.dumps(prepared)) < 30_000


def test_complete_capture_keeps_tail_presentation(client, tmp_path, monkeypatch):
    import plotsrv.runtime as runtime

    path = tmp_path / "source.txt"
    path.write_text("FIRST-----LAST")
    monkeypatch.setattr(runtime, "get_watch_render_limit", lambda _: 4)
    watcher = connect_watcher(monkeypatch, client, path, read_mode="tail")
    tick(watcher)
    tick(watcher)
    assert store.get_artifact(view_id="watch:exact:é").obj == "LAST"
    meta = receiver.public_meta("watch:exact:é")
    assert meta["read_scope"] == "full" and meta["read_mode"] == "tail"
    assert client.get(meta["source_download_url"]).content == b"FIRST-----LAST"

    path = tmp_path / "source.csv"
    path.write_text("n\n" + "\n".join(map(str, range(250))) + "\n")
    result = capture(path, read_mode="tail")
    prepared = prepare(result.raw, result.source).payload
    assert prepared["table"]["rows"][0] == [50]
    assert prepared["table"]["rows"][-1] == [249]


def test_structured_growth_and_resource_limits_replace_old_good_content(client):
    session = register(client)
    post(client, envelope(session, b'{"v":1}', name="state.json"))
    raw = json.dumps({"v": "x" * 70_000}).encode()
    post(client, envelope(session, raw, name="state.json", revision=2))
    meta = receiver.public_meta("watch:exact:é")
    assert meta["status"] == "available"
    assert store.get_artifact(view_id="watch:exact:é").kind == "text"
    assert client.get(meta["source_download_url"]).content == raw


def test_continuous_changes_publish_bounded_latest_snapshots(
    client, tmp_path, monkeypatch
):
    path = tmp_path / "active.log"
    watcher = connect_watcher(monkeypatch, client, path)
    for i in range(20):
        path.write_text(str(i))
        tick(watcher)
    assert store.get_artifact(view_id="watch:exact:é").obj == "19"
    assert watcher.sent_updates == 10
    assert watcher.bytes_read <= 40
    before = watcher.bytes_read
    tick(watcher)
    assert watcher.bytes_read == before


@pytest.mark.parametrize("newer", [False, True])
def test_lost_ack_retries_same_revision_even_with_force(
    client, tmp_path, monkeypatch, newer
):
    path = tmp_path / "active.log"
    path.write_text("one")
    watcher = connect_watcher(monkeypatch, client, path, force=True)
    original = agent.request_json
    updates = []

    def send(target, route, body, **kwargs):
        response = original(target, route, body, **kwargs)
        if route == "/watch/update":
            updates.append(body["revision"])
            if len(updates) == 1:
                raise TransportError("server_unavailable")
        return response

    monkeypatch.setattr(agent, "request_json", send)
    tick(watcher)
    tick(watcher)
    if newer:
        path.write_text("newer")
    tick(watcher)
    tick(watcher)
    assert updates == ([1, 2] if newer else [1, 1])
    assert store.get_data_activity(view_id="watch:exact:é")["event_count"] == (
        2 if newer else 1
    )
    assert store.get_artifact(view_id="watch:exact:é").obj == (
        "newer" if newer else "one"
    )


def test_orphan_takeover_fences_late_updates_and_reclaims_closed_slots(
    client, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(receiver, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    session = register(client)
    post(client, envelope(session, b"old"))
    clock[0] += receiver.SESSION_LEASE_S + 1
    replacement = register(client, client_id="replacement")
    assert replacement != session
    post(client, envelope(replacement, b"new"))
    assert (
        client.post(
            "/watch/update", json=envelope(session, b"late", revision=99)
        ).status_code
        == 409
    )
    # Use a smaller bound to exercise the exact capacity transition without
    # bypassing HTTP rate admission or introducing sleeps.
    monkeypatch.setattr(receiver, "MAX_WATCHES", 2)
    other = register(client, vid="other")
    assert (
        client.post(
            "/watch/register",
            json=dict(protocol_version=1, view_id="full", client_id="x"),
        ).status_code
        == 429
    )
    client.post(
        "/watch/close", json=dict(protocol_version=1, view_id="other", session=other)
    )
    register(client, vid="replacement-slot")
    assert len(receiver.records()) == 2
    assert "other" not in receiver.records()
    assert receiver.public_meta("watch:exact:é")["full_download"]


def test_idle_renewal_ignores_long_capture_cadence(client, tmp_path, monkeypatch):
    path = tmp_path / "idle.txt"
    path.write_text("one")
    watcher = connect_watcher(monkeypatch, client, path, update_limit_s=3600)
    tick(watcher)
    tick(watcher)
    entry = receiver.records()["watch:exact:é"]
    session = entry["session"]
    entry["expires"] = 0
    watcher.states[0].refresh_at = 0
    before = watcher.bytes_read
    watcher.tick()
    assert entry["session"] == session and entry["expires"] > 0
    assert watcher.bytes_read == before


def test_preparation_does_not_block_registration_and_late_revision_is_fenced(
    client, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    session = register(client)
    entered, release = threading.Event(), threading.Event()
    original = receiver.prepare

    def slow(raw, source):
        if raw == b"slow":
            entered.set()
            assert release.wait(3)
        return original(raw, source)

    monkeypatch.setattr(receiver, "prepare", slow)
    with client, ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(post, client, envelope(session, b"slow"))
        assert entered.wait(2)
        try:
            fast = pool.submit(
                lambda: (
                    register(client, vid="independent"),
                    post(client, envelope(session, b"new", revision=2)),
                )
            )
            fast.result(timeout=1)
            assert client.get("/capabilities").status_code == 200
        finally:
            release.set()
        assert old.result(timeout=2)["ignored"]
    assert store.get_artifact(view_id="watch:exact:é").obj == "new"
    assert receiver.records()["watch:exact:é"]["raw"] == b"new"


def test_direct_commit_racing_watch_cannot_retain_wrong_download(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    session = register(client)
    post(client, envelope(session, b"initial"))
    entered, release = threading.Event(), threading.Event()
    original = store.set_artifact

    def paused(*args, **kwargs):
        if kwargs.get("obj") == "direct-final":
            entered.set()
            assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "set_artifact", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        direct = pool.submit(
            client.post,
            "/publish",
            json=dict(
                view_id="watch:exact:é",
                kind="artifact",
                artifact_kind="text",
                artifact="direct-final",
                force=True,
            ),
        )
        assert entered.wait(2)
        try:
            post(client, envelope(session, b"watch-latest", revision=2))
        finally:
            release.set()
        assert direct.result(timeout=2).status_code == 200
    assert store.get_artifact(view_id="watch:exact:é").obj == "direct-final"
    assert receiver.public_meta("watch:exact:é") is None
    assert (
        client.get("/watch/source", params={"view": "watch:exact:é"}).status_code == 404
    )


def test_owner_conflict_can_recover_after_crash_without_receiver_restart(
    client, tmp_path, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(receiver, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = register(client, client_id="crashed")
    path = tmp_path / "source.txt"
    path.write_text("replacement")
    watcher = connect_watcher(monkeypatch, client, path)
    tick(watcher)
    assert not watcher.states[0].fenced
    assert watcher.bytes_read == 0
    clock[0] += receiver.SESSION_LEASE_S + 1
    tick(watcher)
    tick(watcher)
    assert watcher.states[0].session != original
    assert store.get_artifact(view_id="watch:exact:é").obj == "replacement"


def test_registration_preserves_reviewed_catalogue_metadata(client):
    from plotsrv.contracts import ViewDescriptor, SourceMetadata

    descriptor = ViewDescriptor(
        "watch:exact:é",
        "Reviewed",
        kind="artifact",
        description="Keep this",
        source=SourceMetadata("source.txt", "watch"),
        capabilities=("preview",),
    )
    ingestion.register_catalogue([descriptor], seal=False)
    register(client)
    assert ingestion.state().descriptors[descriptor.view_id] == descriptor


def test_old_watch_receiver_is_rejected_before_file_capture(tmp_path, monkeypatch):
    from plotsrv.publishing import transport

    path = tmp_path / "source.txt"
    path.write_text("sensitive")
    target = PublishTarget("remote", base_url="http://old-receiver.test")
    transport.reset_transport()
    requests = []

    def exchange(target, route, payload, timeout):
        requests.append(route)
        return dict(
            protocol_version=1,
            stream_protocol_version=4,
            server_generation="old",
            dashboard_scope="test",
            capabilities=["watch-v1"],
        )

    monkeypatch.setattr(transport, "_exchange", exchange)
    watcher = agent.RemoteWatcher([WatchConfig(path=path)], target, every=0.1)
    for _ in range(10):
        tick(watcher)
    assert requests == ["/capabilities"]
    assert watcher.bytes_read == 0


def test_closed_sources_cannot_exhaust_hosted_byte_budget(client, monkeypatch):
    session = register(client)
    post(client, envelope(session, b"old"))
    cost = receiver.records()["watch:exact:é"]["cost"]
    client.post(
        "/watch/close",
        json=dict(protocol_version=1, view_id="watch:exact:é", session=session),
    )
    monkeypatch.setattr(receiver, "MAX_HOSTED_BYTES", cost)
    replacement = register(client, vid="new")
    post(client, envelope(replacement, b"new", vid="new"))
    assert "watch:exact:é" not in receiver.records()
    assert receiver.records()["new"]["raw"] == b"new"
    assert sum(e.get("cost", 0) for e in receiver.records().values()) <= cost
