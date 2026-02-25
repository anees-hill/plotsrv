# src/plotsrv/cli.py
from __future__ import annotations

import argparse
import importlib.util
import urllib.request
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import config, store
from .discovery import DiscoveredView, discover_views
from .file_kinds import coerce_file_to_publishable, infer_file_kind
from .publisher import publish_artifact

WatchReadMode = Literal["head", "tail"]
RunMode = Literal["passive", "callable"]


@dataclass(frozen=True)
class WatchSpec:
    path: str
    label: str | None = None
    section: str | None = None
    read_mode: WatchReadMode | None = None


class _WatchPathAction(argparse.Action):
    """
    --watch <path>

    Appends a watch path AND ensures watch_read_mode stays aligned by
    appending a placeholder None for this watch.
    Also consumes any pending read mode set by --watch-head/--watch-tail
    that appeared before this --watch.
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | list[str] | None,
        option_string: str | None = None,
    ) -> None:
        path = values if isinstance(values, str) else str(values[0])

        watches: list[str] = getattr(namespace, "watch", None) or []
        modes: list[str | None] = getattr(namespace, "watch_read_mode", None) or []
        pending: str | None = getattr(namespace, "_watch_pending_read_mode", None)

        watches.append(path)

        # default placeholder for this watch
        modes.append(None)

        # if a --watch-head/--watch-tail occurred BEFORE this --watch, bind it now
        if pending is not None:
            modes[-1] = pending
            setattr(namespace, "_watch_pending_read_mode", None)

        setattr(namespace, "watch", watches)
        setattr(namespace, "watch_read_mode", modes)


class _WatchReadModeAction(argparse.Action):
    """
    --watch-head / --watch-tail

    If the most recent watch has no mode yet, set it.
    Otherwise store as "pending" to apply to the NEXT --watch.
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        mode: str = str(self.const)

        modes: list[str | None] = getattr(namespace, "watch_read_mode", None) or []

        # If there's at least one watch and the last one hasn't been assigned, assign it.
        if modes and modes[-1] is None:
            modes[-1] = mode
            setattr(namespace, "watch_read_mode", modes)
            return

        # Otherwise: apply to the *next* --watch
        setattr(namespace, "_watch_pending_read_mode", mode)
        setattr(namespace, "watch_read_mode", modes)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plotsrv", description="plotsrv - serve plots/tables easily"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser(
        "run", help="Serve a codebase (passive) or run a target (callable)"
    )

    # target is now OPTIONAL
    run_p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Import path or path to scan. Examples: pkg, pkg.mod, pkg.mod:fn, ./src, ./script.py. If omitted, uses project root detection.",
    )

    run_p.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)"
    )
    run_p.add_argument(
        "--port", type=int, default=8000, help="Port to bind (default: 8000)"
    )
    run_p.add_argument(
        "--quiet", action="store_true", help="Reduce uvicorn logging noise"
    )

    # New mode flag
    run_p.add_argument(
        "--mode",
        choices=["passive", "callable"],
        default="passive",
        help="Run mode. passive (default) scans and serves; callable also executes the target in a subprocess.",
    )

    # New callable scheduler
    run_p.add_argument(
        "--call-every",
        type=float,
        default=None,
        help="Callable mode only: run the target every N seconds. If omitted, run once.",
    )

    # Optional: run once but keep server up (callable mode)
    run_p.add_argument(
        "--keep-alive",
        action="store_true",
        help="Callable mode only: keep server running after the first run until Ctrl+C (or /shutdown).",
    )

    # Filtering for passive discovery (still useful in both modes)
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
            "Repeatable and/or comma-separated."
        ),
    )

    # Watches (unchanged)
    run_p.add_argument(
        "--watch",
        action=_WatchPathAction,
        default=[],
        help=("Watch a file and publish it as an artifact view. Repeatable."),
    )
    run_p.add_argument(
        "--watch-label",
        action="append",
        default=[],
        help=("Label(s) for watched views. Repeat once per --watch in the same order."),
    )
    run_p.add_argument(
        "--watch-kind",
        choices=["auto", "text", "json"],
        default="auto",
        help="How to interpret watched files (default: auto).",
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
        help="Read at most N bytes (default: 200000).",
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
            "If provided once, applies to all watches. If repeated, once per --watch. If omitted, defaults to 'watch'."
        ),
    )
    run_p.add_argument(
        "--watch-update-limit-s",
        type=int,
        default=None,
        help="Server-side throttle window for watched publishes.",
    )
    run_p.add_argument(
        "--watch-force",
        action="store_true",
        help="Bypass server throttling for watched publishes.",
    )
    run_p.add_argument(
        "--watch-head",
        action=_WatchReadModeAction,
        nargs=0,
        const="head",
        dest="watch_read_mode",
        help="Read watched file from the start (head). Binds to most recent --watch if present; else next --watch.",
    )
    run_p.add_argument(
        "--watch-tail",
        action=_WatchReadModeAction,
        nargs=0,
        const="tail",
        dest="watch_read_mode",
        help="Read watched file from the end (tail). Binds to most recent --watch if present; else next --watch.",
    )

    # Dedicated watch subcommand (unchanged)
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
    mx = watch_p.add_mutually_exclusive_group()
    mx.add_argument(
        "--head", action="store_true", help="Read file from the start (head)."
    )
    mx.add_argument(
        "--tail", action="store_true", help="Read file from the end (tail)."
    )

    return p


def _die(msg: str) -> int:
    print(f"plotsrv: error: {msg}", file=sys.stderr)
    return 2


def _norm_tokens(raw: list[str]) -> set[str]:
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
    sec = (dv.section or "default").strip() or "default"
    lab = (dv.label or "default").strip() or "default"
    return f"{sec}:{lab}"


def _is_included(dv: DiscoveredView, includes: set[str]) -> bool:
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
    return (lab in excludes) or (sec in excludes) or (vid in excludes)


def _resolve_target_to_path_if_importable(target: str) -> str | None:
    """
    If target is importable as a module/package (and not module:function),
    return filesystem path for passive scanning.
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


def _resolve_module_part(target: str) -> str:
    """
    For "pkg.mod:fn" return "pkg.mod".
    For others return as-is.
    """
    if ":" in target:
        return target.split(":", 1)[0].strip()
    return target.strip()


def _find_project_root(start: Path) -> Path | None:
    """
    Walk upwards looking for something that indicates a Python project.
    """
    cur = start.resolve()
    for _ in range(30):
        if (cur / "pyproject.toml").is_file():
            return cur
        if (cur / "setup.cfg").is_file() or (cur / "setup.py").is_file():
            return cur
        if (cur / ".git").exists():
            return cur
        if (cur / "src").is_dir() and any((cur / "src").rglob("*.py")):
            return cur

        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def _wait_for_server(host: str, port: int, *, timeout_s: float = 5.0) -> bool:
    """
    Wait until the plotsrv server is accepting HTTP connections.
    Returns True if ready, else False.
    """
    deadline = time.time() + float(timeout_s)
    url = f"http://{host}:{port}/status"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _default_run_target() -> str:
    """
    If user runs `plotsrv run` with no target, use a safe project root.
    """
    root = _find_project_root(Path.cwd())
    if root is None:
        raise ValueError(
            "No target provided and no Python project detected in current directory or parents. "
            "Run from a project directory (pyproject.toml/setup.cfg/.git), or pass an explicit target/path."
        )
    return str(root)


def _coerce_watch_specs(
    paths: list[str],
    *,
    labels: list[str] | None,
    sections: list[str] | None,
    read_modes: list[str] | None,
) -> list[WatchSpec]:
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

    rm_list = list(read_modes or [])

    if len(rm_list) == 0:
        per_modes: list[WatchReadMode | None] = [None] * n
    elif len(rm_list) < n:
        per_modes = [(m if m in ("head", "tail") else None) for m in rm_list]  # type: ignore[assignment]
        per_modes = per_modes + [None] * (n - len(per_modes))
    elif len(rm_list) == n:
        bad = [m for m in rm_list if m not in ("head", "tail", None)]
        if bad:
            raise ValueError(
                f"Invalid watch read mode(s): {bad}. Expected 'head' or 'tail'."
            )
        per_modes = [m for m in rm_list]  # type: ignore[assignment]
    else:
        raise ValueError(
            f"--watch-head/--watch-tail provided too many times (expected at most {n}, got {len(rm_list)})."
        )

    specs: list[WatchSpec] = []
    for raw_path, lab, sec, rm in zip(
        paths, per_labels, per_sections, per_modes, strict=True
    ):
        specs.append(WatchSpec(path=raw_path, label=lab, section=sec, read_mode=rm))
    return specs


def _default_watch_read_mode(path: Path) -> WatchReadMode:
    fk = infer_file_kind(path)
    return "head" if fk == "csv" else "tail"


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


def _read_head_bytes(p: Path, *, max_bytes: int) -> bytes:
    max_bytes = max(1, int(max_bytes))
    with p.open("rb") as f:
        return f.read(max_bytes)


def _read_csv_tail_with_header_bytes(p: Path, *, max_bytes: int) -> bytes:
    max_bytes = max(1, int(max_bytes))

    header = b""
    with p.open("rb") as f:
        chunk = f.read(min(64_000, max_bytes))
        nl = chunk.find(b"\n")
        header = chunk if nl == -1 else chunk[: nl + 1]

    tail = _read_tail_bytes(p, max_bytes=max_bytes)

    if tail.startswith(header) or tail == header:
        return tail

    if header and not header.endswith(b"\n"):
        header = header + b"\n"

    return header + tail


def _start_watch_threads(
    specs: list[WatchSpec],
    *,
    host: str,
    port: int,
    every: float,
    kind: str,
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

        fk = infer_file_kind(p)
        read_mode: WatchReadMode = spec.read_mode or _default_watch_read_mode(p)
        preregister_kind = "table" if fk == "csv" else "artifact"

        store.register_view(
            view_id=vid,
            section=section,
            label=label,
            kind=preregister_kind,
            activate_if_first=False,
        )

        def _worker(
            pth: Path = p, view_label: str = label, view_section: str = section
        ) -> None:
            last_sig: tuple[int, int] | None = None
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

                try:
                    fk2 = infer_file_kind(pth)
                    if fk2 == "csv" and read_mode == "tail":
                        raw = _read_csv_tail_with_header_bytes(pth, max_bytes=max_bytes)
                    elif read_mode == "head":
                        raw = _read_head_bytes(pth, max_bytes=max_bytes)
                    else:
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

                last_sig = sig

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
                        max_rows=config.get_max_table_rows_rich(),
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


def _passive_register_views(
    scan_root: str,
    *,
    excludes: set[str],
    includes: set[str],
) -> None:
    """
    AST discovery + view registration only. Does NOT start server. Does NOT loop.
    """
    discovered_all = discover_views(scan_root)
    discovered = [
        dv
        for dv in discovered_all
        if _is_included(dv, includes) and not _is_excluded(dv, excludes)
    ]

    if len(discovered) == 0:
        store.register_view(
            view_id="default", section="default", label="default", kind="none"
        )
        store.set_active_view("default")
        return

    for dv in discovered:
        store.register_view(
            section=dv.section,
            label=dv.label,
            kind="none",
            activate_if_first=False,
        )

    first = discovered[0]
    first_id = store.normalize_view_id(None, section=first.section, label=first.label)
    store.set_active_view(first_id)


def _resolve_scan_root_for_passive(target: str) -> str:
    """
    Determine a filesystem root to scan for passive mode, even if target includes ':fn'.
    """
    # If user passed module:function, scan the module part
    mod_or_path = _resolve_module_part(target)

    p = Path(mod_or_path)
    if p.exists():
        return str(p.resolve())

    resolved = _resolve_target_to_path_if_importable(mod_or_path)
    if resolved is not None:
        return resolved

    # If it's neither a path nor importable, still allow scanning current directory
    # but keep this conservative: default to "." and let project-root safeguards handle it
    return (
        str(Path(mod_or_path).resolve())
        if Path(mod_or_path).exists()
        else str(Path.cwd().resolve())
    )


def _run_subprocess_as_main(target: str) -> subprocess.Popen[bytes]:
    """
    Run a module/package/file as __main__:
      - module/package: python -m <target>
      - file path: python <file.py>
    """
    p = Path(target)
    if p.exists() and p.is_file():
        cmd = [sys.executable, str(p)]
        return subprocess.Popen(cmd)

    # Otherwise treat as module/package
    cmd = [sys.executable, "-m", target]
    return subprocess.Popen(cmd)


def _run_subprocess_call_importpath(
    target: str,
    *,
    host: str,
    port: int,
) -> subprocess.Popen[bytes]:
    """
    Run module:function in a subprocess, call it, publish its return to plotsrv.

    - If function raises, publish_traceback to the same view label/section.
    """
    # Tiny runner script executed in subprocess.
    # Note: it publishes over HTTP to the parent server.
    code = r"""
import sys
from plotsrv.loader import load_object
from plotsrv.decorators import get_plotsrv_spec
from plotsrv.publisher import publish_view, publish_artifact
from plotsrv.tracebacks import publish_traceback

target = sys.argv[1]
host = sys.argv[2]
port = int(sys.argv[3])

obj = load_object(target)

spec = get_plotsrv_spec(obj)
label = (spec.label if spec else None) or (getattr(obj, "__name__", None) or "callable")
section = (spec.section if spec else None)

try:
    out = obj()
except Exception as e:
    # publish traceback and exit nonzero
    try:
        publish_traceback(
            e,
            label=label,
            section=section,
            host=host,
            port=port,
        )
    except Exception:
        pass
    raise

# Decide how to publish the return value
kind = (spec.kind if spec else None)

if kind in ("plot", "table"):
    publish_view(out, kind=kind, label=label, section=section, host=host, port=port)
else:
    # artifact (or unknown): let publisher infer unless user forced kind in spec
    publish_artifact(out, label=label, section=section, host=host, port=port, artifact_kind=None)
""".strip()

    cmd = [
        sys.executable,
        "-c",
        code,
        target,
        host,
        str(int(port)),
    ]
    return subprocess.Popen(cmd)


def _callable_loop(
    *,
    target: str,
    host: str,
    port: int,
    call_every: float | None,
    keep_alive: bool,
    stop_event: threading.Event,
) -> None:
    """
    Run the target in a subprocess once or periodically.
    """
    # Service info (shows in statusline)
    store.set_service_info(
        service_mode=True,
        target=f"callable:{target}",
        refresh_rate_s=(int(call_every) if call_every else None),
    )

    proc: subprocess.Popen[bytes] | None = None

    def _terminate_proc() -> None:
        nonlocal proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
        except Exception:
            pass
        finally:
            proc = None

    # Allow /shutdown to stop the loop + kill current child
    def _stop_hook() -> None:
        stop_event.set()
        _terminate_proc()

    store.set_service_stop_hook(_stop_hook)

    def _spawn_once() -> None:
        nonlocal proc

        # If a previous process is still running, don't overlap.
        if proc is not None and proc.poll() is None:
            return

        if ":" in target:
            proc = _run_subprocess_call_importpath(target, host=host, port=port)
        else:
            proc = _run_subprocess_as_main(target)

    # Always do an initial run
    _spawn_once()

    # If no schedule: either exit, or keep-alive
    if call_every is None:
        # Wait for completion (briefly) then either keep alive or exit.
        while not stop_event.is_set():
            if proc is None:
                break
            if proc.poll() is not None:
                break
            stop_event.wait(timeout=0.2)

        if keep_alive:
            while not stop_event.is_set():
                stop_event.wait(timeout=0.2)

        _terminate_proc()
        store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)
        return

    # Periodic schedule: re-run every N seconds (no overlap).
    interval = max(0.25, float(call_every))
    next_run = time.time()

    while not stop_event.is_set():
        now = time.time()
        if now >= next_run:
            _spawn_once()
            next_run = now + interval
        stop_event.wait(timeout=0.2)

    _terminate_proc()
    store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)


def _run_passive_server_forever(
    scan_root: str,
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
      - start server
      - AST scan -> register views
      - optional file watches
      - wait forever until Ctrl+C or /shutdown
    """
    from .server import start_server, stop_server

    start_server(host=host, port=port, auto_on_show=False, quiet=quiet)

    _wait_for_server(host, port, timeout_s=5.0)

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

    _passive_register_views(scan_root, excludes=excludes, includes=includes)

    store.set_service_info(
        service_mode=True, target=f"passive:{scan_root}", refresh_rate_s=None
    )

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_server(join=False)
        store.set_service_info(service_mode=False, target=None, refresh_rate_s=None)
        return 0


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
    read_mode: WatchReadMode | None,
) -> int:
    from .server import start_server, stop_server

    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        return _die(f"watch: file not found: {p}")

    start_server(host=host, port=port, auto_on_show=False, quiet=quiet)

    mode: WatchReadMode = read_mode or _default_watch_read_mode(p)

    view_label = label or p.name
    vid = store.normalize_view_id(view_id, section=section, label=view_label)
    fk = infer_file_kind(p)
    preregister_kind = "table" if fk == "csv" else "artifact"

    store.register_view(
        view_id=vid,
        section=section,
        label=view_label,
        kind=preregister_kind,
        activate_if_first=False,
    )
    store.set_active_view(vid)

    store.set_service_info(service_mode=True, target=f"watch:{p}", refresh_rate_s=None)

    last_sig: tuple[int, int] | None = None

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

            fk2 = infer_file_kind(p)
            if fk2 == "csv" and mode == "tail":
                raw = _read_csv_tail_with_header_bytes(p, max_bytes=max_bytes)
            elif mode == "head":
                raw = _read_head_bytes(p, max_bytes=max_bytes)
            else:
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

            try:
                coerced = coerce_file_to_publishable(
                    p,
                    encoding=encoding,
                    max_bytes=max_bytes,
                    max_rows=config.get_max_table_rows_rich(),
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

    if args.cmd == "watch":
        read_mode = "head" if args.head else ("tail" if args.tail else None)
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
            read_mode=read_mode,
        )

    if args.cmd != "run":
        return 0

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
            read_modes=getattr(args, "watch_read_mode", []) or [],
        )
    except ValueError as e:
        return _die(str(e))

    # Target defaulting
    target = args.target
    if target is None:
        try:
            target = _default_run_target()
        except ValueError as e:
            return _die(str(e))

    mode: RunMode = str(getattr(args, "mode", "passive"))

    # In ALL modes, we do passive registration first. We just decide what scan root is.
    scan_root = _resolve_scan_root_for_passive(target)

    if mode == "passive":
        return _run_passive_server_forever(
            scan_root,
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

    # mode == "callable"
    from .server import start_server, stop_server

    # Start server first
    start_server(host=args.host, port=args.port, auto_on_show=False, quiet=args.quiet)

    _wait_for_server(args.host, args.port, timeout_s=5.0)

    # Watches
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

    # Passive register (pre-populate dropdown)
    _passive_register_views(scan_root, excludes=excludes, includes=includes)

    stop_event = threading.Event()
    call_every = getattr(args, "call_every", None)
    keep_alive = bool(getattr(args, "keep_alive", False))

    try:
        _callable_loop(
            target=target,
            host=args.host,
            port=args.port,
            call_every=call_every,
            keep_alive=keep_alive,
            stop_event=stop_event,
        )
        return 0
    except KeyboardInterrupt:
        stop_event.set()
        stop_server(join=False)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
