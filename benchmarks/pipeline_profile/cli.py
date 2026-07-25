from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import PlotsrvConfigSpec, RunSpec, TableSpec, WorkloadSpec
from .runner import compare_runs, run_benchmark
from .support import write_json


def _off_or_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text == "off":
        return None
    return int(text.replace("_", ""))


def _config_from_args(args: argparse.Namespace) -> PlotsrvConfigSpec:
    defaults = PlotsrvConfigSpec()
    truncate_table_rows = (
        args.table_limit
        if args.truncate_table_rows is None
        else _off_or_int(args.truncate_table_rows)
    )
    truncate_table_columns = (
        defaults.truncate_table_columns
        if args.table_columns_limit is None
        else _off_or_int(args.table_columns_limit)
    )
    return PlotsrvConfigSpec(
        publish_max_plot_bytes=(
            defaults.publish_max_plot_bytes
            if args.publish_max_plot_bytes is None
            else args.publish_max_plot_bytes
        ),
        publish_max_table_rows=(
            defaults.publish_max_table_rows
            if args.publish_max_table_rows is None
            else args.publish_max_table_rows
        ),
        publish_max_table_columns=(
            defaults.publish_max_table_columns
            if args.publish_max_table_columns is None
            else args.publish_max_table_columns
        ),
        publish_max_artifact_text_chars=(
            defaults.publish_max_artifact_text_chars
            if args.publish_max_artifact_text_chars is None
            else args.publish_max_artifact_text_chars
        ),
        publish_max_json_container_items=(
            defaults.publish_max_json_container_items
            if args.publish_max_json_container_items is None
            else args.publish_max_json_container_items
        ),
        truncate_table_rows=truncate_table_rows,
        truncate_table_columns=truncate_table_columns,
        watch_active_max_concurrent=(
            defaults.watch_active_max_concurrent
            if args.watch_active_max_concurrent is None
            else args.watch_active_max_concurrent
        ),
        watch_active_wait_timeout_s=(
            defaults.watch_active_wait_timeout_s
            if args.watch_active_wait_timeout_s is None
            else args.watch_active_wait_timeout_s
        ),
        storage_enabled=bool(args.storage_enabled),
        storage_watch_enabled=bool(args.storage_watch_enabled),
    )


def _default_output(scenario: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("benchmark-results") / f"{stamp}-{scenario}"


def _table_values(values: list[str] | None) -> tuple[TableSpec, ...]:
    if values is None:
        return WorkloadSpec().tables
    return tuple(TableSpec.parse(value) for value in values)


def _json_values(values: list[int] | None) -> tuple[int, ...]:
    if values is None:
        return WorkloadSpec().json_items
    return tuple(values)


def _workload_from_args(args: argparse.Namespace) -> WorkloadSpec:
    defaults = WorkloadSpec()
    return WorkloadSpec(
        tables=_table_values(args.table),
        json_items=_json_values(args.json_items),
        plots=defaults.plots if args.plots is None else args.plots,
        html_kb=defaults.html_kb if args.html_kb is None else args.html_kb,
        text_kb=defaults.text_kb if args.text_kb is None else args.text_kb,
        log_kb=defaults.log_kb if args.log_kb is None else args.log_kb,
        cpu_s=defaults.cpu_s if args.cpu_s is None else args.cpu_s,
        temporary_memory_mb=(
            defaults.temporary_memory_mb
            if args.temporary_memory_mb is None
            else args.temporary_memory_mb
        ),
        iterations=defaults.iterations if args.iterations is None else args.iterations,
        publish_every=(
            defaults.publish_every if args.publish_every is None else args.publish_every
        ),
    )


def run_command(args: argparse.Namespace) -> int:
    watch_csv = None
    if args.scenario.startswith("watch"):
        watch_csv = TableSpec.parse(args.watch_csv or "100000x12")
    spec = RunSpec(
        scenario=args.scenario,
        workload=_workload_from_args(args),
        output_dir=Path(args.output) if args.output else _default_output(args.scenario),
        sample_interval_s=args.sample_interval_s,
        idle_s=args.idle_s,
        max_rss_mb=args.max_rss_mb,
        watch_csv=watch_csv,
        watch_materialization=args.watch_materialization,
        watch_max_mb=(
            None
            if str(args.watch_max_mb).strip().lower() == "off"
            else float(args.watch_max_mb)
        ),
        clients=args.clients,
        requests_per_client=args.requests_per_client,
        client_interval_s=args.client_interval_s,
        table_limit=args.table_limit,
        config=_config_from_args(args),
    )
    result = run_benchmark(spec)
    print(f"Benchmark {result['status']}: {spec.output_dir}")
    return 0 if result["status"] == "completed" else 1


def compare_command(args: argparse.Namespace) -> int:
    comparison = compare_runs(Path(args.baseline), Path(args.candidate))
    output = (
        Path(args.output) if args.output else Path(args.candidate) / "comparison.json"
    )
    if output.exists():
        raise FileExistsError(f"Comparison output already exists: {output}")
    write_json(output, comparison)
    print(f"Comparison written to {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.pipeline_profile",
        description="Profile a realistic plotsrv pipeline in fresh child processes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser(
        "run", help="run one baseline, publishing, or watched-file scenario"
    )
    run.add_argument(
        "--scenario",
        choices=["baseline", "attached", "remote", "watch-idle", "watch-clients"],
        required=True,
        help="baseline has no plotsrv; attached starts plotsrv in the pipeline; remote uses a server process.",
    )
    run.add_argument(
        "--output", help="New output directory. Defaults under benchmark-results/."
    )
    run.add_argument(
        "--table", action="append", help="Repeatable table shape, e.g. 5000x12."
    )
    run.add_argument(
        "--json-items", action="append", type=int, help="Repeatable JSON item count."
    )
    run.add_argument("--plots", type=int)
    run.add_argument("--html-kb", type=int)
    run.add_argument("--text-kb", type=int)
    run.add_argument("--log-kb", type=int)
    run.add_argument(
        "--cpu-s", type=float, help="CPU work per iteration before publishing."
    )
    run.add_argument("--temporary-memory-mb", type=int)
    run.add_argument("--iterations", type=int)
    run.add_argument("--publish-every", type=int)
    run.add_argument("--sample-interval-s", type=float, default=0.2)
    run.add_argument("--idle-s", type=float, default=3.0)
    run.add_argument(
        "--max-rss-mb",
        type=int,
        help="Kill the complete benchmark process tree above this aggregate RSS.",
    )
    run.add_argument(
        "--watch-csv", help="Watched CSV shape for watch scenarios, e.g. 500000x20."
    )
    run.add_argument(
        "--watch-materialization", choices=["memory", "file"], default="file"
    )
    run.add_argument(
        "--watch-max-mb",
        default="16",
        help="Maximum watched-file preview size, or 'off'.",
    )
    run.add_argument("--clients", type=int, default=1)
    run.add_argument("--requests-per-client", type=int, default=1)
    run.add_argument("--client-interval-s", type=float, default=0.0)
    run.add_argument("--table-limit", type=int, default=1_000)
    run.add_argument(
        "--table-columns-limit",
        help="limits.truncate_after.table_columns for generated plotsrv config, or 'off'.",
    )
    run.add_argument(
        "--truncate-table-rows",
        help=(
            "limits.truncate_after.table_rows for generated plotsrv config, or 'off'. "
            "Defaults to --table-limit."
        ),
    )
    run.add_argument("--publish-max-plot-bytes", type=int)
    run.add_argument("--publish-max-table-rows", type=int)
    run.add_argument("--publish-max-table-columns", type=int)
    run.add_argument("--publish-max-artifact-text-chars", type=int)
    run.add_argument("--publish-max-json-container-items", type=int)
    run.add_argument("--watch-active-max-concurrent", type=int)
    run.add_argument("--watch-active-wait-timeout-s", type=float)
    run.add_argument(
        "--storage-enabled",
        action="store_true",
        help="Enable plotsrv storage for this benchmark run.",
    )
    run.add_argument(
        "--storage-watch-enabled",
        action="store_true",
        help="Enable watched-file storage for this benchmark run.",
    )
    run.set_defaults(func=run_command)

    compare = sub.add_parser(
        "compare", help="compare the run.json summaries from two runs"
    )
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--output", help="Defaults to CANDIDATE/comparison.json")
    compare.set_defaults(func=compare_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileExistsError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
        return 2  # pragma: no cover - argparse exits before reaching this line
