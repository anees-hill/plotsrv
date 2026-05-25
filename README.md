<p align="center">
  <img
    src="https://raw.githubusercontent.com/anees-hill/plotsrv/main/src/plotsrv/static/plotsrv_icon_logo.png"
    width="180"
    align="middle"
    alt="plotsrv icon"
  >
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img
    src="https://raw.githubusercontent.com/anees-hill/plotsrv/main/src/plotsrv/static/plotsrv_title_logo.png"
    width="300"
    align="middle"
    style="position: relative; top: -20px;"
    alt="plotsrv"
  >
</p>

---

![eCI](https://github.com/anees-hill/plotsrv/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/github/anees-hill/plotsrv/graph/badge.svg?token=B9D8LB8K2H)](https://codecov.io/github/anees-hill/plotsrv)
[![PyPI - Version](https://img.shields.io/pypi/v/plotsrv.svg?logo=pypi&label=PyPI&logoColor=gold)](https://pypi.org/project/plotsrv/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/plotsrv.svg?logo=python&label=Python&logoColor=gold)](https://pypi.org/project/plotsrv/)

**Lightweight observability for Python processes with instant UI**

> **Live demo:** https://demo.plotsrv.com  
> See plotsrv render plots, tables, JSON, and HTML from real sensor data.

`plotsrv` is a lightweight Python server for exposing live Python objects and on-disk files in a single browser UI. It provides quick visibility into pipelines, experiments, batch jobs, and long-running processes without needing a full observability stack.

Add a decorator to functions you want to expose, or publish artifacts directly from your code. Fire up the server with a single command, and plotsrv takes care of discovery, view registration, and object-specific rendering automatically.

**Key features**:

-   Browser UI built on FastAPI for viewing live outputs in one place
-   Automatic rendering for common Python outputs: plots, tables, JSON, text, HTML, images, code, and tracebacks
-   Minimal setup: decorate functions and launch the server
-   AST-based discovery of decorated views, so the UI can pre-populate navigation on startup
-   Optional on-disk snapshots, with historical browsing and configurable retention
-   Freshness tracking, so you can quickly see when a process is delayed or stale
-   Configuration via `plotsrv.yaml`, including UI settings
-   CLI-first workflow, with Python entry points available where needed

It can also watch files on disk and expose them in the same UI.

# Get going

Install plotsrv:

```bash
pip install plotsrv
```

Or:

```bash
uv add plotsrv
```

## Interactive use

plotsrv can be used directly from a Python session. For quick inspection, pass `launch_server=True` to start a local plotsrv server attached to your current Python process:

```python
import plotsrv as ps

summary = {
    "status": "ok",
    "rows_processed": 123,
    "checks": {
        "schema_valid": True,
        "duplicates": 2,
    },
}

ps.publish_view(summary, label="summary", launch_server=True)
```

Open the viewer at:

```text
http://127.0.0.1:8000
```

In this mode, plotsrv starts a server in the same Python process. When that process exits, the attached server exits too.

## Passive server workflow

For scripts, jobs, and pipelines, start plotsrv as a passive server:

### 1. Adjust your code to publish views

A simple way to expose existing code is to add a `@view` decorator to a function that already returns something useful:

```python
# demo_view.py
import plotsrv as ps

@ps.view(label="daily import", section="pipelines", host="127.0.0.1", port=8000)
def daily_import_status():
    return {
        "job": "daily-import",
        "status": "ok",
        "rows_processed": 123,
        "warnings": ["2 duplicate rows found"],
    }

# Your code can still run as normal.
status = daily_import_status()
print(status)
```

When `daily_import_status()` is called, it returns the same object as usual and also publishes that object to the plotsrv server.

Alternatively, use `publish_view() to publish an object directly:

```python
# demo_pipeline.py
import plotsrv as ps
import polars as pl

df = pl.DataFrame({
    "name": ["Alice", "Bob", "Charlie"],
    "score": [82, 91, 77],
})

ps.publish_view(
    df,
    mode="remote",
    host="127.0.0.1",
    port=8000,
    label="student scores",
)
```

### 2. Start the server

In a terminal, start plotsrv against the script, module, or package you want it to inspect:

```bash
plotsrv run demo_pipeline.py --host 127.0.0.1 --port 8000
```

plotsrv scans the given script, module, or package for `@view` decorators / `publish_view()` calls and uses those to pre-populate the UI.

### 3. Run your script as normal

Run your Python script or process as usual:

```bash
python demo_pipeline.py
```

Then open:

```text
http://127.0.0.1:8000
```

The published views will appear in the browser UI and update each time the script is run.

### 4. Enable history and persistent storage

By default, plotsrv keeps live views in memory. This is fast and simple, but views disappear when the process exits.

To keep historical snapshots and restore the latest live view after restart, create a `plotsrv.yaml` file:

```yaml
storage-settings:
  enabled: true
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20
```

With storage enabled, plotsrv can keep recent snapshots for comparison and restore the latest view when the server starts again.

You can also create a starter config file with:

```bash
plotsrv config create
```

The config file can also control table limits, freshness checks, UI settings, logo/header customisation, and renderer behaviour.

## Watching files on disk

`plotsrv` can expose files directly from disk including logs, reports, HTML files, JSON outputs, CSVs, and generated artifacts.

For quick use:

```bash
plotsrv run --host 127.0.0.1 --port 8000 \
  --watch /var/log/etl_log.txt --watch-label etl-log --watch-section log-files --watch-tail
```

## What can plotsrv render?

plotsrv automatically chooses a renderer for common Python outputs, including:

- matplotlib and plotnine plots
- dictionaries, lists, and JSON-like objects
- pandas and polars DataFrames
- text, logs, markdown, HTML, and images
- Python objects and tracebacks
- files on disk, including CSV, JSON, YAML, TOML, markdown, HTML, text, and images

## License

plotsrv is licensed under the Apache License 2.0.

See the LICENSE file for full details.
