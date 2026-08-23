"""Optional quick check of the caller-side async queue-admission cost.

Run with ``uv run --group benchmark python -m
benchmarks.pipeline_profile.async_admission_microbench``.  It is intentionally
small and measures admission only, not worker serialisation or HTTP delivery.
"""
from __future__ import annotations

import statistics
import time

import pandas as pd

from plotsrv.publisher import _estimate_publish_task_bytes


def main() -> int:
    df = pd.DataFrame(
        {
            "id": range(100_000),
            "name": [f"row-{index}" for index in range(100_000)],
            "group": ["benchmark"] * 100_000,
        }
    )
    samples: list[float] = []
    for _ in range(20):
        started = time.perf_counter_ns()
        _estimate_publish_task_bytes(df)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    print(f"async queue admission median: {statistics.median(samples):.3f} ms")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
