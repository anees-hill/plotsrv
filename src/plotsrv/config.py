# src/plotsrv/config.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from collections.abc import Mapping

from . import settings

TableViewMode = Literal["simple", "rich"]
WatchMaterialization = Literal["auto", "memory", "file"]

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
    # Legacy section.
    # New preferred home for table view behaviour is render-settings.
    "table-settings": {
        "table_view_mode": "rich",
        "max_table_rows_simple": 200,
        "max_table_rows_rich": 1000,
    },
    # Preferred render configuration.
    "render-settings": {
        "plot_dpi": 200,
        "plot_default_figsize_in": (12.0, 6.0),
        "plot_bbox_tight": True,
        "plot_pad_inches": 0.10,
        # Browser-native table plots use SVG marks. Keep the useful default
        # above the old 1,000-point ceiling while bounding DOM work even when
        # a user explicitly raises it.
        "table_plot_max_points": 5_000,
        "table_view_mode": "rich",
        "html_sanitize": False,
        "html_sandbox": "",
        "markdown_sanitize": True,
        "markdown_sandbox": "",
    },
    # Legacy section.
    # New preferred home for artifact render behaviour is render-settings.
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
    # Legacy top-level truncation section.
    # New preferred home is limits.truncate_after.
    "truncation": {
        "text": 1_000_000,
        "html": None,
        "markdown": None,
    },
    "limits": {
        # Preferred hard publish safety limits.
        "published_objects": {
            "max_plot_bytes": 5 * 1024 * 1024,
            "max_table_rows": 100_000,
            "max_table_columns": 200,
            "max_artifact_text_chars": 200_000,
            "max_json_container_items": 20_000,
        },
        # Preferred watched-file read limit.
        "watched_files": {
            "max_mb": 500,
            # Legacy alias.
            "max_bytes": 5_000_000,
        },
        # Preferred preparation/display truncation limits.
        "truncate_after": {
            "text": 1_000_000,
            "html": None,
            "markdown": 100_000,
            "table_rows": 100_000,
            "table_columns": 200,
        },
        # Legacy aliases.
        "render": {
            "text": 1_000_000,
            "html": None,
            "markdown": None,
        },
        "tables": {
            "max_rows": 5_000,
            "max_columns": 200,
        },
    },
    "watch-settings": {
        "materialization": "auto",
        "file_threshold_mb": 10,
        # File-backed previews are parsed on request. Keep expensive table
        # materialisation bounded even when several browser clients refresh at
        # once. Existing limits.truncate_after.* values remain the limits that
        # control how much is prepared for display.
        "active_loads": {
            "max_concurrent": 2,
            "wait_timeout_s": 1.0,
        },
    },
    "publish-settings": {
        "live": {
            # Keep the established synchronous behaviour unless a caller opts
            # in with async_=True or enables this setting explicitly.
            "async_enabled": False,
            # Bound retained source objects, not the eventual rendered payload.
            "max_pending_views": 32,
            "max_pending_mb": 64,
            "flush_timeout_s": 1.0,
        },
    },
    "stream-settings": {
        # Stream transport is independent from snapshot publishing. These
        # values bound failed-delivery recovery without changing existing
        # publish async/latest-wins behaviour.
        "poll_interval_s": 0.1,
        "request_timeout_s": 1.0,
        "retry_initial_delay_s": 0.1,
        "retry_max_delay_s": 5.0,
        # A stream session remains live only while its producer renews this
        # heartbeat. Timeouts are observations of the transport, never proof
        # of a clean producer or application exit.
        "heartbeat_interval_s": 1.0,
        "heartbeat_timeout_s": 3.0,
        # Every explicit stop and the single process-exit manager receives a
        # finite budget; neither installs an application signal handler.
        "shutdown_drain_timeout_s": 1.0,
        "process_exit_cleanup_timeout_s": 0.25,
        # The raw browser window is independently bounded by all three
        # limits.  Age is opt-in because a stream with intermittent source
        # activity may otherwise become empty merely while it is quiet.
        # Fine windows are an internal compaction boundary, not source-time
        # buckets: they use plotsrv's observation time.
        "retention": {
            "max_raw_records": 200,
            "max_raw_bytes": 8 * 1024 * 1024,
            "max_raw_age_s": None,
            "fine_window_s": 60,
            # Derived history keeps a recent fixed fine tier, a coarser fixed
            # tier, then one oldest cumulative aggregate. Every constituent
            # object has explicit field/category/value bounds.
            "max_fine_summary_windows": 32,
            "max_coarse_summary_windows": 24,
            "coarse_window_factor": 60,
            "max_summary_fields": 64,
            "max_categorical_values": 16,
            "max_categorical_value_bytes": 128,
            # Source records are individually bounded by the stream protocol,
            # and system notices have a fixed schema.  A single chronological
            # item cap therefore bounds their combined retained footprint.
            "max_noteworthy_items": 64,
        },
    },
    "storage-settings": {
        "enabled": False,
        "watch_enabled": False,
        "root_dir": ".plotsrv/store",
        "max_snapshot_size_mb": 20.0,
        "default_keep_last": 2,
        "default_min_store_interval": None,
        # Storage is best-effort live-state persistence. Bound objects waiting
        # to be serialised so a busy producer cannot retain an arbitrary queue.
        "max_pending_tasks": 32,
        "max_pending_mb": 64,
        "latest": {
            "enabled": True,
            "restore_on_startup": True,
            "restore_scope": "discovered",
        },
        # Stream storage is deliberately independent of snapshot retention.
        # Global storage remains the master opt-in; once it is enabled, compact
        # stream state is useful by default while source-row persistence stays
        # explicitly off.  The limits below apply to every retained stream
        # file, including metadata, so this cannot become an implicit log
        # archive.
        "streams": {
            "enabled": True,
            # This queue is independent from the ordinary snapshot/latest
            # worker. A busy stream therefore consumes only its own bounded
            # admission budget.
            "max_pending_tasks": 16,
            "max_pending_mb": 8.0,
            "raw_retention": None,
            "summary_retention": 64,
            "noteworthy_keep_last": 64,
            "keep_last_sessions": 8,
            "max_bytes_per_view_mb": 16.0,
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
    # Legacy section.
    # New preferred path is limits.published_objects.
    "publish-limits": {
        "max_plot_bytes": 5 * 1024 * 1024,
        "max_table_rows": 5_000,
        "max_table_columns": 200,
        "max_artifact_text_chars": 200_000,
        "max_json_container_items": 20_000,
    },
}

_MAX_TABLE_ROWS_INF: int = 1_000_000_000
_MAX_BROWSER_TABLE_PLOT_POINTS: int = 25_000


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


def _raw_render_settings() -> dict[str, Any]:
    return _raw_section("render-settings")


def _merged_render_settings() -> dict[str, Any]:
    """
    Preferred render settings section.

    settings.get_section("render-settings") already handles the common
    default/instances pattern, so this gives us the active render settings for
    the current runtime context.
    """
    return _merged_section("render-settings")


def _render_setting_is_explicit(key: str) -> bool:
    """
    Return True if the active user config explicitly provides render-settings.<key>.

    This lets new render-settings values win over legacy table/artifact settings
    without the built-in render defaults accidentally hiding legacy config.
    """
    raw = _raw_render_settings()

    if key in raw:
        return True

    raw_default = raw.get("default")
    if isinstance(raw_default, Mapping) and key in raw_default:
        return True

    return False


def _get_render_setting_prefer_new(
    key: str,
    *,
    legacy_section: str | None = None,
    legacy_key: str | None = None,
    default: Any = None,
) -> Any:
    """
    Read a setting from the new render-settings section first if explicitly set.

    Falls back to a legacy section if present, otherwise returns render/default.
    """
    render_sec = _merged_render_settings()

    if _render_setting_is_explicit(key):
        return render_sec.get(key, default)

    if legacy_section is not None:
        legacy_sec = _raw_section(legacy_section)
        lk = legacy_key or key
        if lk in legacy_sec:
            return legacy_sec.get(lk)

    return render_sec.get(key, default)


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

    Note:
      limits.tables.* is no longer treated as a publish limit. It is a legacy
      display/table-preparation setting only. New display truncation lives under
      limits.truncate_after.table_rows/table_columns.
    """
    raw_limits = _raw_limits_section()

    published_objects = _mapping_value(raw_limits, "published_objects")
    if key in published_objects:
        return _as_int_or_inf(published_objects.get(key), default, min_value=1)

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

    raw = _get_render_setting_prefer_new(
        "table_view_mode",
        legacy_section="table-settings",
        default="rich",
    )

    mode = str(raw or "rich").strip().lower()
    return "simple" if mode == "simple" else "rich"


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
    sec = _merged_render_settings()
    dpi = _as_int_or_inf(sec.get("plot_dpi"), 200, min_value=50)
    return int(dpi)


def get_plot_default_figsize_in() -> tuple[float, float] | None:
    sec = _merged_render_settings()
    val = sec.get("plot_default_figsize_in", (12.0, 6.0))
    return _parse_figsize(val)


def get_plot_bbox_tight() -> bool:
    sec = _merged_render_settings()
    return _as_bool(sec.get("plot_bbox_tight"), True)


def get_plot_pad_inches() -> float:
    sec = _merged_render_settings()
    return _as_float(sec.get("plot_pad_inches"), 0.10, min_value=0.0)


def get_table_plot_max_points() -> int:
    """Return the browser SVG point ceiling, capped at a safe hard maximum."""
    sec = _merged_render_settings()
    requested = _as_int_or_inf(
        sec.get("table_plot_max_points"),
        5_000,
        min_value=1,
    )
    return min(int(requested), _MAX_BROWSER_TABLE_PLOT_POINTS)


# ---- Artifact render settings ------------------------------------------------


def get_html_sanitize() -> bool:
    raw = _get_render_setting_prefer_new(
        "html_sanitize",
        legacy_section="artifact-render-settings",
        default=False,
    )
    return _as_bool(raw, False)


def get_html_sandbox() -> str:
    raw = _get_render_setting_prefer_new(
        "html_sandbox",
        legacy_section="artifact-render-settings",
        default="",
    )
    if isinstance(raw, str):
        return raw.strip()
    return ""


def get_markdown_sanitize() -> bool:
    raw = _get_render_setting_prefer_new(
        "markdown_sanitize",
        legacy_section="artifact-render-settings",
        default=True,
    )
    return _as_bool(raw, True)


def get_markdown_sandbox() -> str:
    raw = _get_render_setting_prefer_new(
        "markdown_sandbox",
        legacy_section="artifact-render-settings",
        default="",
    )
    if isinstance(raw, str):
        return raw.strip()
    return ""


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


def get_watch_materialization() -> WatchMaterialization:
    """
    How watched files should be represented.

    Values:
      - "memory": current behaviour; read/coerce/publish into memory.
      - "file": file-backed watched views where supported.
      - "auto": memory for small files, file-backed for larger files.

    This does not control how much of a watched file is read for preview.
    That remains limits.watched_files.max_mb.
    """
    sec = _merged_section("watch-settings")
    raw = str(sec.get("materialization") or "auto").strip().lower()

    if raw in ("auto", "memory", "file"):
        return raw  # type: ignore[return-value]

    return "auto"


def get_watch_file_threshold_bytes() -> int:
    """
    File size threshold used when watch-settings.materialization is "auto".

    Files smaller than this can use memory materialisation.
    Files at or above this threshold can use file-backed materialisation.

    Invalid/off/null values fall back to the default threshold.
    """
    sec = _merged_section("watch-settings")
    default_mb = _DEFAULTS["watch-settings"]["file_threshold_mb"]

    parsed = _parse_mb_to_bytes(
        sec.get("file_threshold_mb"),
        default_mb,
        min_value=0.000001,
    )

    if parsed is None:
        return int(float(default_mb) * _MB)

    return parsed


def _get_watch_active_load_setting(*keys: str, default: Any) -> Any:
    """
    Look up a file-backed request-load setting.

    ``active_loads`` is the documented spelling. Hyphenated spellings are
    accepted too, so the setting remains pleasant to use in hand-written YAML.
    """
    # Check the unmerged user section first. Otherwise the default
    # ``active_loads`` mapping would mask a user's hyphenated ``active-loads``
    # spelling during the later merged lookup.
    raw_sec = settings.get_section("watch-settings")
    active = raw_sec.get("active_loads")
    if not isinstance(active, Mapping):
        active = raw_sec.get("active-loads")
    if not isinstance(active, Mapping):
        sec = _merged_section("watch-settings")
        active = sec.get("active_loads")
    if not isinstance(active, Mapping):
        active = _merged_section("watch-settings").get("active-loads")
    if not isinstance(active, Mapping):
        return default

    for key in keys:
        if key in active:
            return active[key]
    return default


def get_watch_active_load_max_concurrent() -> int:
    """Maximum concurrent file-backed preview materialisations."""
    default = int(_DEFAULTS["watch-settings"]["active_loads"]["max_concurrent"])
    raw = _get_watch_active_load_setting(
        "max_concurrent",
        "max-concurrent",
        default=default,
    )
    try:
        value = int(float(raw))
    except Exception:
        return default
    return value if value >= 1 else default


def get_watch_active_load_wait_timeout_s() -> float:
    """How long a request may wait for a file-backed preview slot."""
    default = float(_DEFAULTS["watch-settings"]["active_loads"]["wait_timeout_s"])
    raw = _get_watch_active_load_setting(
        "wait_timeout_s",
        "wait-timeout-s",
        default=default,
    )
    try:
        value = float(raw)
    except Exception:
        return default
    return value if value >= 0 else default


# ---- Live publish settings ---------------------------------------------------


def _publish_live_settings() -> dict[str, Any]:
    sec = _merged_section("publish-settings")
    live = sec.get("live")
    default_live = _DEFAULTS["publish-settings"]["live"]
    if not isinstance(live, Mapping):
        return dict(default_live)
    return _deep_merge_dicts(dict(default_live), dict(live))


def get_publish_async_enabled() -> bool:
    """Whether live publish calls use the bounded worker by default."""
    live = _publish_live_settings()
    default = bool(_DEFAULTS["publish-settings"]["live"]["async_enabled"])
    return _as_bool(live.get("async_enabled"), default)


def get_publish_max_pending_views() -> int:
    """Maximum distinct destination/view updates retained by PublishWorker."""
    default = int(_DEFAULTS["publish-settings"]["live"]["max_pending_views"])
    raw = _publish_live_settings().get("max_pending_views")
    value = _as_int_or_inf(raw, default, min_value=1)
    return max(1, value)


def get_publish_max_pending_bytes() -> int:
    """Maximum estimated bytes retained by pending live publish tasks."""
    default_mb = float(_DEFAULTS["publish-settings"]["live"]["max_pending_mb"])
    value = _parse_mb_to_bytes(
        _publish_live_settings().get("max_pending_mb"),
        default_mb,
    )
    if value is None or value < 1:
        return int(default_mb * 1024 * 1024)
    return value


def get_publish_flush_timeout_s() -> float:
    """Default short timeout used when stopping an attached plotsrv server."""
    default = float(_DEFAULTS["publish-settings"]["live"]["flush_timeout_s"])
    value = _as_float(_publish_live_settings().get("flush_timeout_s"), default)
    return value if value >= 0 else default


# ---- Stream settings ---------------------------------------------------------


def _stream_settings() -> dict[str, Any]:
    return _merged_section("stream-settings")


def _stream_retention_settings() -> dict[str, Any]:
    """Return stream retention defaults merged with its nested YAML section."""
    default = dict(_DEFAULTS["stream-settings"]["retention"])
    raw = _stream_settings().get("retention")
    return _deep_merge_dicts(default, dict(raw)) if isinstance(raw, Mapping) else default


def get_stream_raw_max_records() -> int:
    """Maximum source records retained in a stream's recent raw window."""
    default = int(_DEFAULTS["stream-settings"]["retention"]["max_raw_records"])
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_raw_records"),
            default,
            min_value=1,
        ),
    )


def get_stream_raw_max_bytes() -> int:
    """Maximum canonical source bytes retained in a stream's raw window."""
    default = int(_DEFAULTS["stream-settings"]["retention"]["max_raw_bytes"])
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_raw_bytes"),
            default,
            min_value=1,
        ),
    )


def get_stream_raw_max_age_s() -> float | None:
    """Optional maximum plotsrv-observation age for raw stream records."""
    raw = _stream_retention_settings().get("max_raw_age_s")
    if raw is None or raw is False:
        return None
    if isinstance(raw, str) and raw.strip().lower() in {
        "",
        "off",
        "none",
        "null",
        "false",
        "no",
        "0",
    }:
        return None
    value = _as_float(raw, 0.0, min_value=0.001)
    return value if value >= 0.001 else None


def get_stream_fine_window_s() -> int:
    """Fixed observation-time resolution used for the initial fine handoff."""
    default = int(_DEFAULTS["stream-settings"]["retention"]["fine_window_s"])
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("fine_window_s"),
            default,
            min_value=1,
        ),
    )


def get_stream_max_fine_summary_windows() -> int:
    """Maximum retained fixed fine summary windows per stream."""
    default = int(
        _DEFAULTS["stream-settings"]["retention"]["max_fine_summary_windows"]
    )
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_fine_summary_windows"),
            default,
            min_value=1,
        ),
    )


def get_stream_max_coarse_summary_windows() -> int:
    """Maximum retained fixed coarse summary windows per stream."""
    default = int(
        _DEFAULTS["stream-settings"]["retention"]["max_coarse_summary_windows"]
    )
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_coarse_summary_windows"),
            default,
            min_value=1,
        ),
    )


def get_stream_coarse_window_factor() -> int:
    """Number of fine intervals in one deterministic coarse interval."""
    default = int(
        _DEFAULTS["stream-settings"]["retention"]["coarse_window_factor"]
    )
    return max(
        2,
        _as_int_or_inf(
            _stream_retention_settings().get("coarse_window_factor"),
            default,
            min_value=2,
        ),
    )


def get_stream_max_summary_fields() -> int:
    """Maximum deterministically selected fields held by one summary window."""
    default = int(
        _DEFAULTS["stream-settings"]["retention"]["max_summary_fields"]
    )
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_summary_fields"),
            default,
            min_value=1,
        ),
    )


def get_stream_max_categorical_values() -> int:
    """Maximum exact scalar categories retained per field/window."""
    default = int(
        _DEFAULTS["stream-settings"]["retention"]["max_categorical_values"]
    )
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_categorical_values"),
            default,
            min_value=1,
        ),
    )


def get_stream_max_categorical_value_bytes() -> int:
    """Maximum canonical byte length retained for one categorical scalar."""
    default = int(
        _DEFAULTS["stream-settings"]["retention"]["max_categorical_value_bytes"]
    )
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_categorical_value_bytes"),
            default,
            min_value=1,
        ),
    )


def get_stream_max_noteworthy_items() -> int:
    """Maximum source noteworthy records and system notices held per stream."""
    default = int(
        _DEFAULTS["stream-settings"]["retention"]["max_noteworthy_items"]
    )
    return max(
        1,
        _as_int_or_inf(
            _stream_retention_settings().get("max_noteworthy_items"),
            default,
            min_value=1,
        ),
    )


def get_stream_poll_interval_s() -> float:
    """Polling interval for local JSONL observation."""
    default = float(_DEFAULTS["stream-settings"]["poll_interval_s"])
    return _as_float(_stream_settings().get("poll_interval_s"), default, min_value=0.001)


def get_stream_request_timeout_s() -> float:
    """Bounded HTTP wait time for one stream registration or append attempt."""
    default = float(_DEFAULTS["stream-settings"]["request_timeout_s"])
    return _as_float(
        _stream_settings().get("request_timeout_s"), default, min_value=0.001
    )


def get_stream_retry_initial_delay_s() -> float:
    """First delay used after a temporary stream transport failure."""
    default = float(_DEFAULTS["stream-settings"]["retry_initial_delay_s"])
    return _as_float(
        _stream_settings().get("retry_initial_delay_s"), default, min_value=0.001
    )


def get_stream_retry_max_delay_s() -> float:
    """Maximum capped stream transport retry delay."""
    initial = get_stream_retry_initial_delay_s()
    default = float(_DEFAULTS["stream-settings"]["retry_max_delay_s"])
    value = _as_float(
        _stream_settings().get("retry_max_delay_s"), default, min_value=initial
    )
    return max(initial, value)


def get_stream_heartbeat_interval_s() -> float:
    """Interval between producer lifecycle heartbeats."""
    default = float(_DEFAULTS["stream-settings"]["heartbeat_interval_s"])
    return _as_float(
        _stream_settings().get("heartbeat_interval_s"), default, min_value=0.001
    )


def get_stream_heartbeat_timeout_s() -> float:
    """Server-side expiry window for a producer heartbeat."""
    interval = get_stream_heartbeat_interval_s()
    default = float(_DEFAULTS["stream-settings"]["heartbeat_timeout_s"])
    value = _as_float(
        _stream_settings().get("heartbeat_timeout_s"), default, min_value=interval
    )
    return max(interval, value)


def get_stream_shutdown_drain_timeout_s() -> float:
    """Finite default budget for one explicit stream final-drain attempt."""
    default = float(_DEFAULTS["stream-settings"]["shutdown_drain_timeout_s"])
    return _as_float(
        _stream_settings().get("shutdown_drain_timeout_s"),
        default,
        min_value=0.001,
    )


def get_stream_process_exit_cleanup_timeout_s() -> float:
    """Finite total budget used by the one stream atexit cleanup manager."""
    default = float(_DEFAULTS["stream-settings"]["process_exit_cleanup_timeout_s"])
    return _as_float(
        _stream_settings().get("process_exit_cleanup_timeout_s"),
        default,
        min_value=0.001,
    )


# ---- Storage settings ---------------------------------------------------------


def get_storage_enabled() -> bool:
    sec = _merged_section("storage-settings")
    return _as_bool(sec.get("enabled"), False)


def get_storage_max_pending_tasks() -> int:
    """Maximum best-effort storage tasks retained before serialisation."""
    default = int(_DEFAULTS["storage-settings"]["max_pending_tasks"])
    value = _as_int_or_inf(
        _merged_section("storage-settings").get("max_pending_tasks"),
        default,
        min_value=1,
    )
    return max(1, value)


def get_storage_max_pending_bytes() -> int:
    """Maximum estimated bytes held by queued storage tasks."""
    default_mb = float(_DEFAULTS["storage-settings"]["max_pending_mb"])
    value = _parse_mb_to_bytes(
        _merged_section("storage-settings").get("max_pending_mb"),
        default_mb,
    )
    if value is None or value < 1:
        return int(default_mb * 1024 * 1024)
    return value


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


def _storage_stream_settings(view_id: str | None = None) -> dict[str, Any]:
    """Return bounded stream-storage settings, including a view override.

    The existing ``storage-settings.views.<view>`` mapping retains its
    snapshot semantics.  Its nested singular ``stream`` mapping is the
    stream-specific override, so ordinary ``keep_last`` never accidentally
    becomes a source-record policy.  ``streams`` is accepted as a harmless
    spelling alias for early configuration drafts.
    """
    defaults = dict(_DEFAULTS["storage-settings"]["streams"])
    storage = _merged_section("storage-settings")
    configured = storage.get("streams")
    if isinstance(configured, Mapping):
        defaults = _deep_merge_dicts(defaults, dict(configured))

    if view_id is None:
        return defaults

    view = get_storage_view_settings(view_id)
    override = view.get("stream")
    if not isinstance(override, Mapping):
        override = view.get("streams")
    if isinstance(override, Mapping):
        return _deep_merge_dicts(defaults, dict(override))
    return defaults


def get_storage_stream_enabled(view_id: str | None = None) -> bool:
    """Whether compact stream persistence is enabled for one logical view."""
    if not get_storage_enabled():
        return False
    return _as_bool(_storage_stream_settings(view_id).get("enabled"), True)


def get_storage_stream_summary_retention(view_id: str | None = None) -> int:
    """Maximum persisted derived-summary windows for one stream session."""
    default = int(_DEFAULTS["storage-settings"]["streams"]["summary_retention"])
    return max(
        1,
        _as_int_or_inf(
            _storage_stream_settings(view_id).get("summary_retention"),
            default,
            min_value=1,
        ),
    )


def get_storage_stream_max_pending_tasks() -> int:
    """Maximum compact stream persistence tasks held independently in memory."""
    default = int(_DEFAULTS["storage-settings"]["streams"]["max_pending_tasks"])
    return max(
        1,
        _as_int_or_inf(
            _storage_stream_settings().get("max_pending_tasks"),
            default,
            min_value=1,
        ),
    )


def get_storage_stream_max_pending_bytes() -> int:
    """Maximum estimated bytes held by the independent stream queue."""
    default_mb = float(_DEFAULTS["storage-settings"]["streams"]["max_pending_mb"])
    value = _parse_mb_to_bytes(
        _storage_stream_settings().get("max_pending_mb"),
        default_mb,
    )
    return max(1, int(default_mb * _MB) if value is None else value)


def get_storage_stream_noteworthy_keep_last(view_id: str | None = None) -> int:
    """Maximum persisted noteworthy or continuity items for a session."""
    default = int(
        _DEFAULTS["storage-settings"]["streams"]["noteworthy_keep_last"]
    )
    return max(
        1,
        _as_int_or_inf(
            _storage_stream_settings(view_id).get("noteworthy_keep_last"),
            default,
            min_value=1,
        ),
    )


def get_storage_stream_keep_last_sessions(view_id: str | None = None) -> int:
    """Maximum retained persisted stream sessions for a logical view."""
    default = int(
        _DEFAULTS["storage-settings"]["streams"]["keep_last_sessions"]
    )
    return max(
        1,
        _as_int_or_inf(
            _storage_stream_settings(view_id).get("keep_last_sessions"),
            default,
            min_value=1,
        ),
    )


def get_storage_stream_max_bytes_per_view(view_id: str | None = None) -> int:
    """Hard byte ceiling for all persisted stream sessions of one view."""
    default_mb = float(
        _DEFAULTS["storage-settings"]["streams"]["max_bytes_per_view_mb"]
    )
    value = _parse_mb_to_bytes(
        _storage_stream_settings(view_id).get("max_bytes_per_view_mb"),
        default_mb,
    )
    return max(1, int(default_mb * _MB) if value is None else value)


def get_storage_stream_raw_retention(
    view_id: str | None = None,
) -> dict[str, Any] | None:
    """Return an explicitly enabled raw-block policy, otherwise ``None``.

    A mapping is required to opt in.  This prevents a truthy global storage
    setting, a bare boolean, or inherited stream-memory limits from silently
    enabling raw source persistence.
    """
    raw = _storage_stream_settings(view_id).get("raw_retention")
    if not isinstance(raw, Mapping):
        return None
    if not _as_bool(raw.get("enabled"), True):
        return None
    return dict(raw)


def get_storage_stream_raw_enabled(view_id: str | None = None) -> bool:
    """Whether raw stream blocks have been explicitly configured to persist."""
    return (
        get_storage_stream_enabled(view_id)
        and get_storage_stream_raw_retention(view_id) is not None
    )


def get_storage_stream_raw_max_blocks(view_id: str | None = None) -> int:
    """Bound explicitly enabled raw persistence to a finite block count."""
    raw = get_storage_stream_raw_retention(view_id)
    if raw is None:
        return 0
    return max(1, _as_int_or_inf(raw.get("max_blocks"), 16, min_value=1))


def get_storage_stream_raw_max_bytes(view_id: str | None = None) -> int:
    """Bound explicitly enabled raw persistence before the per-view hard cap."""
    raw = get_storage_stream_raw_retention(view_id)
    if raw is None:
        return 0
    value = _parse_mb_to_bytes(raw.get("max_bytes_mb"), 4.0)
    raw_limit = max(1, int(4.0 * _MB) if value is None else value)
    return min(raw_limit, get_storage_stream_max_bytes_per_view(view_id))


def get_storage_stream_raw_max_age_s(view_id: str | None = None) -> int | None:
    """Optional age retention for raw blocks; count and bytes always apply."""
    raw = get_storage_stream_raw_retention(view_id)
    if raw is None:
        return None
    return _parse_duration_seconds(raw.get("max_age_s"))


def _storage_view_overrides() -> dict[str, Any]:
    sec = _merged_section("storage-settings")
    views = sec.get("views")
    return views if isinstance(views, dict) else {}


def get_storage_view_settings(view_id: str) -> dict[str, Any]:
    overrides = _storage_view_overrides()
    raw = overrides.get(view_id)
    return dict(raw) if isinstance(raw, dict) else {}


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


def has_freshness_view_config(view_id: str | None) -> bool:
    """
    Return True when freshness-settings.views contains an explicit entry
    for this view.

    Used to keep global freshness from applying to watched-file views unless
    the user opted that watched view into freshness.
    """
    if not view_id:
        return False

    views = _freshness_view_overrides()
    return str(view_id) in views


def get_freshness_view_enabled(view_id: str | None) -> bool:
    """
    Per-view enabled flag.

    The global freshness-settings.enabled remains the master switch.
    This helper only answers whether a configured view has opted itself out.
    """
    if not view_id:
        return True

    view_sec = get_freshness_view_settings(str(view_id))
    if "enabled" in view_sec:
        return _as_bool(view_sec.get("enabled"), True)

    return True


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
