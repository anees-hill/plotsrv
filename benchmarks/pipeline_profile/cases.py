"""Small, explicit operational benchmark catalogue.

The benchmark runner intentionally remains usable without this file: ``run``
is still the low-level, fully configurable interface.  Cases merely make the
release checks memorable and comparable over time.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .models import PlotsrvConfigSpec, RunSpec, TableSpec, WorkloadSpec


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    description: str
    profiles: tuple[str, ...] = ("quick", "standard", "soak")


CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        "watch.csv.file.large.repeated-clients",
        "Repeated concurrent opens of one large file-backed CSV, with post-idle memory checkpoints.",
    ),
    BenchmarkCase(
        "watch.csv.file.overload",
        "More concurrent clients than the file materialisation admission limit; 503 is expected back-pressure.",
    ),
    BenchmarkCase(
        "publish.remote.sync.small",
        "Small remote synchronous publishing reference case.",
        ("quick", "standard"),
    ),
    BenchmarkCase(
        "publish.remote.async.latest-wins.high-frequency",
        "High-frequency remote async updates to the same view IDs, exercising coalescing.",
    ),
    BenchmarkCase(
        "publish.remote.distinct-views.queue-pressure",
        "Remote async updates with unique view IDs, exercising queue count/byte admission.",
    ),
)


def list_cases() -> tuple[BenchmarkCase, ...]:
    return CASES


def build_case(case_id: str, *, profile: str, output_dir: Path | None = None) -> RunSpec:
    if profile not in {"quick", "standard", "soak"}:
        raise ValueError("profile must be quick, standard, or soak")
    known = {case.case_id: case for case in CASES}
    case = known.get(case_id)
    if case is None:
        raise ValueError(f"unknown benchmark case: {case_id}")
    if profile not in case.profiles:
        raise ValueError(f"{case_id} does not provide the {profile!r} profile")

    scale = {"quick": 1, "standard": 2, "soak": 4}[profile]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir or Path("benchmark-results") / f"{stamp}-{case_id.replace('.', '-')}-{profile}"
    file_config = PlotsrvConfigSpec(
        truncate_table_rows=5_000 * scale,
        watch_active_max_concurrent=2,
        watch_active_wait_timeout_s=0.0,
    )

    if case_id == "watch.csv.file.large.repeated-clients":
        return RunSpec(
            scenario="watch-clients",
            workload=WorkloadSpec(plots=0, json_items=(), text_kb=0, log_kb=0, cpu_s=0),
            output_dir=output,
            case_id=case_id,
            watch_csv=TableSpec(150_000 * scale, 20),
            watch_max_mb=64.0,
            clients=1 + 2 * scale,
            requests_per_client=2,
            cycles=2 + scale,
            cycle_idle_s=2.0,
            idle_s=5.0,
            table_limit=5_000 * scale,
            accept_statuses=(200, 503),
            max_rss_mb=750 if profile == "quick" else 1_500,
            config=file_config,
        )
    if case_id == "watch.csv.file.overload":
        return RunSpec(
            scenario="watch-clients",
            workload=WorkloadSpec(plots=0, json_items=(), text_kb=0, log_kb=0, cpu_s=0),
            output_dir=output,
            case_id=case_id,
            watch_csv=TableSpec(100_000 * scale, 16),
            watch_max_mb=64.0,
            clients=4 * scale,
            requests_per_client=2,
            cycles=1 + scale,
            cycle_idle_s=1.0,
            idle_s=3.0,
            table_limit=2_500 * scale,
            accept_statuses=(200, 503),
            config=PlotsrvConfigSpec(
                truncate_table_rows=2_500 * scale,
                watch_active_max_concurrent=1,
                watch_active_wait_timeout_s=0.0,
            ),
        )

    high_frequency = case_id != "publish.remote.sync.small"
    distinct = case_id == "publish.remote.distinct-views.queue-pressure"
    return RunSpec(
        scenario="remote",
        workload=WorkloadSpec(
            tables=(TableSpec(5_000 * scale, 12),),
            json_items=(),
            plots=0,
            text_kb=0,
            log_kb=0,
            cpu_s=0.02,
            iterations=(1 if not high_frequency else 12 * scale),
            distinct_view_ids=distinct,
        ),
        output_dir=output,
        case_id=case_id,
        publish_behaviour="async" if high_frequency else "sync",
        publish_max_pending_views=(4 if distinct else 32),
        publish_max_pending_mb=(4.0 if distinct else 64.0),
        idle_s=3.0,
    )


def apply_case_overrides(spec: RunSpec, values: list[str]) -> RunSpec:
    """Permit a small set of useful recipe overrides without a second runner."""
    fields: dict[str, tuple[str, type[int] | type[float]]] = {
        "cycles": ("cycles", int),
        "clients": ("clients", int),
        "requests_per_client": ("requests_per_client", int),
        "table_limit": ("table_limit", int),
        "idle_s": ("idle_s", float),
        "cycle_idle_s": ("cycle_idle_s", float),
        "max_rss_mb": ("max_rss_mb", int),
    }
    updates: dict[str, int | float] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or key not in fields:
            available = ", ".join(fields)
            raise ValueError(f"case settings must use one of: {available}")
        field, converter = fields[key]
        updates[field] = converter(raw)
    return replace(spec, **updates)
