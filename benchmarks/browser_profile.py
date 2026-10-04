"""Bounded loopback receiver rehearsal; usable directly or through ptop.

HTTP clients live in the parent, the receiver in a fresh child. This measures
server responses, not browser JavaScript, proxies, or capacity of a deployed VM.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter
import hashlib
import io
import math
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any

import httpx
import yaml

from .pipeline_profile.runner import ProcessMonitor, SAMPLE_FIELDS
from .pipeline_profile.support import free_local_port, utc_now, write_csv, write_json


def distribution(values: list[float]) -> dict[str, float | int | None]:
    """Nearest-rank percentiles; retain count so small samples are apparent."""
    ordered = sorted(values)
    return {"count": len(ordered), **{
        name: ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None
        for name, fraction in (("p50", .5), ("p95", .95), ("p99", .99), ("max", 1))
    }}


def payloads(
    rows: int, columns: int, string_chars: int, artifact_items: int, revision: int,
) -> list[dict[str, Any]]:
    from PIL import Image
    png = io.BytesIO()
    Image.new("RGB", (320, 180), (30, 80, 140)).save(png, format="PNG")
    marker = f"revision-{revision}"
    return [
        {"view_id": "bench:table", "kind": "table", "force": True, "table": {
            "columns": ["revision", *[f"c{i}" for i in range(columns)]],
            "rows": [{"revision": marker, **{
                f"c{i}": f"{row}-{i}-" + "x" * string_chars for i in range(columns)
            }} for row in range(rows)],
        }},
        {"view_id": "bench:artifact", "kind": "artifact", "artifact_kind": "json",
         "force": True, "artifact": {"revision": marker, "items": [
             {"id": i, "amount": i * 1.25} for i in range(artifact_items)]}},
        {"view_id": "bench:plot", "kind": "plot", "force": True,
         "plot_png_b64": base64.b64encode(png.getvalue()).decode()},
    ]


async def exercise(args, base_url, monitor, server, records, streams):
    phase = "setup"
    stop = asyncio.Event()
    phase_metrics = {}

    def checkpoint(name):
        sample_start = len(monitor.samples)
        monitor.sample()
        for row in monitor.samples[sample_start:]:
            row["phase"] = name
        rows = [row for row in monitor.samples if row["role"] == "server"]
        latest = rows[-1]
        return {"phase": name, "cpu_s": latest["cpu_user_s"] + latest["cpu_system_s"],
                "rss_bytes": latest["rss_bytes"], "uss_bytes": latest["uss_bytes"],
                "at_s": time.monotonic()}

    def finish_phase(before):
        after = checkpoint(before["phase"])
        name = before["phase"]
        phase_metrics.setdefault(name, []).append({
            "cpu_s": after["cpu_s"] - before["cpu_s"],
            "wall_s": after["at_s"] - before["at_s"],
            "rss_bytes": after["rss_bytes"], "uss_bytes": after["uss_bytes"],
        })
    paths = {"table": "/table/data?view=bench:table", "artifact": "/artifact?view=bench:artifact",
             "page": "/?view=bench:table", "status": "/status?view=bench:table",
             "plot": "/plot?view=bench:plot"}
    limits = httpx.Limits(max_connections=args.clients * 3 + 10,
                          max_keepalive_connections=args.clients * 3 + 10)
    async with httpx.AsyncClient(base_url=base_url, timeout=args.timeout, limits=limits,
                                 trust_env=False) as client:
        async def request(route, *, expected=None, payload=None, path=None, expected_rows=None):
            started = time.monotonic()
            row = {"phase": phase, "route": route, "started_s": started,
                   "status_code": None, "response_bytes": 0, "error": None}
            try:
                response = await (client.post("/publish", json=payload) if payload is not None
                                  else client.get(path or paths[route]))
                row.update(status_code=response.status_code, response_bytes=len(response.content))
                # End-to-end HTTP time excludes client-side content validation.
                row["duration_s"] = time.monotonic() - started
                if response.is_error:
                    row["response_error"] = response.text[:1000]
                response.raise_for_status()
                if payload is not None and response.json().get("ignored"):
                    raise ValueError("publication was ignored")
                if expected is not None and route == "table":
                    data = response.json()
                    if len(data["rows"]) != (args.rows if expected_rows is None else expected_rows) or any(
                        item["revision"] != f"revision-{expected}" for item in data["rows"]
                    ):
                        raise ValueError("table truncated or stale/mixed publication")
                if expected is not None and route == "artifact":
                    if f"revision-{expected}" not in response.json()["html"]:
                        raise ValueError("artifact did not contain expected revision")
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            row.setdefault("duration_s", time.monotonic() - started)
            records.append(row)
            return row

        # Prebuild payloads outside measured traffic; this client shares the host CPU.
        initial = payloads(args.rows, args.columns, args.string_chars, args.artifact_items, 1)
        updated = payloads(args.rows, args.columns, args.string_chars, args.artifact_items, 2)
        for payload in initial if args.mode == "mixed" else initial[:1]:
            row = await request("publish", payload=payload)
            if row["error"]:
                raise RuntimeError(row["error"])

        async def sample():
            while not stop.is_set():
                sample_start = len(monitor.samples)
                monitor.sample()
                for row in monitor.samples[sample_start:]:
                    row["phase"] = phase
                if monitor.watchdog_triggered or server.poll() is not None:
                    raise RuntimeError("receiver exited or exceeded RSS watchdog")
                await asyncio.sleep(.1)

        async def probes():
            while not stop.is_set():
                await asyncio.gather(*(request(route) for route in ("page", "status", "plot")))
                await asyncio.sleep(.1)

        async def sse(state):
            last = time.monotonic()
            since = 0
            try:
                while not stop.is_set():
                    connection_started = time.monotonic()
                    async with client.stream("GET", f"/updates?view=bench:table&since={since}") as response:
                        state["status_code"] = response.status_code
                        response.raise_for_status()
                        event = ""
                        async for line in response.aiter_lines():
                            if line.startswith("event:"):
                                event = line[6:].strip()
                            if line.startswith("data:"):
                                now = time.monotonic()
                                state["gaps_s"].append(now - last)
                                last = now
                                if event == "keepalive":
                                    state["keepalives"] += 1
                                elif event == "update":
                                    data = json.loads(line[5:])
                                    epoch = data.get("server_instance_id")
                                    if state.get("server_instance_id", epoch) != epoch:
                                        raise RuntimeError("receiver instance changed")
                                    state["server_instance_id"] = epoch
                                    since = max(since, data["revision"])
                                    state["updates"].append({"at_s": now, "revision": data["revision"],
                                                             "view_id": data.get("view_id"),
                                                             "change_type": data.get("change_type")})
                                    state["ready"].set()
                    # The demo intentionally expires streams at 600 seconds.
                    # Reconnect like its browser; an earlier close is a failure.
                    if time.monotonic() - connection_started < args.sse_lifetime - min(5, args.sse_lifetime * .05):
                        raise RuntimeError("unexpected stream close before lifetime limit")
                    state["reconnects"] += 1
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                state["gaps_s"].append(time.monotonic() - last)
                state["ready"].set()

        tasks = [asyncio.create_task(sample())]
        if args.mode == "mixed":
            tasks.append(asyncio.create_task(probes()))
        try:
            for _ in range(args.clients):
                state = {"ready": asyncio.Event(), "updates": [], "gaps_s": [],
                         "keepalives": 0, "reconnects": 0, "error": None, "status_code": None}
                streams.append(state)
                tasks.append(asyncio.create_task(sse(state)))
            await asyncio.wait_for(asyncio.gather(*(s["ready"].wait() for s in streams)), args.timeout)
            if any(s["error"] or not s["updates"] for s in streams):
                raise RuntimeError("not every visitor established a live update stream")

            async def wave(route, expected=None):
                await asyncio.gather(*(request(route, expected=expected) for _ in range(args.clients)))

            async def browse(expected=None):
                await wave("table", expected)
                if args.mode == "mixed":
                    await wave("artifact", expected)

            phase = "cold"
            before_phase = checkpoint(phase)
            await browse(1)
            finish_phase(before_phase)
            phase = "warm"
            before_phase = checkpoint(phase)
            for _ in range(args.rounds):
                await browse(1)
            finish_phase(before_phase)

            before = [s["updates"][-1]["revision"] for s in streams]
            publication_start = time.monotonic()
            for cycle in range(args.publish_cycles):
                phase = "publishing"
                before_phase = checkpoint(phase)
                await asyncio.gather(browse(), *(request("publish", payload=p)
                    for p in (updated[:2] if args.mode == "mixed" else updated[:1])))
                finish_phase(before_phase)
                phase = "republished"
                before_phase = checkpoint(phase)
                await browse(2)
                finish_phase(before_phase)

            if args.soak_seconds:
                phase = "soak-setup"
                # More views than cache entries; varying limits also create
                # distinct response shapes. Pace traffic so the soak measures
                # sustained ownership/eviction behavior, not generator speed.
                for index in range(args.soak_views):
                    await request("publish", payload=dict(initial[0], view_id=f"soak:{index}"))
                revisions = [1] * args.soak_views
                phase = "soak"
                deadline = time.monotonic() + args.soak_seconds
                cycle = 0
                before_phase = checkpoint(phase)
                while time.monotonic() < deadline:
                    index = cycle % args.soak_views
                    if cycle % 10 == 0:
                        revisions[index] = 3 - revisions[index]
                        payload = initial[0] if revisions[index] == 1 else updated[0]
                        await request("publish", payload=dict(payload, view_id=f"soak:{index}"))
                    limit = args.rows if cycle % 3 else max(1, args.rows // 2)
                    await asyncio.gather(*(request("table", expected=revisions[index],
                        expected_rows=limit, path=f"/table/data?view=soak:{index}&limit={limit}")
                        for _ in range(args.clients)))
                    cycle += 1
                    await asyncio.sleep(.5)
                    if cycle % 60 == 0:
                        finish_phase(before_phase)
                        before_phase = checkpoint(phase)
                finish_phase(before_phase)
            phase = "settling"
            # At least 22 seconds in normal recipes: the receiver heartbeat is 20s.
            before_phase = checkpoint(phase)
            await asyncio.sleep(args.settle)
            finish_phase(before_phase)
            for state, revision in zip(streams, before):
                updates = [u for u in state["updates"] if u["revision"] > revision
                           and u["at_s"] >= publication_start and u.get("view_id") == "bench:table"
                           and u.get("change_type") == "ordinary"]
                state["publication_notice_s"] = (updates[0]["at_s"] - publication_start
                                                 if updates else None)
                if not updates:
                    state["error"] = state["error"] or "missing publication notice"
            # Retrieve background exceptions before cleanup.
            for task in tasks:
                if task.done():
                    task.result()
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    for state in streams:
        state.pop("ready", None)
    return records, streams, phase_metrics


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for phase, route in sorted({(r["phase"], r["route"]) for r in records}):
        rows = [r for r in records if r["phase"] == phase and r["route"] == route]
        result[f"{phase}.{route}"] = {
            "latency_s": distribution([r["duration_s"] for r in rows]),
            "statuses": dict(Counter(str(r["status_code"]) for r in rows)),
            "errors": sum(r["error"] is not None for r in rows),
            "response_bytes": sum(r["response_bytes"] for r in rows),
        }
    return result


def run(args: argparse.Namespace, *, exercise_fn=None, case_id="server.browser.concurrent",
        cpu_route="table", harness_paths=()) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = output / "plotsrv.yaml"
    config.write_text(yaml.safe_dump({
        "storage-settings": {"enabled": False},
        "limits": {"truncate_after": {"table_rows": "off", "table_columns": "off"}},
        "browser-update-settings": {"max_connections": 96, "max_connections_per_client": 64,
                                    "max_connection_seconds": args.sse_lifetime},
    }))
    environment = {**os.environ, "PLOTSRV_CONFIG": str(config),
                   "MPLCONFIGDIR": str(output / "matplotlib"), "PYTHONUNBUFFERED": "1"}
    port = free_local_port()
    started = utc_now()
    server = None
    monitor = None
    records, streams, failure = [], [], None
    phase_metrics = {}
    settings = {k: v for k, v in vars(args).items() if k != "output"}
    try:
        with (output / "server.log").open("w") as log:
            server = subprocess.Popen([
                sys.executable, "-m", "benchmarks.pipeline_profile.worker", "server",
                "--port", str(port), "--ready-file", str(output / "ready.json"),
                "--events", str(output / "server-events.jsonl"), "--config", str(config),
                "--cache-metrics", str(output / "cache-samples.jsonl"),
            ], env=environment, stdout=log, stderr=subprocess.STDOUT)
        monitor = ProcessMonitor({"server": server}, .1, args.max_server_rss_mb * 1024**2)
        deadline = time.monotonic() + args.timeout
        while not (output / "ready.json").exists():
            monitor.sample()
            if server.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("receiver failed to start; see server.log")
            time.sleep(.1)
        async def bounded():
            workload = exercise if exercise_fn is None else exercise_fn
            return await asyncio.wait_for(workload(args, f"http://127.0.0.1:{port}", monitor, server, records, streams),
                                          args.max_seconds)
        records, streams, phase_metrics = asyncio.run(bounded())
        monitor.sample()
        if monitor.watchdog_triggered or server.poll() is not None:
            raise RuntimeError("receiver exited or exceeded RSS watchdog")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if server is not None:
            if server.poll() is None:
                server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    for state in streams:
        state.pop("ready", None)
    summary = summarize(records)
    errors = sum(r["error"] is not None for r in records) + sum(bool(s["error"]) for s in streams)
    if errors:
        failure = failure or f"{errors} HTTP/content/SSE failures"
    if args.cheap_p95_ms:
        for key, value in summary.items():
            if key.split(".")[0] in {"cold", "warm", "publishing", "republished"} and key.split(".")[1] in {"page", "status", "plot"}:
                if value["latency_s"]["p95"] * 1000 > args.cheap_p95_ms:
                    failure = failure or f"{key} exceeded cheap request p95 budget"
    samples = monitor.samples if monitor else []
    server_samples = [s for s in samples if s["role"] == "server"]
    result = {
        "status": "failed" if failure else "completed", "failure": failure,
        "case_id": case_id, "settings": settings,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes() + b"".join(
            Path(path).read_bytes() for path in harness_paths)).hexdigest(),
        "case_fingerprint": hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16],
        "started_at": started, "finished_at": utc_now(), "summary": summary, "phase_metrics": phase_metrics,
        "receiver": {"peak_rss_bytes": max((s["rss_bytes"] for s in server_samples), default=0),
                     "peak_cpu_percent": max((s["cpu_percent"] for s in server_samples), default=0),
                     "exit_code_after_cleanup": server.returncode if server else None,
                     "peak_cpu_percent_by_phase": {
                         phase: max(s["cpu_percent"] for s in server_samples
                                    if s.get("phase", "startup") == phase)
                         for phase in sorted({s.get("phase", "startup") for s in server_samples})
                     }},
        "system": {"python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
                   "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                   "cgroup_cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip() if Path("/sys/fs/cgroup/cpu.max").exists() else None,
                   "cgroup_memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip() if Path("/sys/fs/cgroup/memory.max").exists() else None},
        "streams": streams,
    }
    from importlib.metadata import version, distributions
    result["plotsrv_version"] = version("plotsrv")
    cache_path = output / "cache-samples.jsonl"
    result["cache_samples"] = [json.loads(line) for line in cache_path.read_text().splitlines()] if cache_path.exists() else []
    result["dependencies"] = {d.metadata["Name"]: d.version for d in distributions()}
    if (output / "ready.json").exists():
        result["receiver_provenance"] = json.loads((output / "ready.json").read_text())
    for phase_name, values in phase_metrics.items():
        success = sum(r["phase"] == phase_name and r["route"] == cpu_route and not r["error"] for r in records)
        for value in values:
            value[f"{cpu_route}_success_count_total"] = success
        if success:
            result.setdefault(f"cpu_per_{cpu_route}_s", {})[phase_name] = sum(v["cpu_s"] for v in values) / success
    write_json(output / "run.json", result)
    write_json(output / "requests.json", records)
    write_csv(output / "samples.csv", samples, [*SAMPLE_FIELDS, "phase"])
    print(f"Browser rehearsal {result['status']}: {output}")
    for key, value in summary.items():
        if key.startswith(("cold.", "warm.", "publishing.", "republished.")):
            print(f"  {key}: p95={value['latency_s']['p95'] * 1000:.1f}ms errors={value['errors']}")
    if failure:
        print(f"  {failure}")
    return 1 if failure else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["mixed", "table"], default="mixed")
    parser.add_argument("--publish-cycles", type=int, default=1)
    parser.add_argument("--soak-seconds", type=float, default=0)
    parser.add_argument("--soak-views", type=int, default=40)
    parser.add_argument("--sse-lifetime", type=int, default=600)
    for name, default in (("clients", 6), ("rows", 1680), ("columns", 12),
                          ("string-chars", 8), ("artifact-items", 500), ("rounds", 5),
                          ("max-server-rss-mb", 512)):
        parser.add_argument(f"--{name}", type=int, default=default)
    for name, default in (("settle", 22), ("timeout", 30), ("max-seconds", 180), ("cheap-p95-ms", 0)):
        parser.add_argument(f"--{name}", type=float, default=default)
    args = parser.parse_args(argv)
    if not (1 <= args.clients <= 64 and 1 <= args.rows <= 100000 and 1 <= args.columns <= 199
            and 0 <= args.string_chars <= 4096 and 1 <= args.artifact_items <= 10000
            and 1 <= args.rounds <= 100 and args.max_server_rss_mb > 0
            and 0 <= args.settle < args.max_seconds <= 1800 and args.timeout > 0 and args.cheap_p95_ms >= 0
            and 1 <= args.publish_cycles <= 100 and 0 <= args.soak_seconds < args.max_seconds
            and 1 <= args.soak_views <= 64 and 1 <= args.sse_lifetime <= 600):
        parser.error("invalid workload/budget; clients 1..64, rows 1..100000, columns 1..199, max-seconds <=1800")
    estimated_payload = args.rows * (args.columns * (args.string_chars + 40) + 64)
    if estimated_payload > 24 * 1024**2:
        parser.error("estimated table payload exceeds the rehearsal 24 MiB generation budget")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
