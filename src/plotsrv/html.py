# src/plotsrv/html.py
from __future__ import annotations

from typing import Literal

from .config import TableViewMode

ViewKind = Literal["none", "plot", "table"]


def render_index(
    *,
    kind: ViewKind,
    table_view_mode: TableViewMode,
    table_html_simple: str | None,
    max_table_rows_simple: int,
    max_table_rows_rich: int,
) -> str:
    """
    Return the HTML for the main viewer page.

    kind:
        "plot", "table", or "none".
    table_view_mode:
        "simple" or "rich"; only used when kind=="table".
    table_html_simple:
        Pre-rendered HTML for simple mode tables (or None).
    """

    # --- Decide per-kind main content block --------------------------------------

    tabulator_head = ""
    extra_js = ""

    if kind == "table":
        if table_view_mode == "simple" and table_html_simple is not None:
            # SIMPLE table
            main_content = f"""
              <div class="plot-frame">
                <div class="table-scroll">
                  {table_html_simple}
                </div>
              </div>

              <div class="controls">
                <button type="button" onclick="window.location.reload()">Refresh</button>
                <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
              </div>

              <div class="note" id="status">
                Showing up to {max_table_rows_simple} rows (simple table mode).
              </div>
            """
        else:
            # RICH table: Tabulator grid
            tabulator_head = """
            <link href="https://unpkg.com/tabulator-tables@5.5.0/dist/css/tabulator.min.css" rel="stylesheet">
            <script src="https://unpkg.com/tabulator-tables@5.5.0/dist/js/tabulator.min.js"></script>
            """

            extra_js = f"""
            async function loadTable() {{
              const res = await fetch("/table/data");
              if (!res.ok) {{
                console.error("Failed to load table data");
                return;
              }}
              const data = await res.json();
              const columns = data.columns.map(col => {{ return {{ title: col, field: col }}; }});
              const rows = data.rows;

              new Tabulator("#table-grid", {{
                data: rows,
                columns: columns,
                height: "600px",
                layout: "fitDataStretch",
                pagination: "local",
                paginationSize: 20,
                movableColumns: true
              }});
            }}

            document.addEventListener("DOMContentLoaded", function () {{
              if (document.getElementById("table-grid")) {{
                loadTable();
              }}
            }});
            """

            main_content = f"""
              <div class="plot-frame">
                <div id="table-grid" class="table-scroll"></div>
              </div>

              <div class="controls">
                <button type="button" onclick="window.location.reload()">Refresh</button>
                <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
              </div>

              <div class="note" id="status">
                Showing up to {max_table_rows_rich} rows (rich table mode).
              </div>
            """

    elif kind == "plot":
        main_content = """
          <div class="plot-frame">
            <img id="plot" src="/plot" alt="Current plot (or none yet)" />
          </div>

          <div class="controls">
            <button type="button" onclick="refreshPlot()">Refresh</button>
            <button type="button" onclick="exportImage()">Export image</button>
            <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
          </div>

          <div class="note" id="status">
            If no plot has been published yet, you may see a broken image until your code calls
            <code>refresh_view</code> or <code>plt.show()</code>.
          </div>
        """
    else:
        main_content = """
          <div class="plot-frame empty">
            <div class="empty-state">
              No plot or table has been published yet.<br />
              Call <code>refresh_view(fig)</code> or <code>refresh_view(df)</code> in Python.
            </div>
          </div>

          <div class="controls">
            <button type="button" class="danger" onclick="terminateServer()">Terminate plotsrv server</button>
          </div>

          <div class="note" id="status"></div>
        """

    # --- Full page ----------------------------------------------------------------

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
          background: #ffffff;
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
        }}

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

        .note {{
          margin-top: 0.5rem;
          font-size: 0.8rem;
          color: #666;
        }}
      </style>
    </head>
    <body>
      <header class="header">
        <img src="/static/plotsrv_logo.jpg" alt="plotsrv logo" class="header-logo" />
        <div class="header-title">live viewer</div>
      </header>

      <main class="page">
        <section class="plot-card">
          {main_content}
        </section>
      </main>

      <script>
        function refreshPlot() {{
          const img = document.getElementById("plot");
          if (!img) return;
          img.src = "/plot?_ts=" + Date.now();
        }}

        function exportImage() {{
          window.location.href = "/plot?download=1&_ts=" + Date.now();
        }}

        function terminateServer() {{
          fetch("/shutdown", {{ method: "POST" }})
            .then(() => {{
              const status = document.getElementById("status");
              if (status) status.textContent = "plotsrv server is shutting down…";
            }})
            .catch(() => {{
              const status = document.getElementById("status");
              if (status) status.textContent = "Failed to contact server (it may already be down).";
            }});
        }}

        {extra_js}
      </script>
    </body>
    </html>
    """
    return html
