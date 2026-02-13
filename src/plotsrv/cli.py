# src/plotsrv/cli.py
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
import importlib.util
from typing import Any

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

    run_p.add_argument(
        "--include",
        action="append",
        default=[],
        help=(
            "Include ONLY discovered views by label, section, or full view_id (section:label). "
            "Repeatable and/or comma-separated. Example: --include 'Resource Usage' --include 'CPU%%' --include 'etl:import'"
        ),
    )

    return p


def _norm_tokens(raw: list[str]) -> set[str]:
    """
    Normalize include/exclude tokens.
    - allow repeating flags
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


def _is_included(dv: DiscoveredView, includes: set[str]) -> bool:
    """
    If includes is empty => allow all.
    Otherwise allow if token matches label, section, or full view id.
    """
    if not includes:
        return True

    sec = dv.section or "default"
    lab = dv.label
    vid = _view_id_for(dv)
    return (lab in includes) or (sec in includes) or (vid in includes)


def _is_excluded(dv: DiscoveredView, excludes: set[str]) -> bool:
    if not excludes:
        return False

    sec = dv.section or "default"
    lab = dv.label
    vid = _view_id_for(dv)

    # Exclude if token matches label, section, or full view id
    return (lab in excludes) or (sec in excludes) or (vid in excludes)


def _resolve_target_to_path_if_importable(target: str) -> str | None:
    """
    If target is importable as a module/package (and not module:function),
    return the filesystem path for passive scanning.

    - package -> package directory
    - module  -> module .py file
    """
    if ":" in target:
        return None

    spec = importlib.util.find_spec(target)
    if spec is None:
        return None

    # package
    if spec.submodule_search_locations:
        locs = list(spec.submodule_search_locations)
        if locs:
            return str(Path(locs[0]).resolve())

    # module
    if spec.origin:
        return str(Path(spec.origin).resolve())

    return None


def _run_passive_dir_mode(
    target: str,
    *,
    host: str,
    port: int,
    quiet: bool,
    excludes: set[str],
    includes: set[str],
) -> int:
    """
    Passive mode:
      - start viewer server
      - AST-scan directory for @plot/@table
      - register views into dropdown
      - wait forever until Ctrl+C or /shutdown
    """
    start_server(host=host, port=port, auto_on_show=False, quiet=quiet)

    # discovery + filtering (include first, then exclude)
    discovered_all = discover_views(target)
    discovered = [
        dv
        for dv in discovered_all
        if _is_included(dv, includes) and not _is_excluded(dv, excludes)
    ]

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


def _die(msg: str) -> int:
    print(f"plotsrv: error: {msg}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "run":
        excludes = _norm_tokens(getattr(args, "exclude", []))
        includes = _norm_tokens(getattr(args, "include", []))

        # Passive filesystem mode:
        p = Path(args.target)
        if ":" not in args.target and p.exists():
            return _run_passive_dir_mode(
                args.target,
                host=args.host,
                port=args.port,
                quiet=args.quiet,
                excludes=excludes,
                includes=includes,
            )

        # Passive importable mode (package/module)
        resolved = _resolve_target_to_path_if_importable(args.target)
        if resolved is not None:
            return _run_passive_dir_mode(
                resolved,
                host=args.host,
                port=args.port,
                quiet=args.quiet,
                excludes=excludes,
                includes=includes,
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

        try:
            svc = RunnerService(cfg)
        except ValueError as e:
            # e.g. loader parse requiring package.module:function
            return _die(str(e))
        except SystemExit as e:
            return _die(
                "Target import exited early (SystemExit). This commonly happens when the target "
                "module calls argparse.parse_args() at import time.\n"
                "Fix: move argument parsing under `if __name__ == '__main__':` in the target module, "
                "or run passive scan mode instead (e.g. point plotsrv at a directory/package)."
            )
        except Exception as e:
            return _die(f"{type(e).__name__}: {e}")

        try:
            svc.run()
            return 0
        except KeyboardInterrupt:
            svc.stop()
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
