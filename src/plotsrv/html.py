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

    extra_css = ""

    if include_tabulator:
        tabulator_head = """
        <link href="https://unpkg.com/tabulator-tables@5.5.0/dist/css/tabulator.min.css" rel="stylesheet">
        <script src="https://unpkg.com/tabulator-tables@5.5.0/dist/js/tabulator.min.js"></script>
        """
        extra_css = """
        .table-grid {
          width: 100%;
        }
        """

    # --- Shared statusline HTML ------------------------------------------------

    statusline_html = ""
    if ui.show_statusline:
        statusline_html = """
        <div class="note" id="statusline">
          <span><strong>Last updated:</strong> <span id="status-updated">—</span> <span id="status-updated-ago"></span></span>
          &nbsp;|&nbsp;
          <span><strong>Last run time:</strong> <span id="status-duration">—</span></span>
          &nbsp;|&nbsp;
          <span><strong>Mode:</strong> <span id="status-mode">—</span></span>
          &nbsp;|&nbsp;
          <span><strong>Server refresh:</strong> <span id="status-srv-refresh">—</span></span>
          <span id="status-error-wrap" style="display:none;">
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
          <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
        """

    def _auto_refresh_controls_html() -> str:
        """
        Auto-refresh controls (used for plot/table/artifact).
        Uses double curly braces inside JS template literals.
        """
        if not ui.auto_refresh_option:
            return ""
        return """
            <label class="toggle">
              <input id="auto-refresh-toggle" type="checkbox" />
              <span>Auto-refresh</span>
            </label>

            <label class="interval">
              <span>Every</span>
              <select id="auto-refresh-interval">
                <option value="2">2s</option>
                <option value="5" selected>5s</option>
                <option value="10">10s</option>
                <option value="30">30s</option>
                <option value="60">60s</option>
              </select>
            </label>
        """

    # --- View dropdown ---------------------------------------------------------

    dropdown_html = ""
    if getattr(ui, "show_view_selector", True) and len(views) > 0:
        # group by section
        groups: dict[str, list[ViewMeta]] = {}
        for v in views:
            sec = v.section or "default"
            groups.setdefault(sec, []).append(v)

        # stable ordering
        sections = sorted(groups.keys())
        for s in sections:
            groups[s] = sorted(groups[s], key=lambda x: x.label)

        options: list[str] = []
        for sec in sections:
            options.append(f'<optgroup label="{sec}">')
            for v in groups[sec]:
                sel = "selected" if v.view_id == active_view_id else ""
                options.append(f'<option value="{v.view_id}" {sel}>{v.label}</option>')
            options.append("</optgroup>")

        dropdown_html = f"""
          <div class="view-select">
            <select id="view-select">
              {''.join(options)}
            </select>
          </div>
        """

    # --- Main content ----------------------------------------------------------

    if kind == "table":
        table_controls = """
          <button type="button" onclick="window.location.reload()">Refresh</button>
        """

        if ui.export_table:
            table_controls += """
          <button type="button" onclick="exportTable()">Export table</button>
            """

        # FIX 2: auto-refresh for tables too
        table_controls += _auto_refresh_controls_html()

        table_controls += _terminate_button_html()

        if table_view_mode == "simple" and table_html_simple is not None:
            main_content = f"""
              <div class="plot-frame">
                <div class="table-scroll">
                  {table_html_simple}
                </div>
              </div>

              <div class="controls">
                {table_controls}
              </div>

              {statusline_html}

              <div class="note" id="status">
                Showing up to {max_table_rows_simple} rows (simple table mode).
              </div>
            """
        else:
            main_content = f"""
              <div class="plot-frame">
                <div id="table-grid" class="table-grid"></div>
              </div>

              <div class="controls">
                {table_controls}
              </div>

              {statusline_html}

              <div class="note" id="status">
                Showing up to {max_table_rows_rich} rows (rich table mode).
              </div>
            """

    elif kind == "plot":
        plot_controls = """
            <button type="button" onclick="refreshPlot()">Refresh</button>
        """

        if ui.export_image:
            plot_controls += """
            <button type="button" onclick="exportImage()">Export image</button>
            """

        # Keep existing behaviour (and now shared helper)
        plot_controls += _auto_refresh_controls_html()

        plot_controls += _terminate_button_html()

        help_note = ""
        if ui.show_help_note:
            help_note = """
              <div class="note" id="status">
                If no plot has been published yet, you may see a broken image until your code calls
                <code>refresh_view</code> or <code>plt.show()</code>.
              </div>
            """

        main_content = f"""
          <div class="plot-frame">
            <img id="plot" src="/plot?view={active_view_id}" alt="Current plot (or none yet)" />
          </div>

          <div class="controls">
            {plot_controls}
          </div>

          {statusline_html}

          {help_note}
        """
    elif kind == "artifact":
        # We'll render a generic artifact container and fetch /artifact on load.
        # Buttons match existing UX patterns.
        artifact_controls = """
            <button type="button" onclick="refreshArtifact()">Refresh</button>
        """

        if ui.export_image:
            # harmless even if current artifact isn't a plot; only works when /plot exists
            artifact_controls += """
            <button type="button" onclick="exportImage()">Export image</button>
            """

        if ui.export_table:
            artifact_controls += """
            <button type="button" onclick="exportTable()">Export table</button>
            """

        # FIX 2: auto-refresh for artifacts too
        artifact_controls += _auto_refresh_controls_html()

        artifact_controls += _terminate_button_html()

        main_content = f"""
          <div class="plot-frame">
            <div style="width:100%;">
              <div id="artifact-topline" style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.5rem;">
                <span id="artifact-kind" class="note" style="margin:0;"></span>
                <span id="artifact-truncation" class="note" style="margin:0;"></span>
              </div>
              <div id="artifact-root"></div>
            </div>
          </div>

          <div class="controls">
            {artifact_controls}
          </div>

          {statusline_html}

          <div class="note" id="status"></div>
        """

    else:
        controls = _auto_refresh_controls_html() + _terminate_button_html()
        main_content = f"""
          <div class="plot-frame empty">
            <div class="empty-state">
              No plot or table has been published yet.<br />
              Call <code>refresh_view(fig)</code> or <code>refresh_view(df)</code> in Python.
            </div>
          </div>

          <div class="controls">
            {controls}
          </div>

          {statusline_html}

          <div class="note" id="status"></div>
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
    <body>
      <header class="header">
        <div class="header-left">
          <img src="{logo_url}" alt="plotsrv logo" class="header-logo" />
          <div class="header-title">{header_text}</div>
        </div>

        <div class="header-right">
          {dropdown_html}
        </div>
      </header>

      <main class="page">
        <section class="plot-card">
          {main_content}
        </section>
      </main>

    </body>
    </html>
    """
    return html
