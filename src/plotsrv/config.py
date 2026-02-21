# src/plotsrv/config.py
from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Literal

TableViewMode = Literal["simple", "rich"]

TABLE_VIEW_MODE: TableViewMode = "rich"
MAX_TABLE_ROWS_SIMPLE: int = 200
MAX_TABLE_ROWS_RICH: int = 1000
_MAX_TABLE_ROWS_INF: int = 1_000_000_000

# Plot rendering defaults (static PNG generation)

# Higher default DPI makes PNGs crisper on high-res displays.
PLOT_DPI: int = 200

# If set, and the incoming matplotlib Figure is still at the default size,
# we will "upgrade" it to this size for rendering only.
PLOT_DEFAULT_FIGSIZE_IN: tuple[float, float] | None = (12.0, 6.0)

# Keep tight bounding box, but allow padding so labels don't get clipped.
PLOT_BBOX_TIGHT: bool = True
PLOT_PAD_INCHES: float = 0.10

# View ordering (optional)

# If set, these determine dropdown ordering:
# - sections listed come first in the given order
# - remaining sections come afterwards alphabetically
# - labels.<section> listed come first in given order within section
# - remaining labels come afterwards alphabetically
VIEW_ORDER_SECTIONS: list[str] | None = None
VIEW_ORDER_LABELS: dict[str, list[str]] = {}

# Internal: lazy load ini once
_LOADED_RENDER_SETTINGS: bool = False


def get_table_view_mode() -> TableViewMode:
    _load_ini_settings_once()
    return TABLE_VIEW_MODE


def set_table_view_mode(mode: TableViewMode) -> None:
    """
    Set how DataFrames are shown in the browser.

    - "simple": static HTML (df.head(N).to_html()).
    - "rich": Tabulator JS grid over a sample of the DataFrame.
    """
    global TABLE_VIEW_MODE
    if mode not in ("simple", "rich"):
        raise ValueError("table_view_mode must be 'simple' or 'rich'")
    TABLE_VIEW_MODE = mode


# plotsrv.ini resolution + parsing (render settings)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == "'") or (s[0] == s[-1] == '"')):
        return s[1:-1].strip()
    return s


def _resolve_ini_path() -> Path | None:
    """
    Resolution order:
      1) env var PLOTSRV_INI
      2) ./plotsrv.ini (cwd)
      3) None
    """
    env_path = os.environ.get("PLOTSRV_INI")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists() and p.is_file():
            return p

    cwd_ini = Path.cwd() / "plotsrv.ini"
    if cwd_ini.exists() and cwd_ini.is_file():
        return cwd_ini

    return None


def _parse_table_view_mode(raw: str, default: TableViewMode) -> TableViewMode:
    s = _strip_quotes(raw).strip().lower()
    if s in ("simple", "rich"):
        return s  # type: ignore[return-value]
    return default


def _parse_int_or_inf(raw: str, *, default: int, min_value: int = 1) -> int:
    s = _strip_quotes(raw).strip().lower()

    if s in ("inf", "infinity", "none", "null", ""):
        return _MAX_TABLE_ROWS_INF

    try:
        n = int(float(s))  # allow "1000.0"
        if n >= min_value:
            return n
    except Exception:
        pass

    return default


def _parse_listish(raw: str) -> list[str]:
    """
    Parse an ini value into an ordered list of strings.

    Supports:
      - comma-separated: "a, b, c"
      - multiline values:
            a
            b
            c
      - mixtures of both
    """
    s = _strip_quotes(raw)
    if not s.strip():
        return []

    # Normalize commas to newlines, then splitlines.
    s = s.replace(",", "\n")
    items: list[str] = []
    for line in s.splitlines():
        t = line.strip()
        if t:
            items.append(t)
    return items


def get_view_order_sections() -> list[str] | None:
    _load_ini_settings_once()
    return list(VIEW_ORDER_SECTIONS) if VIEW_ORDER_SECTIONS else None


def get_view_order_labels(section: str) -> list[str] | None:
    _load_ini_settings_once()
    key = (section or "").strip()
    vals = VIEW_ORDER_LABELS.get(key)
    return list(vals) if vals else None


def _load_ini_settings_once() -> None:
    """
    Read settings from plotsrv.ini once.

    Sections:

    [view-order-settings]
      sections = polars, pandas, plotnine
      # OR multiline:
      # sections =
      #   polars
      #   pandas
      #   plotnine
      #
      # label ordering per section:
      # labels.polars = MEM-USED, CPU%
      # labels.pandas =
      #   A
      #   B

    [table-settings]
      table_view_mode = rich
      max_table_rows_simple = 200
      max_table_rows_rich = 1000
      # use "inf" to effectively disable limits:
      # max_table_rows_rich = inf

    [render-settings]
      plot_dpi = 200
      plot_default_figsize_in = 12,6   # or blank to disable
      plot_bbox_tight = true
      plot_pad_inches = 0.10
    """
    global _LOADED_RENDER_SETTINGS
    global TABLE_VIEW_MODE, MAX_TABLE_ROWS_SIMPLE, MAX_TABLE_ROWS_RICH
    global PLOT_DPI, PLOT_DEFAULT_FIGSIZE_IN, PLOT_BBOX_TIGHT, PLOT_PAD_INCHES
    global VIEW_ORDER_SECTIONS, VIEW_ORDER_LABELS

    if _LOADED_RENDER_SETTINGS:
        return

    _LOADED_RENDER_SETTINGS = True
    ini_path = _resolve_ini_path()
    if ini_path is None:
        return

    cfg = configparser.ConfigParser()
    cfg.read(ini_path)

    # view-order-settings
    osec = "view-order-settings"
    if cfg.has_section(osec):
        # sections = ...
        try:
            raw = cfg.get(osec, "sections", fallback="").strip()
            sections = _parse_listish(raw)
            VIEW_ORDER_SECTIONS = sections or None
        except Exception:
            pass

        # labels.<section> = ...
        # e.g. labels.polars = MEM-USED, CPU%
        try:
            for key, val in cfg.items(osec):
                k = key.strip()
                if not k.startswith("labels."):
                    continue
                sec = k[len("labels.") :].strip()
                if not sec:
                    continue
                labels = _parse_listish(val)
                if labels:
                    VIEW_ORDER_LABELS[sec] = labels
        except Exception:
            pass

    # table-settings
    tsec = "table-settings"
    if cfg.has_section(tsec):
        # table_view_mode
        try:
            raw_mode = cfg.get(tsec, "table_view_mode", fallback=str(TABLE_VIEW_MODE))
            TABLE_VIEW_MODE = _parse_table_view_mode(raw_mode, TABLE_VIEW_MODE)
        except Exception:
            pass

        # max_table_rows_simple / rich (supports inf)
        try:
            raw = cfg.get(
                tsec, "max_table_rows_simple", fallback=str(MAX_TABLE_ROWS_SIMPLE)
            )
            MAX_TABLE_ROWS_SIMPLE = _parse_int_or_inf(
                raw, default=MAX_TABLE_ROWS_SIMPLE, min_value=1
            )
        except Exception:
            pass

        try:
            raw = cfg.get(
                tsec, "max_table_rows_rich", fallback=str(MAX_TABLE_ROWS_RICH)
            )
            MAX_TABLE_ROWS_RICH = _parse_int_or_inf(
                raw, default=MAX_TABLE_ROWS_RICH, min_value=1
            )
        except Exception:
            pass

    # render-settings
    rsec = "render-settings"
    if not cfg.has_section(rsec):
        return

    # plot_dpi
    try:
        dpi = cfg.getint(rsec, "plot_dpi", fallback=PLOT_DPI)
        if dpi >= 50:
            PLOT_DPI = dpi
    except Exception:
        pass

    # plot_default_figsize_in
    raw_size = _strip_quotes(
        cfg.get(rsec, "plot_default_figsize_in", fallback="")
    ).strip()
    if raw_size:
        try:
            parts = [p.strip() for p in raw_size.replace("x", ",").split(",")]
            w = float(parts[0])
            h = float(parts[1])
            if w > 0 and h > 0:
                PLOT_DEFAULT_FIGSIZE_IN = (w, h)
        except Exception:
            pass
    else:
        PLOT_DEFAULT_FIGSIZE_IN = None

    # plot_bbox_tight
    try:
        PLOT_BBOX_TIGHT = cfg.getboolean(
            rsec, "plot_bbox_tight", fallback=PLOT_BBOX_TIGHT
        )
    except Exception:
        pass

    # plot_pad_inches
    try:
        pad = float(
            _strip_quotes(
                cfg.get(rsec, "plot_pad_inches", fallback=str(PLOT_PAD_INCHES))
            )
        )
        if pad >= 0:
            PLOT_PAD_INCHES = pad
    except Exception:
        pass


# Public getters for render settings (ensure ini loaded)


def get_plot_dpi() -> int:
    _load_ini_settings_once()
    return int(PLOT_DPI)


def get_plot_default_figsize_in() -> tuple[float, float] | None:
    _load_ini_settings_once()
    return PLOT_DEFAULT_FIGSIZE_IN


def get_plot_bbox_tight() -> bool:
    _load_ini_settings_once()
    return bool(PLOT_BBOX_TIGHT)


def get_plot_pad_inches() -> float:
    _load_ini_settings_once()
    return float(PLOT_PAD_INCHES)


def get_max_table_rows_simple() -> int:
    _load_ini_settings_once()
    return int(MAX_TABLE_ROWS_SIMPLE)


def get_max_table_rows_rich() -> int:
    _load_ini_settings_once()
    return int(MAX_TABLE_ROWS_RICH)
