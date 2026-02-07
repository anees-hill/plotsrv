# src/plotsrv/config.py
from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Literal

TableViewMode = Literal["simple", "rich"]

TABLE_VIEW_MODE: TableViewMode = "simple"
MAX_TABLE_ROWS_SIMPLE: int = 200
MAX_TABLE_ROWS_RICH: int = 1000

# ------------------------------------------------------------------------------
# Plot rendering defaults (static PNG generation)
# ------------------------------------------------------------------------------

# Higher default DPI makes PNGs crisper on high-res displays.
PLOT_DPI: int = 200

# If set, and the incoming matplotlib Figure is still at the default size,
# we will "upgrade" it to this size for rendering only.
PLOT_DEFAULT_FIGSIZE_IN: tuple[float, float] | None = (12.0, 6.0)

# Keep tight bounding box, but allow padding so labels don't get clipped.
PLOT_BBOX_TIGHT: bool = True
PLOT_PAD_INCHES: float = 0.10

# Internal: lazy load ini once
_LOADED_RENDER_SETTINGS: bool = False


def get_table_view_mode() -> TableViewMode:
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


# ------------------------------------------------------------------------------
# plotsrv.ini resolution + parsing (render settings)
# ------------------------------------------------------------------------------


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


def _load_render_settings_once() -> None:
    """
    Read render-related settings from plotsrv.ini once.

    Section: [render-settings]
      plot_dpi = 200
      plot_default_figsize_in = 12,6   # or blank to disable
      plot_bbox_tight = true
      plot_pad_inches = 0.10
    """
    global _LOADED_RENDER_SETTINGS
    global PLOT_DPI, PLOT_DEFAULT_FIGSIZE_IN, PLOT_BBOX_TIGHT, PLOT_PAD_INCHES

    if _LOADED_RENDER_SETTINGS:
        return

    _LOADED_RENDER_SETTINGS = True
    ini_path = _resolve_ini_path()
    if ini_path is None:
        return

    cfg = configparser.ConfigParser()
    cfg.read(ini_path)

    section = "render-settings"
    if not cfg.has_section(section):
        return

    # plot_dpi
    try:
        dpi = cfg.getint(section, "plot_dpi", fallback=PLOT_DPI)
        if dpi >= 50:
            PLOT_DPI = dpi
    except Exception:
        pass

    # plot_default_figsize_in
    raw_size = _strip_quotes(cfg.get(section, "plot_default_figsize_in", fallback="")).strip()
    if raw_size:
        try:
            parts = [p.strip() for p in raw_size.replace("x", ",").split(",")]
            w = float(parts[0])
            h = float(parts[1])
            if w > 0 and h > 0:
                PLOT_DEFAULT_FIGSIZE_IN = (w, h)
        except Exception:
            # keep existing default
            pass
    else:
        # allow disabling via blank
        # e.g. plot_default_figsize_in =
        PLOT_DEFAULT_FIGSIZE_IN = None

    # plot_bbox_tight
    try:
        PLOT_BBOX_TIGHT = cfg.getboolean(section, "plot_bbox_tight", fallback=PLOT_BBOX_TIGHT)
    except Exception:
        pass

    # plot_pad_inches
    try:
        pad = float(_strip_quotes(cfg.get(section, "plot_pad_inches", fallback=str(PLOT_PAD_INCHES))))
        if pad >= 0:
            PLOT_PAD_INCHES = pad
    except Exception:
        pass


# ------------------------------------------------------------------------------
# Public getters for render settings (ensure ini loaded)
# ------------------------------------------------------------------------------


def get_plot_dpi() -> int:
    _load_render_settings_once()
    return int(PLOT_DPI)


def get_plot_default_figsize_in() -> tuple[float, float] | None:
    _load_render_settings_once()
    return PLOT_DEFAULT_FIGSIZE_IN


def get_plot_bbox_tight() -> bool:
    _load_render_settings_once()
    return bool(PLOT_BBOX_TIGHT)


def get_plot_pad_inches() -> float:
    _load_render_settings_once()
    return float(PLOT_PAD_INCHES)
