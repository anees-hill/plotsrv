from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest
from fastapi.testclient import TestClient

from plotsrv import config, settings, store
from plotsrv.app import app
import plotsrv.http_streams as http_streams
import plotsrv.server as server_mod
import plotsrv.storage.stream_worker as stream_worker_mod
from plotsrv.storage import (
    STREAM_STORAGE_FORMAT_VERSION,
    FileStreamStorageBackend,
    RawBlockPolicy,
    StreamStorageCapacityError,
    StreamStoragePolicy,
    StreamStorageValidationError,
)
from plotsrv.storage import backend as storage_backend
from plotsrv.storage.stream_worker import (
    StreamPersistenceGapMarkerScheduler,
    StreamStorageSubmission,
    StreamStorageWorker,
)
from plotsrv.storage.worker import StorageWorker
from plotsrv.streams.models import (
    STREAM_PROTOCOL_VERSION,
    StreamAppend,
    StreamClose,
    StreamRegistration,
)
from plotsrv.streams.server_state import StreamRegistry, StreamStateError


@pytest.fixture(autouse=True)
def reset_stream_storage_state() -> None:
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]
    store.reset()
    yield
    store.reset()
    settings._CTX = settings.RuntimeContext()  # type: ignore[attr-defined]
    settings._CONFIG_CACHE.clear()  # type: ignore[attr-defined]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Keep route tests isolated from the process-global registry used by the
    # rest of the stream suite. Route handlers resolve this module attribute at
    # request time, so a fresh registry models a clean server process.
    monkeypatch.setattr(http_streams, "stream_registry", StreamRegistry())
    monkeypatch.setattr(config, "get_control_local_only", lambda: False)
    return TestClient(app)


def _configure_stream_storage(
    tmp_path: Path,
    *,
    enabled: bool = True,
    streams_yaml: str = "",
) -> Path:
    root = tmp_path / "stream-store"
    config_path = tmp_path / "plotsrv.yml"
    config_path.write_text(
        "\n".join(
            (
                "storage-settings:",
                f"  enabled: {'true' if enabled else 'false'}",
                f"  root_dir: {root}",
                streams_yaml.rstrip(),
            )
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    settings.set_runtime_context(config_path=config_path)
    return root


def _register(client: TestClient, *, view_id: str = "logs:persisted") -> None:
    response = client.post(
        "/stream/register",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": view_id,
            "label": "persisted",
            "section": "logs",
            "client_id": "storage-client",
            "session_id": "storage-session",
        },
    )
    assert response.status_code == 200, response.text


def _append(
    client: TestClient,
    *,
    batch_sequence: int,
    view_id: str = "logs:persisted",
    records: list[dict[str, object]] | None = None,
) -> None:
    response = client.post(
        "/stream/append",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": view_id,
            "client_id": "storage-client",
            "session_id": "storage-session",
            "batch_id": f"source-batch-{batch_sequence}",
            "batch_sequence": batch_sequence,
            "records": records or [{"level": "warning", "count": batch_sequence}],
        },
    )
    assert response.status_code == 200, response.text


def _wait_until(predicate: object, *, timeout_s: float = 2.0) -> None:
    assert callable(predicate)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "timed out waiting for independent stream persistence"


def _policy(*, max_bytes_per_view: int = 10_000) -> StreamStoragePolicy:
    return StreamStoragePolicy(
        summary_retention=2,
        noteworthy_keep_last=2,
        keep_last_sessions=2,
        max_bytes_per_view=max_bytes_per_view,
    )


def _write_completed_compact_session(root: Path) -> None:
    """Create a true compact snapshot with one derived and noteworthy item."""
    registry = StreamRegistry(max_recent_records=1, max_recent_bytes=10_000)
    registration = StreamRegistration(
        view_id="logs:restored",
        label="restored",
        section="logs",
        client_id="restore-client",
        session_id="restore-session",
    )
    registry.register(registration)
    for sequence, value in enumerate((10, 20)):
        registry.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id=f"batch-{sequence}",
                batch_sequence=sequence,
                records=({"level": "warning", "value": value},),
            )
        )
    registry.close(
        StreamClose(
            view_id=registration.view_id,
            client_id=registration.client_id,
            session_id=registration.session_id,
            drain_completed=True,
        )
    )
    snapshot = registry.persistence_snapshot(
        view_id=registration.view_id,
        session_id=registration.session_id,
    )
    snapshot["metadata"]["durable_history"] = {
        "state": "complete",
        "persistence_enabled": True,
        "pending_writes": 0,
        "completed_writes": 1,
        "rejected_writes": 0,
        "failed_writes": 0,
        "last_error": None,
        "last_persisted_at": None,
        "raw_persistence": "disabled",
    }
    FileStreamStorageBackend(root_dir=root).write_compact_session(
        view_id=snapshot["view_id"],
        session_id=snapshot["session_id"],
        client_id=snapshot["client_id"],
        metadata=snapshot["metadata"],
        summary_windows=snapshot["summary_windows"],
        noteworthy_items=snapshot["noteworthy_items"],
        policy=StreamStoragePolicy(
            summary_retention=8,
            noteworthy_keep_last=8,
            keep_last_sessions=2,
            max_bytes_per_view=100_000,
        ),
    )


def test_compact_stream_layout_is_versioned_atomic_and_raw_free(tmp_path: Path) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")

    paths = backend.session_paths(view_id="logs:worker/a", session_id="session/a")
    assert not paths.session_dir.exists()
    assert not backend.streams_root.exists()

    result = backend.write_compact_session(
        view_id="logs:worker/a",
        session_id="session/a",
        client_id="producer-a",
        metadata={
            "lifecycle": "ended",
            "cumulative": {"total_records": "4"},
            "continuity_warning": "source was truncated",
        },
        summary_windows=[
            {"object_type": "derived_stream_summary_window", "record_count": "3"},
            {"object_type": "derived_stream_summary_window", "record_count": "4"},
            {"object_type": "derived_stream_summary_window", "record_count": "5"},
        ],
        noteworthy_items=[
            {"kind": "system_notice", "event": "source_continuity_uncertain"},
            {"kind": "source_record", "data": {"level": "warning"}},
            {"kind": "system_notice", "event": "stream_schema_changed"},
        ],
        policy=_policy(),
    )

    assert result.summary_count == result.noteworthy_count == 2
    assert result.byte_count <= _policy().max_bytes_per_view
    assert paths.metadata.exists()
    assert paths.summaries.exists()
    assert paths.noteworthy.exists()
    assert not paths.raw_dir.exists()
    assert not list(paths.session_dir.glob(".*.tmp-*"))

    metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    assert metadata["storage_format_version"] == STREAM_STORAGE_FORMAT_VERSION
    assert metadata["storage_format"] == "plotsrv.stream-storage"
    assert metadata["view_id"] == "logs:worker/a"
    assert metadata["session_id"] == "session/a"
    assert metadata["compact_state"]["raw_persistence"] == "not_written_by_compact_storage"
    assert backend.read_session_metadata(
        view_id="logs:worker/a", session_id="session/a"
    ) == metadata

    summaries = [json.loads(line) for line in paths.summaries.read_text().splitlines()]
    assert [item["payload"]["record_count"] for item in summaries] == ["4", "5"]
    assert all(item["storage_kind"] == "summary" for item in summaries)
    noteworthy = [json.loads(line) for line in paths.noteworthy.read_text().splitlines()]
    assert [item["payload"]["kind"] for item in noteworthy] == [
        "source_record",
        "system_notice",
    ]
    assert all(item["storage_kind"] == "noteworthy" for item in noteworthy)


def test_compact_stream_write_rejects_raw_summary_and_over_capacity_without_mutation(
    tmp_path: Path,
) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    kwargs = {
        "view_id": "logs:bounded",
        "session_id": "session-1",
        "client_id": "producer",
        "metadata": {"lifecycle": "ended"},
        "summary_windows": [{"record_count": "1"}],
        "noteworthy_items": [],
    }
    backend.write_compact_session(**kwargs, policy=_policy())
    paths = backend.session_paths(view_id="logs:bounded", session_id="session-1")
    original = paths.metadata.read_bytes()

    with pytest.raises(StreamStorageValidationError, match="derived state"):
        backend.write_compact_session(
            **{**kwargs, "summary_windows": [{"data": {"not": "a summary"}}]},
            policy=_policy(),
        )
    assert paths.metadata.read_bytes() == original

    with pytest.raises(StreamStorageCapacityError, match="hard per-view byte limit"):
        backend.write_compact_session(
            **{
                **kwargs,
                "noteworthy_items": [{"kind": "source_record", "data": "x" * 4_000}],
            },
            policy=_policy(max_bytes_per_view=200),
        )
    assert paths.metadata.read_bytes() == original


def test_oversized_new_compact_does_not_prune_retained_history(
    tmp_path: Path,
) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:preflight"
    retained_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=1,
        max_bytes_per_view=20_000,
    )
    backend.write_compact_session(
        view_id=view_id,
        session_id="session-retained",
        client_id="producer",
        metadata={"lifecycle": "ended", "detail": "known-good"},
        summary_windows=[],
        noteworthy_items=[],
        policy=retained_policy,
    )
    retained_paths = backend.session_paths(
        view_id=view_id, session_id="session-retained"
    )
    original = retained_paths.metadata.read_bytes()

    with pytest.raises(StreamStorageCapacityError, match="hard per-view byte limit"):
        backend.write_compact_session(
            view_id=view_id,
            session_id="session-too-large",
            client_id="producer",
            metadata={"lifecycle": "ended", "detail": "x" * 10_000},
            summary_windows=[],
            noteworthy_items=[],
            policy=StreamStoragePolicy(
                summary_retention=1,
                noteworthy_keep_last=1,
                keep_last_sessions=1,
                max_bytes_per_view=500,
            ),
        )

    assert retained_paths.metadata.read_bytes() == original
    assert not backend.session_paths(
        view_id=view_id, session_id="session-too-large"
    ).session_dir.exists()


def test_stream_session_retention_prunes_only_older_generated_sessions(tmp_path: Path) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=2,
        max_bytes_per_view=10_000,
    )
    for index in range(3):
        backend.write_compact_session(
            view_id="logs:retained",
            session_id=f"session-{index}",
            client_id="producer",
            metadata={"lifecycle": "ended", "generation": index},
            summary_windows=[],
            noteworthy_items=[],
            policy=policy,
        )

    sessions = [path for path in backend.session_paths(
        view_id="logs:retained", session_id="session-2"
    ).view_dir.iterdir() if path.is_dir()]
    assert len(sessions) == 2
    assert backend.read_session_metadata(
        view_id="logs:retained", session_id="session-1"
    )["metadata"]["generation"] == 1
    assert backend.read_session_metadata(
        view_id="logs:retained", session_id="session-2"
    )["metadata"]["generation"] == 2
    with pytest.raises(LookupError):
        backend.read_session_metadata(view_id="logs:retained", session_id="session-0")


def test_compact_loader_rejects_files_from_different_generations(tmp_path: Path) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    kwargs = {
        "view_id": "logs:generation",
        "session_id": "session-1",
        "client_id": "producer",
        "metadata": {"lifecycle": "ended"},
        "noteworthy_items": [],
        "policy": _policy(),
    }
    backend.write_compact_session(
        **kwargs,
        summary_windows=[{"record_count": "1"}],
    )
    paths = backend.session_paths(view_id="logs:generation", session_id="session-1")
    old_metadata = paths.metadata.read_bytes()

    # Simulate a process stopping after replacing the compact JSONL files but
    # before publishing their matching metadata generation.
    backend.write_compact_session(
        **kwargs,
        summary_windows=[{"record_count": "2"}],
    )
    paths.metadata.write_bytes(old_metadata)

    with pytest.raises(LookupError, match="history (is invalid|is missing)"):
        backend.load_compact_session(view_id="logs:generation", session_id="session-1")


def test_durable_gap_marker_prevents_stale_complete_snapshot_restore(
    tmp_path: Path,
) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    kwargs = {
        "view_id": "logs:durable-gap",
        "session_id": "session-1",
        "client_id": "producer",
        "metadata": {
            "lifecycle": "ended",
            "durable_history": {"state": "complete", "persistence_enabled": True},
        },
        "summary_windows": [],
        "noteworthy_items": [],
        "policy": _policy(),
    }
    backend.write_compact_session(**kwargs)
    backend.mark_session_incomplete(
        view_id="logs:durable-gap",
        session_id="session-1",
        reason="stream persistence queue task budget reached",
        policy=_policy(),
    )

    # An older admitted worker snapshot may finish after the rejection. It
    # must not erase the irreversible observed-history gap on restart.
    backend.write_compact_session(**kwargs)
    loaded = backend.load_compact_session(
        view_id="logs:durable-gap", session_id="session-1"
    )
    durable = loaded.metadata["metadata"]["durable_history"]
    assert durable["state"] == "incomplete"
    assert "queue task budget" in durable["last_error"]


def test_durable_gap_marker_replaces_its_near_ceiling_compact_snapshot(
    tmp_path: Path,
) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:marker-current-session"
    session_id = "session-1"
    permissive_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=1,
        max_bytes_per_view=20_000,
    )
    backend.write_compact_session(
        view_id=view_id,
        session_id=session_id,
        client_id="producer",
        metadata={"lifecycle": "ended", "detail": "x" * 4_000},
        summary_windows=[],
        noteworthy_items=[],
        policy=permissive_policy,
    )
    paths = backend.session_paths(view_id=view_id, session_id=session_id)
    near_ceiling = backend._view_byte_count(paths.view_dir)
    assert near_ceiling > 1_000

    backend.mark_session_incomplete(
        view_id=view_id,
        session_id=session_id,
        reason="stream persistence queue task budget reached",
        policy=StreamStoragePolicy(
            summary_retention=1,
            noteworthy_keep_last=1,
            keep_last_sessions=1,
            max_bytes_per_view=near_ceiling,
        ),
    )

    # The compact payload cannot coexist with the marker at this ceiling, so
    # retaining the irreversible gap marker takes precedence over stale detail.
    assert paths.incomplete_marker.exists()
    assert not paths.metadata.exists()
    assert not paths.summaries.exists()
    assert not paths.noteworthy.exists()
    assert backend._view_byte_count(paths.view_dir) <= near_ceiling


def test_marker_only_gap_is_restored_as_visible_incomplete_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ceiling-preserved gap remains browseable even without compact data."""
    root = _configure_stream_storage(tmp_path)
    backend = FileStreamStorageBackend(root_dir=root)
    view_id = "logs:marker-current-session"
    session_id = "session-1"
    permissive_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=1,
        max_bytes_per_view=20_000,
    )
    backend.write_compact_session(
        view_id=view_id,
        session_id=session_id,
        client_id="producer",
        metadata={"lifecycle": "ended", "detail": "x" * 4_000},
        summary_windows=[],
        noteworthy_items=[],
        policy=permissive_policy,
    )
    paths = backend.session_paths(view_id=view_id, session_id=session_id)
    near_ceiling = backend._view_byte_count(paths.view_dir)
    backend.mark_session_incomplete(
        view_id=view_id,
        session_id=session_id,
        reason="stream persistence queue task budget reached",
        policy=StreamStoragePolicy(
            summary_retention=1,
            noteworthy_keep_last=1,
            keep_last_sessions=1,
            max_bytes_per_view=near_ceiling,
        ),
    )
    assert not paths.metadata.exists()
    assert backend.list_compact_sessions() == []
    assert [gap.session_id for gap in backend.list_marker_only_sessions()] == [
        session_id
    ]

    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)
    monkeypatch.setattr(http_streams, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 1
    client = TestClient(app)
    catalogue = client.get("/stream/history", params={"view": view_id})
    assert catalogue.status_code == 200, catalogue.text
    sessions = catalogue.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["view_id"] == view_id
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["historical"] is True
    assert sessions[0]["lifecycle"] == "incomplete"
    assert sessions[0]["durable_history"]["state"] == "incomplete"
    assert sessions[0]["raw_record_count"] == 0
    historical = client.get(
        "/stream/history", params={"view": view_id, "session_id": session_id}
    )
    assert historical.status_code == 200, historical.text
    data = historical.json()["data"]
    assert data["historical"] is True
    assert data["lifecycle"] == "incomplete"
    assert data["records"] == []
    assert data["durable_history"]["state"] == "incomplete"
    assert "queue task budget" in data["durable_history"]["last_error"]


def test_tiny_gap_marker_limit_removes_stale_complete_session(tmp_path: Path) -> None:
    """A gap that cannot fit must still not restore stale complete history."""
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:tiny-marker"
    session_id = "session-1"
    backend.write_compact_session(
        view_id=view_id,
        session_id=session_id,
        client_id="producer",
        metadata={"lifecycle": "ended", "detail": "previously complete"},
        summary_windows=[],
        noteworthy_items=[],
        policy=StreamStoragePolicy(
            summary_retention=1,
            noteworthy_keep_last=1,
            keep_last_sessions=1,
            max_bytes_per_view=20_000,
        ),
    )
    paths = backend.session_paths(view_id=view_id, session_id=session_id)

    backend.mark_session_incomplete(
        view_id=view_id,
        session_id=session_id,
        reason="write failed",
        policy=StreamStoragePolicy(
            summary_retention=1,
            noteworthy_keep_last=1,
            keep_last_sessions=1,
            max_bytes_per_view=1,
        ),
    )

    assert not paths.session_dir.exists()
    assert backend.list_compact_sessions() == []


def test_failed_compact_replacement_keeps_retained_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retention cleanup cannot run before a new compact commit is durable."""
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:replacement-failure"
    policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=1,
        max_bytes_per_view=20_000,
    )
    backend.write_compact_session(
        view_id=view_id,
        session_id="retained",
        client_id="producer",
        metadata={"lifecycle": "ended", "detail": "known-good"},
        summary_windows=[],
        noteworthy_items=[],
        policy=policy,
    )
    retained = backend.session_paths(view_id=view_id, session_id="retained")
    original_metadata = retained.metadata.read_bytes()
    replacement = backend.session_paths(view_id=view_id, session_id="replacement")
    write_atomic = storage_backend._write_bytes_atomic

    def fail_metadata(path: Path, data: bytes) -> None:
        if path == replacement.metadata:
            raise OSError("test metadata failure")
        write_atomic(path, data)

    monkeypatch.setattr(storage_backend, "_write_bytes_atomic", fail_metadata)
    with pytest.raises(OSError, match="metadata failure"):
        backend.write_compact_session(
            view_id=view_id,
            session_id="replacement",
            client_id="producer",
            metadata={"lifecycle": "ended"},
            summary_windows=[],
            noteworthy_items=[],
            policy=policy,
        )

    assert retained.metadata.read_bytes() == original_metadata
    assert backend.load_compact_session(view_id=view_id, session_id="retained")
    assert not replacement.metadata.exists()
    assert not replacement.session_dir.exists()


def test_restart_discards_uncommitted_compact_candidates_before_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash-staged newer session must not evict the prior valid session."""
    root = _configure_stream_storage(
        tmp_path,
        streams_yaml="""  streams:
    keep_last_sessions: 1
    max_bytes_per_view_mb: 1""",
    )
    _write_completed_compact_session(root)
    backend = FileStreamStorageBackend(root_dir=root)
    staged = backend.session_paths(
        view_id="logs:restored", session_id="interrupted-new-session"
    )
    # Model process interruption after both initial-generation candidates are
    # atomically staged but before their session.json commit record exists.
    storage_backend._write_bytes_atomic(staged.summaries, b"staged summary\n")
    storage_backend._write_bytes_atomic(staged.noteworthy, b"staged noteworthy\n")

    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 1
    assert not staged.session_dir.exists()
    assert restored_registry.status(view_id="logs:restored")["lifecycle"] == "ended"


def test_backend_instances_serialize_marker_retention_transactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    first = FileStreamStorageBackend(root_dir=root)
    second = FileStreamStorageBackend(root_dir=root)
    view_id = "logs:marker-transaction"
    policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=1,
        max_bytes_per_view=20_000,
    )
    first_cleanup_started = threading.Event()
    second_cleanup_started = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    errors: list[BaseException] = []
    original_first_cleanup = first._apply_cleanup
    original_second_cleanup = second._apply_cleanup

    def pause_first_cleanup(**kwargs: object) -> None:
        first_cleanup_started.set()
        assert release_first.wait(timeout=2.0)
        original_first_cleanup(**kwargs)  # type: ignore[arg-type]

    def record_second_cleanup(**kwargs: object) -> None:
        second_cleanup_started.set()
        original_second_cleanup(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(first, "_apply_cleanup", pause_first_cleanup)
    monkeypatch.setattr(second, "_apply_cleanup", record_second_cleanup)

    def mark(backend: FileStreamStorageBackend, session_id: str) -> None:
        try:
            backend.mark_session_incomplete(
                view_id=view_id,
                session_id=session_id,
                reason="stream persistence queue task budget reached",
                policy=policy,
            )
        except BaseException as error:  # pragma: no cover - thread assertion aid
            errors.append(error)

    first_thread = threading.Thread(target=lambda: mark(first, "session-1"))
    first_thread.start()
    assert first_cleanup_started.wait(timeout=2.0)

    def mark_second() -> None:
        mark(second, "session-2")
        second_finished.set()

    second_thread = threading.Thread(target=mark_second)
    second_thread.start()
    # The second instance must not plan or mutate the shared view while the
    # first instance holds its plan/cleanup/write transaction open.
    assert not second_cleanup_started.wait(timeout=0.1)
    assert not second_finished.is_set()

    release_first.set()
    first_thread.join(timeout=2.0)
    second_thread.join(timeout=2.0)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors

    paths = second.session_paths(view_id=view_id, session_id="session-2")
    assert paths.incomplete_marker.exists()
    assert len([path for path in paths.view_dir.iterdir() if path.is_dir()]) == 1
    assert second._view_byte_count(paths.view_dir) <= policy.max_bytes_per_view


def test_durable_gap_markers_obey_session_and_byte_retention(tmp_path: Path) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    retained_view = "logs:marker-session-retention"
    retention_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=2,
        max_bytes_per_view=100_000,
    )
    for index in range(5):
        backend.mark_session_incomplete(
            view_id=retained_view,
            session_id=f"marker-{index}",
            reason="stream persistence queue task budget reached",
            policy=retention_policy,
        )

    retained_paths = backend.session_paths(
        view_id=retained_view, session_id="marker-4"
    )
    marker_sessions = [
        path for path in retained_paths.view_dir.iterdir() if path.is_dir()
    ]
    assert len(marker_sessions) == 2
    assert backend.session_paths(
        view_id=retained_view, session_id="marker-3"
    ).incomplete_marker.exists()
    assert retained_paths.incomplete_marker.exists()

    byte_view = "logs:marker-byte-retention"
    byte_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=8,
        max_bytes_per_view=2_000,
    )
    for index in range(5):
        backend.mark_session_incomplete(
            view_id=byte_view,
            session_id=f"marker-{index}",
            reason="x" * 1_000,
            policy=byte_policy,
        )

    byte_paths = backend.session_paths(view_id=byte_view, session_id="marker-4")
    assert backend._view_byte_count(byte_paths.view_dir) <= byte_policy.max_bytes_per_view
    assert byte_paths.incomplete_marker.exists()


def test_lowered_view_byte_limit_prunes_existing_history(tmp_path: Path) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:lowered-limit"
    high_policy = StreamStoragePolicy(
        summary_retention=2,
        noteworthy_keep_last=2,
        keep_last_sessions=2,
        max_bytes_per_view=100_000,
    )
    for session_id in ("session-1", "session-2"):
        backend.write_compact_session(
            view_id=view_id,
            session_id=session_id,
            client_id="producer",
            metadata={"lifecycle": "ended", "detail": "x" * 1_000},
            summary_windows=[],
            noteworthy_items=[],
            policy=high_policy,
        )

    latest_paths = backend.session_paths(view_id=view_id, session_id="session-2")
    lowered_limit = backend._view_byte_count(latest_paths.session_dir)
    assert backend._view_byte_count(latest_paths.view_dir) > lowered_limit

    backend.enforce_view_retention(
        view_id=view_id,
        policy=StreamStoragePolicy(
            summary_retention=2,
            noteworthy_keep_last=2,
            keep_last_sessions=2,
            max_bytes_per_view=lowered_limit,
        ),
    )

    assert backend._view_byte_count(latest_paths.view_dir) <= lowered_limit
    assert not backend.session_paths(view_id=view_id, session_id="session-1").session_dir.exists()
    assert latest_paths.session_dir.exists()


def test_disabling_raw_retention_removes_existing_raw_blocks(tmp_path: Path) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:disable-raw"
    session_id = "session-1"
    policy = StreamStoragePolicy(
        summary_retention=2,
        noteworthy_keep_last=2,
        keep_last_sessions=2,
        max_bytes_per_view=100_000,
    )
    backend.write_compact_session(
        view_id=view_id,
        session_id=session_id,
        client_id="producer",
        metadata={"lifecycle": "ended"},
        summary_windows=[],
        noteworthy_items=[],
        policy=policy,
    )
    backend.write_raw_block(
        view_id=view_id,
        session_id=session_id,
        block_id="batch-1",
        records=[
            {
                "browser_sequence": 1,
                "observed_at": "2026-01-01T00:00:00+00:00",
                "data": {"value": 1},
            }
        ],
        raw_policy=RawBlockPolicy(max_blocks=2, max_bytes=10_000),
        storage_policy=policy,
    )
    paths = backend.session_paths(view_id=view_id, session_id=session_id)
    assert list(paths.raw_dir.glob("*.jsonl"))

    backend.enforce_view_retention(view_id=view_id, policy=policy, raw_policy=None)

    assert not list(paths.raw_dir.glob("*.jsonl"))


def test_compact_session_loader_reads_only_versioned_compact_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    _write_completed_compact_session(root)

    loaded = FileStreamStorageBackend(root_dir=root).load_compact_session(
        view_id="logs:restored", session_id="restore-session"
    )

    assert loaded.view_id == "logs:restored"
    assert loaded.session_id == "restore-session"
    assert len(loaded.summary_windows) == 1
    assert loaded.summary_windows[0]["record_count"] == "1"
    assert len(loaded.noteworthy_items) == 3
    assert FileStreamStorageBackend(root_dir=root).list_compact_sessions() == [loaded]


def test_restore_streams_from_storage_rebuilds_historical_compact_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path)
    _write_completed_compact_session(root)
    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 1

    data = restored_registry.data(view_id="logs:restored")
    summary = restored_registry.summary(view_id="logs:restored")
    status = restored_registry.status(view_id="logs:restored")
    assert data["lifecycle"] == "ended"
    assert data["records"] == []
    assert data["columns"] == ["level", "value"]
    assert data["cumulative"]["total_records"] == "2"
    assert data["noteworthy"]["retained_item_count"] == 3
    assert summary["summary_window_count"] == 1
    assert summary["windows"][0]["record_count"] == "1"
    assert status["durable_history"]["state"] == "complete"

    # The preserved session is historical: its original producer cannot append
    # after restart, but a later distinct session can supersede it.
    with pytest.raises(StreamStateError, match="already closed"):
        restored_registry.append(
            StreamAppend(
                view_id="logs:restored",
                client_id="restore-client",
                session_id="restore-session",
                batch_id="after-restart",
                batch_sequence=2,
                records=({"value": 30},),
            )
        )
    next_session = restored_registry.register(
        StreamRegistration(
            view_id="logs:restored",
            label="restored",
            section="logs",
            client_id="restore-client",
            session_id="next-session",
        )
    )
    assert next_session.lifecycle == "live"


def test_restore_exposes_each_session_through_history_without_reviving_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path)
    policy = StreamStoragePolicy(
        summary_retention=8,
        noteworthy_keep_last=8,
        keep_last_sessions=3,
        max_bytes_per_view=100_000,
    )

    def write_session(session_id: str, value: int, *, incomplete: bool = False) -> None:
        source = StreamRegistry(max_recent_records=1, max_recent_bytes=10_000)
        registration = StreamRegistration(
            view_id="logs:multi-session",
            label="multi session",
            section="logs",
            client_id="restore-client",
            session_id=session_id,
        )
        source.register(registration)
        source.append(
            StreamAppend(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                batch_id="batch-0",
                batch_sequence=0,
                records=({"level": "warning", "value": value},),
            )
        )
        source.close(
            StreamClose(
                view_id=registration.view_id,
                client_id=registration.client_id,
                session_id=registration.session_id,
                drain_completed=True,
            )
        )
        snapshot = source.persistence_snapshot(
            view_id=registration.view_id, session_id=registration.session_id
        )
        snapshot["metadata"]["durable_history"] = {
            "state": "complete",
            "persistence_enabled": True,
            "pending_writes": 0,
            "completed_writes": 1,
            "rejected_writes": 0,
            "failed_writes": 0,
            "last_error": None,
            "last_persisted_at": None,
            "raw_persistence": "disabled",
        }
        backend = FileStreamStorageBackend(root_dir=root)
        backend.write_compact_session(
            view_id=snapshot["view_id"],
            session_id=snapshot["session_id"],
            client_id=snapshot["client_id"],
            metadata=snapshot["metadata"],
            summary_windows=snapshot["summary_windows"],
            noteworthy_items=snapshot["noteworthy_items"],
            policy=policy,
        )
        if incomplete:
            backend.mark_session_incomplete(
                view_id=registration.view_id,
                session_id=registration.session_id,
                reason="simulated durable gap",
                policy=policy,
            )

    write_session("session-one", 1, incomplete=True)
    write_session("session-two", 2)
    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)
    monkeypatch.setattr(http_streams, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 2
    client = TestClient(app)
    catalogue = client.get("/stream/history", params={"view": "logs:multi-session"})
    assert catalogue.status_code == 200, catalogue.text
    sessions = catalogue.json()["sessions"]
    assert {session["session_id"] for session in sessions} == {
        "session-one",
        "session-two",
    }
    assert all(session["historical"] is True for session in sessions)

    first = client.get(
        "/stream/history",
        params={"view": "logs:multi-session", "session_id": "session-one"},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["historical"] is True
    assert first_payload["data"]["historical"] is True
    assert first_payload["data"]["lifecycle"] == "ended"
    assert first_payload["data"]["durable_history"]["state"] == "incomplete"
    assert first_payload["summary"]["historical"] is True

    # A real producer becomes the current view, while the persisted sessions
    # remain addressable through the historical route and never become live.
    restored_registry.register(
        StreamRegistration(
            view_id="logs:multi-session",
            label="multi session",
            section="logs",
            client_id="new-client",
            session_id="live-session",
        )
    )
    assert restored_registry.data(view_id="logs:multi-session")["lifecycle"] == "live"
    historical_again = client.get(
        "/stream/history",
        params={"view": "logs:multi-session", "session_id": "session-two"},
    ).json()
    assert historical_again["data"]["lifecycle"] == "ended"
    assert historical_again["data"]["historical"] is True


def test_restore_streams_applies_current_retention_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path)
    _write_completed_compact_session(root)
    restored_registry = StreamRegistry()
    calls: list[str] = []
    original = FileStreamStorageBackend.enforce_view_retention

    def record_retention(
        self: FileStreamStorageBackend, *, view_id: str, policy: StreamStoragePolicy, **kwargs: object
    ) -> int:
        calls.append(view_id)
        return original(self, view_id=view_id, policy=policy, **kwargs)

    monkeypatch.setattr(
        FileStreamStorageBackend, "enforce_view_retention", record_retention
    )
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 1
    assert calls == ["logs:restored"]


def test_restore_history_exposes_explicitly_retained_raw_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(
        tmp_path,
        streams_yaml="""  streams:
    raw_retention:
      max_blocks: 2
      max_bytes_mb: 1""",
    )
    _write_completed_compact_session(root)
    backend = FileStreamStorageBackend(root_dir=root)
    backend.write_raw_block(
        view_id="logs:restored",
        session_id="restore-session",
        block_id="batch-00000000000000000001",
        records=[
            {
                "browser_sequence": 2,
                "observed_at": "2026-01-01T00:00:01+00:00",
                "data": {"level": "warning", "value": 20},
            }
        ],
        raw_policy=RawBlockPolicy(max_blocks=2, max_bytes=10_000),
        storage_policy=StreamStoragePolicy(
            summary_retention=8,
            noteworthy_keep_last=8,
            keep_last_sessions=2,
            max_bytes_per_view=100_000,
        ),
    )
    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 1
    historical = restored_registry.historical_data(
        view_id="logs:restored", session_id="restore-session"
    )

    assert historical["historical"] is True
    assert historical["records"] == [
        {
            "browser_sequence": 2,
            "observed_at": "2026-01-01T00:00:01+00:00",
            "data": {"level": "warning", "value": 20},
        }
    ]


def test_restore_marks_damaged_retained_raw_history_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(
        tmp_path,
        streams_yaml="""  streams:
    raw_retention:
      max_blocks: 2
      max_bytes_mb: 1""",
    )
    _write_completed_compact_session(root)
    backend = FileStreamStorageBackend(root_dir=root)
    raw = backend.write_raw_block(
        view_id="logs:restored",
        session_id="restore-session",
        block_id="batch-00000000000000000001",
        records=[
            {
                "browser_sequence": 2,
                "observed_at": "2026-01-01T00:00:01+00:00",
                "data": {"level": "warning", "value": 20},
            }
        ],
        raw_policy=RawBlockPolicy(max_blocks=2, max_bytes=10_000),
        storage_policy=StreamStoragePolicy(
            summary_retention=8,
            noteworthy_keep_last=8,
            keep_last_sessions=2,
            max_bytes_per_view=100_000,
        ),
    )
    raw.path.write_text("{not valid json\n", encoding="utf-8")

    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 1
    historical = restored_registry.historical_data(
        view_id="logs:restored", session_id="restore-session"
    )

    assert historical["historical"] is True
    assert historical["records"] == []
    assert historical["durable_history"]["state"] == "incomplete"
    assert "raw history could not be validated" in historical["durable_history"][
        "last_error"
    ]


def test_restore_streams_respects_global_storage_master_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path, enabled=False)
    _write_completed_compact_session(root)
    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)

    assert server_mod.restore_streams_from_storage() == 0
    with pytest.raises(StreamStateError, match="has not been registered"):
        restored_registry.status(view_id="logs:restored")


def test_restore_streams_honours_view_opt_in_when_default_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(
        tmp_path,
        streams_yaml="""  streams:
    enabled: false
  views:
    logs:restored:
      stream:
        enabled: true""",
    )
    _write_completed_compact_session(root)
    restored_registry = StreamRegistry()
    monkeypatch.setattr(server_mod, "stream_registry", restored_registry)

    assert config.get_storage_stream_enabled() is False
    assert config.get_storage_stream_enabled("logs:restored") is True
    assert server_mod.restore_streams_from_storage() == 1
    assert restored_registry.status(view_id="logs:restored")["lifecycle"] == "ended"


def test_stream_routes_persist_compact_state_but_not_raw_by_default(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=8, max_pending_bytes=128_000)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)
    try:
        _register(client)
        _append(client, batch_sequence=0, records=[{"level": "warning", "n": 1}])
        close = client.post(
            "/stream/close",
            json={
                "protocol_version": STREAM_PROTOCOL_VERSION,
                "view_id": "logs:persisted",
                "client_id": "storage-client",
                "session_id": "storage-session",
                "drain_completed": True,
            },
        )
        assert close.status_code == 200

        backend = FileStreamStorageBackend(root_dir=root)
        paths = backend.session_paths(
            view_id="logs:persisted", session_id="storage-session"
        )
        _wait_until(lambda: worker.stats()["processed"] >= 3)

        metadata = backend.read_session_metadata(
            view_id="logs:persisted", session_id="storage-session"
        )
        compact = metadata["metadata"]
        assert compact["lifecycle"] == "ended"
        assert compact["cumulative"]["total_records"] == "1"
        assert compact["durable_history"]["raw_persistence"] == "disabled"
        compact_state = metadata["compact_state"]
        assert (paths.session_dir / compact_state["summaries_filename"]).exists()
        assert (paths.session_dir / compact_state["noteworthy_filename"]).exists()
        assert not paths.raw_dir.exists()
        assert client.get("/stream/status", params={"view": "logs:persisted"}).json()[
            "durable_history"
        ]["state"] == "complete"
    finally:
        worker.stop(join=True)


def test_storage_disabled_stream_routes_create_no_stream_history(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path, enabled=False)
    worker = StreamStorageWorker(max_queue_size=8, max_pending_bytes=128_000)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)
    try:
        _register(client)
        _append(client, batch_sequence=0)

        assert not (root / "streams").exists()
        assert worker.stats()["submitted"] == 0
        status = client.get("/stream/status", params={"view": "logs:persisted"}).json()
        assert status["durable_history"]["state"] == "disabled"
    finally:
        worker.stop(join=True)


def test_stream_routes_only_write_raw_blocks_after_explicit_opt_in(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(
        tmp_path,
        streams_yaml="""  streams:
    raw_retention:
      max_blocks: 1
      max_bytes_mb: 1
    max_bytes_per_view_mb: 2""",
    )
    worker = StreamStorageWorker(max_queue_size=8, max_pending_bytes=128_000)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)
    try:
        _register(client)
        _append(client, batch_sequence=0)
        _append(client, batch_sequence=1)
        _wait_until(lambda: worker.stats()["processed"] >= 3)

        paths = FileStreamStorageBackend(root_dir=root).session_paths(
            view_id="logs:persisted", session_id="storage-session"
        )
        raw_blocks = sorted(paths.raw_dir.glob("*.jsonl"))
        assert [path.name for path in raw_blocks] == ["batch-00000000000000000001.jsonl"]
        raw_record = json.loads(raw_blocks[0].read_text(encoding="utf-8").strip())
        assert raw_record["storage_kind"] == "raw_record"
        assert raw_record["payload"]["data"]["count"] == 1
    finally:
        worker.stop(join=True)


def test_raw_block_retention_is_enforced_across_sessions(tmp_path: Path) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:cross-session-raw"
    storage_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=2,
        max_bytes_per_view=20_000,
    )
    raw_policy = RawBlockPolicy(max_blocks=1, max_bytes=10_000)
    for session_id in ("older", "newer"):
        backend.write_compact_session(
            view_id=view_id,
            session_id=session_id,
            client_id="producer",
            metadata={"lifecycle": "ended"},
            summary_windows=[],
            noteworthy_items=[],
            policy=storage_policy,
        )
        backend.write_raw_block(
            view_id=view_id,
            session_id=session_id,
            block_id="batch-00000000000000000000",
            records=[
                {
                    "browser_sequence": 1,
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "data": {"session": session_id},
                }
            ],
            raw_policy=raw_policy,
            storage_policy=storage_policy,
        )

    newest_paths = backend.session_paths(view_id=view_id, session_id="newer")
    older_paths = backend.session_paths(view_id=view_id, session_id="older")
    assert len(list(newest_paths.raw_dir.glob("*.jsonl"))) == 1
    assert not list(older_paths.raw_dir.glob("*.jsonl"))


def test_failed_raw_replacement_keeps_previous_retained_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:raw-write-failure"
    session_id = "session-1"
    storage_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=1,
        max_bytes_per_view=20_000,
    )
    raw_policy = RawBlockPolicy(max_blocks=1, max_bytes=10_000)
    backend.write_compact_session(
        view_id=view_id,
        session_id=session_id,
        client_id="producer",
        metadata={"lifecycle": "ended"},
        summary_windows=[],
        noteworthy_items=[],
        policy=storage_policy,
    )
    backend.write_raw_block(
        view_id=view_id,
        session_id=session_id,
        block_id="batch-old",
        records=[
            {
                "browser_sequence": 1,
                "observed_at": "2026-01-01T00:00:00+00:00",
                "data": {"value": "old"},
            }
        ],
        raw_policy=raw_policy,
        storage_policy=storage_policy,
    )
    paths = backend.session_paths(view_id=view_id, session_id=session_id)
    old_block = paths.raw_dir / "batch-old.jsonl"
    new_block = paths.raw_dir / "batch-new.jsonl"
    write_atomic = storage_backend._write_bytes_atomic

    def fail_new_raw(path: Path, data: bytes) -> None:
        if path == new_block:
            raise OSError("test raw write failure")
        write_atomic(path, data)

    monkeypatch.setattr(storage_backend, "_write_bytes_atomic", fail_new_raw)
    with pytest.raises(OSError, match="raw write failure"):
        backend.write_raw_block(
            view_id=view_id,
            session_id=session_id,
            block_id="batch-new",
            records=[
                {
                    "browser_sequence": 2,
                    "observed_at": "2026-01-01T00:00:01+00:00",
                    "data": {"value": "new"},
                }
            ],
            raw_policy=raw_policy,
            storage_policy=storage_policy,
        )

    assert old_block.exists()
    assert not new_block.exists()


def test_interrupted_raw_replacement_is_reconciled_on_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-commit interruption leaves both blocks for safe later pruning."""
    backend = FileStreamStorageBackend(root_dir=tmp_path / "store")
    view_id = "logs:raw-interruption"
    session_id = "session-1"
    storage_policy = StreamStoragePolicy(
        summary_retention=1,
        noteworthy_keep_last=1,
        keep_last_sessions=1,
        max_bytes_per_view=20_000,
    )
    raw_policy = RawBlockPolicy(max_blocks=1, max_bytes=10_000)
    backend.write_compact_session(
        view_id=view_id,
        session_id=session_id,
        client_id="producer",
        metadata={"lifecycle": "ended"},
        summary_windows=[],
        noteworthy_items=[],
        policy=storage_policy,
    )
    backend.write_raw_block(
        view_id=view_id,
        session_id=session_id,
        block_id="batch-old",
        records=[
            {
                "browser_sequence": 1,
                "observed_at": "2026-01-01T00:00:00+00:00",
                "data": {"value": "old"},
            }
        ],
        raw_policy=raw_policy,
        storage_policy=storage_policy,
    )
    paths = backend.session_paths(view_id=view_id, session_id=session_id)
    old_block = paths.raw_dir / "batch-old.jsonl"
    new_block = paths.raw_dir / "batch-new.jsonl"
    write_atomic = storage_backend._write_bytes_atomic

    def commit_then_interrupt(path: Path, data: bytes) -> None:
        write_atomic(path, data)
        if path == new_block:
            raise KeyboardInterrupt("test interruption after raw commit")

    monkeypatch.setattr(storage_backend, "_write_bytes_atomic", commit_then_interrupt)
    with pytest.raises(KeyboardInterrupt, match="after raw commit"):
        backend.write_raw_block(
            view_id=view_id,
            session_id=session_id,
            block_id="batch-new",
            records=[
                {
                    "browser_sequence": 2,
                    "observed_at": "2026-01-01T00:00:01+00:00",
                    "data": {"value": "new"},
                }
            ],
            raw_policy=raw_policy,
            storage_policy=storage_policy,
        )

    assert old_block.exists()
    assert new_block.exists()
    backend.enforce_view_retention(
        view_id=view_id,
        policy=storage_policy,
        raw_policy=raw_policy,
    )
    assert not old_block.exists()
    assert new_block.exists()


def test_stream_persistence_failure_is_visible_without_rejecting_live_append(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=8, max_pending_bytes=128_000)

    def fail_write(_task: object) -> None:
        raise OSError("test disk is unavailable")

    monkeypatch.setattr(worker, "_process_task", fail_write)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)
    try:
        _register(client)
        _append(client, batch_sequence=0)
        _wait_until(lambda: worker.stats()["failed"] >= 1)

        data = client.get("/stream/data", params={"view": "logs:persisted"}).json()
        assert data["records"] == [
            {
                "browser_sequence": 1,
                "data": {"level": "warning", "count": 0},
                "observed_at": data["records"][0]["observed_at"],
            }
        ]
        durable = data["durable_history"]
        assert durable["state"] == "incomplete"
        assert durable["failed_writes"] >= 1
        assert "OSError: test disk is unavailable" in durable["last_error"]
    finally:
        worker.stop(join=True)


def test_full_stream_admission_does_not_consume_ordinary_storage_admission(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_stream_storage(tmp_path)
    stream_worker = StreamStorageWorker(max_queue_size=1, max_pending_bytes=128_000)
    # Keep the one stream task queued so the following accepted append is
    # rejected by stream-only admission rather than being processed first.
    monkeypatch.setattr(stream_worker, "start", lambda: None)
    monkeypatch.setattr(
        http_streams, "get_stream_storage_worker", lambda: stream_worker
    )
    ordinary_worker = StorageWorker(max_queue_size=1, max_pending_bytes=128_000)
    monkeypatch.setattr(ordinary_worker, "start", lambda: None)

    _register(client)
    _append(client, batch_sequence=0)

    status = client.get("/stream/status", params={"view": "logs:persisted"}).json()
    assert status["durable_history"]["state"] == "incomplete"
    assert status["durable_history"]["rejected_writes"] == 1
    assert stream_worker.stats()["queued"] == 1

    # This is the established latest/snapshot worker, with a distinct queue.
    # It remains admissible while stream persistence is saturated.
    assert ordinary_worker.submit(view_id="ordinary:view", kind="text", obj="ok")
    assert ordinary_worker.stats()["queued"] == 1


def test_rejected_persistence_admission_does_not_wait_for_storage_lock(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live append returns promptly while its gap marker waits asynchronously."""
    root = _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=1, max_pending_bytes=128_000)
    entered = threading.Event()
    release = threading.Event()

    def hold_backend_lock(_task: object) -> None:
        backend = FileStreamStorageBackend(root_dir=root)
        with backend._lock:
            entered.set()
            assert release.wait(timeout=2.0)

    monkeypatch.setattr(worker, "_process_task", hold_backend_lock)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)
    try:
        _register(client)
        assert entered.wait(timeout=2.0)
        _append(client, batch_sequence=0)

        started = time.monotonic()
        _append(client, batch_sequence=1)
        assert time.monotonic() - started < 0.15

        status = client.get("/stream/status", params={"view": "logs:persisted"}).json()
        assert status["durable_history"]["state"] == "incomplete"
        assert status["durable_history"]["rejected_writes"] == 1
    finally:
        release.set()
        worker.stop(join=True, timeout=2.0)


def test_rejected_persistence_markers_coalesce_behind_storage_lock(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejection burst has one bounded marker attempt, not one thread each."""
    root = _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=1, max_pending_bytes=128_000)
    scheduler = StreamPersistenceGapMarkerScheduler(max_pending=2)
    entered = threading.Event()
    release = threading.Event()

    def hold_backend_lock(_task: object) -> None:
        backend = FileStreamStorageBackend(root_dir=root)
        with backend._lock:
            entered.set()
            assert release.wait(timeout=2.0)

    monkeypatch.setattr(worker, "_process_task", hold_backend_lock)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)
    monkeypatch.setattr(stream_worker_mod, "_GAP_MARKER_SCHEDULER", scheduler)
    try:
        _register(client)
        assert entered.wait(timeout=2.0)
        _append(client, batch_sequence=0)
        for sequence in range(1, 65):
            _append(client, batch_sequence=sequence)

        _wait_until(lambda: scheduler.stats()["inflight"] == 1)
        marker_stats = scheduler.stats()
        assert marker_stats["scheduled"] == 64
        assert marker_stats["coalesced"] >= 63
        assert marker_stats["pending"] + marker_stats["inflight"] == 1
        assert marker_stats["worker_starts"] == 1
    finally:
        release.set()
        worker.stop(join=True, timeout=2.0)
        _wait_until(lambda: not scheduler.stats()["running"])


def test_marker_scheduler_start_failure_does_not_break_live_request(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A marker-thread startup failure is contained after live rejection."""
    _configure_stream_storage(tmp_path)
    scheduler = StreamPersistenceGapMarkerScheduler(max_pending=1)
    original_start = threading.Thread.start

    class RejectedWorker:
        def submit(self, **_kwargs: object) -> StreamStorageSubmission:
            return StreamStorageSubmission(
                accepted=False,
                enabled=True,
                reason="test stream persistence admission rejection",
            )

    def fail_marker_start(thread: threading.Thread) -> None:
        if thread.name == "plotsrv-stream-storage-gap-marker":
            raise RuntimeError("test marker thread cannot start")
        original_start(thread)

    monkeypatch.setattr(http_streams, "get_stream_storage_worker", RejectedWorker)
    monkeypatch.setattr(stream_worker_mod, "_GAP_MARKER_SCHEDULER", scheduler)
    monkeypatch.setattr(threading.Thread, "start", fail_marker_start)

    _register(client)

    status = client.get("/stream/status", params={"view": "logs:persisted"}).json()
    assert status["durable_history"]["state"] == "incomplete"
    assert status["durable_history"]["rejected_writes"] == 1
    marker_stats = scheduler.stats()
    assert marker_stats["start_failures"] == 1
    assert marker_stats["pending"] == 0
    assert not marker_stats["running"]


def test_rejected_admission_survives_a_stale_worker_snapshot(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=1, max_pending_bytes=128_000)
    monkeypatch.setattr(worker, "start", lambda: None)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)

    _register(client)
    _append(client, batch_sequence=0)

    # The registration snapshot was admitted first. The append is rejected
    # while it waits, which must leave an on-disk gap even if that old snapshot
    # subsequently reaches storage and otherwise says "complete".
    task = worker._queue.get_nowait()
    assert task is not None
    worker._process_task(task)
    worker._queue.task_done()

    loaded = FileStreamStorageBackend(root_dir=root).load_compact_session(
        view_id="logs:persisted", session_id="storage-session"
    )
    assert loaded.metadata["metadata"]["durable_history"]["state"] == "incomplete"


def test_stream_worker_drains_accepted_tasks_before_stop_and_can_restart(
    tmp_path: Path,
) -> None:
    _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=4, max_pending_bytes=128_000)
    entered = threading.Event()
    release = threading.Event()
    processed: list[str] = []

    def process(task: object) -> None:
        session_id = getattr(task, "session_id")
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=2.0)
        processed.append(session_id)

    worker._process_task = process  # type: ignore[method-assign]

    def submit(session_id: str) -> None:
        outcome = worker.submit(
            view_id="logs:shutdown-drain",
            session_id=session_id,
            client_id="producer",
            metadata={"lifecycle": "ended"},
            summary_windows=[],
            noteworthy_items=[],
            raw_block_id=None,
            raw_records=[],
            on_complete=lambda _success, _error: None,
        )
        assert outcome.accepted

    submit("session-1")
    assert entered.wait(timeout=2.0)
    submit("session-2")
    worker.stop(join=False)
    release.set()
    worker.stop(join=True, timeout=2.0)
    assert processed == ["session-1", "session-2"]
    assert worker.stats()["queued"] == 0

    assert worker.open_admission()
    submit("session-3")
    _wait_until(lambda: processed == ["session-1", "session-2", "session-3"])
    worker.stop(join=True, timeout=2.0)


def test_stream_worker_start_failure_rolls_back_admission_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed Thread.start leaves no queued task or unjoinable lifecycle."""
    _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=1, max_pending_bytes=128_000)
    original_start = threading.Thread.start

    def fail_worker_start(thread: threading.Thread) -> None:
        if thread.name == "plotsrv-stream-storage-worker":
            raise RuntimeError("test storage worker cannot start")
        original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_worker_start)
    outcome = worker.submit(
        view_id="logs:start-failure",
        session_id="session-1",
        client_id="producer",
        metadata={"lifecycle": "ended"},
        summary_windows=[],
        noteworthy_items=[],
        raw_block_id=None,
        raw_records=[],
        on_complete=lambda _success, _error: None,
    )

    assert not outcome.accepted
    assert outcome.enabled
    assert outcome.reason is not None and "failed to start" in outcome.reason
    assert worker.stats() == {
        "queued": 0,
        "pending_bytes": 0,
        "max_pending_tasks": 1,
        "max_pending_bytes": 128_000,
        "submitted": 0,
        "processed": 0,
        "rejected": 1,
        "failed": 0,
        "last_error": outcome.reason,
        "running": False,
    }
    assert not worker._outstanding_tasks
    worker.stop(join=True)


def test_stream_worker_shutdown_timeout_does_not_wait_for_backend_lock(
    tmp_path: Path,
) -> None:
    """The public drain timeout remains a deadline under a stalled write."""
    root = _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=1, max_pending_bytes=128_000)
    entered = threading.Event()
    release = threading.Event()
    callback_results: list[tuple[bool, str | None]] = []

    def hold_backend_lock(_task: object) -> None:
        backend = FileStreamStorageBackend(root_dir=root)
        with backend._lock:
            entered.set()
            assert release.wait(timeout=2.0)

    worker._process_task = hold_backend_lock  # type: ignore[method-assign]
    outcome = worker.submit(
        view_id="logs:shutdown-timeout",
        session_id="session-1",
        client_id="producer",
        metadata={"lifecycle": "ended"},
        summary_windows=[],
        noteworthy_items=[],
        raw_block_id=None,
        raw_records=[],
        on_complete=lambda success, error: callback_results.append((success, error)),
    )
    assert outcome.accepted
    assert entered.wait(timeout=2.0)

    started = time.monotonic()
    worker.stop(join=True, timeout=0.01)
    assert time.monotonic() - started < 0.15
    assert (False, "stream persistence shutdown drain timed out") in callback_results

    release.set()
    _wait_until(lambda: not worker.stats()["running"])


def test_stream_worker_shutdown_is_atomic_with_admission_start_and_restart(
    tmp_path: Path,
) -> None:
    """An accepted task cannot be left to start after shutdown returns."""
    root = _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=2, max_pending_bytes=128_000)
    queued_before_start = threading.Event()
    allow_start = threading.Event()
    shutdown_returned = threading.Event()
    start_calls: list[str] = []
    outcome: list[object] = []
    original_start = worker.start

    def delayed_start() -> None:
        start_calls.append("start")
        queued_before_start.set()
        assert allow_start.wait(timeout=2.0)
        original_start()

    worker.start = delayed_start  # type: ignore[method-assign]

    def submit(session_id: str) -> None:
        outcome.append(
            worker.submit(
                view_id="logs:atomic-shutdown",
                session_id=session_id,
                client_id="producer",
                metadata={"lifecycle": "ended", "cumulative": {"total_records": "1"}},
                summary_windows=[],
                noteworthy_items=[],
                raw_block_id=None,
                raw_records=[],
                on_complete=lambda _success, _error: None,
            )
        )

    submitter = threading.Thread(target=lambda: submit("session-1"))
    submitter.start()
    assert queued_before_start.wait(timeout=2.0)

    def stop() -> None:
        worker.stop(join=True, timeout=2.0)
        shutdown_returned.set()

    stopper = threading.Thread(target=stop)
    stopper.start()
    # submit() still owns the lifecycle lock while it is between enqueue and
    # worker start, so stop() cannot report completion through this gap.
    assert not shutdown_returned.wait(timeout=0.1)

    allow_start.set()
    submitter.join(timeout=2.0)
    stopper.join(timeout=2.0)
    assert not submitter.is_alive()
    assert not stopper.is_alive()
    assert shutdown_returned.is_set()
    assert len(outcome) == 1 and getattr(outcome[0], "accepted")

    # The accepted first task reached durable storage before shutdown returned,
    # and no delayed worker start remains after the completed drain.
    metadata = FileStreamStorageBackend(root_dir=root).read_session_metadata(
        view_id="logs:atomic-shutdown", session_id="session-1"
    )
    assert metadata["metadata"]["lifecycle"] == "ended"
    assert start_calls == ["start"]
    assert not worker.stats()["running"]

    # A fresh explicit lifecycle can admit new work after the prior sentinel
    # was consumed; it does not inherit stale queued tasks or control state.
    assert worker.open_admission()
    submit("session-2")
    backend = FileStreamStorageBackend(root_dir=root)
    _wait_until(
        lambda: backend.session_paths(
            view_id="logs:atomic-shutdown", session_id="session-2"
        ).metadata.exists()
    )
    assert backend.read_session_metadata(
        view_id="logs:atomic-shutdown", session_id="session-2"
    )["metadata"]["lifecycle"] == "ended"
    worker.stop(join=True, timeout=2.0)


def test_worker_shutdown_drains_queued_close_state_to_storage(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _configure_stream_storage(tmp_path)
    worker = StreamStorageWorker(max_queue_size=4, max_pending_bytes=128_000)
    real_start = worker.start
    monkeypatch.setattr(worker, "start", lambda: None)
    monkeypatch.setattr(http_streams, "get_stream_storage_worker", lambda: worker)

    _register(client)
    _append(client, batch_sequence=0)
    close = client.post(
        "/stream/close",
        json={
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "view_id": "logs:persisted",
            "client_id": "storage-client",
            "session_id": "storage-session",
            "drain_completed": True,
        },
    )
    assert close.status_code == 200
    assert worker.stats()["queued"] == 3

    worker.start = real_start  # type: ignore[method-assign]
    worker.start()
    worker.stop(join=True, timeout=2.0)

    metadata = FileStreamStorageBackend(root_dir=root).read_session_metadata(
        view_id="logs:persisted", session_id="storage-session"
    )
    assert metadata["metadata"]["lifecycle"] == "ended"
    assert metadata["metadata"]["cumulative"]["total_records"] == "1"
