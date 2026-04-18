# src/plotsrv/html.py
from __future__ import annotations

from typing import Literal
import json

from .config import TableViewMode
from .store import ViewMeta
from .ui_config import UISettings, get_ui_settings

ViewKind = Literal["none", "plot", "table", "artifact"]


def render_index(
    *,
    kind: ViewKind,
    table_view_mode: TableViewMode,
    table_html_simple: str | None,
    max_table_rows_simple: int,
    max_table_rows_rich: int,
    ui_settings: UISettings | None = None,
    views: list[ViewMeta] | None = None,
    active_view_id: str | None = None,
) -> str:
    """
    Return the HTML for the main viewer page.
    """
    ui = ui_settings or get_ui_settings()
    views = views or []
    active_view_id = active_view_id or "default"

    page_title = getattr(ui, "page_title", None) or "plotsrv - live view"
    favicon_url = getattr(ui, "favicon_url", None) or "/static/plotsrv_favicon.png"

    tabulator_head = ""
    include_tabulator = kind in ("table", "artifact") and table_view_mode != "simple"

    if include_tabulator:
        tabulator_head = """
        <link href=
"https://unpkg.com/tabulator-tables@5.5.0/dist/css/tabulator.min.css"
 rel="stylesheet">
        <script src=
"https://unpkg.com/tabulator-tables@5.5.0/dist/js/tabulator.min.js"
></script>
        """

    statusline_html = ""
    if ui.show_statusline:
        freshness_html = ""
        if ui.show_freshness:
            freshness_html = """
              &nbsp;|&nbsp;
              <span class="ps-statusline__item">
                <strong>Freshness:</strong> <span id="status-freshness">—</span>
              </span>
            """

        statusline_html = f"""
        <div class="note ps-note ps-statusline" id="statusline">
          <span class="ps-statusline__item">
            <strong>Last updated:</strong> <span id="status-updated">—</span>
            <span id="status-updated-ago"></span>
          </span>
          {freshness_html}
          <span id="status-error-wrap" class="ps-statusline__error" style="display:none;">
            &nbsp;|&nbsp;
            <strong style="color:#792424;">Error:</strong>
            <span id="status-error" style="color:#792424;"></span>
          </span>
        </div>
        """

    def _refresh_control_html(action: str) -> str:
        return (
            f'<button type="button" class="ps-btn" onclick="{action}">Refresh</button>'
        )

    def _terminate_button_html() -> str:
        if not ui.terminate_process_option:
            return ""
        return """
          <button type="button" class="ps-btn ps-btn--danger" onclick="terminateServer()">Terminate plotsrv server</button>
        """

    def _auto_refresh_controls_html() -> str:
        if not ui.auto_refresh_option:
            return ""
        return """
          <label class="ps-auto-refresh">
            <span>Auto-refresh</span>
            <select id="auto-refresh-select" class="ps-select">
              <option value="off" selected>Off</option>
              <option value="2">2s</option>
              <option value="5">5s</option>
              <option value="10">10s</option>
              <option value="30">30s</option>
              <option value="60">60s</option>
              <option value="120">120s</option>
              <option value="300">300s</option>
            </select>
          </label>
        """

    def _history_controls_html() -> str:
        if not ui.show_history_controls:
            return ""
        return """
          <label class="interval ps-history">
            <span>History</span>
            <select id="history-select" class="ps-select">
              <option value="">Loading…</option>
            </select>
          </label>
        """

    LOGO_BY_KEY = {
        "unknown": "/static/logo_unknown.png",
        "plot": "/static/logo_plot.png",
        "table": "/static/logo_table.png",
        "image": "/static/logo_image.png",
        "markdown": "/static/logo_markdown.png",
        "json": "/static/logo_json.png",
        "python": "/static/logo_python.png",
        "exception": "/static/logo_exception.png",
        "text": "/static/logo_txt.png",
        "html": "/static/logo_html.png",
    }

    def _icon_url(v: ViewMeta | None) -> str:
        if v is None:
            return LOGO_BY_KEY["unknown"]
        return LOGO_BY_KEY.get(
            getattr(v, "icon_key", "unknown"), LOGO_BY_KEY["unknown"]
        )

    dropdown_html = ""
    if getattr(ui, "show_view_selector", True) and len(views) > 0:
        groups: dict[str, list[ViewMeta]] = {}
        sections: list[str] = []
        for v in views:
            sec = v.section or "default"
            if sec not in groups:
                groups[sec] = []
                sections.append(sec)
            groups[sec].append(v)

        active_meta = None
        for v in views:
            if v.view_id == active_view_id:
                active_meta = v
                break
        active_label = active_meta.label if active_meta else active_view_id
        active_icon = _icon_url(active_meta)

        menu_parts: list[str] = []
        for sec in sections:
            menu_parts.append('<div class="ps-viewselect__group">')
            menu_parts.append(f'<div class="ps-viewselect__group-label">{sec}</div>')
            for v in groups[sec]:
                is_sel = "true" if v.view_id == active_view_id else "false"
                icon = _icon_url(v)
                menu_parts.append(
                    f"""
                    <button type="button"
                            class="ps-viewselect__item"
                            role="option"
                            aria-selected="{is_sel}"
                            data-plotsrv-view="{v.view_id}">
                      <img class="ps-viewselect__itemicon" src="{icon}" alt="" />
                      <span class="ps-viewselect__itemlabel">{v.label}</span>
                    </button>
                    """
                )
            menu_parts.append("</div>")

        dropdown_html = f"""
          <div class="ps-viewselect" data-plotsrv-viewselect="1">
            <button type="button"
                    class="ps-viewselect__btn"
                    aria-haspopup="listbox"
                    aria-expanded="false">
              <img class="ps-viewselect__icon" src="{active_icon}" alt="" />
              <span class="ps-viewselect__label">{active_label}</span>
              <span class="ps-viewselect__chev" aria-hidden="true">▾</span>
            </button>

            <div class="ps-viewselect__menu" role="listbox" tabindex="-1" hidden>
              {''.join(menu_parts)}
            </div>
          </div>
        """

    def _footer_html(*, controls_html: str) -> str:
        return f"""
          <div class="ps-footer-controls">
            {controls_html}
          </div>

          <div class="ps-footer-inline">
            <div class="note ps-note" id="status"></div>
          </div>

          {statusline_html}
        """

    content_html = ""
    footer_html = ""

    if kind == "table":
        controls_html = (
            _refresh_control_html("window.location.reload()")
            + (
                """
                <button type="button" class="ps-btn" onclick="exportTable()">Export table</button>
                """
                if ui.export_table
                else ""
            )
            + _history_controls_html()
            + _auto_refresh_controls_html()
            + _terminate_button_html()
        )

        if table_view_mode == "simple" and table_html_simple is not None:
            content_html = f"""
              <div class="plot-frame ps-frame ps-frame--table plot-frame--table">
                <div class="table-scroll ps-table-scroll ps-table--simple">
                  {table_html_simple}
                </div>
              </div>
            """
        else:
            content_html = """
              <div class="plot-frame ps-frame ps-frame--table plot-frame--table">
                <div id="table-grid" class="table-grid ps-tablegrid ps-table--rich"></div>
              </div>
            """

        footer_html = _footer_html(controls_html=controls_html)

    elif kind == "plot":
        controls_html = (
            _refresh_control_html("refreshPlot()")
            + (
                """
                <button type="button" class="ps-btn" onclick="exportImage()">Export image</button>
                """
                if ui.export_image
                else ""
            )
            + _history_controls_html()
            + _auto_refresh_controls_html()
            + _terminate_button_html()
        )

        content_html = f"""
          <div class="plot-frame ps-frame ps-frame--plot plot-frame--plot">
            <img id="plot" class="ps-plot" src="/plot?view={active_view_id}" alt="Current plot (or none yet)" />
          </div>
        """
        footer_html = _footer_html(controls_html=controls_html)

    elif kind == "artifact":
        controls_html = (
            _refresh_control_html("refreshArtifact()")
            + (
                """
                <button type="button" class="ps-btn" onclick="exportImage()">Export image</button>
                """
                if ui.export_image
                else ""
            )
            + (
                """
                <button type="button" class="ps-btn" onclick="exportTable()">Export table</button>
                """
                if ui.export_table
                else ""
            )
            + _history_controls_html()
            + _auto_refresh_controls_html()
            + _terminate_button_html()
        )

        content_html = """
          <div class="plot-frame ps-frame ps-frame--artifact plot-frame--artifact">
            <div class="ps-artifact">
              <div id="artifact-topline" class="ps-artifact__meta">
                <span id="artifact-kind" class="note ps-note"></span>
                <span id="artifact-truncation" class="note ps-note"></span>
              </div>
              <div id="artifact-root" class="ps-artifact__content"></div>
            </div>
          </div>
        """
        footer_html = _footer_html(controls_html=controls_html)

    else:
        controls_html = (
            _refresh_control_html("window.location.reload()")
            + _history_controls_html()
            + _auto_refresh_controls_html()
            + _terminate_button_html()
        )

        content_html = """
          <div class="plot-frame empty ps-frame ps-frame--empty plot-frame--empty">
            <div class="empty-state ps-empty">
              No plot or table has been published yet.<br />
              Call <code>refresh_view(fig)</code> or <code>refresh_view(df)</code> in Python.
            </div>
          </div>
        """
        footer_html = _footer_html(controls_html=controls_html)

    header_fill = ui.header_fill_colour or "#ffffff"
    header_text = ui.header_text or ""
    logo_url = ui.logo_url or "/static/plotsrv_title_logo.png"

    cfg_json = json.dumps(
        {
            "active_view_id": active_view_id,
            "kind": kind,
            "table_view_mode": table_view_mode,
            "max_table_rows_simple": max_table_rows_simple,
            "max_table_rows_rich": max_table_rows_rich,
        },
        ensure_ascii=False,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>{page_title}</title>
      <link rel="icon" href="{favicon_url}">
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <link rel="stylesheet" href="/static/plotsrv.css">
      <script>
        window.PLOTSRV_CONFIG = {cfg_json};
      </script>
      {tabulator_head}
      <script src="/static/js/core/dom.js" defer></script>
      <script src="/static/js/core/state.js" defer></script>
      <script src="/static/js/core/storage.js" defer></script>
      <script src="/static/js/core/history.js" defer></script>
      <script src="/static/js/core/status.js" defer></script>
      <script src="/static/js/core/auto_refresh.js" defer></script>
      <script src="/static/js/core/view_selector.js" defer></script>
      <script src="/static/js/renderers/artifact.js" defer></script>
      <script src="/static/js/renderers/plot.js" defer></script>
      <script src="/static/js/renderers/table.js" defer></script>
      <script src="/static/js/renderers/json.js" defer></script>
      <script src="/static/js/renderers/text.js" defer></script>
      <script src="/static/js/renderers/code.js" defer></script>
      <script src="/static/js/core/app.js" defer></script>
    </head>
    <body class="ps-body"
          data-kind="{kind}"
          data-view="{active_view_id}"
          data-table-mode="{table_view_mode}">
      <header class="header ps-header" style="background:{header_fill};">
        <div class="header-left ps-header__left">
          <img src="{logo_url}" alt="plotsrv logo" class="header-logo ps-header__logo" />
          <div class="header-title ps-header__title">{header_text}</div>
        </div>

        <div class="header-centre ps-header__centre">
          <div id="header-history" class="ps-header__history" hidden>
            <span id="header-history-label" class="ps-header__history-label">Historical mode</span>
            <button type="button" class="ps-header__linkbtn" onclick="returnToLive()">Return to Live</button>
          </div>
        </div>

        <div class="header-right ps-header__right">
          <span id="header-freshness-dot" class="ps-header__freshness-dot" hidden aria-hidden="true"></span>
          {dropdown_html}
        </div>
      </header>

      <main class="page ps-page">
        <section class="plot-card ps-card">
          {content_html}
          {footer_html}
        </section>
      </main>

    </body>
    </html>
    """
    return html
