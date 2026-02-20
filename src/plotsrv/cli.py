# src/plotsrv/cli.py
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
import importlib.util
from typing import Any
import json
import os
import threading
from dataclasses import dataclass

from .publisher import publish_artifact
from .service import RunnerService, ServiceConfig
from .server import start_server, stop_server
from . import store
from .discovery import discover_views, DiscoveredView
from .file_kinds import coerce_file_to_publishable, infer_file_kind


@dataclass(frozen=True)
class WatchSpec:
    path: str
    label: str | None = None
    section: str | None = None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plotsrv", description="plotsrv - serve plots/tables easily"
    )
    # [plotsrv].[RUN]
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

    run_p.add_argument(
        "--watch",
        action="append",
        default=[],
        help=(
            "Watch a file and publish it as an artifact view. "
            "Repeatable. Example: --watch /var/log/app.log --watch ./data.json"
        ),
    )

    run_p.add_argument(
        "--watch-label",
        action="append",
        default=[],
        help=(
            "Label(s) for watched views. Repeat once per --watch in the same order. "
            "If omitted, defaults to the filename."
        ),
    )

    run_p.add_argument(
        "--watch-kind",
        choices=["auto", "text", "json"],
        default="auto",
        help="How to interpret watched files (default: auto; .json => json else text).",
    )
    run_p.add_argument(
        "--watch-every",
        type=float,
        default=1.0,
        help="Watch poll interval seconds (default: 1.0).",
    )
    run_p.add_argument(
        "--watch-max-bytes",
        type=int,
        default=200_000,
        help="Read at most N bytes from watched files (default: 200000).",
    )
    run_p.add_argument(
        "--watch-encoding",
        default="utf-8",
        help="Text encoding for watched files (default: utf-8).",
    )

    run_p.add_argument(
        "--watch-section",
        action="append",
        default=[],
        help=(
            "Section name(s) for watched views. "
            "If provided once, it applies to all --watch entries (backwards compatible). "
            "If repeated, provide once per --watch in the same order. "
            "If omitted, defaults to 'watch'."
        ),
    )

    run_p.add_argument(
        "--watch-update-limit-s",
        type=int,
        default=None,
        help="Server-side throttle window for watched publishes (default: none).",
    )
    run_p.add_argument(
        "--watch-force",
        action="store_true",
        help="Bypass server throttling for watched publishes.",
    )

    # [plotsrv].[WATCH]
    watch_p = sub.add_parser("watch", help="Watch a text/JSON file and publish it live")
    watch_p.add_argument("path", help="Path to a text/log/json file")
    watch_p.add_argument("--host", default="127.0.0.1")
    watch_p.add_argument("--port", type=int, default=8000)
    watch_p.add_argument(
        "--every", type=float, default=1.0, help="Poll interval seconds (default: 1.0)"
    )
    watch_p.add_argument(
        "--kind",
        choices=["auto", "text", "json"],
        default="auto",
        help="How to interpret the file",
    )
    watch_p.add_argument(
        "--section", default="watch", help="View section (default: watch)"
    )
    watch_p.add_argument("--label", default=None, help="View label (default: filename)")
    watch_p.add_argument(
        "--view-id", default=None, help="Explicit view_id (overrides section/label)"
    )
    watch_p.add_argument(
        "--max-bytes",
        type=int,
        default=200_000,
        help="Read at most N bytes (default: 200000)",
    )
    watch_p.add_argument(
        "--encoding", default="utf-8", help="Text encoding (default: utf-8)"
    )
    watch_p.add_argument(
        "--update-limit-s",
        type=int,
        default=None,
        help="Server-side throttle window seconds",
    )
    watch_p.add_argument(
        "--force", action="store_true", help="Bypass server throttling"
    )
    watch_p.add_argument(
        "--quiet", action="store_true", help="Reduce uvicorn logging noise"
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


def _coerce_watch_specs(
    paths: list[str],
    *,
    labels: list[str] | None,
    sections: list[str] | None,
) -> list[WatchSpec]:
    """
    Build per-watch specs in a backwards-compatible way.

    labels:
      - 0 => filename
      - N => per-watch labels
      - otherwise => error

    sections:
      - 0 => 'watch'
      - 1 => apply to all watches (backwards compatible)
      - N => per-watch sections
      - otherwise => error
    """
    paths = [p for p in (paths or []) if str(p).strip()]
    n = len(paths)

    lab_list = [x for x in (labels or []) if str(x).strip()]
    sec_list = [x for x in (sections or []) if str(x).strip()]

    if n == 0:
        return []

    # labels
    if len(lab_list) == 0:
        per_labels = [None] * n
    elif len(lab_list) == n:
        per_labels = lab_list
    else:
        raise ValueError(
            f"--watch-label must be provided either 0 times or exactly once per --watch "
            f"(expected {n}, got {len(lab_list)})."
        )

    # sections
    if len(sec_list) == 0:
        per_sections = ["watch"] * n
    elif len(sec_list) == 1:
        per_sections = [sec_list[0]] * n
    elif len(sec_list) == n:
        per_sections = sec_list
    else:
        raise ValueError(
            f"--watch-section must be provided either 0 times, 1 time (apply to all), "
            f"or exactly once per --watch (expected {n}, got {len(sec_list)})."
        )

    specs: list[WatchSpec] = []
    for raw_path, lab, sec in zip(paths, per_labels, per_sections, strict=True):
        specs.append(WatchSpec(path=raw_path, label=lab, section=sec))
    return specs


def _start_watch_threads(
    specs: list[WatchSpec],
    *,
    host: str,
    port: int,
    every: float,
    kind: str,  # auto|text|json
    max_bytes: int,
    encoding: str,
    update_limit_s: int | None,
    force: bool,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []

    for spec in specs:
        p = Path(spec.path).expanduser().resolve()
        section = (spec.section or "watch").strip() or "watch"
        label = (spec.label or p.name).strip() or p.name
        vid = store.normalize_view_id(None, section=section, label=label)

        # Pre-register so dropdown shows it immediately
        store.register_view(
            view_id=vid,
            section=section,
            label=label,
            kind="artifact",
            activate_if_first=False,
        )

        def _worker(
            pth: Path = p, view_label: str = label, view_section: str = section
        ) -> None:
            last_sig: tuple[int, int] | None = None  # (mtime_ns, size)
            while True:
                try:
                    st = pth.stat()
                    sig = (
                        int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                        int(st.st_size),
                    )
                except Exception:
                    sig = None

                if sig is not None and sig == last_sig:
                    time.sleep(max(0.05, float(every)))
                    continue
                last_sig = sig

                try:
                    raw = _read_tail_bytes(pth, max_bytes=max_bytes)
                except Exception as e:
                    publish_artifact(
                        f"[plotsrv watch] read error: {type(e).__name__}: {e}",
                        host=host,
                        port=port,
                        label=view_label,
                        section=view_section,
                        artifact_kind="text",
                        update_limit_s=update_limit_s,
                        force=force,
                    )
                    time.sleep(max(0.05, float(every)))
                    continue

                # Forced modes stay simple
                if kind == "text":
                    txt = raw.decode(encoding, errors="replace")
                    publish_artifact(
                        txt,
                        host=host,
                        port=port,
                        label=view_label,
                        section=view_section,
                        artifact_kind="text",
                        update_limit_s=update_limit_s,
                        force=force,
                    )
                    time.sleep(max(0.05, float(every)))
                    continue

                if kind == "json":
                    # Force JSON parse (regardless of suffix)
                    try:
                        txt = raw.decode(encoding, errors="replace")
                        obj = json.loads(txt)
                        publish_artifact(
                            obj,
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            artifact_kind="json",
                            update_limit_s=update_limit_s,
                            force=force,
                        )
                    except Exception as e:
                        txt = raw.decode(encoding, errors="replace")
                        publish_artifact(
                            f"[plotsrv watch] JSON parse error: {type(e).__name__}: {e}\n\n{txt}",
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            artifact_kind="text",
                            update_limit_s=update_limit_s,
                            force=force,
                        )
                    time.sleep(max(0.05, float(every)))
                    continue

                # Auto mode: infer/parse via shared coercer (NO re-read)
                try:
                    coerced = coerce_file_to_publishable(
                        pth,
                        encoding=encoding,
                        max_bytes=max_bytes,
                        raw=raw,
                    )

                    if coerced.publish_kind == "table":
                        publish_artifact(
                            coerced.obj,
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            artifact_kind=None,
                            update_limit_s=update_limit_s,
                            force=force,
                        )
                    else:
                        publish_artifact(
                            coerced.obj,
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            artifact_kind=coerced.artifact_kind or "text",
                            update_limit_s=update_limit_s,
                            force=force,
                        )

                except Exception as e:
                    txt = raw.decode(encoding, errors="replace")
                    publish_artifact(
                        f"[plotsrv watch] parse error: {type(e).__name__}: {e}\n\n{txt}",
                        host=host,
                        port=port,
                        label=view_label,
                        section=view_section,
                        artifact_kind="text",
                        update_limit_s=update_limit_s,
                        force=force,
                    )

                time.sleep(max(0.05, float(every)))

        t = threading.Thread(
            target=_worker, name=f"plotsrv-watch:{p.name}", daemon=True
        )
        t.start()
        threads.append(t)

    return threads


def _run_passive_dir_mode(
    target: str,
    *,
    host: str,
    port: int,
    quiet: bool,
    excludes: set[str],
    includes: set[str],
    watch_specs: list[WatchSpec] | None = None,
    watch_kind: str = "auto",
    watch_every: float = 1.0,
    watch_max_bytes: int = 200_000,
    watch_encoding: str = "utf-8",
    watch_update_limit_s: int | None = None,
    watch_force: bool = False,
) -> int:
    """
    Passive mode:
      - start viewer server
      - AST-scan directory for @plot/@table
      - register views into dropdown
      - wait forever until Ctrl+C or /shutdown
    """
    start_server(host=host, port=port, auto_on_show=False, quiet=quiet)

    if watch_specs:
        _start_watch_threads(
            watch_specs,
            host=host,
            port=port,
            every=watch_every,
            kind=watch_kind,
            max_bytes=watch_max_bytes,
            encoding=watch_encoding,
            update_limit_s=watch_update_limit_s,
            force=watch_force,
        )

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


def _infer_watch_artifact_kind(path: Path, watch_kind: str) -> str:
    """
    Returns "text" or "json" (artifact_kind) for watch publishing.

    watch_kind:
      - "text" => force text
      - "json" => force json (parse JSON)
      - "auto" => infer by suffix: .json/.ini/.cfg/.toml/.yaml/.yml => json, else text

    Note: YAML parsing not implemented yet, but we still classify it as json in "auto"
    and will fallback to text with a clear error until implemented.
    """
    if watch_kind in ("text", "json"):
        return watch_kind

    fk = infer_file_kind(path)
    if fk in ("json", "ini", "toml", "yaml"):
        return "json"
    return "text"


def _read_tail_bytes(p: Path, *, max_bytes: int) -> bytes:
    max_bytes = max(1, int(max_bytes))
    with p.open("rb") as f:
        try:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start, os.SEEK_SET)
        except Exception:
            f.seek(0)
        return f.read(max_bytes)


def _run_watch_mode(
    path: str,
    *,
    host: str,
    port: int,
    every: float,
    kind: str,
    section: str,
    label: str | None,
    view_id: str | None,
    max_bytes: int,
    encoding: str,
    update_limit_s: int | None,
    force: bool,
    quiet: bool,
) -> int:
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        return _die(f"watch: file not found: {p}")

    start_server(host=host, port=port, auto_on_show=False, quiet=quiet)

    # view identity
    view_label = label or p.name
    vid = store.normalize_view_id(view_id, section=section, label=view_label)
    store.register_view(
        view_id=vid,
        section=section,
        label=view_label,
        kind="artifact",
        activate_if_first=False,
    )
    store.set_active_view(vid)

    store.set_service_info(service_mode=True, target=f"watch:{p}", refresh_rate_s=None)

    last_sig: tuple[int, int] | None = None  # (mtime_ns, size)

    try:
        while True:
            try:
                st = p.stat()
                sig = (
                    int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                    int(st.st_size),
                )
            except Exception:
                sig = None

            if sig is not None and sig == last_sig:
                time.sleep(max(0.05, float(every)))
                continue
            last_sig = sig

            raw = _read_tail_bytes(p, max_bytes=max_bytes)

            if kind == "text":
                txt = raw.decode(encoding, errors="replace")
                publish_artifact(
                    txt,
                    host=host,
                    port=port,
                    label=view_label,
                    section=section,
                    artifact_kind="text",
                    update_limit_s=update_limit_s,
                    force=force,
                )
                time.sleep(max(0.05, float(every)))
                continue

            if kind == "json":
                try:
                    txt = raw.decode(encoding, errors="replace")
                    obj = json.loads(txt)
                    publish_artifact(
                        obj,
                        host=host,
                        port=port,
                        label=view_label,
                        section=section,
                        artifact_kind="json",
                        update_limit_s=update_limit_s,
                        force=force,
                    )
                except Exception as e:
                    txt = raw.decode(encoding, errors="replace")
                    publish_artifact(
                        f"[plotsrv watch] JSON parse error: {type(e).__name__}: {e}\n\n{txt}",
                        host=host,
                        port=port,
                        label=view_label,
                        section=section,
                        artifact_kind="text",
                        update_limit_s=update_limit_s,
                        force=force,
                    )
                time.sleep(max(0.05, float(every)))
                continue

            # Auto mode: infer/parse via shared coercer (NO re-read)
            try:
                coerced = coerce_file_to_publishable(
                    p,
                    encoding=encoding,
                    max_bytes=max_bytes,
                    raw=raw,
                )
                if coerced.publish_kind == "table":
                    publish_artifact(
                        coerced.obj,
                        host=host,
                        port=port,
                        label=view_label,
                        section=section,
                        artifact_kind=None,
                        update_limit_s=update_limit_s,
                        force=force,
                    )
                else:
                    publish_artifact(
                        coerced.obj,
                        host=host,
                        port=port,
                        label=view_label,
                        section=section,
                        artifact_kind=coerced.artifact_kind or "text",
                        update_limit_s=update_limit_s,
                        force=force,
                    )
            except Exception as e:
                txt = raw.decode(encoding, errors="replace")
                publish_artifact(
                    f"[plotsrv watch] parse error: {type(e).__name__}: {e}\n\n{txt}",
                    host=host,
                    port=port,
                    label=view_label,
                    section=section,
                    artifact_kind="text",
                    update_limit_s=update_limit_s,
                    force=force,
                )

            time.sleep(max(0.05, float(every)))

    except KeyboardInterrupt:
        stop_server(join=False)
        store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)
        return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "run":
        excludes = _norm_tokens(getattr(args, "exclude", []))
        includes = _norm_tokens(getattr(args, "include", []))

        watch_paths = [w for w in (getattr(args, "watch", []) or []) if str(w).strip()]
        watch_kind = getattr(args, "watch_kind", "auto")
        watch_every = float(getattr(args, "watch_every", 1.0))
        watch_max_bytes = int(getattr(args, "watch_max_bytes", 200_000))
        watch_encoding = str(getattr(args, "watch_encoding", "utf-8"))
        watch_update_limit_s = getattr(args, "watch_update_limit_s", None)
        watch_force = bool(getattr(args, "watch_force", False))

        try:
            watch_specs = _coerce_watch_specs(
                watch_paths,
                labels=getattr(args, "watch_label", []) or [],
                sections=getattr(args, "watch_section", []) or [],
            )
        except ValueError as e:
            return _die(str(e))

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
                watch_specs=watch_specs,
                watch_kind=watch_kind,
                watch_every=watch_every,
                watch_max_bytes=watch_max_bytes,
                watch_encoding=watch_encoding,
                watch_update_limit_s=watch_update_limit_s,
                watch_force=watch_force,
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
                watch_specs=watch_specs,
                watch_kind=watch_kind,
                watch_every=watch_every,
                watch_max_bytes=watch_max_bytes,
                watch_encoding=watch_encoding,
                watch_update_limit_s=watch_update_limit_s,
                watch_force=watch_force,
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

        if watch_specs:
            _start_watch_threads(
                watch_specs,
                host=args.host,
                port=args.port,
                every=watch_every,
                kind=watch_kind,
                max_bytes=watch_max_bytes,
                encoding=watch_encoding,
                update_limit_s=watch_update_limit_s,
                force=watch_force,
            )

        try:
            svc.run()
            return 0
        except KeyboardInterrupt:
            svc.stop()
            return 0

    if args.cmd == "watch":
        return _run_watch_mode(
            args.path,
            host=args.host,
            port=args.port,
            every=args.every,
            kind=args.kind,
            section=args.section,
            label=args.label,
            view_id=args.view_id,
            max_bytes=args.max_bytes,
            encoding=args.encoding,
            update_limit_s=args.update_limit_s,
            force=args.force,
            quiet=args.quiet,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
