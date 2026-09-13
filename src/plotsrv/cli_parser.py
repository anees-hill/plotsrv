from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Literal

WatchReadMode = Literal["head", "tail"]
WatchMaterializationOverride = Literal["auto", "memory", "file"]


@dataclass(frozen=True)
class WatchSpec:
    path: str
    label: str | None = None
    section: str | None = None
    read_mode: WatchReadMode | None = None
    materialization: WatchMaterializationOverride | None = None
    view_id: str | None = None


class _ExplicitValueAction(argparse.Action):
    """Keep legacy defaults while exposing whether a bind option was supplied."""
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        setattr(namespace, self.dest + "_supplied", True)


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
            namespace._watch_pending_read_mode = None

        namespace.watch = watches
        namespace.watch_read_mode = modes


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
            namespace.watch_read_mode = modes
            return

        # Otherwise: apply to the *next* --watch
        namespace._watch_pending_read_mode = mode
        namespace.watch_read_mode = modes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plotsrv",
        description=(
            "plotsrv - inspect data, files, and live outputs in your browser\n\n"
            "Documentation: https://docs.plotsrv.com"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('plotsrv')}",
    )
    sub = p.add_subparsers(dest="cmd")

    serve_p = sub.add_parser("serve", help="Serve publisher data without discovering or executing application code")
    serve_p.add_argument("--host", default=None, help="Bind host (server config, otherwise 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=None, help="Bind port (server config, otherwise 8000)")
    serve_p.add_argument("--config", default=None, help="Server configuration file")
    serve_p.add_argument("--name", default=None, help="Configuration instance name")
    serve_p.add_argument("--quiet", action="store_true", help="Reduce server logging")

    run_p = sub.add_parser(
        "run",
        help="Discover and serve views from a project; optionally execute targets",
    )

    run_p.set_defaults(host_supplied=False, port_supplied=False)

    # target is now OPTIONAL
    run_p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Import path or path to scan. Examples: pkg, pkg.mod, pkg.mod:fn, ./src, ./script.py. If omitted, uses configured discovery target, then project root detection.",
    )

    run_p.add_argument(
        "--host", action=_ExplicitValueAction, default="127.0.0.1", help="Host to bind (default: 127.0.0.1)"
    )
    run_p.add_argument(
        "--port", action=_ExplicitValueAction, type=int, default=8000, help="Port to bind (default: 8000)"
    )
    run_p.add_argument(
        "--quiet", action="store_true", help="Reduce server logs and suppress discovery progress"
    )
    run_p.add_argument(
        "--name",
        default=None,
        help="Optional instance name used to select per-instance settings from plotsrv.yml",
    )
    run_p.add_argument(
        "--config",
        default=None,
        help="Path to plotsrv.yml (or plotsrv.yaml). If omitted, uses ./plotsrv.yml or env PLOTSRV_CONFIG.",
    )
    run_p.add_argument(
        "--truncate",
        default=None,
        help="Override render limit for text/html/markdown views. Examples: 1000000 or 'off'.",
    )
    run_p.add_argument(
        "--no-truncate",
        action="store_true",
        help="Disable render truncation for text/html/markdown views.",
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

    run_p.add_argument("--scan-all", action="store_true", default=None,
                       help="Include normally pruned cache/environment/vendor directories in discovery")
    # Watches: an explicitly empty set is independent of target overrides.
    watch_group = run_p.add_mutually_exclusive_group()
    watch_group.add_argument("--no-watch", action="store_true", help="Disable configured watches for this run")
    watch_group.add_argument(
        "--watch",
        action=_WatchPathAction,
        default=[],
        help=("Watch a file and publish it as a live view. Repeatable; replaces configured watches."),
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
        "--watch-max-mb",
        default=None,
        help=(
            "Read at most N MB from each watched file. "
            "Use 'off' to read whole files. "
            "Preferred over --watch-max-bytes. "
            "Default comes from limits.watched_files.max_mb."
        ),
    )
    run_p.add_argument(
        "--watch-max-bytes",
        default=None,
        help=(
            "Legacy/advanced watched-file read limit in bytes. "
            "Use 'off' to read whole files. "
            "Prefer --watch-max-mb for ordinary use."
        ),
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
        "--watch-materialization",
        "--watch-materialisation",
        choices=["auto", "memory", "file"],
        default=None,
        help=(
            "Override watched-file materialization for all --watch files. "
            "auto uses config threshold; memory publishes contents; file reads previews on demand."
        ),
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

    # Dedicated watch subcommand
    publish_p = sub.add_parser("publish", help="Register a catalogue and publish configured watches to an existing server")
    publish_p.add_argument("target", nargs="?", default=None, help="Optional static discovery target; otherwise configured target")
    publish_p.add_argument("--config", default=None)
    publish_p.add_argument("--name", default=None)
    publish_p.add_argument("--destination", default=None, help="Existing server URL; never launches a server")
    publish_p.add_argument("--bearer-token-env", default=None, help="Credential environment variable for explicit destination")
    publish_p.add_argument("--no-discovery", action="store_true")
    publish_p.add_argument("--no-watch", action="store_true")
    publish_p.add_argument("--add-id", action="append", default=[], help="Reviewed dynamic ID; repeat for a complete multi-project union")
    publish_p.add_argument("--reviewed", action="store_true", help="Acknowledge unresolved discovery issues after review")
    publish_p.add_argument("--seal-catalogue", action="store_true", help="Explicitly initialise/seal the complete catalogue union")
    publish_p.add_argument("--every", type=float, default=1.0, help="Watch poll/debounce interval (at least 0.1s)")
    publish_p.add_argument("--quiet", action="store_true")

    watch_p = sub.add_parser(
        "watch", help="Watch a file or directory and publish live updates as views"
    )
    watch_p.add_argument(
        "path", help="File or directory to watch (directory discovery runs once)"
    )
    watch_p.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Directory subfolder depth, 0 = root only (default: 2; maximum: 16)",
    )
    watch_p.add_argument(
        "--max-views",
        type=int,
        default=None,
        help="Directory view limit (default: 32; maximum: 64); overflow stops startup",
    )
    watch_p.add_argument(
        "--include",
        action="append",
        default=None,
        metavar="GLOB",
        help="Directory filename or relative-path pattern; repeat to match any (quote globs)",
    )
    watch_p.add_argument("--config", default=None)
    watch_p.add_argument("--name", default=None)
    watch_p.add_argument(
        "--destination",
        default=None,
        help="Publish to this existing server; file remains local to this process",
    )
    watch_p.add_argument(
        "--bearer-token-env",
        default=None,
        help="Credential environment variable for explicit destination",
    )
    watch_p.set_defaults(host_supplied=False, port_supplied=False)
    watch_p.add_argument("--host", action=_ExplicitValueAction, default="127.0.0.1")
    watch_p.add_argument("--port", action=_ExplicitValueAction, type=int, default=8000)
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
        "--section",
        action=_ExplicitValueAction,
        default="watch",
        help="File section (default: watch); directory section prefix",
    )
    watch_p.add_argument("--label", default=None, help="View label (default: filename)")
    watch_p.add_argument(
        "--view-id", default=None, help="Explicit view_id (overrides section/label)"
    )
    watch_p.add_argument(
        "--max-mb",
        "--watch-max-mb",
        dest="max_mb",
        default=None,
        help=(
            "Read at most N MB from the watched file. "
            "Use 'off' to read the whole file. "
            "Preferred over --max-bytes / --watch-max-bytes. "
            "Default comes from limits.watched_files.max_mb."
        ),
    )

    watch_p.add_argument(
        "--max-bytes",
        "--watch-max-bytes",
        dest="max_bytes",
        default=None,
        help=(
            "Legacy/advanced watched-file read limit in bytes. "
            "Use 'off' to read the whole file. "
            "Prefer --max-mb / --watch-max-mb for ordinary use."
        ),
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
        "--materialization",
        "--materialisation",
        choices=["auto", "memory", "file"],
        default=None,
        help=(
            "Override watched-file materialization. "
            "auto uses config threshold; memory publishes contents; file reads previews on demand."
        ),
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

    store_p = sub.add_parser(
        "store", help="Inspect or clear persisted plotsrv views, snapshots, and streams"
    )
    store_p.add_argument(
        "--name",
        default=None,
        help="Optional instance name used to select per-instance settings from plotsrv.yml",
    )
    store_p.add_argument(
        "--config",
        default=None,
        help="Path to plotsrv.yml (or plotsrv.yaml). If omitted, uses ./plotsrv.yml or env PLOTSRV_CONFIG.",
    )

    store_sub = store_p.add_subparsers(dest="store_cmd", required=True)

    store_sub.add_parser("stats", help="Show storage statistics")

    store_list_p = store_sub.add_parser(
        "list", help="List stored latest views, snapshots, and stream sessions"
    )
    store_list_p.add_argument(
        "--view",
        default=None,
        help="View id to inspect. If omitted, lists stored views.",
    )

    store_clear_p = store_sub.add_parser(
        "clear", help="Delete stored latest state, snapshots, and stream history"
    )
    store_clear_p.add_argument(
        "--view",
        default=None,
        help="Delete stored latest state, snapshots, and stream history for one view id.",
    )
    store_clear_p.add_argument(
        "--all",
        action="store_true",
        help="Delete all stored latest state, snapshots, and stream history.",
    )
    store_clear_p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    config_p = sub.add_parser(
        "config",
        help="Open the configuration wizard, create configs or populate view settings",
    )
    config_sub = config_p.add_subparsers(dest="config_cmd", required=True)

    config_init_p = config_sub.add_parser(
        "init", help="Keyboard configuration wizard with reviewed, backed-up saving"
    )
    config_init_p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Optional package or path to focus discovery",
    )
    config_init_p.add_argument(
        "--config",
        default=None,
        help="Existing config or draft path; otherwise detected plotsrv.yml/plotsrv.yaml",
    )
    config_init_p.add_argument(
        "--name", default=None, help="Configuration instance to edit"
    )

    config_ui_p = config_sub.add_parser(
        "ui", help="Temporary browser editor for server UI settings"
    )
    config_ui_p.add_argument(
        "--config",
        default=None,
        help="Server config to edit (default: detected config or plotsrv.yml)",
    )
    config_ui_p.add_argument(
        "--name", default=None, help="Configuration instance to edit"
    )
    config_ui_p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1; use 0.0.0.0 for remote access)",
    )
    config_ui_p.add_argument(
        "--port",
        type=int,
        default=8766,
        help="Temporary editor port (default: 8766; 0 chooses a free port)",
    )
    config_ui_p.add_argument(
        "--assets-dir",
        default="plotsrv-assets",
        help="Approved image directory inside the config folder; created only on save",
    )
    config_ui_p.add_argument(
        "--origin",
        default=None,
        help="Optional exact browser-origin restriction, e.g. https://plots.example.org",
    )
    config_ui_p.add_argument(
        "--no-open",
        action="store_true",
        help="Print connection instructions without opening a browser",
    )

    config_create_p = config_sub.add_parser(
        "create",
        help="Create a starter plotsrv.yml config file",
    )
    config_create_p.add_argument(
        "--config",
        default="plotsrv.yml",
        help="Path to config file to create (default: plotsrv.yml)",
    )
    config_create_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the config file if it already exists",
    )
    config_create_p.add_argument(
        "--expanded",
        action="store_true",
        help="Include less-common storage queue and rendering settings",
    )
    config_populate_p = config_sub.add_parser(
        "populate",
        help="Populate config sections from discovered @view functions",
    )
    populate_sub = config_populate_p.add_subparsers(
        dest="populate_cmd",
        required=True,
    )

    freshness_p = populate_sub.add_parser(
        "freshness",
        help="Populate freshness-settings.views",
    )
    freshness_p.add_argument("target", help="Path/module target to discover")
    freshness_p.add_argument("--config", default="plotsrv.yml")
    freshness_p.add_argument("--mode", choices=["merge", "replace"], default="merge")
    freshness_p.add_argument("--yes", action="store_true", help="Do not prompt")
    freshness_p.add_argument("--expected-every", default="60s")
    freshness_p.add_argument("--warn-after", default="90s")
    freshness_p.add_argument("--overdue-after", default="180s")

    storage_p = populate_sub.add_parser(
        "storage",
        help="Populate storage-settings.views",
    )
    storage_p.add_argument("target", help="Path/module target to discover")
    storage_p.add_argument("--config", default="plotsrv.yml")
    storage_p.add_argument("--mode", choices=["merge", "replace"], default="merge")
    storage_p.add_argument("--yes", action="store_true", help="Do not prompt")
    storage_p.add_argument("--keep-last", type=int, default=2)
    storage_p.add_argument("--min-store-interval", default=None)
    storage_p.add_argument("--max-snapshot-size-mb", type=float, default=None)

    limits_p = populate_sub.add_parser(
        "limits",
        help="Populate per-view truncation limits",
    )
    limits_p.add_argument("target", help="Path/module target to discover")
    limits_p.add_argument("--config", default="plotsrv.yml")
    limits_p.add_argument("--mode", choices=["merge", "replace"], default="merge")
    limits_p.add_argument("--yes", action="store_true", help="Do not prompt")
    limits_p.add_argument("--text", default="1000000")
    limits_p.add_argument("--html", default="off")
    limits_p.add_argument("--markdown", default="off")

    return p
