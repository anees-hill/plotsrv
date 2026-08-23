from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from .discovery import DiscoveredView, discover_views

PopulateMode = Literal["merge", "replace"]


DEFAULT_CONFIG_TEXT = """# plotsrv.yml
#
# Starter configuration for plotsrv. plotsrv also works without this file.
# Change the settings below when you need to tune persistence, watched files,
# publishing, or the safety limits used for browser output.
# More options are available in the configuration reference:
# https://docs.plotsrv.com/guides/configuration-reference

# Storage is off by default. Enable it to keep the latest views and history
# on disk between runs.
storage-settings:
  enabled: false
  watch_enabled: false
  root_dir: .plotsrv/store
  max_snapshot_size_mb: 20.0
  default_keep_last: 2
  default_min_store_interval: off
  latest:
    # Restore the latest stored view when storage is enabled.
    enabled: true
    restore_on_startup: true
    restore_scope: discovered

watch-settings:
  # Controls how watched files are represented internally:
  # memory = read and publish the content into memory;
  # file = keep metadata and read previews from disk on demand;
  # auto = memory below file_threshold_mb, file-backed at or above it.
  materialization: auto
  file_threshold_mb: 10

  # Bound simultaneous file-backed preview loads from browser requests.
  active_loads:
    max_concurrent: 2
    wait_timeout_s: 1.0

publish-settings:
  live:
    # Synchronous by default. Set true to make publish_view() and @view()
    # asynchronous when async_ is not supplied.
    async_enabled: false

    # Bounds for pending async updates. Repeated updates to one view coalesce
    # so only its latest pending value is retained.
    max_pending_views: 32
    max_pending_mb: 64

    # Default bounded wait used by flush_views() and server shutdown.
    flush_timeout_s: 1.0

limits:
  published_objects:
    # Hard safety limits for objects sent to the plotsrv server.
    max_plot_bytes: 5242880          # 5 MiB
    max_table_rows: 100000
    max_table_columns: 200
    max_artifact_text_chars: 200000
    max_json_container_items: 20000

  watched_files:
    # Maximum amount plotsrv reads from each watched file.
    # Use "off" to allow full-file reads, but this can use a lot of memory.
    max_mb: 500

  truncate_after:
    # Preparation/display limits. These truncate browser output rather than
    # rejecting the view.
    text: 1000000
    markdown: 100000
    html: off
    table_rows: 100000
    table_columns: 200

freshness-settings:
  # Optional checks for views that are expected to update regularly.
  enabled: false
  expected_every: 60s
  warn_after: 2m
  overdue_after: 10m

security-settings:
  # Keep browser-facing errors concise. Enable tracebacks only for trusted use.
  tracebacks_enabled: false
"""


EXPANDED_CONFIG_TEXT = """# plotsrv.yml
#
# Expanded starter configuration. It includes the less commonly adjusted
# storage queue and rendering controls as well as the normal starter settings.
# Remove sections you do not need; plotsrv works without this file.

# Storage is off by default. Enable it to keep the latest views and history
# on disk between runs.
storage-settings:
  enabled: false
  watch_enabled: false
  root_dir: .plotsrv/store
  max_snapshot_size_mb: 20.0
  default_keep_last: 2
  default_min_store_interval: off
  latest:
    # Restore the latest stored view when storage is enabled.
    enabled: true
    restore_on_startup: true
    restore_scope: discovered

  # Bounds for best-effort snapshot work waiting to be serialised.
  max_pending_tasks: 32
  max_pending_mb: 64

watch-settings:
  # Controls how watched files are represented internally:
  # memory = read and publish the content into memory;
  # file = keep metadata and read previews from disk on demand;
  # auto = memory below file_threshold_mb, file-backed at or above it.
  materialization: auto
  file_threshold_mb: 10

  # Bound simultaneous file-backed preview loads from browser requests.
  active_loads:
    max_concurrent: 2
    wait_timeout_s: 1.0

publish-settings:
  live:
    # Synchronous by default. Set true to make publish_view() and @view()
    # asynchronous when async_ is not supplied.
    async_enabled: false
    max_pending_views: 32
    max_pending_mb: 64
    flush_timeout_s: 1.0

limits:
  published_objects:
    # Hard safety limits for objects sent to the plotsrv server.
    max_plot_bytes: 5242880          # 5 MiB
    max_table_rows: 100000
    max_table_columns: 200
    max_artifact_text_chars: 200000
    max_json_container_items: 20000
  watched_files:
    max_mb: 500
  truncate_after:
    text: 1000000
    markdown: 100000
    html: off
    table_rows: 100000
    table_columns: 200

freshness-settings:
  enabled: false
  expected_every: 60s
  warn_after: 2m
  overdue_after: 10m

render-settings:
  default:
    # Renderer defaults. Change these only when you need different output.
    plot_dpi: 200
    plot_default_figsize_in: "12,6"
    plot_bbox_tight: true
    plot_pad_inches: 0.10
    table_view_mode: rich
    html_sanitize: false
    markdown_sanitize: true
    html_sandbox: ""
    markdown_sandbox: ""

security-settings:
  # Keep browser-facing errors concise. Enable tracebacks only for trusted use.
  tracebacks_enabled: false
"""


@dataclass(frozen=True, slots=True)
class ConfigCreateResult:
    path: Path
    created: bool
    overwritten: bool


@dataclass(frozen=True, slots=True)
class ConfigPopulateResult:
    path: Path
    created: bool
    section: str
    mode: PopulateMode
    discovered_count: int
    added_count: int
    preserved_count: int
    replaced: bool


def default_config_text(*, expanded: bool = False) -> str:
    """Return the compact starter config, or its expanded variant."""
    return EXPANDED_CONFIG_TEXT if expanded else DEFAULT_CONFIG_TEXT


def create_config_file(
    path: str | Path,
    *,
    force: bool = False,
    expanded: bool = False,
) -> ConfigCreateResult:
    p = Path(path).expanduser().resolve()

    if p.exists() and not force:
        raise FileExistsError(f"Config file already exists: {p}")

    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(default_config_text(expanded=expanded), encoding="utf-8")

    return ConfigCreateResult(
        path=p,
        created=not existed,
        overwritten=existed,
    )


def _require_yaml() -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required for config writing.")
    return yaml


def _load_config_data(path: Path) -> tuple[dict[str, Any], bool]:
    y = _require_yaml()

    if not path.exists():
        # Population commands need the complete defaults so adding one
        # per-view section does not drop unrelated safety settings.
        base = y.safe_load(EXPANDED_CONFIG_TEXT) or {}
        if not isinstance(base, dict):
            base = {}
        return base, True

    raw = y.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}, False
    if not isinstance(raw, dict):
        raise ValueError("plotsrv config must be a YAML mapping at top level.")
    return raw, False


def _write_config_data(path: Path, data: dict[str, Any]) -> None:
    y = _require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        y.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def _view_id_for_discovered(v: DiscoveredView) -> str:
    section = (v.section or "default").strip() or "default"
    label = (v.label or "default").strip() or "default"
    return f"{section}:{label}"


def discover_view_ids(target: str | Path) -> list[str]:
    views = discover_views(target)
    out = [_view_id_for_discovered(v) for v in views]
    return sorted(set(out))


def _ensure_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _populate_view_section(
    *,
    path: str | Path,
    target: str | Path,
    section_key: str,
    mode: PopulateMode,
    ensure_section: Callable[[dict[str, Any]], dict[str, Any]],
    make_entry: Callable[[str], dict[str, Any]],
) -> ConfigPopulateResult:
    p = Path(path).expanduser().resolve()
    data, created = _load_config_data(p)

    view_ids = discover_view_ids(target)
    section = ensure_section(data)
    views = _ensure_mapping(section, "views")

    existing_count = len(views)
    replaced = False

    if mode == "replace":
        views.clear()
        replaced = existing_count > 0

    added = 0
    preserved = 0

    for view_id in view_ids:
        if mode == "merge" and view_id in views:
            preserved += 1
            continue
        views[view_id] = make_entry(view_id)
        added += 1

    _write_config_data(p, data)

    return ConfigPopulateResult(
        path=p,
        created=created,
        section=section_key,
        mode=mode,
        discovered_count=len(view_ids),
        added_count=added,
        preserved_count=preserved,
        replaced=replaced,
    )


def populate_freshness(
    *,
    path: str | Path,
    target: str | Path,
    mode: PopulateMode = "merge",
    expected_every: str = "60s",
    warn_after: str = "90s",
    overdue_after: str = "180s",
) -> ConfigPopulateResult:

    def ensure(data: dict[str, Any]) -> dict[str, Any]:
        sec = _ensure_mapping(data, "freshness-settings")
        sec["enabled"] = True
        sec.setdefault("expected_every", expected_every)
        sec.setdefault("warn_after", warn_after)
        sec.setdefault("overdue_after", overdue_after)
        return sec

    def make_entry(_view_id: str) -> dict[str, Any]:
        return {
            "expected_every": expected_every,
            "warn_after": warn_after,
            "overdue_after": overdue_after,
        }

    return _populate_view_section(
        path=path,
        target=target,
        section_key="freshness-settings",
        mode=mode,
        ensure_section=ensure,
        make_entry=make_entry,
    )


def populate_storage(
    *,
    path: str | Path,
    target: str | Path,
    mode: PopulateMode = "merge",
    keep_last: int = 2,
    min_store_interval: str | None = None,
    max_snapshot_size_mb: float | None = None,
) -> ConfigPopulateResult:

    def ensure(data: dict[str, Any]) -> dict[str, Any]:
        sec = _ensure_mapping(data, "storage-settings")
        sec["enabled"] = True
        sec.setdefault("root_dir", ".plotsrv/store")

        latest = _ensure_mapping(sec, "latest")
        latest.setdefault("enabled", True)
        latest.setdefault("restore_on_startup", True)
        latest.setdefault("restore_scope", "discovered")

        sec.setdefault("default_keep_last", keep_last)
        return sec

    def make_entry(_view_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {
            "enabled": True,
            "keep_last": keep_last,
        }
        if min_store_interval is not None:
            out["min_store_interval"] = min_store_interval
        if max_snapshot_size_mb is not None:
            out["max_snapshot_size_mb"] = max_snapshot_size_mb
        return out

    return _populate_view_section(
        path=path,
        target=target,
        section_key="storage-settings",
        mode=mode,
        ensure_section=ensure,
        make_entry=make_entry,
    )


def populate_limits(
    *,
    path: str | Path,
    target: str | Path,
    mode: PopulateMode = "merge",
    text: str | int | None = "1000000",
    html: str | int | None = "off",
    markdown: str | int | None = "100000",
    max_mb: str | int | float | None = 500,
    table_rows: str | int | None = 100000,
    table_columns: str | int | None = 200,
) -> ConfigPopulateResult:
    def ensure(data: dict[str, Any]) -> dict[str, Any]:
        sec = _ensure_mapping(data, "limits")

        published = _ensure_mapping(sec, "published_objects")
        published.setdefault("max_plot_bytes", 5 * 1024 * 1024)
        published.setdefault("max_table_rows", 100000)
        published.setdefault("max_table_columns", 200)
        published.setdefault("max_artifact_text_chars", 200000)
        published.setdefault("max_json_container_items", 20000)

        watched = _ensure_mapping(sec, "watched_files")
        if max_mb is not None:
            watched.setdefault("max_mb", max_mb)

        truncate_after = _ensure_mapping(sec, "truncate_after")
        if text is not None:
            truncate_after.setdefault("text", text)
        if markdown is not None:
            truncate_after.setdefault("markdown", markdown)
        if html is not None:
            truncate_after.setdefault("html", html)
        if table_rows is not None:
            truncate_after.setdefault("table_rows", table_rows)
        if table_columns is not None:
            truncate_after.setdefault("table_columns", table_columns)

        return sec

    def make_entry(_view_id: str) -> dict[str, Any]:
        truncate_after: dict[str, Any] = {}

        if text is not None:
            truncate_after["text"] = text
        if markdown is not None:
            truncate_after["markdown"] = markdown
        if html is not None:
            truncate_after["html"] = html

        return {"truncate_after": truncate_after}

    return _populate_view_section(
        path=path,
        target=target,
        section_key="limits",
        mode=mode,
        ensure_section=ensure,
        make_entry=make_entry,
    )
