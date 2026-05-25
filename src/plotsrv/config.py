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
        "watched_files": {
            "max_bytes": 5_000_000,
        },
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
      limits.render.<kind>
      limits.views.<view_id>.render.<kind>

    Legacy config path:
      truncation.<kind>

    Runtime/CLI truncate override remains global and wins.
    """
    override = settings.get_truncate_override()

    if not settings.is_truncate_override_unset(override):
        if settings.is_truncate_override_off(override):
            return None
        return int(max(1, int(override)))

    # Use the raw user-supplied limits section first.
    # Do NOT use _merged_limits_section() here for render defaults, because that
    # would make built-in limits.render defaults override legacy truncation config.
    raw_limits = settings.get_section("limits")

    if view_id and isinstance(raw_limits, dict):
        raw_views = raw_limits.get("views")
        raw_view_limits = (
            raw_views.get(view_id) if isinstance(raw_views, dict) else None
        )
        raw_view_render = (
            raw_view_limits.get("render") if isinstance(raw_view_limits, dict) else None
        )

        if isinstance(raw_view_render, dict) and kind in raw_view_render:
            default_val = _DEFAULTS["limits"]["render"].get(kind)
            return _parse_limit_int_or_none(
                raw_view_render.get(kind),
                default_val,
                min_value=1,
            )

    raw_render = raw_limits.get("render") if isinstance(raw_limits, dict) else None
    if isinstance(raw_render, dict) and kind in raw_render:
        default_val = _DEFAULTS["limits"]["render"].get(kind)
        return _parse_limit_int_or_none(
            raw_render.get(kind),
            default_val,
            min_value=1,
        )

    # Legacy config section.
    raw_truncation = settings.get_section("truncation")
    if isinstance(raw_truncation, dict) and kind in raw_truncation:
        val = raw_truncation.get(kind)
        default_val = _DEFAULTS["truncation"].get(kind)

        if val is None:
            return None

        if isinstance(val, str) and val.strip().lower() in (
            "off",
            "none",
            "false",
            "no",
            "0",
            "",
        ):
            return None

        if default_val is None:
            return _parse_limit_int_or_none(val, None, min_value=1)

        return _as_int_or_inf(val, int(default_val), min_value=1)

    # Built-in defaults.
    default_val = _DEFAULTS["limits"]["render"].get(kind)
    return _parse_limit_int_or_none(default_val, default_val, min_value=1)


def get_watch_max_bytes(view_id: str | None = None) -> int | None:
    """
    Maximum bytes read from watched files.

    Preferred config path:
      limits.watched_files.max_bytes

    Returns:
      - int => read at most this many bytes
      - None => read the whole file

    Note:
      view_id is accepted for API stability, but watched-file input limits are
      currently global only. Use per-view render limits for display behaviour.
    """
    limits = _merged_limits_section()
    watched = limits.get("watched_files")
    if not isinstance(watched, dict):
        watched = {}

    default_val = _DEFAULTS["limits"]["watched_files"]["max_bytes"]
    return _parse_limit_int_or_none(
        watched.get("max_bytes", default_val),
        default_val,
        min_value=1,
    )


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
    sec = _merged_section("publish-limits")
    return _as_int_or_inf(sec.get("max_plot_bytes"), 5 * 1024 * 1024, min_value=1)


def get_publish_max_table_rows() -> int:
    raw_limits = settings.get_section("limits")
    tables = raw_limits.get("tables") if isinstance(raw_limits, dict) else None
    if isinstance(tables, dict) and "max_rows" in tables:
        return _as_int_or_inf(tables.get("max_rows"), 5000, min_value=1)

    sec = _merged_section("publish-limits")
    return _as_int_or_inf(sec.get("max_table_rows"), 5000, min_value=1)


def get_publish_max_table_columns() -> int:
    raw_limits = settings.get_section("limits")
    tables = raw_limits.get("tables") if isinstance(raw_limits, dict) else None
    if isinstance(tables, dict) and "max_columns" in tables:
        return _as_int_or_inf(tables.get("max_columns"), 200, min_value=1)

    sec = _merged_section("publish-limits")
    return _as_int_or_inf(sec.get("max_table_columns"), 200, min_value=1)


def get_publish_max_artifact_text_chars() -> int:
    sec = _merged_section("publish-limits")
    return _as_int_or_inf(sec.get("max_artifact_text_chars"), 200_000, min_value=1)


def get_publish_max_json_container_items() -> int:
    sec = _merged_section("publish-limits")
    return _as_int_or_inf(sec.get("max_json_container_items"), 20_000, min_value=1)
