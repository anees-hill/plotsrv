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
# Starter configuration for plotsrv.
# Use this file to control limits, rendering, storage, freshness, and security.

limits:
  watched_files:
    # Maximum bytes read from watched files.
    # Use "off" to read whole files.
    max_bytes: 5000000

  render:
    # Display limits for text-like rendered views.
    # Use "off" to disable render truncation.
    text: 1000000
    html: off
    markdown: off

  tables:
    max_rows: 10000
    max_columns: 200

table-settings:
  table_view_mode: rich
  max_table_rows_simple: 200
  max_table_rows_rich: 1000

artifact-render-settings:
  html_sanitize: false
  markdown_sanitize: true

render-settings:
  default:
    plot_dpi: 200
    plot_default_figsize_in: "12,6"
    plot_bbox_tight: true
    plot_pad_inches: 0.10

storage-settings:
  enabled: false
  root_dir: .plotsrv/store

  # Latest live-state persistence.
  # When enabled, plotsrv can restore the most recent live view after restart.
  latest:
    enabled: false
    restore_on_startup: true

  # Historical snapshots.
  default_keep_last: 2
  max_snapshot_size_mb: 20

freshness-settings:
  enabled: false
  expected_every: 60s
  warn_after: 90s
  overdue_after: 180s

security-settings:
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


def default_config_text() -> str:
    return DEFAULT_CONFIG_TEXT


def create_config_file(
    path: str | Path,
    *,
    force: bool = False,
) -> ConfigCreateResult:
    p = Path(path).expanduser().resolve()

    if p.exists() and not force:
        raise FileExistsError(f"Config file already exists: {p}")

    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")

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
        base = y.safe_load(DEFAULT_CONFIG_TEXT) or {}
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
        latest.setdefault("enabled", False)
        latest.setdefault("restore_on_startup", True)

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
    markdown: str | int | None = "off",
) -> ConfigPopulateResult:
    def ensure(data: dict[str, Any]) -> dict[str, Any]:
        sec = _ensure_mapping(data, "limits")

        watched = _ensure_mapping(sec, "watched_files")
        watched.setdefault("max_bytes", 5_000_000)

        render = _ensure_mapping(sec, "render")
        render.setdefault("text", 1_000_000)
        render.setdefault("html", "off")
        render.setdefault("markdown", "off")

        tables = _ensure_mapping(sec, "tables")
        tables.setdefault("max_rows", 10_000)
        tables.setdefault("max_columns", 200)

        return sec

    def make_entry(_view_id: str) -> dict[str, Any]:
        render: dict[str, Any] = {}
        if text is not None:
            render["text"] = text
        if html is not None:
            render["html"] = html
        if markdown is not None:
            render["markdown"] = markdown
        return {"render": render}

    return _populate_view_section(
        path=path,
        target=target,
        section_key="limits",
        mode=mode,
        ensure_section=ensure,
        make_entry=make_entry,
    )
