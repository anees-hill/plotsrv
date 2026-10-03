<p align="center">
  <img
    src="https://raw.githubusercontent.com/anees-hill/plotsrv/main/src/plotsrv/static/plotsrv_icon_logo.png"
    width="180"
    align="middle"
    alt="plotsrv icon"
  >
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img
    src="https://raw.githubusercontent.com/anees-hill/plotsrv/main/src/plotsrv/static/plotsrv_title_logo_ui-white-bk.png"
    width="300"
    align="middle"
    style="position: relative; top: -20px;"
    alt="plotsrv"
  >
</p>

<p align="center">
  <strong>See Python objects, tables, plots, and logs in your browser.</strong>
</p>

<p align="center">
  <a href="https://github.com/anees-hill/plotsrv/actions/workflows/ci.yml"><img
    src="https://github.com/anees-hill/plotsrv/actions/workflows/ci.yml/badge.svg"
    alt="CI"
  /></a>
  <a href="https://codecov.io/github/anees-hill/plotsrv"><img
    src="https://codecov.io/github/anees-hill/plotsrv/graph/badge.svg?token=B9D8LB8K2H"
    alt="Codecov"
  /></a>
  <a href="https://pypi.org/project/plotsrv/"><img
    src="https://img.shields.io/pypi/v/plotsrv.svg?logo=pypi&label=PyPI&logoColor=gold"
    alt="PyPI"
  /></a>
  <a href="https://pypi.org/project/plotsrv/"><img
    src="https://img.shields.io/pypi/pyversions/plotsrv.svg?logo=python&label=Python&logoColor=gold"
    alt="Python versions"
  /></a>
</p>

<p align="center">
  <a href="https://docs.plotsrv.com"><strong>Documentation</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/get-started/quick-start/"><strong>Quick start</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/reference/python-api/"><strong>Python API</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/reference/cli/"><strong>CLI</strong></a>
  &middot;
  <a href="https://docs.plotsrv.com/examples/etl-pipeline/"><strong>Examples</strong></a>
</p>

Got a Python object you’d like to see in a browser?

```bash
python -m pip install plotsrv
```

In a Python REPL or notebook:

```python
import plotsrv as ps

ps.publish_view({"status": "ok", "rows": 123}, label="status", launch_server=True)
```

Open **http://127.0.0.1:8000**. Keep the Python session running while you look around.
Publish a DataFrame to get a table, or a Matplotlib figure to see a plot.

Already have a log?

```bash
plotsrv watch ./logs/job.log --tail
```

[Quick start](https://docs.plotsrv.com/get-started/quick-start/) ·
[Live demo](https://demo.plotsrv.com)

Python 3.11 or newer is required. In a uv project, use `uv add plotsrv` and
`uv run python`.

## Put it in a job

For a script that exits, keep plotsrv in a separate process. Save this as `job.py`:

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

Start `plotsrv run job.py` in one terminal, then `python job.py` in another.
The server discovers the declared view before the job runs. Calling the function
publishes its result and still returns it to your code.

[Use plotsrv in a project](https://docs.plotsrv.com/get-started/use-in-a-project/)
explains discovery, publishing, and configuration.

## What can plotsrv show?

plotsrv automatically chooses renderers for common outputs, including:

- pandas and Polars DataFrames
- matplotlib and plotnine plots
- dictionaries, lists, and JSON-like objects
- text, logs, markdown, HTML, and images
- Python objects, plus tracebacks when explicitly enabled
- files on disk, including CSV, JSON, YAML, TOML, markdown, HTML, text, and images

HTML reports can run scripts with the dashboard's browser-origin privileges.
Only publish HTML you trust. See the
[security reference](https://docs.plotsrv.com/reference/remote-publishing-and-security/)
before exposing a server publicly.

## Learn more

- [Quick start](https://docs.plotsrv.com/get-started/quick-start/)
- [Explore in the browser](https://docs.plotsrv.com/guides/explore-in-browser/)
- [Follow logs and streams](https://docs.plotsrv.com/guides/follow-logs-and-streams/)
- [Keep history](https://docs.plotsrv.com/guides/keep-history/)
- [Keep an eye on a job](https://docs.plotsrv.com/guides/keep-an-eye-on-a-job/)
- [Python API](https://docs.plotsrv.com/reference/python-api/)
- [CLI reference](https://docs.plotsrv.com/reference/cli/)
- [Supported outputs and files](https://docs.plotsrv.com/reference/supported-outputs-and-files/)
- [Run plotsrv on another machine](https://docs.plotsrv.com/guides/run-on-another-machine/)
- [Live demo](https://demo.plotsrv.com)

## License

plotsrv is licensed under the Apache License 2.0.

See the [LICENSE](LICENSE) file for full details.
