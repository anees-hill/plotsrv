from __future__ import annotations

from datetime import UTC, datetime
import io
import json
from pathlib import Path

import pytest

from plotsrv.streams import api, text_framing
from plotsrv.streams.file_source import JsonlFollower
from plotsrv.streams.http_adapter import adapt_frame
from plotsrv.streams.models import validate_stream_batch
from plotsrv.streams.text_framing import TextFrame, TextFramer, ReadBudget
from plotsrv.streams.text_source import TextFollower

FIXTURES = Path(__file__).parent / "fixtures/http_logs"
NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)


def follow(tmp_path, content, callback=None):
    source = tmp_path / "service.log"
    source.write_bytes(b"")
    batches = []
    follower = TextFollower(
        source, on_batch=callback or (lambda batch: batches.append(batch) or True)
    )
    source.write_bytes(content)
    return source, follower, batches


def finish(follower, batches):
    try:
        assert follower.drain(timeout_s=2)
        for batch in batches:
            validate_stream_batch(tuple(r.data for r in batch.records))
        return [r.data for batch in batches for r in batch.records]
    finally:
        follower.close()


def test_mixed_fixture_keeps_unknown_and_does_not_correlate_500(tmp_path):
    _, follower, batches = follow(tmp_path, (FIXTURES / "mixed.txt").read_bytes())
    events = finish(follower, batches)
    assert len(events) == 9
    requests = [e for e in events if "http" in e]
    assert [e["http"]["status"] for e in requests] == [200, 404, 500]
    assert requests[1]["http"]["path"] == "/missing"
    assert "private" not in json.dumps(events)
    assert all("duration_ms" not in e["http"] for e in requests)
    assert all(e["event"]["publisher_observed_at"] for e in events)
    assert all("source_timestamp" not in e["event"] for e in events)
    assert events[-1]["raw"]["text"].startswith('{"incomplete":')
    assert events[5]["raw"]["text"] == "\n"


def test_supported_timestamps_duration_and_malformed_paths(tmp_path):
    _, follower, batches = follow(tmp_path, (FIXTURES / "forms.txt").read_bytes())
    events = finish(follower, batches)
    assert [e.get("http", {}).get("status") for e in events] == [
        201,
        200,
        204,
        None,
        None,
    ]
    assert events[1]["http"]["duration_ms"] == 12.5
    assert events[2]["http"]["duration_ms"] == 500
    assert events[1]["event"]["source_timestamp"] == "2026-09-09T12:00:00+00:00"
    assert events[2]["event"]["source_timezone_known"] is False
    assert "terminal_controls_removed" in events[0]["raw"]["transformations"]


def test_chains_group_without_paths_or_request_association(tmp_path):
    _, follower, batches = follow(tmp_path, (FIXTURES / "chained.txt").read_bytes())
    events = finish(follower, batches)
    assert len(events) == 1
    event = events[0]
    assert event["event"]["kind"] == "traceback"
    assert event["raw"]["ambiguous"] is True
    assert "During handling" in event["raw"]["text"]
    assert 'File "app.py"' in event["raw"]["text"]
    assert 'File "api.py"' in event["raw"]["text"]
    assert "private" not in json.dumps(event)
    assert "http" not in event


def test_interleaving_splits_at_recognisable_boundaries(tmp_path):
    _, follower, batches = follow(tmp_path, (FIXTURES / "interleaved.txt").read_bytes())
    events = finish(follower, batches)
    assert [e["event"]["kind"] for e in events] == [
        "traceback",
        "traceback",
        "http_request",
        "text",
        "text",
    ]
    assert all(e["raw"]["ambiguous"] for e in events[:2])
    assert all("request_id" not in e for e in events)


def test_idle_partial_frame_finalises_without_newline():
    source = io.BytesIO(b"application partial")
    framer = TextFramer()
    assert framer.read(source, 0, now=0, budget=ReadBudget())[0] is None
    frame, end = framer.read(source, 0, now=1.1, budget=ReadBudget())
    assert frame.raw == b"application partial" and frame.partial
    assert end == len(source.getvalue())
    assert framer.read(source, end, now=2, budget=ReadBudget())[0] is None


def test_partial_write_completed_during_grace_is_one_access_event():
    framer = TextFramer()
    first = b'INFO: 127.0.0.1:42 - "GET /health'
    assert framer.read(io.BytesIO(first), 0, now=0, budget=ReadBudget())[0] is None
    frame, _ = framer.read(
        io.BytesIO(first + b' HTTP/1.1" 200\n'), 0, now=0.5, budget=ReadBudget()
    )
    assert (
        adapt_frame(frame, observed_at=NOW, adapter="uvicorn")["http"]["status"] == 200
    )
    assert not frame.partial


def test_giant_unterminated_line_is_bounded_and_resynchronises(tmp_path):
    source, follower, batches = follow(tmp_path, b"x" * (2 * 1024 * 1024))
    try:
        follower._read_available_records()
        assert len(batches) == 1
        assert batches[0].records[0].data["raw"]["truncated"] is True
        assert follower.accounted_source_offset <= text_framing.MAX_CYCLE_BYTES
        assert len(json.dumps(batches[0].records[0].data)) < 10_000
        previous = follower.accounted_source_offset
        for _ in range(2):
            follower._read_available_records()
            assert (
                follower.accounted_source_offset - previous
                <= text_framing.MAX_CYCLE_BYTES
            )
            previous = follower.accounted_source_offset
        with source.open("ab") as output:
            output.write(b'\nINFO: 127.0.0.1:42 - "GET /ok HTTP/1.1" 200\n')
        assert follower.drain(timeout_s=2)
        events = [r.data for b in batches for r in b.records]
        assert len(events) == 2 and events[-1]["http"]["path"] == "/ok"
    finally:
        follower.close()


def test_batch_retry_keeps_ids_timestamps_and_does_not_read_ahead(tmp_path):
    calls = []
    source, follower, _ = follow(
        tmp_path, b"one\n", lambda batch: calls.append(batch) or len(calls) > 1
    )
    try:
        follower._read_available_records()
        with source.open("ab") as output:
            output.write(b"two\n")
        assert follower.acknowledged_source_offset == 0
        follower._read_available_records()
        assert calls[0] is calls[1]
        assert follower.acknowledged_source_offset == 4
        follower._read_available_records()
        assert calls[2].batch_id != calls[0].batch_id
        assert calls[2].records[0].data["raw"]["text"] == "two\n"
    finally:
        follower.close()


def test_rotation_finalises_partial_predecessor_and_warns_before_new_records(tmp_path):
    source, follower, batches = follow(tmp_path, b"old unfinished")
    try:
        follower._read_available_records()
        source.rename(source.with_suffix(".old"))
        source.write_bytes(b"new complete\n")
        assert follower.drain(timeout_s=2)
        events = [r.data for b in batches for r in b.records]
        assert [e["raw"]["text"] for e in events] == [
            "old unfinished",
            "new complete\n",
        ]
        assert events[0]["raw"]["partial"]
        assert follower.health()["continuity_warning"] is not None
    finally:
        follower.close()


def test_truncation_resets_unaccepted_partial_state(tmp_path):
    source, follower, batches = follow(tmp_path, b"pending longer fragment")
    try:
        follower._read_available_records()
        source.write_bytes(b"new\n")
        assert follower.drain(timeout_s=2)
        assert [r.data["raw"]["text"] for b in batches for r in b.records] == ["new\n"]
        assert follower.health()["continuity_warning"]
    finally:
        follower.close()


@pytest.mark.parametrize(
    "value",
    [
        b"\xff" * 8192,
        b"?x " * 2700,
        b"cookie:\n" * 1024,
        b"\x1b]52;c;secret\x07",
        b"Authorization: Bearer private\npassword=secret /home/private/key.txt\n",
    ],
)
def test_sanitised_events_fit_wire_and_remove_controls(value):
    frame = TextFrame(value, 0, len(value))
    data = adapt_frame(frame, observed_at=NOW, adapter="uvicorn")
    validate_stream_batch((data,))
    assert "\x1b" not in data["raw"]["text"]
    assert "Bearer private" not in data["raw"]["text"]
    assert "/home/private" not in data["raw"]["text"]


def test_explicit_text_adapter_does_not_invent_http():
    raw = b'INFO: 127.0.0.1:42 - "GET / HTTP/1.1" 200\n'
    assert "http" not in adapt_frame(
        TextFrame(raw, 0, len(raw)), observed_at=NOW, adapter="text"
    )


def test_api_default_and_auto_preserve_strict_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(api.StreamClient, "start", lambda self: None)
    monkeypatch.setattr(JsonlFollower, "start", lambda self: None)
    for format, name, expected in [
        ("jsonl", "source.jsonl", JsonlFollower),
        ("auto", "source.ndjson", JsonlFollower),
        ("auto", "service.log", TextFollower),
        ("text", "service.log", TextFollower),
        ("uvicorn", "service.log", TextFollower),
    ]:
        handle = api.stream_view(source=tmp_path / name, format=format)
        try:
            assert type(handle._follower) is expected
        finally:
            api._stream_exit_cleanup_manager.unregister(handle)
            handle._follower.close()
    with pytest.raises(ValueError):
        api.stream_view(source=tmp_path / "service.log")
    with pytest.raises(ValueError):
        api.stream_view(source=tmp_path / "service.log", format="universal")


def test_cycle_budget_counts_actual_reads_and_lines():
    class Counted(io.BytesIO):
        bytes_read = 0
        calls = 0

        def readline(self, limit=-1):
            assert 0 <= limit <= text_framing.MAX_LINE_BYTES + 1
            value = super().readline(limit)
            self.bytes_read += len(value)
            self.calls += 1
            return value

    source = Counted(b"x" * (1024 * 1024))
    framer, budget, cursor = TextFramer(), ReadBudget(), 0
    while True:
        frame, end = framer.read(source, cursor, now=0, budget=budget)
        if end == cursor:
            break
        cursor = end
    assert source.bytes_read <= text_framing.MAX_CYCLE_BYTES
    assert source.calls <= text_framing.MAX_CYCLE_LINES
    assert framer.discarding
    assert not any(isinstance(v, (bytes, bytearray)) for v in vars(framer).values())


def test_line_and_frame_limits_preserve_following_records(tmp_path):
    content = (
        b"Traceback (most recent call last):\n"
        + b"  repeated frame\n" * 100
        + b"RuntimeError: done\n"
        + b"\n" * 200
    )
    _, follower, batches = follow(tmp_path, content)
    events = finish(follower, batches)
    assert events[0]["raw"]["truncated"]
    assert len(events[0]["raw"]["text"].splitlines()) <= text_framing.MAX_FRAME_LINES
    assert any("RuntimeError: done" in event["raw"]["text"] for event in events)
    assert sum(event["raw"]["text"] == "\n" for event in events) == 200
    assert all(len(batch.records) <= 100 for batch in batches)


def test_batch_byte_limit_retains_one_lookahead_without_duplicates(
    tmp_path, monkeypatch
):
    import plotsrv.streams.text_source as text_source

    monkeypatch.setattr(text_source, "MAX_STREAM_BATCH_BYTES", 600)
    _, follower, batches = follow(tmp_path, b"one\ntwo\nthree\nfour\n")
    events = finish(follower, batches)
    assert [e["raw"]["text"] for e in events] == ["one\n", "two\n", "three\n", "four\n"]
    assert len(batches) > 1
    assert len({b.batch_id for b in batches}) == len(batches)


def test_default_start_at_end_and_mid_line_continuation_are_explicit(tmp_path):
    source = tmp_path / "app.log"
    source.write_bytes(b"history without newline")
    batches = []
    follower = TextFollower(source, on_batch=lambda b: batches.append(b) or True)
    with source.open("ab") as output:
        output.write(b' continued\nINFO: 127.0.0.1:42 - "GET / HTTP/1.1" 200\n')
    events = finish(follower, batches)
    assert events[0]["raw"]["text"] == " continued\n"
    assert events[0]["raw"]["ambiguous"]
    assert events[1]["http"]["path"] == "/"
    assert "history" not in json.dumps(events)


def test_ansi_traceback_and_direct_exception_chain(tmp_path):
    text = (
        (FIXTURES / "chained.txt")
        .read_bytes()
        .replace(
            b"During handling of the above exception, another exception occurred:",
            b"The above exception was the direct cause of the following exception:",
        )
        .replace(
            b"Traceback (most recent call last):",
            b"\x1b[31mTraceback (most recent call last):\x1b[0m",
        )
    )
    _, follower, batches = follow(tmp_path, text)
    events = finish(follower, batches)
    assert len(events) == 1 and events[0]["event"]["kind"] == "traceback"
    assert "\x1b" not in events[0]["raw"]["text"]


def test_remote_text_uses_existing_authenticated_stream_and_survives_restart(
    tmp_path, monkeypatch
):
    import time
    from plotsrv import settings
    from plotsrv.publishing import transport
    from plotsrv.publishing.models import PublishTarget
    from plotsrv.streams.client import StreamClient
    from plotsrv.streams.models import StreamRegistration
    from tests.test_standalone import ServerProcess

    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.setenv("REMOTE_TEST_KEY", "integration-test-key")
    monkeypatch.setattr(transport, "FAILURE_COOLDOWN_S", 0.05)
    server = ServerProcess(tmp_path, key=True)
    target = PublishTarget(
        kind="remote",
        base_url=f"http://127.0.0.1:{server.port}/",
        bearer_token_env="REMOTE_TEST_KEY",
    )
    source = server.publisher_dir / "access.log"
    source.write_bytes(b"")
    client = StreamClient(
        destination=target,
        registration=StreamRegistration(
            view_id="web:access",
            label="Access",
            section="web",
            client_id="producer",
            session_id="first",
        ),
    )
    batches = []

    def send(batch):
        batches.append(batch)
        return client.append_batch(batch, force=True)

    follower = TextFollower(
        source, on_batch=send, on_source_status=client.publish_source_status
    )
    client.set_source_status_provider(follower.source_status)
    client.set_source_health_provider(follower.health)
    try:
        server.start()
        source.write_bytes(
            b'INFO: 127.0.0.1:42 - "GET /health?token=secret HTTP/1.1" 200\n'
        )
        assert follower.drain(timeout_s=2)
        first = server.get("/stream/data?view=web:access")
        assert first["records"][0]["data"]["http"]["path"] == "/health"
        assert "secret" not in json.dumps(first)
        server.stop()
        with source.open("ab") as output:
            output.write(b'INFO: 127.0.0.1:42 - "GET /next HTTP/1.1" 503\n')
        follower._read_available_records()
        pending = batches[-1]
        assert follower._in_flight_batch is pending
        server.start()
        # The existing stream client fences the old receiver epoch, then
        # retries this exact already-framed candidate in its new session.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            time.sleep(0.05)
            follower._read_available_records()
            if follower._in_flight_batch is None:
                break
        assert follower._in_flight_batch is None
        assert batches[-1] is pending
        current = server.get("/stream/data?view=web:access")
        assert current["accepted_records"] == 1
        assert current["records"][0]["data"]["http"]["status"] == 503
        assert client.registration.session_id != "first"
        assert str(server.publisher_dir) not in json.dumps(current)
    finally:
        follower.close()
        server.close()


def test_jsonl_malformed_lines_and_oversized_suffix_have_per_turn_budgets(tmp_path):
    from plotsrv.streams import file_source

    source = tmp_path / "strict.jsonl"
    source.write_bytes(b"")
    batches = []
    follower = JsonlFollower(
        source, on_batch=lambda batch: batches.append(batch) or True
    )
    try:
        source.write_bytes(b"not-json\n" * 1000 + b'{"valid":true}\n')
        follower._read_available_records()
        assert follower.records_rejected == file_source.MAX_BATCH_RECORDS
        assert (
            follower.accounted_source_offset
            == len(b"not-json\n") * file_source.MAX_BATCH_RECORDS
        )
        assert follower.drain(timeout_s=2)
        assert batches[-1].records[0].data == {"valid": True}
    finally:
        follower.close()
    source.write_bytes(b"")
    follower = JsonlFollower(
        source, on_batch=lambda batch: batches.append(batch) or True
    )
    try:
        source.write_bytes(b"x" * (2 * 1024 * 1024) + b'\n{"next":true}\n')
        follower._read_available_records()
        assert follower._oversized_partial_scan_offset <= file_source.MAX_BATCH_BYTES
        assert follower.records_rejected == 0
        for _ in range(6):
            follower._read_available_records()
        assert follower.records_rejected == 1
        assert batches[-1].records[0].data == {"next": True}
        assert follower.acknowledged_source_offset == source.stat().st_size
    finally:
        follower.close()


def test_secret_fields_in_unknown_json_do_not_become_metadata():
    raw = b'{"event":"fake","http":{"status":200},"token":"private-value"}\n'
    event = adapt_frame(TextFrame(raw, 0, len(raw)), observed_at=NOW, adapter="uvicorn")
    assert event["event"]["kind"] == "text"
    assert "http" not in event
    assert "private-value" not in json.dumps(event)


def test_control_in_request_target_is_not_silently_turned_into_valid_http():
    raw = b'INFO: 127.0.0.1:42 - "GET /bad\x00path HTTP/1.1" 200\n'
    event = adapt_frame(TextFrame(raw, 0, len(raw)), observed_at=NOW, adapter="uvicorn")
    assert "http" not in event
    assert "\x00" not in event["raw"]["text"]


def test_late_fragment_cannot_become_a_spurious_http_request():
    framer = TextFramer()
    first = b"incomplete "
    frame, cursor = framer.read(
        io.BytesIO(first), 0, now=0, budget=ReadBudget(), finalize=True
    )
    assert frame.partial
    access = b'INFO: 127.0.0.1:42 - "GET / HTTP/1.1" 200\n'
    source = io.BytesIO(first + access + access)
    frame, cursor = framer.read(source, cursor, now=2, budget=ReadBudget())
    assert frame.ambiguous
    assert "http" not in adapt_frame(frame, observed_at=NOW, adapter="uvicorn")
    frame, cursor = framer.read(source, cursor, now=2, budget=ReadBudget())
    assert (
        adapt_frame(frame, observed_at=NOW, adapter="uvicorn")["http"]["status"] == 200
    )


def test_final_drain_does_not_retry_rejected_batch_after_skipped_jsonl(tmp_path):
    source = tmp_path / "drain.jsonl"
    source.write_bytes(b"")
    calls = []
    follower = JsonlFollower(
        source, on_batch=lambda batch: calls.append(batch) or False
    )
    try:
        source.write_bytes(b'bad-json\n{"valid":true}\n')
        assert not follower.drain(timeout_s=2)
        assert len(calls) == 1
        assert follower.accounted_source_offset == len(b"bad-json\n")
        assert follower.acknowledged_source_offset == 0
    finally:
        follower.close()
