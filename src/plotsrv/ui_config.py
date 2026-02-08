# src/plotsrv/ui_config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import configparser
import os

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


def _parse_bool(
    cfg: configparser.ConfigParser,
    section: str,
    key: str,
    default: bool,
) -> bool:
    try:
        return cfg.getboolean(section, key, fallback=default)
    except Exception:
        # if user typed something weird, just fall back safely
        return default


def load_ui_settings() -> UISettings:
    """
    Load optional plotsrv.ini and return UISettings.

    Defaults match current UI exactly if no ini is present.
    """
    ini_path = _resolve_ini_path()

    # Defaults (current behaviour)
    header_text = DEFAULT_HEADER_TEXT
    header_fill = DEFAULT_HEADER_FILL
    logo_url = DEFAULT_LOGO_URL

    # New (multi-view header dropdown)
    show_view_selector = True

    # Buttons / controls
    terminate_process_option = True
    auto_refresh_option = True
    export_image = True
    export_table = True

    # Lower UI bits
    show_statusline = True
    show_help_note = True

    page_title = DEFAULT_PAGE_TITLE
    favicon_url = DEFAULT_FAVICON_URL


    assets_dir: Path | None = None

    if ini_path is None:
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
            assets_dir=None,
        )

    cfg = configparser.ConfigParser()
    cfg.read(ini_path)

    section = "ui-settings"
    if not cfg.has_section(section):
        # ini exists but doesn't define ui-settings
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
            assets_dir=None,
        )


    # Strings
    page_title = _strip_quotes(cfg.get(section, "page_title", fallback=page_title)).strip() or page_title
    header_text = _strip_quotes(cfg.get(section, "header_text", fallback=header_text))
    header_fill = _strip_quotes(cfg.get(section, "header_fill_colour", fallback=header_fill)).strip() or header_fill

    # Booleans
    show_view_selector = _parse_bool(cfg, section, "show_view_selector", show_view_selector)

    terminate_process_option = _parse_bool(cfg, section, "terminate_process_option", terminate_process_option)
    auto_refresh_option = _parse_bool(cfg, section, "auto_refresh_option", auto_refresh_option)
    export_image = _parse_bool(cfg, section, "export_image", export_image)
    export_table = _parse_bool(cfg, section, "export_table", export_table)
    show_statusline = _parse_bool(cfg, section, "show_statusline", show_statusline)
    show_help_note = _parse_bool(cfg, section, "show_help_note", show_help_note)

    # Logo resolution
    raw_logo = _strip_quotes(cfg.get(section, "logo", fallback="")).strip()
    if raw_logo:
        # allow direct URLs or already-served paths
        if raw_logo.startswith(("http://", "https://", "/static/", "/assets/")):
            logo_url = raw_logo
        else:
            # treat as file path, relative to the ini file's directory
            base = ini_path.parent
            logo_path = (base / raw_logo).expanduser().resolve()

            if logo_path.exists() and logo_path.is_file():
                assets_dir = logo_path.parent
                logo_url = f"/assets/{logo_path.name}"
            else:
                # fallback to default logo if file doesn't exist
                logo_url = DEFAULT_LOGO_URL

    raw_favicon = _strip_quotes(cfg.get(section, "favicon", fallback="")).strip()
    if raw_favicon:
        if raw_favicon.startswith(("http://", "https://", "/static/", "/assets/")):
            favicon_url = raw_favicon
        else:
            base = ini_path.parent
            favicon_path = (base / raw_favicon).expanduser().resolve()
            if favicon_path.exists() and favicon_path.is_file():
                # if assets_dir already set from logo, keep it
                if assets_dir is None:
                    assets_dir = favicon_path.parent
                favicon_url = f"/assets/{favicon_path.name}"
            else:
                favicon_url = DEFAULT_FAVICON_URL


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




_UI_SETTINGS: UISettings | None = None


def get_ui_settings() -> UISettings:
    global _UI_SETTINGS
    if _UI_SETTINGS is None:
        _UI_SETTINGS = load_ui_settings()
    return _UI_SETTINGS
