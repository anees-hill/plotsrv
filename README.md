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

1. **Install plotsrv**
```bash
pip install plotsrv
```
Or
```bash
uv add plotsrv
```

2.  **Start the server**

Provide a script, module or entire package: 

``` bash
plotsrv run your_module.py --host 127.0.0.1 --port 8000
```

You can also start the server from Python if needed.

3.  **Expose views from your code**

The main pattern is to decorate functions whose output you want to expose:

``` python
from plotsrv import plotsrv

@ps.view(label="sales", section="insights")
def sales_plot():
    return fig

@ps.view(label="latest", section="insights")
def latest_results():
    return df
```

`plotsrv` inspects the returned object and chooses an appropriate renderer automatically.

You can also publish artifacts directly instead of using decorators:

``` python
import plotsrv as ps

ps.publish_view({"status": "ok", "rows": 123}, label="summary")
```

## Watching files on disk

`plotsrv` can also expose files directly from disk, which is useful for logs, reports, HTML files, JSON outputs, CSVs, and generated artifacts.

``` bash
plotsrv run src.etl --host 127.0.0.1 --port 8000 \
  --watch /var/log/etl_log.txt --watch-label etl-log --watch-section log-files --watch-tail --no-truncate
```

## License

plotsrv is licensed under the Apache License 2.0.

See the LICENSE file for full details.
