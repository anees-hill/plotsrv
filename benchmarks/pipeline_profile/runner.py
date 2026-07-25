from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import RunSpec
from .support import free_local_port, read_json, read_json_lines, utc_now, write_csv, write_json
from .workload import write_watched_csv


SAMPLE_FIELDS = [
    "timestamp_utc",
    "elapsed_s",
    "role",
    "pid_count",
    "rss_bytes",
    "uss_bytes",
    "vms_bytes",
    "cpu_user_s",
    "cpu_system_s",
    "cpu_percent",
    "read_bytes",
    "write_bytes",
]

EVENT_FIELDS = [
    "timestamp_utc",
    "elapsed_s",
    "source",
    "event",
    "duration_s",
    "view_id",
    "kind",
    "published",
    "request_number",
    "status_code",
    "response_bytes",
    "error",
    "detail",
]


def _require_psutil():
    try:
        import psutil
    except ImportError as exc:  # pragma: no cover - depends on caller environment
        raise RuntimeError(
            "The pipeline profile needs psutil. Run it with "
            "`uv run --group benchmark python -m benchmarks.pipeline_profile ...`."
        ) from exc
    return psutil


def _assert_process_monitoring_available() -> None:
    """Fail early rather than writing an apparently valid run with no samples."""
    psutil = _require_psutil()
    try:
        psutil.Process(os.getpid()).memory_info()
    except Exception as exc:  # pragma: no cover - only unusual sandbox/container setups
        raise RuntimeError(
            "psutil cannot inspect this process in the current PID namespace. "
            "Run the benchmark on a normal development machine, VM, or container "
            "where the benchmark process tree is visible through /proc."
        ) from exc


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_revision(project_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _process_stats(process: Any) -> dict[str, float | int]:
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except Exception:
        pass

    seen: set[int] = set()
    rss = uss = vms = 0
    cpu_user = cpu_system = 0.0
    read_bytes = write_bytes = 0
    alive = 0
    for current in processes:
        try:
            pid = int(current.pid)
            if pid in seen:
                continue
            seen.add(pid)
            memory = current.memory_info()
            rss += int(memory.rss)
            vms += int(memory.vms)
            try:
                full = current.memory_full_info()
                uss += int(getattr(full, "uss", memory.rss))
            except Exception:
                uss += int(memory.rss)
            cpu = current.cpu_times()
            cpu_user += float(cpu.user)
            cpu_system += float(cpu.system)
            try:
                io = current.io_counters()
                read_bytes += int(io.read_bytes)
                write_bytes += int(io.write_bytes)
            except Exception:
                pass
            alive += 1
        except Exception:
            continue
    return {
        "pid_count": alive,
        "rss_bytes": rss,
        "uss_bytes": uss,
        "vms_bytes": vms,
        "cpu_user_s": cpu_user,
        "cpu_system_s": cpu_system,
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
    }


@dataclass(slots=True)
class ProcessMonitor:
    roots: dict[str, subprocess.Popen[Any]]
    sample_interval_s: float
    max_rss_bytes: int | None
    started_at: float = field(default_factory=time.monotonic)
    samples: list[dict[str, Any]] = field(default_factory=list)
    watchdog_triggered: bool = False
    _previous_cpu: dict[str, tuple[float, float]] = field(default_factory=dict)

    def sample(self) -> None:
        psutil = _require_psutil()
        elapsed = time.monotonic() - self.started_at
        timestamp = utc_now()
        roles: list[dict[str, Any]] = []
        for role, child in self.roots.items():
            if child.poll() is not None:
                continue
            try:
                stats = _process_stats(psutil.Process(child.pid))
            except Exception:
                continue
            total_cpu = float(stats["cpu_user_s"]) + float(stats["cpu_system_s"])
            previous = self._previous_cpu.get(role)
            cpu_percent = 0.0
            if previous is not None:
                previous_elapsed, previous_cpu = previous
                elapsed_delta = elapsed - previous_elapsed
                if elapsed_delta > 0:
                    cpu_percent = 100.0 * (total_cpu - previous_cpu) / elapsed_delta
            self._previous_cpu[role] = (elapsed, total_cpu)
            row = {
                "timestamp_utc": timestamp,
                "elapsed_s": round(elapsed, 6),
                "role": role,
                **stats,
                "cpu_percent": round(cpu_percent, 3),
            }
            roles.append(row)
            self.samples.append(row)

        active_roots = [child for child in self.roots.values() if child.poll() is None]
        if active_roots and not roles:
            raise RuntimeError(
                "The benchmark process monitor could not inspect any live child process."
            )

        if roles:
            aggregate = {
                key: sum(float(row[key]) for row in roles)
                for key in (
                    "pid_count",
                    "rss_bytes",
                    "uss_bytes",
                    "vms_bytes",
                    "cpu_user_s",
                    "cpu_system_s",
                    "read_bytes",
                    "write_bytes",
                )
            }
            aggregate["pid_count"] = int(aggregate["pid_count"])
            aggregate_row = {
                "timestamp_utc": timestamp,
                "elapsed_s": round(elapsed, 6),
                "role": "aggregate",
                **aggregate,
                "cpu_percent": round(sum(float(row["cpu_percent"]) for row in roles), 3),
            }
            self.samples.append(aggregate_row)
            if (
                self.max_rss_bytes is not None
                and int(aggregate_row["rss_bytes"]) > self.max_rss_bytes
            ):
                self.watchdog_triggered = True
                self.terminate_all()

    def wait_for(self, children: Iterable[subprocess.Popen[Any]]) -> None:
        pending = list(children)
        while any(child.poll() is None for child in pending):
            self.sample()
            if self.watchdog_triggered:
                return
            time.sleep(self.sample_interval_s)
        self.sample()

    def observe_idle(self, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self.sample()
            if self.watchdog_triggered:
                return
            time.sleep(self.sample_interval_s)
        self.sample()

    def terminate_all(self) -> None:
        for child in self.roots.values():
            if child.poll() is not None:
                continue
            try:
                if os.name != "nt":
                    os.killpg(child.pid, signal.SIGTERM)
                else:  # pragma: no cover - Windows-specific process handling
                    child.terminate()
            except ProcessLookupError:
                continue
            except Exception:
                try:
                    child.terminate()
                except Exception:
                    pass

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if all(child.poll() is not None for child in self.roots.values()):
                return
            time.sleep(0.05)

        for child in self.roots.values():
            if child.poll() is None:
                try:
                    child.kill()
                except Exception:
                    pass


def _spawn(
    args: list[str],
    *,
    project_root: Path,
    environment: dict[str, str],
    log_path: Path,
) -> subprocess.Popen[Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        return subprocess.Popen(
            args,
            cwd=project_root,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
        )


def _wait_for_file(path: Path, child: subprocess.Popen[Any], *, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return
        if child.poll() is not None:
            raise RuntimeError(
                f"Server worker exited before becoming ready (exit code {child.returncode})."
            )
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for server worker ready file: {path}")


def _write_run_config(spec: RunSpec, path: Path) -> None:
    config: dict[str, Any] = {
        "benchmark": spec.to_dict(),
        "plotsrv": {
            "limits": {
                "watched_files": {
                    "max_mb": "off" if spec.watch_max_mb is None else spec.watch_max_mb,
                },
                "truncate_after": {
                    "table_rows": spec.table_limit,
                    "table_columns": 200,
                },
            },
            "watch-settings": {
                "materialization": spec.watch_materialization,
                "file_threshold_mb": 1,
            },
            "storage-settings": {"enabled": False, "watch_enabled": False},
        },
    }
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def _plotsrv_config_from_benchmark_config(path: Path) -> Path:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    plotsrv_config = raw.get("plotsrv", {}) if isinstance(raw, dict) else {}
    result = path.with_name("plotsrv.yaml")
    with result.open("w", encoding="utf-8") as f:
        yaml.safe_dump(plotsrv_config, f, sort_keys=False)
    return result


def _system_metadata(project_root: Path) -> dict[str, Any]:
    psutil = _require_psutil()
    memory = psutil.virtual_memory()
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "total_memory_bytes": int(memory.total),
        "psutil_version": psutil.__version__,
        "plotsrv_revision": _git_revision(project_root),
    }


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = [row for row in samples if row["role"] == "aggregate"]
    if not aggregate:
        return {"sample_count": 0}

    def maximum(key: str) -> float:
        return max(float(row[key]) for row in aggregate)

    def delta(key: str) -> float:
        values = [float(row[key]) for row in aggregate]
        return max(values) - min(values)

    return {
        "sample_count": len(aggregate),
        "max_rss_bytes": int(maximum("rss_bytes")),
        "max_uss_bytes": int(maximum("uss_bytes")),
        "max_vms_bytes": int(maximum("vms_bytes")),
        "max_cpu_percent": round(maximum("cpu_percent"), 3),
        "read_bytes_delta": int(delta("read_bytes")),
        "write_bytes_delta": int(delta("write_bytes")),
        "peak_by_role": {
            role: int(max(float(row["rss_bytes"]) for row in samples if row["role"] == role))
            for role in sorted({str(row["role"]) for row in samples if row["role"] != "aggregate"})
        },
    }


def _write_events(output_dir: Path, *, paths: list[Path]) -> None:
    rows: list[dict[str, Any]] = []
    for raw in read_json_lines(paths):
        known = {key: raw.get(key) for key in EVENT_FIELDS if key in raw}
        detail = {key: value for key, value in raw.items() if key not in EVENT_FIELDS}
        known["detail"] = json.dumps(detail, sort_keys=True) if detail else ""
        known["elapsed_s"] = raw.get("elapsed_s", "")
        rows.append(known)
    rows.sort(key=lambda row: str(row.get("timestamp_utc", "")))
    write_csv(output_dir / "events.csv", rows, EVENT_FIELDS)


def run_benchmark(spec: RunSpec) -> dict[str, Any]:
    """Execute one benchmark in fresh child process(es) and write its artefacts."""
    _assert_process_monitoring_available()
    output_dir = spec.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise FileExistsError(
            f"Benchmark output directory already exists: {output_dir}. Choose a new --output directory."
        )
    output_dir.mkdir(parents=True)
    work_dir = output_dir / "work"
    work_dir.mkdir()
    logs_dir = output_dir / "logs"

    _write_run_config(spec, output_dir / "config.yml")
    plotsrv_config = _plotsrv_config_from_benchmark_config(output_dir / "config.yml")
    worker_spec_path = work_dir / "worker-spec.json"
    write_json(worker_spec_path, spec.to_dict())

    watch_csv_path: Path | None = None
    if spec.watch_csv is not None:
        watch_csv_path = work_dir / "watched.csv"
        write_watched_csv(watch_csv_path, spec.watch_csv)

    project_root = _project_root()
    environment = os.environ.copy()
    environment["PLOTSRV_CONFIG"] = str(plotsrv_config)
    environment["PLOTSRV_DEBUG"] = "1"
    environment["MPLCONFIGDIR"] = str(work_dir / "matplotlib")
    environment["PYTHONUNBUFFERED"] = "1"
    port = free_local_port()
    command_prefix = [sys.executable, "-m", "benchmarks.pipeline_profile.worker"]
    roots: dict[str, subprocess.Popen[Any]] = {}
    event_paths: list[Path] = []
    started_wall = time.monotonic()
    started_at = utc_now()
    monitor = ProcessMonitor(
        roots=roots,
        sample_interval_s=spec.sample_interval_s,
        max_rss_bytes=(
            None if spec.max_rss_mb is None else spec.max_rss_mb * 1024 * 1024
        ),
    )
    status = "completed"
    failure: str | None = None

    try:
        if spec.scenario in {"remote", "watch-idle", "watch-clients"}:
            ready_file = work_dir / "server-ready.json"
            server_events = work_dir / "server-events.jsonl"
            event_paths.append(server_events)
            server_args = [
                *command_prefix,
                "server",
                "--port",
                str(port),
                "--ready-file",
                str(ready_file),
                "--events",
                str(server_events),
                "--config",
                str(plotsrv_config),
            ]
            if watch_csv_path is not None:
                server_args.extend(["--watch-csv", str(watch_csv_path)])
                server_args.extend(["--watch-materialization", spec.watch_materialization])
                if spec.watch_max_bytes is not None:
                    server_args.extend(["--watch-max-bytes", str(spec.watch_max_bytes)])
            server = _spawn(
                server_args,
                project_root=project_root,
                environment=environment,
                log_path=logs_dir / "server.log",
            )
            roots["server"] = server
            _wait_for_file(ready_file, server)
            monitor.sample()

        if spec.scenario in {"baseline", "attached", "remote"}:
            pipeline_events = work_dir / "pipeline-events.jsonl"
            event_paths.append(pipeline_events)
            mode = {
                "baseline": "none",
                "attached": "attached",
                "remote": "remote",
            }[spec.scenario]
            pipeline = _spawn(
                [
                    *command_prefix,
                    "pipeline",
                    "--spec",
                    str(worker_spec_path),
                    "--mode",
                    mode,
                    "--port",
                    str(port),
                    "--events",
                    str(pipeline_events),
                ],
                project_root=project_root,
                environment=environment,
                log_path=logs_dir / "pipeline.log",
            )
            roots["pipeline"] = pipeline
            monitor.wait_for([pipeline])
            if pipeline.returncode not in (0, None):
                raise RuntimeError(f"Pipeline worker failed with exit code {pipeline.returncode}")

        if spec.scenario == "watch-clients" and not monitor.watchdog_triggered:
            clients: list[subprocess.Popen[Any]] = []
            for client_id in range(1, spec.clients + 1):
                client_events = work_dir / f"client-{client_id}-events.jsonl"
                event_paths.append(client_events)
                client = _spawn(
                    [
                        *command_prefix,
                        "client",
                        "--port",
                        str(port),
                        "--view-id",
                        "watch:watched-csv",
                        "--table-limit",
                        str(spec.table_limit),
                        "--requests",
                        str(spec.requests_per_client),
                        "--interval-s",
                        str(spec.client_interval_s),
                        "--client-id",
                        str(client_id),
                        "--events",
                        str(client_events),
                    ],
                    project_root=project_root,
                    environment=environment,
                    log_path=logs_dir / f"client-{client_id}.log",
                )
                roots[f"client-{client_id}"] = client
                clients.append(client)
            monitor.wait_for(clients)
            failed_clients = [client for client in clients if client.returncode not in (0, None)]
            if failed_clients:
                raise RuntimeError(f"{len(failed_clients)} client worker(s) failed")

        if not monitor.watchdog_triggered:
            monitor.observe_idle(spec.idle_s)
    except Exception as exc:
        status = "failed"
        failure = f"{type(exc).__name__}: {exc}"
        monitor.terminate_all()
    finally:
        if monitor.watchdog_triggered:
            status = "watchdog_terminated"
            failure = (
                f"Aggregate RSS exceeded the configured {spec.max_rss_mb} MiB watchdog limit."
            )
        monitor.terminate_all()
        monitor.sample()

    write_csv(output_dir / "samples.csv", monitor.samples, SAMPLE_FIELDS)
    _write_events(output_dir, paths=event_paths)
    process_exit_codes = {role: child.returncode for role, child in roots.items()}
    result: dict[str, Any] = {
        "status": status,
        "failure": failure,
        "scenario": spec.scenario,
        "started_at": started_at,
        "finished_at": utc_now(),
        "wall_time_s": round(time.monotonic() - started_wall, 6),
        "workload": spec.workload.to_dict(),
        "watch": {
            "csv": None if spec.watch_csv is None else spec.watch_csv.to_dict(),
            "materialization": spec.watch_materialization if spec.watch_csv else None,
            "max_mb": spec.watch_max_mb if spec.watch_csv else None,
            "clients": spec.clients if spec.scenario == "watch-clients" else 0,
            "requests_per_client": (
                spec.requests_per_client if spec.scenario == "watch-clients" else 0
            ),
        },
        "safety": {
            "max_rss_mb": spec.max_rss_mb,
            "watchdog_triggered": monitor.watchdog_triggered,
        },
        "summary": _summary(monitor.samples),
        "process_exit_codes": process_exit_codes,
        "system": _system_metadata(project_root),
    }
    write_json(output_dir / "run.json", result)
    return result


COMPARISON_METRICS = [
    "wall_time_s",
    "summary.max_rss_bytes",
    "summary.max_uss_bytes",
    "summary.max_cpu_percent",
    "summary.read_bytes_delta",
    "summary.write_bytes_delta",
]


def _nested_value(data: dict[str, Any], dotted_key: str) -> float | int | None:
    value: Any = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, (int, float)) else None


def compare_runs(baseline_dir: Path, candidate_dir: Path) -> dict[str, Any]:
    baseline = read_json(baseline_dir / "run.json")
    candidate = read_json(candidate_dir / "run.json")
    metrics: dict[str, Any] = {}
    for key in COMPARISON_METRICS:
        before = _nested_value(baseline, key)
        after = _nested_value(candidate, key)
        delta = None if before is None or after is None else after - before
        percent = None
        if delta is not None and before not in (None, 0):
            percent = 100.0 * delta / before
        metrics[key] = {
            "baseline": before,
            "candidate": after,
            "delta": delta,
            "percent_change": percent,
        }
    return {
        "baseline": str(baseline_dir.resolve()),
        "candidate": str(candidate_dir.resolve()),
        "baseline_status": baseline.get("status"),
        "candidate_status": candidate.get("status"),
        "metrics": metrics,
    }
