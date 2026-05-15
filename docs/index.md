---
icon: lucide/home
---

# plotsrv

**plotsrv** is a lightweight browser UI for observing what your Python processes are producing.

It lets you publish plots, tables, logs, JSON, markdown, HTML, images, tracebacks, and files to a local or server-side web UI with very little setup.

It is especially useful when you have Python scripts, ETL jobs, experiments, inference processes, or headless server workflows where you want to see what is happening without building a dashboard application.

!!! note

    plotsrv is not a dashboard framework. It is a low-friction way to observe what Python processes are producing.

## Install

=== "pip"

    ```bash
    pip install plotsrv
    ```

=== "uv"

    ```bash
    uv add plotsrv
    ```

## Quick start

```python title="quickstart.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df)
```

Then open:

```text
http://127.0.0.1:8000
```

`refresh_view()` publishes the object and starts the local plotsrv server automatically if one is not already running.

??? info "What happened?"

    plotsrv inspected the object, chose a renderer, stored the latest value in memory, and started the local browser UI if needed.

    Because the object was a DataFrame, plotsrv rendered it as a table.

## What plotsrv can show

plotsrv chooses a renderer based on what you publish.

| Object | Renderer |
|---|---|
| Polars or pandas DataFrame | Table |
| matplotlib or plotnine plot | Plot |
| `dict`, `list`, `tuple` | JSON tree |
| `str`, `bytes`, log output | Text |
| Markdown text or files | Markdown |
| HTML text or files | HTML |
| Image files | Image |
| Exceptions / tracebacks | Traceback |
| Other Python objects | Python/repr view |

## Common ways to use plotsrv

### Mark views in a project

Use `@ps.view(...)` to describe outputs in your code, then run a plotsrv server.

```python title="views.py"
import polars as pl
import plotsrv as ps

@ps.view(label="Daily checks", section="etl")
def daily_checks():
    return pl.DataFrame({
        "check": ["source rows", "loaded rows", "warnings"],
        "value": [10000, 9985, 15],
    })
```

Then start plotsrv:

```bash
plotsrv run
```

This is the main server-style workflow: mark the views in code, start plotsrv, and let the UI organise them by section and label.

### Publish from Python

Use `refresh_view()` when working interactively in Python.

```python
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df, label="Example table", section="quickstart")
```

Use `publish_view()` when sending data to an already-running plotsrv server.

```python
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.publish_view(df, label="Example table", section="quickstart")
```

### Watch files

Use plotsrv to watch logs, CSV files, JSON files, markdown files, and other files on disk.

```bash
plotsrv watch app.log
```

```bash
plotsrv watch results.csv
```

You can also start a plotsrv server and attach watched files at the same time:

```bash
plotsrv run --watch app.log --watch results.csv
```

## Why plotsrv?

plotsrv is for people who already have Python processes and want useful observability without building a full web app.

It is designed to be:

- quick to start
- useful on headless servers
- friendly to scripts and ETL jobs
- good at rendering ordinary Python objects
- simple enough to use during exploration
- flexible enough to use in longer-running processes

## What plotsrv is not

plotsrv is not trying to replace Grafana, Prometheus, Streamlit, Dash, Shiny, or a full BI platform.

It is best thought of as a lightweight observability layer for Python work: a way to see the current state, recent outputs, logs, files, tables, and artifacts from a process while it runs.

## Next steps

Start with:

- [Installation](get-started/installation.md)
- [Quick start](get-started/quick-start.md)
- [Ways to use plotsrv](get-started/ways-to-use.md)
- [Renderer overview](renderers.md)
