"""On-demand metadata cost, independent of stored body size; no idle worker."""

import gc
import json
import time
import tracemalloc

import pytest

from plotsrv.storage.navigation import navigation_page, _view_dir


@pytest.mark.benchmark
@pytest.mark.parametrize("count", [50, 1000])
def test_metadata_navigation_memory_and_cpu(tmp_path, count):
    directory = _view_dir(tmp_path, "bench")
    directory.mkdir()
    for index in range(count):
        sid = f"{index:06}"
        (directory / (sid + "__meta.json")).write_text(
            json.dumps(
                dict(
                    snapshot_id=sid,
                    view_id="bench",
                    created_at="2026-09-09T12:00:00Z",
                    kind="text",
                    extra={"unused": "x" * 512},
                )
            )
        )
    # Sparse payload: scanning it would be both incorrect and very expensive.
    with (directory / "000000__payload.txt").open("wb") as payload:
        payload.truncate(4 * 1024**3)
    start_cpu = time.thread_time()
    navigation_page(root_dir=tmp_path, view_id="bench", limit=50)
    untraced_cpu = time.thread_time() - start_cpu
    gc.collect()
    tracemalloc.start()
    cpu = time.thread_time()
    wall = time.monotonic()
    page = navigation_page(
        root_dir=tmp_path, view_id="bench", limit=50, selected="000000"
    )
    elapsed = time.monotonic() - wall
    cpu = time.thread_time() - cpu
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    encoded = len(json.dumps(page).encode())
    print(
        json.dumps(
            dict(
                entries=count,
                untraced_cpu_ms=untraced_cpu * 1000,
                wall_ms=elapsed * 1000,
                cpu_ms=cpu * 1000,
                retained_bytes=current,
                peak_bytes=peak,
                response_bytes=encoded,
            )
        )
    )
    assert page["count"] == count and len(page["snapshots"]) == 50
    assert peak < 1024 * 1024
    assert encoded < 32 * 1024
