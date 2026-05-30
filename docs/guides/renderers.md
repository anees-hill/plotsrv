---
icon: lucide/rocket
---

# Renderers

plotsrv chooses a renderer based on the object or file that is published.

Most of the time, there is no need to choose a renderer manually. Publish an object, and plotsrv will display it in a useful way.

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="status",
    launch_server=True,
)
```

This publishes a dictionary-like object, so plotsrv displays it with the JSON renderer.

## Renderer summary

| Input | Renderer | Useful for |
|---|---|---|
| pandas or Polars DataFrame | Table | data inspection, search, filters, export |
| matplotlib or plotnine plot | Plot | charts and visual checks |
| `dict`, `list`, `tuple` | JSON | structured objects, metadata, configs, API responses |
| `str`, `bytes`, logs | Text | logs, plain text, command output |
| generic Python objects | Python | `repr()` output and object inspection |
| markdown text/files | Markdown | reports, notes, generated documentation |
| HTML text/files | HTML | HTML reports and generated pages |
| image files/payloads | Image | PNG, JPEG, GIF, WebP, BMP, SVG |
| traceback payloads | Traceback | exception observability |
| path-like files | Inferred from file type | CSV, JSON, YAML, TOML, markdown, HTML, text, images |

## Table renderer

DataFrames are rendered as tables.

```python title="table_example.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "centre": ["A", "B", "C"],
    "returned": [120, 98, 143],
    "expected": [125, 100, 150],
})

ps.publish_view(
    df,
    label="returns",
    section="renderers",
    launch_server=True,
)
```

The table renderer includes:

- search
- filters
- column controls
- pagination
- export
- status information when only part of a table is shown

pandas DataFrames are also supported.

```python title="pandas_table_example.py"
import pandas as pd
import plotsrv as ps

df = pd.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.publish_view(
    df,
    label="pandas table",
    section="renderers",
    launch_server=True,
)
```

Table limits can be configured in `plotsrv.yaml`.

```yaml title="plotsrv.yaml"
limits:
  tables:
    max_rows: 10000
    max_columns: 200
```

## Plot renderer

matplotlib and plotnine plots are rendered as image views.

```python title="plot_example.py"
import matplotlib.pyplot as plt
import plotsrv as ps

fig, ax = plt.subplots()
ax.plot([1, 2, 3, 4], [10, 20, 15, 30])
ax.set_title("Example metric")
ax.set_xlabel("Run")
ax.set_ylabel("Value")

ps.publish_view(
    fig,
    label="metric plot",
    section="renderers",
    launch_server=True,
)
```

The plot renderer is useful for checking charts from scripts, jobs, notebooks, or server sessions.

plotsrv renders plots using a headless matplotlib backend, which is useful on servers where a desktop plotting window is not available.

## JSON renderer

Dictionaries, lists, and tuples are shown with the JSON renderer.

```python title="json_example.py"
import plotsrv as ps

metadata = {
    "experiment": "baseline-model",
    "status": "complete",
    "metrics": {
        "accuracy": 0.91,
        "precision": 0.88,
        "recall": 0.86,
    },
    "features": ["age", "score", "previous_attempts"],
}

ps.publish_view(
    metadata,
    label="model metadata",
    section="renderers",
    launch_server=True,
)
```

The JSON renderer includes:

- expandable tree view
- simple tree view
- text view
- search
- expand/collapse controls
- pinned values

It is useful for:

- API responses
- model metadata
- configuration-like objects
- nested dictionaries
- validation summaries
- job status objects

## Text renderer

Strings and bytes are shown with the text renderer.

```python title="text_example.py"
import plotsrv as ps

log_text = """INFO job started
INFO extract complete
WARNING 15 rows skipped
ERROR one optional file was missing
INFO job finished
"""

ps.publish_view(
    log_text,
    label="job log",
    section="renderers",
    launch_server=True,
)
```

The text renderer includes:

- copy
- word wrap
- reverse line order
- lightweight log colouring
- jump to bottom

This is useful for:

- logs
- console output
- plain text reports
- watched text files
- simple status messages

## Python renderer

Generic Python objects that do not match a more specific renderer are shown using a Python/repr-style view.

```python title="python_object_example.py"
from dataclasses import dataclass
import plotsrv as ps

@dataclass
class RunConfig:
    model_name: str
    threshold: float
    max_rows: int

config = RunConfig(
    model_name="baseline",
    threshold=0.75,
    max_rows=10000,
)

ps.publish_view(
    config,
    label="run config",
    section="renderers",
    launch_server=True,
)
```

The Python renderer is useful when debugging object state or publishing a `repr()`-style artifact.

## Markdown renderer

Markdown strings and markdown files are rendered as markdown views.

```python title="markdown_example.py"
import plotsrv as ps

report = """
# Daily import report

## Summary

- Rows in: 10,000
- Rows loaded: 9,985
- Warnings: 15

| Check | Status |
|---|---|
| Schema | OK |
| Duplicates | Warning |
"""

ps.publish_view(
    report,
    label="markdown report",
    section="renderers",
    artifact_kind="markdown",
    launch_server=True,
)
```

Markdown is useful for:

- generated reports
- summaries
- notes
- lightweight documentation
- validation output

Markdown sanitisation is configurable.

## HTML renderer

HTML strings and HTML files are rendered with the HTML renderer.

```python title="html_example.py"
import plotsrv as ps

html = """
<h1>Daily import report</h1>
<p>Status: <strong>ok</strong></p>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Rows processed</td><td>9985</td></tr>
  <tr><td>Warnings</td><td>15</td></tr>
</table>
"""

ps.publish_view(
    html,
    label="html report",
    section="renderers",
    artifact_kind="html",
    launch_server=True,
)
```

HTML artifacts are useful for:

- generated reports
- existing HTML output
- simple rendered pages
- exported artifacts from other tools

!!! warning

    HTML can contain active content.

    Use trusted HTML where possible, and review sanitisation/sandbox settings before exposing HTML views more widely.

## Image renderer

Image files can be published directly using a `Path`.

```python title="image_file_example.py"
from pathlib import Path
import plotsrv as ps

ps.publish_view(
    Path("example.png"),
    label="example image",
    section="renderers",
    launch_server=True,
)
```

A `Path` object tells plotsrv to read the file contents.

A plain string is treated as text:

```python
ps.publish_view(
    "example.png",
    label="literal text",
    section="renderers",
    launch_server=True,
)
```

The image renderer supports common image types such as:

- PNG
- JPEG
- GIF
- WebP
- BMP
- SVG

## Traceback renderer

Tracebacks can be published as structured artifacts.

Traceback rendering is disabled by default because tracebacks can expose file paths, source-code context, and other implementation details.

Enable it in config:

```yaml title="plotsrv.yaml"
security-settings:
  tracebacks_enabled: true
```

Then use `capture_exceptions()`:

```python title="traceback_example.py"
import plotsrv as ps

with ps.capture_exceptions(
    label="job error",
    section="renderers",
    launch_server=True,
):
    raise RuntimeError("Example failure")
```

The traceback renderer shows:

- exception type
- exception message
- stack frames
- file names
- line numbers
- source-code context where available

!!! warning

    Tracebacks are useful for development and internal observability, but they may expose sensitive implementation details.

    Enable traceback rendering only where that is acceptable.

## File rendering

plotsrv can infer renderers from file extensions.

```python title="publish_file.py"
from pathlib import Path
import plotsrv as ps

ps.publish_view(
    Path("results.csv"),
    label="results table",
    section="files",
    launch_server=True,
)
```

File inference is useful for existing outputs written by a process, such as CSVs, JSON files, markdown reports, HTML reports, logs, and images.

## File type summary

| Extension | Renderer |
|---|---|
| `.csv` | Table |
| `.json` | JSON |
| `.yaml`, `.yml` | JSON-like structured view |
| `.toml` | JSON-like structured view |
| `.ini`, `.cfg` | JSON-like structured view |
| `.md`, `.markdown` | Markdown |
| `.html`, `.htm` | HTML |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg` | Image |
| anything else | Text |

## Forcing a renderer

Most of the time, automatic renderer selection is enough.

When needed, provide an explicit artifact kind.

```python title="force_markdown.py"
import plotsrv as ps

text = """
# Report

This should be rendered as markdown.
"""

ps.publish_view(
    text,
    label="forced markdown",
    section="renderers",
    artifact_kind="markdown",
    launch_server=True,
)
```

For HTML:

```python title="force_html.py"
import plotsrv as ps

html = "<h1>Hello from HTML</h1>"

ps.publish_view(
    html,
    label="forced html",
    section="renderers",
    artifact_kind="html",
    launch_server=True,
)
```

## Publishing to an existing server

The examples above use `launch_server=True`, which starts an attached server inside the current Python process.

For the server workflow, start plotsrv separately:

```bash
plotsrv run script.py --host 127.0.0.1 --port 8000
```

Then publish with `host` and `port`:

```python
ps.publish_view(
    obj,
    label="result",
    section="renderers",
    host="127.0.0.1",
    port=8000,
)
```

Do not use `launch_server=True` in this case. With `host` and `port` only, `publish_view()` publishes to an existing plotsrv server.

## Renderer limits

Some renderers apply display limits to keep the browser responsive.

For example:

```yaml title="plotsrv.yaml"
limits:
  render:
    text: 1000000
    html: off
    markdown: off

  tables:
    max_rows: 10000
    max_columns: 200
```

Text-like renderer limits control how much content is displayed in the browser.

Table limits control how much table data plotsrv accepts and displays.

## Next steps

- [Quick start](../get-started/quick-start.md)
- [Watch files](../get-started/watch-files.md)
- [Configuration basics](../get-started/configuration-basics.md)
- [Storage and history](storage-and-history.md)
