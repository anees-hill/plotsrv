# src/plotsrv/html.py
from __future__ import annotations

from typing import Literal

from .config import TableViewMode
from .ui_config import UISettings, get_ui_settings

ViewKind = Literal["none", "plot", "table"]


def render_index(
    *,
    kind: ViewKind,
    table_view_mode: TableViewMode,
    table_html_simple: str | None,
    max_table_rows_simple: int,
    max_table_rows_rich: int,
    ui_settings: UISettings | None = None,
) -> str:
    """
    Return the HTML for the main viewer page.
    """
    ui = ui_settings or get_ui_settings()

    # --- Head deps -------------------------------------------------------------

    tabulator_head = ""
    include_tabulator = kind == "table" and table_view_mode != "simple"
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

    # --- Main content ----------------------------------------------------------

    if kind == "table":
        # Build controls
        table_controls = """
          <button type="button" onclick="window.location.reload()">Refresh</button>
        """

        if ui.export_table:
            table_controls += """
          <button type="button" onclick="exportTable()">Export table</button>
            """

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
        # Build controls
        plot_controls = """
            <button type="button" onclick="refreshPlot()">Refresh</button>
        """

        if ui.export_image:
            plot_controls += """
            <button type="button" onclick="exportImage()">Export image</button>
            """

        if ui.auto_refresh_option:
            plot_controls += """
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
            <img id="plot" src="/plot" alt="Current plot (or none yet)" />
          </div>

          <div class="controls">
            {plot_controls}
          </div>

          {statusline_html}

          {help_note}
        """

    else:
        controls = _terminate_button_html()

        help_note = ""
        if ui.show_help_note:
            help_note = """
              <div class="note" id="status"></div>
            """

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

          {help_note}
        """

    # --- Full page -------------------------------------------------------------

    # Header fill from ini (default white)
    header_fill = ui.header_fill_colour or "#ffffff"
    header_text = ui.header_text or "live viewer"
    logo_url = ui.logo_url or "/static/plotsrv_logo.jpg"

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>plotsrv – viewer</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      {tabulator_head}
      <style>
        :root {{
          --bg: #f5f5f5;
          --border: #ddd;
          --button-bg: #ffffff;
          --button-bg-hover: #f0f0f0;
        }}

        * {{
          box-sizing: border-box;
        }}

        body {{
          margin: 0;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: var(--bg);
          color: #222;
        }}

        .header {{
          background: {header_fill};
          border-bottom: 1px solid var(--border);
          padding: 0.5rem 1rem;
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }}

        .header-logo {{
          height: 28px;
          width: auto;
          display: block;
        }}

        .header-title {{
          font-weight: 600;
          font-size: 1rem;
          color: #555;
        }}

        .page {{
          max-width: 1100px;
          margin: 1.5rem auto;
          padding: 0 1rem 2rem;
        }}

        .plot-card {{
          background: #fff;
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 1rem;
          box-shadow: 0 2px 6px rgba(0,0,0,0.03);
        }}

        .plot-frame {{
          border-radius: 6px;
          overflow: hidden;
          border: 1px solid #eee;
          background: #fafafa;
          padding: 0.5rem;
          min-height: 200px;
          display: flex;
          align-items: center;
          justify-content: center;
        }}

        .plot-frame.empty {{
          background: #fcfcfc;
        }}

        .empty-state {{
          text-align: center;
          font-size: 0.9rem;
          color: #666;
        }}

        #plot {{
          max-width: 100%;
          height: auto;
          display: block;
        }}

        .table-scroll {{
          overflow: auto;
          max-height: 600px;
          width: 100%;
        }}

        {extra_css}

        .controls {{
          margin-top: 0.75rem;
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }}

        .controls button {{
          padding: 0.4rem 0.9rem;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--button-bg);
          cursor: pointer;
          font-size: 0.9rem;
        }}

        .controls button:hover {{
          background: var(--button-bg-hover);
        }}

        .controls .danger {{
          border-color: #e48b8b;
          color: #792424;
          background: #ffecec;
        }}

        .toggle, .interval {{
          display: inline-flex;
          align-items: center;
          gap: 0.35rem;
          padding: 0.35rem 0.55rem;
          border: 1px solid var(--border);
          border-radius: 4px;
         A background: #fff;
          font-size: 0.9rem;
        }}

        .toggle input {{
          transform: translateY(1px);
        }}

        .note {{
          margin-top: 0.5rem;
          font-size: 0.8rem;
          color: #666;
        }}
      </style>
    </head>
    <body>
      <header class="header">
        <img src="{logo_url}" alt="plotsrv logo" class="header-logo" />
        <div class="header-title">{header_text}</div>
      </header>

      <main class="page">
        <section class="plot-card">
          {main_content}
        </section>
      </main>

      <script>
        let _autoRefreshTimer = null;
        let _tabulatorInstance = null;

        function _fmtLocalTime(iso) {{
          if (!iso) return "—";
          const d = new Date(iso);
          if (isNaN(d.getTime())) return iso;
          return d.toLocaleString();
        }}

        function _fmtAgo(iso) {{
          if (!iso) return "";
          const d = new Date(iso);
          if (isNaN(d.getTime())) return "";
          const s = Math.floor((Date.now() - d.getTime()) / 1000);
          if (s < 0) return "";
          if (s < 60) return "(" + s + "s ago)";
          const m = Math.floor(s / 60);
          if (m < 60) return "(" + m + "m ago)";
          const h = Math.floor(m / 60);
          return "(" + h + "h ago)";
        }}

        async function refreshStatus() {{
          try {{
            const res = await fetch("/status?_ts=" + Date.now());
            if (!res.ok) return;
            const s = await res.json();

            const updated = document.getElementById("status-updated");
            const updatedAgo = document.getElementById("status-updated-ago");
            const duration = document.getElementById("status-duration");
            const errWrap = document.getElementById("status-error-wrap");
            const err = document.getElementById("status-error");

            const mode = document.getElementById("status-mode");
            const srvRate = document.getElementById("status-srv-refresh");

            if (updated) updated.textContent = _fmtLocalTime(s.last_updated);
            if (updatedAgo) updatedAgo.textContent = _fmtAgo(s.last_updated);

            if (duration) {{
              duration.textContent =
                (s.last_duration_s == null) ? "—" : (Number(s.last_duration_s).toFixed(3) + "s");
            }}

            if (errWrap && err) {{
              if (s.last_error) {{
                err.textContent = s.last_error;
                errWrap.style.display = "inline";
              }} else {{
                err.textContent = "";
                errWrap.style.display = "none";
              }}
            }}

            if (mode) {{
              mode.textContent = s.service_mode ? "service" : "interactive";
            }}

            if (srvRate) {{
              if (s.service_mode && s.service_refresh_rate_s) {{
                srvRate.textContent = "every " + s.service_refresh_rate_s + "s";
              }} else if (s.service_mode) {{
                srvRate.textContent = "once";
              }} else {{
                srvRate.textContent = "—";
              }}
            }}
          }} catch (e) {{
            // ignore
          }}
        }}

        function refreshPlot() {{
          const img = document.getElementById("plot");
          if (!img) return;
          img.src = "/plot?_ts=" + Date.now();
          refreshStatus();
        }}

        function exportImage() {{
          window.location.href = "/plot?download=1&_ts=" + Date.now();
        }}

        function exportTable() {{
          window.location.href = "/table/export?format=csv&_ts=" + Date.now();
        }}

        function terminateServer() {{
          fetch("/shutdown", {{ method: "POST" }})
            .then(() => {{
              const status = document.getElementById("status");
              if (status) status.textContent = "plotsrv is shutting down…";
            }})
            .catch(() => {{
              const status = document.getElementById("status");
              if (status) status.textContent = "Failed to contact server (it may already be down).";
            }});
        }}

        async function loadTable() {{
          const grid = document.getElementById("table-grid");
          if (!grid) return;

          const res = await fetch("/table/data?_ts=" + Date.now());
          if (!res.ok) {{
            console.error("Failed to load table data");
            return;
          }}

          const data = await res.json();
          const columns = data.columns.map(col => ({{ title: col, field: col }}));
          const rows = data.rows;

          if (_tabulatorInstance) {{
            _tabulatorInstance.setColumns(columns);
            _tabulatorInstance.replaceData(rows);
            return;
          }}

          _tabulatorInstance = new Tabulator("#table-grid", {{
            data: rows,
            columns: columns,
            height: "600px",
            layout: "fitDataStretch",
            pagination: "local",
            paginationSize: 20,
            paginationSizeSelector: [10, 20, 50, 100],
            movableColumns: true
          }});
        }}

        function _getAutoRefreshMs() {{
          const sel = document.getElementById("auto-refresh-interval");
          if (!sel) return 5000;
          const seconds = Number(sel.value || 5);
          return Math.max(1, seconds) * 1000;
        }}

        function _stopAutoRefresh() {{
          if (_autoRefreshTimer !== null) {{
            clearInterval(_autoRefreshTimer);
            _autoRefreshTimer = null;
          }}
        }}

        function _tickAutoRefresh() {{
          const img = document.getElementById("plot");
          if (img) {{
            refreshPlot();
            return;
          }}

          if (document.getElementById("table-grid")) {{
            loadTable().then(() => refreshStatus());
            return;
          }}

          refreshStatus();
        }}

        function _startAutoRefresh() {{
          _stopAutoRefresh();
          const ms = _getAutoRefreshMs();
          _autoRefreshTimer = setInterval(_tickAutoRefresh, ms);
        }}

        function _bindAutoRefreshControls() {{
          const toggle = document.getElementById("auto-refresh-toggle");
          const interval = document.getElementById("auto-refresh-interval");
          if (!toggle) return;

          toggle.addEventListener("change", function () {{
            if (toggle.checked) {{
              _tickAutoRefresh();
              _startAutoRefresh();
            }} else {{
              _stopAutoRefresh();
            }}
          }});

          if (interval) {{
            interval.addEventListener("change", function () {{
              if (toggle.checked) _startAutoRefresh();
            }});
          }}
        }}

        document.addEventListener("DOMContentLoaded", function () {{
          refreshStatus();
          if (document.getElementById("table-grid")) {{
            loadTable().then(() => refreshStatus());
          }}
          _bindAutoRefreshControls();
        }});
      </script>
    </body>
    </html>
    """
    return html
