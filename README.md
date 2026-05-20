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
> See plotsrv render live plots, tables, JSON, and HTML from real sensor data.

`plotsrv` is a lightweight Python server for exposing live Python objects and on-disk files in a single browser UI. It gives you quick visibility into pipelines, experiments, batch jobs, and long-running processes without needing a full observability stack.

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

plotsrv can be used in an interactive session. Open a Python session and publish an object:

```python
import plotsrv as ps

summary = {
    "status": "ok",
    "rows_processed": 123,
    "checks": {
        "schema_valid": True,
        "missing_values": 0,
        "duplicates": 2,
    },
}

ps.publish_view(summary, label="summary", section="demo")
```

Open the viewer at:

```text
http://127.0.0.1:8000
```

`publish_view()` starts a local plotsrv server automatically when needed (attached to the process).

To serve the viewer on a custom host or port, use explicit local mode:

## Passive server workflow

For process **observability** (longer-running scripts, batch jobs, pipelines, etc.), you can run a separate plotsrv server and publish updates to it from your normal Python code.

### 1. Adjust your code to publish views

The most natural pattern is to add `@view` to a function that already produces something useful:

```python
# demo_view.py
import plotsrv as ps

@ps.view(
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
)
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

You can also publish directly with `publish_view()` when you already have an object:

```python
# demo_pipeline.py
import plotsrv as ps

result = {
    "job": "daily-import",
    "status": "ok",
    "rows_processed": 123,
    "warnings": ["2 duplicate rows found"],
}

ps.publish_view(
    result,
    mode="remote",
    host="127.0.0.1",
    port=8000,
    label="daily import",
    section="pipelines",
)
```

### 2. Start the server

In a terminal, start plotsrv against the script, module, or package you want it to inspect:

```bash
plotsrv run demo_pipeline.py --host 127.0.0.1 --port 8000
```

The server uses static discovery to pre-populate views where possible.

### 3. Run your script as normal

Run your python script/process as usual. i.e:

```bash
python demo_pipeline.py
```

Then open:

```text
http://127.0.0.1:8000
```

The published view should appear in the browser UI.

## Watching files on disk

`plotsrv` can expose files directly from disk, which is useful for logs, reports, HTML files, JSON outputs, CSVs, and generated artifacts.

For quick use:

```bash
plotsrv run --host 127.0.0.1 --port 8000 \
  --watch /var/log/etl_log.txt --watch-label etl-log --watch-section log-files --watch-tail
```



## License

plotsrv is licensed under the Apache License 2.0.

See the LICENSE file for full details.
