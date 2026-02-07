# src/plotsrv/cli.py
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .service import RunnerService, ServiceConfig
from .server import start_server, stop_server
from . import store
from .discovery import discover_views, DiscoveredView


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plotsrv", description="plotsrv - serve plots/tables easily"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser(
        "run", help="Run a function OR serve a codebase with decorated plots"
    )
    run_p.add_argument(
        "target",
        help="Import path: package.module:function OR a directory/file to scan",
    )
    run_p.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)"
    )
    run_p.add_argument(
        "--port", type=int, default=8000, help="Port to bind (default: 8000)"
    )

    run_p.add_argument(
        "--refresh-rate",
        type=int,
        default=None,
        help="Re-run function every N seconds (callable mode only)",
    )

    run_p.add_argument(
        "--once",
        action="store_true",
        help="Run once then exit (callable mode only unless keep-alive)",
    )
    run_p.add_argument(
        "--keep-alive",
        action="store_true",
        help="Keep server running after first run until Ctrl+C",
    )
    run_p.add_argument(
        "--exit-after-run",
        action="store_true",
        help="Force exit after first run (callable mode only).",
    )

    run_p.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce uvicorn logging noise",
    )

    run_p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help=(
            "Exclude discovered views by label, section, or full view_id (section:label). "
            "Repeatable. Example: --exclude 'Resource Usage' --exclude 'MEM%%' --exclude 'etl:import'"
        ),
    )

    return p


def _norm_excludes(raw: list[str]) -> set[str]:
    """
    Normalize exclude tokens.
    - allow repeating --exclude
    - allow comma-separated lists in a single flag
    """
    out: set[str] = set()
    for item in raw or []:
        if not item:
            continue
        parts = [p.strip() for p in str(item).split(",")]
        for p in parts:
            if p:
                out.add(p)
    return out


def _view_id_for(dv: DiscoveredView) -> str:
    # match store.normalize_view_id(None, section, label) behaviour
    sec = (dv.section or "default").strip() or "default"
    lab = (dv.label or "default").strip() or "default"
    return f"{sec}:{lab}"


def _is_excluded(dv: DiscoveredView, excludes: set[str]) -> bool:
    if not excludes:
        return False

    sec = dv.section or "default"
    lab = dv.label
    vid = _view_id_for(dv)

    # Exclude if token matches label, section, or full view id
    return (lab in excludes) or (sec in excludes) or (vid in excludes)


def _run_passive_dir_mode(
    target: str, *, host: str, port: int, quiet: bool, excludes: set[str]
) -> int:
    """
    Passive mode:
      - start viewer server
      - AST-scan directory for @plot/@table
      - register views into dropdown
      - wait forever until Ctrl+C or /shutdown
    """
    start_server(host=host, port=port, auto_on_show=False, quiet=quiet)

    # discovery + filtering
    discovered = [dv for dv in discover_views(target) if not _is_excluded(dv, excludes)]

    if len(discovered) == 0:
        # still start with a default view so UI isn't empty
        store.register_view(
            view_id="default", section="default", label="default", kind="none"
        )
        store.set_active_view("default")
    else:
        for dv in discovered:
            store.register_view(
                section=dv.section,
                label=dv.label,
                kind="none",
                activate_if_first=False,
            )

        # activate first discovered
        first = discovered[0]
        first_id = store.normalize_view_id(
            None, section=first.section, label=first.label
        )
        store.set_active_view(first_id)

    # mark as "service-like" mode so statusline shows it
    store.set_service_info(
        service_mode=True, target=f"dir:{target}", refresh_rate_s=None
    )

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_server(join=False)
        store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)
        return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "run":
        excludes = _norm_excludes(getattr(args, "exclude", []))

        # Directory mode:
        # - if target exists as file/dir AND does not contain ":" => passive scan mode
        p = Path(args.target)
        if ":" not in args.target and p.exists():
            return _run_passive_dir_mode(
                args.target,
                host=args.host,
                port=args.port,
                quiet=args.quiet,
                excludes=excludes,
            )

        # Callable mode:
        periodic = args.refresh_rate is not None
        refresh_rate = args.refresh_rate if periodic else 0

        once = args.once or not periodic
        if once:
            keep_alive = args.keep_alive or (not args.exit_after_run)
        else:
            keep_alive = False

        cfg = ServiceConfig(
            target=args.target,
            host=args.host,
            port=args.port,
            refresh_rate=refresh_rate,
            once=once,
            keep_alive=keep_alive,
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
