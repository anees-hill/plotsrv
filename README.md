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

<p align="center">
  <strong>Developer friendly, lightweight observability for Python processes.</strong>
</p>

<p align="center">
  <a href="https://docs.plotsrv.com"><strong>Documentation</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/get-started/quick-start/"><strong>Quick start</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/guides/python-api/"><strong>Python API</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/guides/cli/"><strong>CLI</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/examples/"><strong>Examples</strong></a>
</p>

<p align="center">
  <a href="https://docs.plotsrv.com"><strong>Documentation</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/get-started/quick-start/"><strong>Quick start</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/guides/python-api/"><strong>Python API</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/guides/cli/"><strong>CLI</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/examples/"><strong>Examples</strong></a>
  &middot;
  <a href="https://demo.plotsrv.com"><strong>Live demo</strong></a>
</p>

Turn Python objects into live browser views with minimal code.

It is designed for scripts, pipelines, experiments, batch jobs, and long-running processes where useful outputs are otherwise hidden in terminal logs, temporary objects, generated files, or ad hoc plots.

`plotsrv` can render tables, plots, JSON, HTML, logs, images, tracebacks, files, and ordinary Python objects in a single browser UI.

> **Live demo:** https://demo.plotsrv.com  
> See a deployed example showing real sensor data.

## Install

```bash
pip install plotsrv
```

or:

```bash
uv add plotsrv
```

## Quick example

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

ps.publish_view(
    summary,
    label="summary",
    section="demo",
    launch_server=True,
)
```

Open:

```text
http://127.0.0.1:8000
```

## Server workflow

For scripts, jobs, and pipelines, start plotsrv separately:

```bash
plotsrv run demo_pipeline.py --host 127.0.0.1 --port 8000
```

Then publish to it from Python:

```python
import plotsrv as ps

@ps.view(label="daily import", section="pipelines", host="127.0.0.1", port=8000)
def daily_import_status():
    return {
        "job": "daily-import",
        "status": "ok",
        "rows_processed": 123,
    }

daily_import_status()
```

The function still returns normally, while plotsrv publishes the returned object into the browser UI.

## What can plotsrv show?

plotsrv automatically chooses renderers for common outputs, including:

- pandas and Polars DataFrames
- matplotlib and plotnine plots
- dictionaries, lists, and JSON-like objects
- text, logs, markdown, HTML, and images
- Python objects and tracebacks
- files on disk, including CSV, JSON, YAML, TOML, markdown, HTML, text, and images

## Why use it?

plotsrv provides cheap observability for Python processes.

It is useful when you want more visibility into a script or pipeline without building a dashboard, adopting a full observability stack, or manually opening generated files on disk.

## Learn more

- [What is plotsrv?](https://docs.plotsrv.com/get-started/what-is-plotsrv/)
- [Quick start](https://docs.plotsrv.com/get-started/quick-start/)
- [Python API](https://docs.plotsrv.com/guides/python-api/)
- [CLI reference](https://docs.plotsrv.com/guides/cli/)
- [Renderers](https://docs.plotsrv.com/guides/renderers/)
- [Storage and history](https://docs.plotsrv.com/guides/storage-and-history/)
- [Deployment patterns](https://docs.plotsrv.com/guides/deployment-patterns/)
- [Live demo](https://demo.plotsrv.com)

## License

plotsrv is licensed under the Apache License 2.0.

See the [LICENSE](LICENSE) file for full details.
