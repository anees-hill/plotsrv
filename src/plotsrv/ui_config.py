# src/plotsrv/ui_config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import settings

DEFAULT_LOGO_URL = "/static/plotsrv_logo.jpg"
DEFAULT_HEADER_TEXT = "live viewer"
DEFAULT_HEADER_FILL = "#ffffff"
DEFAULT_PAGE_TITLE = "plotsrv - live view"
DEFAULT_FAVICON_URL = "/static/plotsrv_favicon.png"


@dataclass(frozen=True, slots=True)
class UISettings:
    # Page chrome
    page_title: str
    favicon_url: str

    # Header
    logo_url: str
    header_text: str
    header_fill_colour: str

    # Header controls
    show_view_selector: bool

    # Buttons / controls
    terminate_process_option: bool
    auto_refresh_option: bool
    export_image: bool
    export_table: bool

    # Lower UI bits
    show_statusline: bool
    show_help_note: bool

    # Serving user assets (logo/favicon)
    assets_dir: Path | None = None


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


def _strip_quotes(s: str) -> str:
    t = s.strip()
    if len(t) >= 2 and ((t[0] == t[-1] == "'") or (t[0] == t[-1] == '"')):
        return t[1:-1].strip()
    return t


def _resolve_asset_url(raw: str, *, default_url: str) -> tuple[str, Path | None]:
    """
    Accept:
      - direct URL or served paths: http(s)://, /static/, /assets/
      - file path: resolved relative to YAML config dir (if present), else cwd
    Returns (url, assets_dir_or_none)
    """
    raw2 = _strip_quotes(raw).strip()
    if not raw2:
        return default_url, None

    if raw2.startswith(("http://", "https://", "/static/", "/assets/")):
        return raw2, None

    base = settings.get_runtime_config_dir() or Path.cwd()
    p = (base / raw2).expanduser().resolve()
    if p.exists() and p.is_file():
        return f"/assets/{p.name}", p.parent

    return default_url, None


_UI_SETTINGS: UISettings | None = None
_UI_CACHE_KEY: tuple[str | None, str | None] | None = None


def load_ui_settings() -> UISettings:
    # defaults (current behaviour)
    page_title = DEFAULT_PAGE_TITLE
    favicon_url = DEFAULT_FAVICON_URL

    logo_url = DEFAULT_LOGO_URL
    header_text = DEFAULT_HEADER_TEXT
    header_fill = DEFAULT_HEADER_FILL

    # controls
    show_view_selector = True
    terminate_process_option = True
    auto_refresh_option = True
    export_image = True
    export_table = True
    show_statusline = True
    show_help_note = True

    assets_dir: Path | None = None

    # YAML ui-settings section (merged global + instance[name])
    ui = settings.get_section("ui-settings")

    if isinstance(ui.get("page_title"), str) and ui["page_title"].strip():
        page_title = _strip_quotes(ui["page_title"]).strip() or page_title

    if isinstance(ui.get("header_text"), str):
        header_text = _strip_quotes(ui["header_text"])

    if (
        isinstance(ui.get("header_fill_colour"), str)
        and ui["header_fill_colour"].strip()
    ):
        header_fill = _strip_quotes(ui["header_fill_colour"]).strip() or header_fill

    show_view_selector = _as_bool(ui.get("show_view_selector"), show_view_selector)
    terminate_process_option = _as_bool(
        ui.get("terminate_process_option"), terminate_process_option
    )
    auto_refresh_option = _as_bool(ui.get("auto_refresh_option"), auto_refresh_option)
    export_image = _as_bool(ui.get("export_image"), export_image)
    export_table = _as_bool(ui.get("export_table"), export_table)
    show_statusline = _as_bool(ui.get("show_statusline"), show_statusline)
    show_help_note = _as_bool(ui.get("show_help_note"), show_help_note)

    # logo/favicon
    if isinstance(ui.get("logo"), str):
        logo_url, ad = _resolve_asset_url(ui["logo"], default_url=DEFAULT_LOGO_URL)
        if ad is not None:
            assets_dir = ad

    if isinstance(ui.get("favicon"), str):
        favicon_url, ad2 = _resolve_asset_url(
            ui["favicon"], default_url=DEFAULT_FAVICON_URL
        )
        if ad2 is not None and assets_dir is None:
            assets_dir = ad2

    return UISettings(
        page_title=page_title,
        favicon_url=favicon_url,
        logo_url=logo_url,
        header_text=header_text,
        header_fill_colour=header_fill,
        show_view_selector=show_view_selector,
        terminate_process_option=terminate_process_option,
        auto_refresh_option=auto_refresh_option,
        export_image=export_image,
        export_table=export_table,
        show_statusline=show_statusline,
        show_help_note=show_help_note,
        assets_dir=assets_dir,
    )


def get_ui_settings() -> UISettings:
    global _UI_SETTINGS, _UI_CACHE_KEY
    key = (
        str(settings.get_runtime_config_path()),
        settings.get_runtime_name(),
    )
    if _UI_SETTINGS is None or _UI_CACHE_KEY != key:
        _UI_SETTINGS = load_ui_settings()
        _UI_CACHE_KEY = key
    return _UI_SETTINGS
