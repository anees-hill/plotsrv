---
icon: lucide/map
---

# Ways to use plotsrv

plotsrv can be used in a few different ways.

If you are unsure where to start, start with this:

```bash
plotsrv run
```

Then add `@ps.view(...)` decorators to the Python functions you want plotsrv to discover.

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

This is the main server-style workflow: mark useful outputs in your code, run a plotsrv server, and publish data into those views as your process runs.

## Choose a workflow

| You want to... | Start with |
|---|---|
| Mark useful outputs in a project | `@ps.view(...)` and `plotsrv run` |
| Send an object from a Python session | `ps.refresh_view(obj)` |
| Send an object to an already-running plotsrv server | `ps.publish_view(obj, label=...)` |
| Watch a file on disk | `plotsrv watch file.log` |
| Watch files while running a plotsrv server | `plotsrv run --watch file.log` |
| Keep historical snapshots | enable `storage-settings` |
| Show freshness/staleness indicators | enable `freshness-settings` |

!!! note

    You do not need to choose perfectly up front.

    Most projects start with one simple workflow, then gradually add labels, sections, watched files, storage, or freshness indicators later.

## 1. Run a plotsrv server

Use this when you have a Python project, script, package, or process that you want to observe from a browser UI.

Mark a view in your code:

```python title="views.py"
import polars as pl
import plotsrv as ps

@ps.view(label="Current status", section="etl")
def current_status():
    return {
        "job": "daily-import",
        "status": "ok",
        "rows_loaded": 9985,
    }
```

Start the server:

```bash
plotsrv run
```

Then publish to the same view from Python:

```python
import plotsrv as ps

ps.publish_view(
    {
        "job": "daily-import",
        "status": "ok",
        "rows_loaded": 9985,
    },
    label="Current status",
    section="etl",
)
```

The decorator gives plotsrv metadata about the view. `publish_view()` sends data to the running plotsrv server.

Read more: [Run a plotsrv server](run-a-plotsrv-server.md).

## 2. Use plotsrv interactively

Use this when you are working in a Python session and want to quickly inspect an object.

```python title="interactive.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df, label="Example table", section="interactive")
```

Open:

```text
http://127.0.0.1:8000
```

`refresh_view()` is the simplest way to publish an object from the same Python process.

It is useful for:

- exploratory data analysis
- working over SSH
- inspecting large-ish tables in a browser
- checking plots on a headless server
- viewing JSON-like objects without printing them to the terminal

Read more: [Use plotsrv interactively](interactive-use.md).

## 3. Watch files

Use this when your process already writes useful files to disk.

For example, watch a log file:

```bash
plotsrv watch app.log
```

Watch a CSV file as a table:

```bash
plotsrv watch results.csv
```

Or start a server and attach watched files:

```bash
plotsrv run --watch app.log --watch results.csv
```

plotsrv can infer common file types, including text, logs, CSV, JSON, YAML, TOML, markdown, HTML, and images.

Read more: [Watch files](watch-files.md).

## 4. Add configuration

Once you have more than one view, create a config file:

```bash
plotsrv config create
```

Configuration lets you control things like:

- table limits
- watched-file byte limits
- storage
- historical snapshots
- freshness indicators
- UI customisation
- security settings

Read more: [Configuration basics](configuration-basics.md).

## 5. Add storage and freshness later

You do not need storage or freshness indicators to start using plotsrv.

They are useful once plotsrv is observing a repeated or scheduled process.

Storage lets you keep recent snapshots:

```yaml title="plotsrv.yml"
storage-settings:
  enabled: true
  default_keep_last: 5
```

Freshness indicators let the UI show whether a view is fresh, stale, or overdue:

```yaml title="plotsrv.yml"
freshness-settings:
  enabled: true
  expected_every: 60s
  warn_after: 90s
  overdue_after: 180s
```

These features are best added after the basic publishing workflow is working.

## Recommended path

For most users:

- start with [Quick start](quick-start.md)
- then try [Run a plotsrv server](run-a-plotsrv-server.md)
- then add [Watch files](watch-files.md) if your process writes files
- then add [Configuration basics](configuration-basics.md) once you have multiple views
