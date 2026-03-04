# src/plotsrv/config.py
from __future__ import annotations

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

# Defaults (match your current defaults)
_DEFAULTS: dict[str, Any] = {
    "table-settings": {
        "table_view_mode": "rich",
        "max_table_rows_simple": 200,
        "max_table_rows_rich": 1000,
    },
    "render-settings": {
        "plot_dpi": 200,
        "plot_default_figsize_in": (12.0, 6.0),  # tuple[float,float] | None
        "plot_bbox_tight": True,
        "plot_pad_inches": 0.10,
    },
    "view-order-settings": {
        # sections: list[str]
        # labels: {section: [labels...]}
    },
    "truncation": {
        # defaults:
        # - text: 50_000 (existing behaviour)
        # - html/markdown: OFF by default (your request)
        "text": 50_000,
        "html": None,
        "markdown": None,
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
    # allow:
    # - null/None => disable
    # - "12,6" / "12x6"
    # - [12, 6]
    # - {"w": 12, "h": 6}
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
# Note: JSON is explicitly "do nothing".
# We only use this for text/html/markdown for now.


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
