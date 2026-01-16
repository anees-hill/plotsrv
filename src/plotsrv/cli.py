from __future__ import annotations

import argparse
import sys

from .service import RunnerService, ServiceConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plotsrv", description="plotsrv - serve plots/tables easily"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser(
        "run", help="Run a function and serve its output via plotsrv"
    )
    run_p.add_argument("target", help="Import path: package.module:function")
    run_p.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)"
    )
    run_p.add_argument(
        "--port", type=int, default=8000, help="Port to bind (default: 8000)"
    )
    run_p.add_argument(
        "--refresh-rate",
        type=int,
        default=120,
        help="Re-run function every N seconds (default: 120)",
    )
    run_p.add_argument(
        "--once",
        action="store_true",
        help="Run once then exit (server shuts down unless --keep-alive is set)",
    )
    run_p.add_argument(
        "--keep-alive",
        action="store_true",
        help="With --once: keep server running after the first run until Ctrl+C",
    )
    run_p.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce uvicorn logging noise",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "run":
        cfg = ServiceConfig(
            target=args.target,
            host=args.host,
            port=args.port,
            refresh_rate=args.refresh_rate,
            once=args.once,
            keep_alive=args.keep_alive,
            quiet=args.quiet,
        )
        svc = RunnerService(cfg)

        try:
            svc.run()
            return 0
        except KeyboardInterrupt:
            svc.stop()
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
