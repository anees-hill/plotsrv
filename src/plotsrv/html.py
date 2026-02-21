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

    # Page chrome (safe defaults for older UISettings)
    page_title = getattr(ui, "page_title", None) or "plotsrv - live view"
    favicon_url = getattr(ui, "favicon_url", None) or "/static/plotsrv_favicon.png"

    # --- Head deps -------------------------------------------------------------

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

    # --- Shared statusline HTML ------------------------------------------------
    statusline_html = ""
    if ui.show_statusline:
        statusline_html = """
        <div class=
"note ps-note ps-statusline"
 id="statusline">
          <span class="ps-statusline__item"><strong>Last updated:</strong> <span id="status-updated">—</span> <span id="status-updated-ago"></span></span>
          &nbsp;|&nbsp;
          <span class="ps-statusline__item"><strong>Last run time:</strong> <span id="status-duration">—</span></span>
          &nbsp;|&nbsp;
          <span class="ps-statusline__item"><strong>Mode:</strong> <span id="status-mode">—</span></span>
          &nbsp;|&nbsp;
          <span class="ps-statusline__item"><strong>Server refresh:</strong> <span id="status-srv-refresh">—</span></span>
          <span id="status-error-wrap" class="ps-statusline__error" style="display:none;">
            &nbsp;|&nbsp;
            <strong style="color:#792424;">Error:</strong>
            <span id="status-error" style="color:#792424;"></span>
          </span>
        </div>
        """

    # --- Controls blocks -------------------------------------------------------
    def _terminate_button_html() -> str:
        if not ui.terminate_process_option:
            return ""
        return """
          <button type="button" class="danger ps-btn ps-btn--danger" onclick="terminateServer()">Terminate plotsrv server</button>
        """

    def _auto_refresh_controls_html() -> str:
        """
        Auto-refresh controls (used for plot/table/artifact).
        """
        if not ui.auto_refresh_option:
            return ""
        return """
            <label class="toggle ps-toggle">
              <input id="auto-refresh-toggle" type="checkbox" />
              <span>Auto-refresh</span>
            </label>

            <label class="interval ps-interval">
              <span>Every</span>
              <select id="auto-refresh-interval" class="ps-select">
                <option value="2">2s</option>
                <option value="5" selected>5s</option>
                <option value="10">10s</option>
                <option value="30">30s</option>
                <option value="60">60s</option>
              </select>
            </label>
        """

    # --- View dropdown (custom, with icons) -----------------------------------

    LOGO_BY_KEY = {
        "plot": "/static/logo_plot.png",
        "table": "/static/logo_table.png",
        "image": "/static/logo_image.png",
        "markdown": "/static/logo_markdown.png",
        "json": "/static/logo_json.png",
        "python": "/static/logo_python.png",
        "exception": "/static/logo_exception.png",
        "txt": "/static/logo_txt.png",
        "html": "/static/logo_html.png",
    }

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
        # group by section, preserving the incoming ordering of `views`.
        # (store.list_views() applies the configured order from plotsrv.ini)
        groups: dict[str, list[ViewMeta]] = {}
        sections: list[str] = []
        for v in views:
            sec = v.section or "default"
            if sec not in groups:
                groups[sec] = []
                sections.append(sec)
            groups[sec].append(v)

        # find active view meta (for button display)
        active_meta = None
        for v in views:
            if v.view_id == active_view_id:
                active_meta = v
                break
        active_label = active_meta.label if active_meta else active_view_id
        active_icon = _icon_url(active_meta) if active_meta else LOGO_BY_KEY["txt"]

        # build menu
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

    # --- Main content ----------------------------------------------------------

    if kind == "table":
        table_controls = """
          <button type="button" class="ps-btn" onclick="window.location.reload()">Refresh</button>
        """

        if ui.export_table:
            table_controls += """
          <button type="button" class="ps-btn" onclick="exportTable()">Export table</button>
            """

        table_controls += _auto_refresh_controls_html()
        table_controls += _terminate_button_html()

        if table_view_mode == "simple" and table_html_simple is not None:
            main_content = f"""
              <div class="plot-frame ps-frame ps-frame--table plot-frame--table">
                <div class="table-scroll ps-table-scroll ps-table--simple">
                  {table_html_simple}
                </div>
              </div>

              <div class="controls ps-controls">
                {table_controls}
              </div>

              {statusline_html}

              <div class="note ps-note" id="status">
                Showing up to {max_table_rows_simple} rows (simple table mode).
              </div>
            """
        else:
            main_content = f"""
              <div class="plot-frame ps-frame ps-frame--table plot-frame--table">
                <div id="table-grid" class="table-grid ps-tablegrid ps-table--rich"></div>
              </div>

              <div class="controls ps-controls">
                {table_controls}
              </div>

              {statusline_html}

              <div class="note ps-note" id="status">
                Showing up to {max_table_rows_rich} rows (rich table mode).
              </div>
            """

    elif kind == "plot":
        plot_controls = """
            <button type="button" class="ps-btn" onclick="refreshPlot()">Refresh</button>
        """

        if ui.export_image:
            plot_controls += """
            <button type="button" class="ps-btn" onclick="exportImage()">Export image</button>
            """

        plot_controls += _auto_refresh_controls_html()
        plot_controls += _terminate_button_html()

        help_note = ""
        if ui.show_help_note:
            help_note = """
              <div class="note ps-note" id="status">
                If no plot has been published yet, you may see a broken image until your code calls
                <code>refresh_view</code> or <code>plt.show()</code>.
              </div>
            """

        main_content = f"""
          <div class="plot-frame ps-frame ps-frame--plot plot-frame--plot">
            <img id="plot" class="ps-plot" src="/plot?view={active_view_id}" alt="Current plot (or none yet)" />
          </div>

          <div class="controls ps-controls">
            {plot_controls}
          </div>

          {statusline_html}

          {help_note}
        """

    elif kind == "artifact":
        artifact_controls = """
            <button type="button" class="ps-btn" onclick="refreshArtifact()">Refresh</button>
        """

        if ui.export_image:
            artifact_controls += """
            <button type="button" class="ps-btn" onclick="exportImage()">Export image</button>
            """

        if ui.export_table:
            artifact_controls += """
            <button type="button" class="ps-btn" onclick="exportTable()">Export table</button>
            """

        artifact_controls += _auto_refresh_controls_html()
        artifact_controls += _terminate_button_html()

        main_content = """
          <div class="plot-frame ps-frame ps-frame--artifact plot-frame--artifact">
            <div class="ps-artifact" style="width:100%;">
              <div id="artifact-topline" class="ps-artifact__meta" style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.5rem;">
                <span id="artifact-kind" class="note ps-note" style="margin:0;"></span>
                <span id="artifact-truncation" class="note ps-note" style="margin:0;"></span>
              </div>
              <div id="artifact-root" class="ps-artifact__content"></div>
            </div>
          </div>

          <div class="controls ps-controls">
            {artifact_controls}
          </div>

          {statusline_html}

          <div class="note ps-note" id="status"></div>
        """.format(
            artifact_controls=artifact_controls,
            statusline_html=statusline_html,
        )

    else:
        controls = _auto_refresh_controls_html() + _terminate_button_html()
        main_content = f"""
          <div class="plot-frame empty ps-frame ps-frame--empty plot-frame--empty">
            <div class="empty-state ps-empty">
              No plot or table has been published yet.<br />
              Call <code>refresh_view(fig)</code> or <code>refresh_view(df)</code> in Python.
            </div>
          </div>

          <div class="controls ps-controls">
            {controls}
          </div>

          {statusline_html}

          <div class="note ps-note" id="status"></div>
        """

    # --- Full page -------------------------------------------------------------

    header_fill = ui.header_fill_colour or "#ffffff"
    header_text = ui.header_text or "live viewer"
    logo_url = ui.logo_url or "/static/plotsrv_logo.jpg"

    cfg_json = json.dumps(
        {
            "active_view_id": active_view_id,
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
      <script src="/static/plotsrv.js" defer></script>
      {tabulator_head}
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

        <div class="header-right ps-header__right">
          {dropdown_html}
        </div>
      </header>

      <main class="page ps-page">
        <section class="plot-card ps-card">
          {main_content}
        </section>
      </main>

    </body>
    </html>
    """
    return html
