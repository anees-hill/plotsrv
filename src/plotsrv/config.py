# src/plotsrv/config.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from collections.abc import Mapping

from . import settings

TableViewMode = Literal["simple", "rich"]
_RUNTIME_TABLE_VIEW_MODE: TableViewMode | None = None

PLOTSRV_COLOURS = {
    "served-apple": "#9E2239",
    "grey": "#C8C8C8",
    "light-red": "#D55970",
    "pink": "#F1C5CD",
    "dirty-pink": "#BA8E96",
}

# Defaults
_DEFAULTS: dict[str, Any] = {
    "table-settings": {
        "table_view_mode": "rich",
        "max_table_rows_simple": 200,
        "max_table_rows_rich": 1000,
    },
    "render-settings": {
        "plot_dpi": 200,
        "plot_default_figsize_in": (12.0, 6.0),
        "plot_bbox_tight": True,
        "plot_pad_inches": 0.10,
    },
    "artifact-render-settings": {
        "html_sanitize": False,
        "html_sandbox": "",
        "markdown_sanitize": True,
        "markdown_sandbox": "",
    },
    "security-settings": {
        "docs_enabled": False,
        "openapi_enabled": False,
        "shutdown_enabled": False,
        "control_local_only": True,
        "internal_read_local_only": False,
        "status_local_only": False,
        "history_local_only": False,
        "views_local_only": True,
        "tracebacks_enabled": False,
    },
    "view-order-settings": {},
    "truncation": {
        "text": 1_000_000,
        "html": None,
        "markdown": None,
    },
    "limits": {
        "published_objects": {
            "max_plot_bytes": 5 * 1024 * 1024,
            "max_table_rows": 100_000,
            "max_table_columns": 200,
            "max_artifact_text_chars": 200_000,
            "max_json_container_items": 20_000,
        },
        "watched_files": {
            "max_mb": 500,
            # Legacy alias
            "max_bytes": 5_000_000,
        },
        "truncate_after": {
            "text": 1_000_000,
            "html": None,
            "markdown": 100_000,
            "table_rows": 100_000,
            "table_columns": 200,
        },
        # Legacy aliases
        "render": {
            "text": 1_000_000,
            "html": None,
            "markdown": None,
        },
        "tables": {
            "max_rows": 5000,
            "max_columns": 200,
        },
    },
    "storage-settings": {
        "enabled": False,
        "watch_enabled": False,
        "root_dir": ".plotsrv/store",
        "max_snapshot_size_mb": 20.0,
        "default_keep_last": 2,
        "default_min_store_interval": None,
        "latest": {
            "enabled": False,
            "restore_on_startup": True,
            "restore_scope": "discovered",
        },
        "views": {},
    },
    "freshness-settings": {
        "enabled": False,
        "expected_every": None,
        "warn_after": None,
        "overdue_after": None,
        "views": {},
    },
    "publish-limits": {
        # Legacy section. New preferred path is limits.published_objects.
        "max_plot_bytes": 5 * 1024 * 1024,
        "max_table_rows": 5000,
        "max_table_columns": 200,
        "max_artifact_text_chars": 200_000,
        "max_json_container_items": 20_000,
    },
}

_MAX_TABLE_ROWS_INF: int = 1_000_000_000


def set_table_view_mode(mode: TableViewMode) -> None:
    """
    Backwards compatible setter.

    This is a runtime override for the current process only.
    It does NOT write to plotsrv.yml.
    """
    global _RUNTIME_TABLE_VIEW_MODE
    m = str(mode).strip().lower()
    if m not in ("simple", "rich"):
        raise ValueError("table_view_mode must be 'simple' or 'rich'")
    _RUNTIME_TABLE_VIEW_MODE = m  # type: ignore[assignment]


def _as_bool(x: Any, default: bool) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    return default


def _as_int_or_inf(x: Any, default: int, *, min_value: int = 1) -> int:
    if x is None:
        return default
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("inf", "infinity", "none", "null", ""):
            return _MAX_TABLE_ROWS_INF
        try:
            n = int(float(s))
            return n if n >= min_value else default
        except Exception:
            return default
    try:
        n2 = int(x)
        return n2 if n2 >= min_value else default
    except Exception:
        return default


def _as_float(x: Any, default: float, *, min_value: float | None = None) -> float:
    if x is None:
        return default
    try:
        f = float(x)
        if min_value is not None and f < min_value:
            return default
        return f
    except Exception:
        return default


def _parse_figsize(x: Any) -> tuple[float, float] | None:
    if x is None:
        return None

    if isinstance(x, (list, tuple)) and len(x) >= 2:
        try:
            w = float(x[0])
            h = float(x[1])
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            return None

    if isinstance(x, dict):
        try:
            w = float(x.get("w"))
            h = float(x.get("h"))
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            return None

    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        parts = [p.strip() for p in s.replace("x", ",").split(",") if p.strip()]
        if len(parts) >= 2:
            try:
                w = float(parts[0])
                h = float(parts[1])
                if w > 0 and h > 0:
                    return (w, h)
            except Exception:
                return None

    return None


def _parse_duration_seconds(x: Any) -> int | None:
    """
    Supports:
    - 300 / 300.0
    - "300"
    - "30s", "5m", "1h", "2d"
    - "off"/"none"/null => None
    """
    if x is None:
        return None

    if isinstance(x, (int, float)):
        try:
            n = int(float(x))
            return n if n > 0 else None
        except Exception:
            return None

    if isinstance(x, str):
        s = x.strip().lower()
        if not s or s in ("off", "none", "null", "false", "0"):
            return None

        try:
            n = int(float(s))
            return n if n > 0 else None
        except Exception:
            pass

        units = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
        }
        if len(s) >= 2 and s[-1] in units:
            try:
                n2 = float(s[:-1].strip())
                secs = int(n2 * units[s[-1]])
                return secs if secs > 0 else None
            except Exception:
                return None

    return None


def _parse_limit_int_or_none(
    x: Any,
    default: int | None,
    *,
    min_value: int = 1,
) -> int | None:
    """
    Parse a limit value.

    Returns:
      - int => apply this limit
      - None => no limit/off
    """
    if x is None:
        return None

    # YAML parses unquoted "off", "false", "no" as False.
    if isinstance(x, bool):
        return default if x else None

    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("off", "none", "null", "false", "no", "0", ""):
            return None
        try:
            n = int(float(s))
            return n if n >= min_value else default
        except Exception:
            return default

    try:
        n2 = int(x)
        return n2 if n2 >= min_value else default
    except Exception:
        return default


def _as_keep_last(x: Any, default: int | None) -> int | None:
    """
    Returns:
    - int => keep last N
    - None => infinite retention
    """
    if x is None:
        return default

    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("inf", "infinity", "none", "null", "off", ""):
            return None
        try:
            n = int(float(s))
            return n if n >= 1 else default
        except Exception:
            return default

    try:
        n2 = int(x)
        return n2 if n2 >= 1 else default
    except Exception:
        return default


def _merged_section(section: str) -> dict[str, Any]:
    base = dict(_DEFAULTS.get(section, {}) or {})
    sec = settings.get_section(section)
    base.update(sec)
    return base


def _deep_merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        cur = out.get(k)
        if isinstance(cur, Mapping) and isinstance(v, Mapping):
            out[k] = _deep_merge_dicts(dict(cur), dict(v))
        else:
            out[k] = v
    return out


def _merged_limits_section() -> dict[str, Any]:
    base = dict(_DEFAULTS.get("limits", {}) or {})
    raw = settings.get_section("limits")
    if not isinstance(raw, dict):
        return base
    return _deep_merge_dicts(base, raw)


_MB: int = 1024 * 1024


def _raw_section(section: str) -> dict[str, Any]:
    raw = settings.get_section(section)
    return raw if isinstance(raw, dict) else {}


def _raw_limits_section() -> dict[str, Any]:
    return _raw_section("limits")


def _mapping_value(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    return value if isinstance(value, Mapping) else {}


def _parse_mb_to_bytes(
    x: Any,
    default_mb: int | float | None,
    *,
    min_value: float = 0.000001,
) -> int | None:
    """
    Parse a megabyte limit.

    Returns:
      - int bytes
      - None for off/no limit
    """
    if x is None:
        if default_mb is None:
            return None
        return max(1, int(float(default_mb) * _MB))

    if isinstance(x, bool):
        if x is False:
            return None
        if default_mb is None:
            return None
        return max(1, int(float(default_mb) * _MB))

    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("off", "none", "null", "false", "no", "0", ""):
            return None

        try:
            mb = float(s)
            if mb < min_value:
                if default_mb is None:
                    return None
                return max(1, int(float(default_mb) * _MB))
            return max(1, int(mb * _MB))
        except Exception:
            if default_mb is None:
                return None
            return max(1, int(float(default_mb) * _MB))

    try:
        mb2 = float(x)
        if mb2 < min_value:
            if default_mb is None:
                return None
            return max(1, int(float(default_mb) * _MB))
        return max(1, int(mb2 * _MB))
    except Exception:
        if default_mb is None:
            return None
        return max(1, int(float(default_mb) * _MB))


def _get_global_truncate_limit(kind: Literal["text", "html", "markdown"]) -> int | None:
    """
    Preferred:
      limits.truncate_after.<kind>

    Legacy:
      limits.render.<kind>
      truncation.<kind>
    """
    raw_limits = _raw_limits_section()

    truncate_after = _mapping_value(raw_limits, "truncate_after")
    if kind in truncate_after:
        default_val = _DEFAULTS["limits"]["truncate_after"].get(kind)
        return _parse_limit_int_or_none(
            truncate_after.get(kind),
            default_val,
            min_value=1,
        )

    legacy_render = _mapping_value(raw_limits, "render")
    if kind in legacy_render:
        default_val = _DEFAULTS["limits"]["render"].get(kind)
        return _parse_limit_int_or_none(
            legacy_render.get(kind),
            default_val,
            min_value=1,
        )

    raw_truncation = _raw_section("truncation")
    if kind in raw_truncation:
        default_val = _DEFAULTS["truncation"].get(kind)
        return _parse_limit_int_or_none(
            raw_truncation.get(kind),
            default_val,
            min_value=1,
        )

    default_val = _DEFAULTS["limits"]["truncate_after"].get(kind)
    return _parse_limit_int_or_none(default_val, default_val, min_value=1)


def _get_view_truncate_limit(
    kind: Literal["text", "html", "markdown"],
    *,
    view_id: str,
) -> int | None | object:
    """
    Return a per-view truncate limit if configured.

    Returns settings._UNSET if no per-view override exists.
    """
    raw_limits = _raw_limits_section()
    raw_views = raw_limits.get("views")
    if not isinstance(raw_views, Mapping):
        return settings._UNSET

    raw_view_limits = raw_views.get(view_id)
    if not isinstance(raw_view_limits, Mapping):
        return settings._UNSET

    raw_view_truncate = raw_view_limits.get("truncate_after")
    if isinstance(raw_view_truncate, Mapping) and kind in raw_view_truncate:
        default_val = _DEFAULTS["limits"]["truncate_after"].get(kind)
        return _parse_limit_int_or_none(
            raw_view_truncate.get(kind),
            default_val,
            min_value=1,
        )

    raw_view_render = raw_view_limits.get("render")
    if isinstance(raw_view_render, Mapping) and kind in raw_view_render:
        default_val = _DEFAULTS["limits"]["render"].get(kind)
        return _parse_limit_int_or_none(
            raw_view_render.get(kind),
            default_val,
            min_value=1,
        )

    return settings._UNSET


def _get_table_truncate_limit(
    key: Literal["table_rows", "table_columns"],
) -> int | None:
    """
    Preferred:
      limits.truncate_after.table_rows/table_columns

    Legacy:
      limits.tables.max_rows/max_columns
      table-settings.max_table_rows_rich for rows only
    """
    raw_limits = _raw_limits_section()

    truncate_after = _mapping_value(raw_limits, "truncate_after")
    if key in truncate_after:
        default_val = _DEFAULTS["limits"]["truncate_after"].get(key)
        return _parse_limit_int_or_none(
            truncate_after.get(key),
            default_val,
            min_value=1,
        )

    legacy_tables = _mapping_value(raw_limits, "tables")

    if key == "table_rows":
        if "max_rows" in legacy_tables:
            return _parse_limit_int_or_none(
                legacy_tables.get("max_rows"),
                _DEFAULTS["limits"]["tables"]["max_rows"],
                min_value=1,
            )

        raw_table_settings = _raw_section("table-settings")
        if "max_table_rows_rich" in raw_table_settings:
            return _parse_limit_int_or_none(
                raw_table_settings.get("max_table_rows_rich"),
                _DEFAULTS["table-settings"]["max_table_rows_rich"],
                min_value=1,
            )

    if key == "table_columns" and "max_columns" in legacy_tables:
        return _parse_limit_int_or_none(
            legacy_tables.get("max_columns"),
            _DEFAULTS["limits"]["tables"]["max_columns"],
            min_value=1,
        )

    default_val = _DEFAULTS["limits"]["truncate_after"].get(key)
    return _parse_limit_int_or_none(default_val, default_val, min_value=1)


def _get_published_object_limit(key: str, default: int) -> int:
    """
    Preferred:
      limits.published_objects.<key>

    Legacy:
      publish-limits.<key>

    Temporary compatibility:
      limits.tables.max_rows/max_columns still act as table publish limits until
      the later table truncation refactor separates display truncation from hard
      server limits.
    """
    raw_limits = _raw_limits_section()

    published_objects = _mapping_value(raw_limits, "published_objects")
    if key in published_objects:
        return _as_int_or_inf(published_objects.get(key), default, min_value=1)

    if key == "max_table_rows":
        legacy_tables = _mapping_value(raw_limits, "tables")
        if "max_rows" in legacy_tables:
            return _as_int_or_inf(legacy_tables.get("max_rows"), default, min_value=1)

    if key == "max_table_columns":
        legacy_tables = _mapping_value(raw_limits, "tables")
        if "max_columns" in legacy_tables:
            return _as_int_or_inf(
                legacy_tables.get("max_columns"),
                default,
                min_value=1,
            )

    legacy_publish = _raw_section("publish-limits")
    if key in legacy_publish:
        return _as_int_or_inf(legacy_publish.get(key), default, min_value=1)

    return default


# ---- View ordering ------------------------------------------------------------


def get_view_order_sections() -> list[str] | None:
    sec = _merged_section("view-order-settings")
    xs = sec.get("sections")
    if isinstance(xs, list):
        out = [str(x).strip() for x in xs if str(x).strip()]
        return out or None
    return None


def get_view_order_labels(section: str) -> list[str] | None:
    sec = _merged_section("view-order-settings")
    labels = sec.get("labels")
    if not isinstance(labels, dict):
        return None
    key = (section or "").strip() or "default"
    xs = labels.get(key)
    if isinstance(xs, list):
        out = [str(x).strip() for x in xs if str(x).strip()]
        return out or None
    return None


# ---- Table settings -----------------------------------------------------------


def get_table_view_mode() -> TableViewMode:
    if _RUNTIME_TABLE_VIEW_MODE is not None:
        return _RUNTIME_TABLE_VIEW_MODE

    sec = _merged_section("table-settings")
    raw = str(sec.get("table_view_mode") or "rich").strip().lower()
    return "simple" if raw == "simple" else "rich"


def get_max_table_rows_simple() -> int:
    sec = _merged_section("table-settings")
    return _as_int_or_inf(sec.get("max_table_rows_simple"), 200, min_value=1)


def get_max_table_rows_rich() -> int:
    sec = _merged_section("table-settings")
    return _as_int_or_inf(sec.get("max_table_rows_rich"), 1000, min_value=1)


def get_render_text_max_chars() -> int | None:
    return _get_global_truncate_limit("text")


def get_render_markdown_max_chars() -> int | None:
    return _get_global_truncate_limit("markdown")


def get_render_html_max_chars() -> int | None:
    return _get_global_truncate_limit("html")


def get_table_truncate_rows() -> int | None:
    return _get_table_truncate_limit("table_rows")


def get_table_truncate_columns() -> int | None:
    return _get_table_truncate_limit("table_columns")


# ---- Render settings ----------------------------------------------------------


def get_plot_dpi() -> int:
    sec = _merged_section("render-settings")
    dpi = _as_int_or_inf(sec.get("plot_dpi"), 200, min_value=50)
    return int(dpi)


def get_plot_default_figsize_in() -> tuple[float, float] | None:
    sec = _merged_section("render-settings")
    val = sec.get("plot_default_figsize_in", (12.0, 6.0))
    return _parse_figsize(val)


def get_plot_bbox_tight() -> bool:
    sec = _merged_section("render-settings")
    return _as_bool(sec.get("plot_bbox_tight"), True)


def get_plot_pad_inches() -> float:
    sec = _merged_section("render-settings")
    return _as_float(sec.get("plot_pad_inches"), 0.10, min_value=0.0)


# ---- Artifact render settings ------------------------------------------------


def get_html_sanitize() -> bool:
    sec = _merged_section("artifact-render-settings")
    return _as_bool(sec.get("html_sanitize"), False)


def get_html_sandbox() -> str:
    sec = _merged_section("artifact-render-settings")
    raw = sec.get("html_sandbox")
    default = ""
    if isinstance(raw, str):
        return raw.strip()
    return default


def get_markdown_sanitize() -> bool:
    sec = _merged_section("artifact-render-settings")
    return _as_bool(sec.get("markdown_sanitize"), True)


def get_markdown_sandbox() -> str:
    sec = _merged_section("artifact-render-settings")
    raw = sec.get("markdown_sandbox")
    default = ""
    if isinstance(raw, str):
        return raw.strip()
    return default


def get_tracebacks_enabled() -> bool:
    sec = _merged_section("security-settings")
    return _as_bool(sec.get("tracebacks_enabled"), False)


# ---- Truncation ---------------------------------------------------------------


def get_truncation_max_chars(
    kind: Literal["text", "html", "markdown"],
    view_id: str | None = None,
) -> int | None:
    """
    Renderer display limit for text/html/markdown views.

    Preferred config path:
      limits.truncate_after.<kind>
      limits.views.<view_id>.truncate_after.<kind>

    Legacy config paths:
      limits.render.<kind>
      limits.views.<view_id>.render.<kind>
      truncation.<kind>

    Runtime/CLI truncate override remains global and wins.
    """
    override = settings.get_truncate_override()

    if not settings.is_truncate_override_unset(override):
        if settings.is_truncate_override_off(override):
            return None
        return int(max(1, int(override)))

    if view_id:
        view_limit = _get_view_truncate_limit(kind, view_id=view_id)
        if view_limit is not settings._UNSET:
            return view_limit  # type: ignore[return-value]

    return _get_global_truncate_limit(kind)


def get_watch_max_bytes(view_id: str | None = None) -> int | None:
    """
    Maximum bytes read from watched files.

    Preferred config path:
      limits.watched_files.max_mb

    Legacy config path:
      limits.watched_files.max_bytes

    Returns:
      - int => read at most this many bytes
      - None => read the whole file

    Note:
      view_id is accepted for API stability, but watched-file input limits are
      currently global only. Use per-view truncate/render limits for display
      behaviour.
    """
    raw_limits = _raw_limits_section()
    watched = _mapping_value(raw_limits, "watched_files")

    default_mb = _DEFAULTS["limits"]["watched_files"]["max_mb"]

    if "max_mb" in watched:
        return _parse_mb_to_bytes(watched.get("max_mb"), default_mb)

    if "max_bytes" in watched:
        default_bytes = _DEFAULTS["limits"]["watched_files"]["max_bytes"]
        return _parse_limit_int_or_none(
            watched.get("max_bytes"),
            default_bytes,
            min_value=1,
        )

    return _parse_mb_to_bytes(default_mb, default_mb)


# ---- Storage settings ---------------------------------------------------------


def get_storage_enabled() -> bool:
    sec = _merged_section("storage-settings")
    return _as_bool(sec.get("enabled"), False)


def get_storage_root_dir() -> Path:
    sec = _merged_section("storage-settings")
    raw = sec.get("root_dir", ".plotsrv/store")

    if isinstance(raw, str) and raw.strip():
        p = Path(raw.strip()).expanduser()
    else:
        p = Path(".plotsrv/store")

    if p.is_absolute():
        return p.resolve()

    base = settings.get_runtime_config_dir() or Path.cwd()
    return (base / p).resolve()


def _storage_latest_settings() -> dict[str, Any]:
    sec = _merged_section("storage-settings")
    latest = sec.get("latest")
    default_latest = _DEFAULTS["storage-settings"]["latest"]

    if not isinstance(latest, dict):
        return dict(default_latest)

    return _deep_merge_dicts(dict(default_latest), latest)


def get_storage_latest_enabled() -> bool:
    """
    Whether latest live-state persistence is enabled.

    Global storage-settings.enabled remains the master switch. This means latest
    persistence is active only when both storage is enabled and latest.enabled is
    true.
    """
    if not get_storage_enabled():
        return False

    latest = _storage_latest_settings()
    return _as_bool(latest.get("enabled"), False)


def get_storage_restore_latest_on_startup() -> bool:
    """
    Whether plotsrv should restore latest live-state records into memory on
    server startup.

    This only has effect when latest persistence is enabled.
    """
    if not get_storage_latest_enabled():
        return False

    latest = _storage_latest_settings()
    return _as_bool(latest.get("restore_on_startup"), True)


def get_storage_latest_restore_scope() -> str:
    """
    Scope used when restoring latest live-state records.

    Values:
      - "discovered": restore only views already registered/discovered.
        If no views are registered, restore all latest records.
      - "all": restore all latest records.
      - "none": restore nothing.
    """
    if not get_storage_restore_latest_on_startup():
        return "none"

    latest = _storage_latest_settings()
    raw = str(latest.get("restore_scope") or "discovered").strip().lower()

    if raw not in ("discovered", "all", "none"):
        return "discovered"

    return raw


def _storage_view_overrides() -> dict[str, Any]:
    sec = _merged_section("storage-settings")
    views = sec.get("views")
    return views if isinstance(views, dict) else {}


def get_storage_view_settings(view_id: str) -> dict[str, Any]:
    overrides = _storage_view_overrides()
    raw = overrides.get(view_id)
    return dict(raw) if isinstance(raw, dict) else {}


def get_storage_view_enabled(view_id: str) -> bool:
    view_sec = get_storage_view_settings(view_id)
    if "enabled" in view_sec:
        return _as_bool(view_sec.get("enabled"), get_storage_enabled())
    return get_storage_enabled()


def get_storage_max_snapshot_size_bytes(view_id: str | None = None) -> int:
    sec = _merged_section("storage-settings")

    if view_id:
        view_sec = get_storage_view_settings(view_id)
        if "max_snapshot_size_mb" in view_sec:
            mb = _as_float(
                view_sec.get("max_snapshot_size_mb"),
                20.0,
                min_value=0.001,
            )
            return max(1, int(mb * 1024 * 1024))

    mb = _as_float(sec.get("max_snapshot_size_mb"), 20.0, min_value=0.001)
    return max(1, int(mb * 1024 * 1024))


def get_storage_default_keep_last() -> int | None:
    sec = _merged_section("storage-settings")
    return _as_keep_last(sec.get("default_keep_last"), 2)


def get_storage_default_min_store_interval_s() -> int | None:
    sec = _merged_section("storage-settings")
    return _parse_duration_seconds(sec.get("default_min_store_interval"))


def get_storage_keep_last(view_id: str) -> int | None:
    view_sec = get_storage_view_settings(view_id)
    if "keep_last" in view_sec:
        return _as_keep_last(view_sec.get("keep_last"), get_storage_default_keep_last())
    return get_storage_default_keep_last()


def get_storage_min_store_interval_s(view_id: str) -> int | None:
    view_sec = get_storage_view_settings(view_id)
    if "min_store_interval" in view_sec:
        return _parse_duration_seconds(view_sec.get("min_store_interval"))
    return get_storage_default_min_store_interval_s()


def get_storage_watch_enabled() -> bool:
    sec = _merged_section("storage-settings")
    return _as_bool(sec.get("watch_enabled"), False)


def get_storage_view_enabled(
    view_id: str,
    *,
    source: str | None = None,
) -> bool:
    """
    Source-aware storage admission.

    Rules:
    - global storage-settings.enabled is the master switch
    - non-watch publishes default to enabled=True (subject to global enabled)
      unless views.<view_id>.enabled overrides
    - watch publishes default to storage-settings.watch_enabled (default False)
      unless views.<view_id>.watch_enabled overrides
    """
    if not get_storage_enabled():
        return False

    view_sec = get_storage_view_settings(view_id)

    if source == "watch":
        default_watch = get_storage_watch_enabled()
        if "watch_enabled" in view_sec:
            return _as_bool(view_sec.get("watch_enabled"), default_watch)
        return default_watch

    if "enabled" in view_sec:
        return _as_bool(view_sec.get("enabled"), True)
    return True


# ---- Freshness settings -------------------------------------------------------


def get_freshness_enabled() -> bool:
    sec = _merged_section("freshness-settings")
    return _as_bool(sec.get("enabled"), False)


def _freshness_view_overrides() -> dict[str, Any]:
    sec = _merged_section("freshness-settings")
    views = sec.get("views")
    return views if isinstance(views, dict) else {}


def get_freshness_view_settings(view_id: str) -> dict[str, Any]:
    raw = _freshness_view_overrides().get(view_id)
    return dict(raw) if isinstance(raw, dict) else {}


def get_freshness_expected_every_s(view_id: str | None = None) -> int | None:
    sec = _merged_section("freshness-settings")
    if view_id:
        view_sec = get_freshness_view_settings(view_id)
        if "expected_every" in view_sec:
            return _parse_duration_seconds(view_sec.get("expected_every"))
    return _parse_duration_seconds(sec.get("expected_every"))


def get_freshness_warn_after_s(view_id: str | None = None) -> int | None:
    sec = _merged_section("freshness-settings")
    if view_id:
        view_sec = get_freshness_view_settings(view_id)
        if "warn_after" in view_sec:
            return _parse_duration_seconds(view_sec.get("warn_after"))
    return _parse_duration_seconds(sec.get("warn_after"))


def get_freshness_overdue_after_s(view_id: str | None = None) -> int | None:
    sec = _merged_section("freshness-settings")
    if view_id:
        view_sec = get_freshness_view_settings(view_id)
        if "overdue_after" in view_sec:
            return _parse_duration_seconds(view_sec.get("overdue_after"))
        if "error_after" in view_sec:  # legacy alias
            return _parse_duration_seconds(view_sec.get("error_after"))

    if sec.get("overdue_after") is not None:
        return _parse_duration_seconds(sec.get("overdue_after"))
    return _parse_duration_seconds(sec.get("error_after"))


def get_freshness_error_after_s(view_id: str | None = None) -> int | None:
    """
    Legacy alias retained for backwards compatibility.
    Prefer get_freshness_overdue_after_s().
    """
    return get_freshness_overdue_after_s(view_id)


# ---- Security settings --------------------------------------------------------


def get_docs_enabled() -> bool:
    sec = _merged_section("security-settings")
    return _as_bool(sec.get("docs_enabled"), False)


def get_openapi_enabled() -> bool:
    sec = _merged_section("security-settings")
    return _as_bool(sec.get("openapi_enabled"), False)


def get_shutdown_enabled() -> bool:
    sec = _merged_section("security-settings")
    return _as_bool(sec.get("shutdown_enabled"), False)


def get_control_local_only() -> bool:
    sec = _merged_section("security-settings")
    return _as_bool(sec.get("control_local_only"), True)


def get_internal_read_local_only() -> bool:
    """
    Legacy compatibility getter.

    Older code/tests/config used one switch for all internal read routes.
    """
    sec = _merged_section("security-settings")
    return _as_bool(sec.get("internal_read_local_only"), False)


def get_status_local_only() -> bool:
    raw = settings.get_section("security-settings")
    if "status_local_only" in raw:
        return _as_bool(raw.get("status_local_only"), False)
    if "internal_read_local_only" in raw:
        return _as_bool(raw.get("internal_read_local_only"), False)
    return _as_bool(_DEFAULTS["security-settings"].get("status_local_only"), False)


def get_history_local_only() -> bool:
    raw = settings.get_section("security-settings")
    if "history_local_only" in raw:
        return _as_bool(raw.get("history_local_only"), False)
    if "internal_read_local_only" in raw:
        return _as_bool(raw.get("internal_read_local_only"), False)
    return _as_bool(_DEFAULTS["security-settings"].get("history_local_only"), False)


def get_views_local_only() -> bool:
    raw = settings.get_section("security-settings")
    if "views_local_only" in raw:
        return _as_bool(raw.get("views_local_only"), True)
    if "internal_read_local_only" in raw:
        return _as_bool(raw.get("internal_read_local_only"), True)
    return _as_bool(_DEFAULTS["security-settings"].get("views_local_only"), True)


# ---- Publish limits -----------------------------------------------------------


def get_publish_max_plot_bytes() -> int:
    return _get_published_object_limit(
        "max_plot_bytes",
        int(_DEFAULTS["limits"]["published_objects"]["max_plot_bytes"]),
    )


def get_publish_max_table_rows() -> int:
    return _get_published_object_limit(
        "max_table_rows",
        int(_DEFAULTS["limits"]["published_objects"]["max_table_rows"]),
    )


def get_publish_max_table_columns() -> int:
    return _get_published_object_limit(
        "max_table_columns",
        int(_DEFAULTS["limits"]["published_objects"]["max_table_columns"]),
    )


def get_publish_max_artifact_text_chars() -> int:
    return _get_published_object_limit(
        "max_artifact_text_chars",
        int(_DEFAULTS["limits"]["published_objects"]["max_artifact_text_chars"]),
    )


def get_publish_max_json_container_items() -> int:
    return _get_published_object_limit(
        "max_json_container_items",
        int(_DEFAULTS["limits"]["published_objects"]["max_json_container_items"]),
    )
