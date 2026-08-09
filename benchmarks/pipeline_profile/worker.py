from __future__ import annotations

import argparse
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .models import RunSpec
from .support import read_json, utc_now, write_json, write_json_line
from .workload import run_workload


def _event_writer(path: Path, *, source: str):
    def write(event: str, detail: dict[str, Any] | None, duration_s: float | None) -> None:
        row: dict[str, Any] = {
            "timestamp_utc": utc_now(),
            "source": source,
            "event": event,
        }
        if duration_s is not None:
            row["duration_s"] = duration_s
        if detail:
            row.update(detail)
        write_json_line(path, row)

    return write


def _wait_for_http(port: int, *, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/status"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if 200 <= response.status < 500:
                    return
        except Exception as exc:  # the server thread may still be starting
            last_error = exc
        time.sleep(0.05)
    raise RuntimeError(f"plotsrv server did not become ready on port {port}: {last_error}")


def run_server(args: argparse.Namespace) -> int:
    from plotsrv import WatchConfig, start_server, stop_server

    event = _event_writer(Path(args.events), source="server")
    watches = []
    if args.watch_csv:
        watches.append(
            WatchConfig(
                path=args.watch_csv,
                section="watch",
                label="watched-csv",
                read_mode="head",
                max_bytes=args.watch_max_bytes,
                materialization=args.watch_materialization,
            )
        )

    stopping = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    previous_term = signal.signal(signal.SIGTERM, request_stop)
    previous_int = signal.signal(signal.SIGINT, request_stop)
    try:
        event("server_starting", {"port": args.port, "watch": bool(watches)}, None)
        start_server(
            host="127.0.0.1",
            port=args.port,
            auto_on_show=False,
            quiet=True,
            config=args.config,
            watches=watches or None,
            restore_latest=False,
        )
        _wait_for_http(args.port)
        write_json(Path(args.ready_file), {"pid": __import__("os").getpid(), "port": args.port})
        event("server_ready", {"port": args.port}, None)
        while not stopping:
            time.sleep(0.1)
        return 0
    finally:
        event("server_stopping", None, None)
        stop_server(join=True)
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def run_pipeline(args: argparse.Namespace) -> int:
    raw = read_json(Path(args.spec))
    spec = RunSpec.from_dict(raw)
    event = _event_writer(Path(args.events), source="pipeline")
    event("pipeline_started", {"mode": args.mode}, None)
    started = time.perf_counter()
    try:
        run_workload(
            spec.workload,
            mode=args.mode,
            host="127.0.0.1",
            port=args.port,
            event=event,
            async_publish=(spec.publish_behaviour == "async"),
        )

        # This marks when the user's pipeline work has finished, before any
        # final async flush. It lets the benchmark distinguish responsiveness
        # from total delivery completion.
        event(
            "pipeline_work_finished",
            {
                "publish_behaviour": spec.publish_behaviour,
            },
            time.perf_counter() - started,
        )

        if (
            spec.publish_behaviour == "async"
            and spec.flush_async
            and args.mode != "none"
        ):
            from plotsrv import flush_views

            flush_started = time.perf_counter()
            flushed = flush_views(timeout=spec.flush_timeout_s)

            event(
                "publish_flush_finished",
                {
                    "flushed": flushed,
                    "timeout_s": spec.flush_timeout_s,
                },
                time.perf_counter() - flush_started,
            )

            if not flushed:
                raise RuntimeError(
                    "Async publishing did not flush within "
                    f"{spec.flush_timeout_s:.1f} seconds"
                )
    except Exception as exc:
        event("pipeline_failed", {"error": f"{type(exc).__name__}: {exc}"}, None)
        raise
    finally:
        event("pipeline_finished", None, time.perf_counter() - started)
        if args.mode == "attached":
            try:
                from plotsrv import stop_server

                stop_server(join=True)
            except Exception:
                pass
    return 0


def run_client(args: argparse.Namespace) -> int:
    event = _event_writer(Path(args.events), source=f"client-{args.client_id}")
    url = (
        f"http://127.0.0.1:{args.port}/table/data?"
        + urllib.parse.urlencode({"view": args.view_id, "limit": args.table_limit})
    )
    failures = 0
    for request_number in range(1, args.requests + 1):
        started = time.perf_counter()
        status_code: int | None = None
        response_bytes = 0
        error: str | None = None
        try:
            with urllib.request.urlopen(url, timeout=args.timeout_s) as response:
                status_code = int(response.status)
                response_bytes = len(response.read())
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            response_bytes = len(exc.read())
            error = str(exc)
            failures += 1
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failures += 1
        event(
            "table_request",
            {
                "request_number": request_number,
                "status_code": status_code,
                "response_bytes": response_bytes,
                "error": error,
            },
            time.perf_counter() - started,
        )
        if args.interval_s:
            time.sleep(args.interval_s)
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.pipeline_profile.worker")
    sub = parser.add_subparsers(dest="command", required=True)

    server = sub.add_parser("server")
    server.add_argument("--port", type=int, required=True)
    server.add_argument("--ready-file", required=True)
    server.add_argument("--events", required=True)
    server.add_argument("--config", required=True)
    server.add_argument("--watch-csv")
    server.add_argument("--watch-materialization", choices=["memory", "file"], default="file")
    server.add_argument("--watch-max-bytes", type=int)
    server.set_defaults(func=run_server)

    pipeline = sub.add_parser("pipeline")
    pipeline.add_argument("--spec", required=True)
    pipeline.add_argument("--mode", choices=["none", "attached", "remote"], required=True)
    pipeline.add_argument("--port", type=int, required=True)
    pipeline.add_argument("--events", required=True)
    pipeline.set_defaults(func=run_pipeline)

    client = sub.add_parser("client")
    client.add_argument("--port", type=int, required=True)
    client.add_argument("--view-id", required=True)
    client.add_argument("--table-limit", type=int, required=True)
    client.add_argument("--requests", type=int, required=True)
    client.add_argument("--interval-s", type=float, default=0.0)
    client.add_argument("--timeout-s", type=float, default=30.0)
    client.add_argument("--client-id", type=int, required=True)
    client.add_argument("--events", required=True)
    client.set_defaults(func=run_client)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
