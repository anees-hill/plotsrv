# src/plotsrv/config.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
    "view-order-settings": {},
    "truncation": {
        "text": 50_000,
        "html": None,
        "markdown": None,
    },
    # 0.0.5 storage defaults are intentionally conservative and opt-in.
    "storage-settings": {
        "enabled": False,
        "root_dir": ".plotsrv/store",
        "max_snapshot_size_mb": 20.0,
        "default_keep_last": 2,
        "default_min_store_interval": None,
        "views": {},
    },
    "freshness-settings": {
        "enabled": False,
        "expected_every": None,
        "warn_after": None,
        "error_after": None,
        "views": {},
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


# ---- Truncation ---------------------------------------------------------------


def get_truncation_max_chars(kind: Literal["text", "html", "markdown"]) -> int | None:
    """
    Returns:
      - int => truncate to this max chars
      - None => truncation disabled for this kind
    """
    override = settings.get_truncate_override()

    if not settings.is_truncate_override_unset(override):
        if settings.is_truncate_override_off(override):
            return None
        return int(max(1, int(override)))

    sec = _merged_section("truncation")
    val = sec.get(kind)

    if val is None:
        return None

    if isinstance(val, str) and val.strip().lower() in (
        "off",
        "none",
        "false",
        "0",
        "",
    ):
        return None

    default_val = _DEFAULTS["truncation"].get(kind)
    if default_val is None:
        return None

    return _as_int_or_inf(val, int(default_val), min_value=1)


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


def get_storage_max_snapshot_size_bytes() -> int:
    sec = _merged_section("storage-settings")
    mb = _as_float(sec.get("max_snapshot_size_mb"), 20.0, min_value=0.001)
    return max(1, int(mb * 1024 * 1024))


def get_storage_default_keep_last() -> int | None:
    sec = _merged_section("storage-settings")
    return _as_keep_last(sec.get("default_keep_last"), 2)


def get_storage_default_min_store_interval_s() -> int | None:
    sec = _merged_section("storage-settings")
    return _parse_duration_seconds(sec.get("default_min_store_interval"))


def _storage_view_overrides() -> dict[str, Any]:
    sec = _merged_section("storage-settings")
    views = sec.get("views")
    return views if isinstance(views, dict) else {}


def get_storage_view_settings(view_id: str) -> dict[str, Any]:
    """
    Exact view_id match only for 0.0.5 foundation.
    """
    overrides = _storage_view_overrides()
    raw = overrides.get(view_id)
    return dict(raw) if isinstance(raw, dict) else {}


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


def get_freshness_error_after_s(view_id: str | None = None) -> int | None:
    sec = _merged_section("freshness-settings")
    if view_id:
        view_sec = get_freshness_view_settings(view_id)
        if "error_after" in view_sec:
            return _parse_duration_seconds(view_sec.get("error_after"))
    return _parse_duration_seconds(sec.get("error_after"))
