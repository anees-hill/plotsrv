---
icon: lucide/server
---

# Run a plotsrv server

This is the main server-style way to use plotsrv.

You mark useful outputs in your Python code with `@ps.view(...)`, then start the plotsrv server with:

```bash
plotsrv run
```

plotsrv discovers the marked views and shows them in the browser UI.

!!! note

    In this workflow, `@ps.view(...)` is the main way to describe what should appear in the plotsrv UI.

    `publish_view()` is then used by running Python code to send data into those views.

## A minimal view

Create a Python file:

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

Then run plotsrv from the same project directory:

```bash
plotsrv run
```

Open:

```text
http://127.0.0.1:8000
```

You should see a plotsrv UI with a view called **Daily checks** in the **etl** section.

??? info "What did plotsrv discover?"

    plotsrv scans Python files for `@ps.view(...)` / `@view(...)` decorators.

    It can use that metadata to pre-register views in the UI without needing to execute your functions just to build the view selector.

## Publishing data to the view

The decorator gives plotsrv the view metadata.

To send data to a running plotsrv server, publish an object with the same label and section.

```python title="publish_daily_checks.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "check": ["source rows", "loaded rows", "warnings"],
    "value": [10000, 9985, 15],
})

ps.publish_view(df, label="Daily checks", section="etl")
```

The browser UI will update the **Daily checks** view.

## Why use both `@view` and `publish_view()`?

They do different jobs.

`@ps.view(...)` describes the view:

```python
@ps.view(label="Daily checks", section="etl")
def daily_checks():
    ...
```

`ps.publish_view(...)` sends data to the server:

```python
ps.publish_view(df, label="Daily checks", section="etl")
```

For small examples, these may look repetitive. In a real project, the decorator helps plotsrv discover and organise views, while `publish_view()` can be called from the process that produces the actual output.

## Using a callable

You can also point plotsrv at a callable target.

For example, if you have:

```python title="my_project/views.py"
import polars as pl
import plotsrv as ps

@ps.view(label="Summary", section="etl")
def summary():
    return pl.DataFrame({
        "metric": ["rows_in", "rows_out", "warnings"],
        "value": [10000, 9985, 15],
    })
```

You can run plotsrv in callable mode:

```bash
plotsrv run my_project.views:summary --mode callable --keep-alive
```

This runs the callable and keeps the server alive.

You can also run it repeatedly:

```bash
plotsrv run my_project.views:summary --mode callable --call-every 60
```

!!! note

    Callable mode currently expects functions that can be called without required arguments.

## Running against a project path

You can also give `plotsrv run` an explicit path to scan:

```bash
plotsrv run ./src
```

or:

```bash
plotsrv run .
```

If no target is supplied, plotsrv tries to detect a Python project root from the current directory.

## Labels and sections

Labels and sections control how views are shown in the UI.

```python
@ps.view(label="Bookings", section="operations")
def bookings():
    ...
```

- `label` is the display name for the view.
- `section` groups related views together.
- Together they form a natural view identity.

For example:

```python
ps.publish_view(df, label="Bookings", section="operations")
```

will publish to the same **Bookings** view in the **operations** section.

## Publishing different object types

`publish_view()` can publish many object types.

### Table

```python
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "centre": ["A", "B", "C"],
    "returned": [120, 98, 143],
})

ps.publish_view(df, label="Returns", section="operations")
```

### JSON

```python
import plotsrv as ps

summary = {
    "job": "daily-import",
    "status": "ok",
    "rows_loaded": 9985,
    "warnings": 15,
}

ps.publish_view(summary, label="Summary", section="operations")
```

### Text

```python
import plotsrv as ps

log_text = """INFO job started
INFO extract complete
WARNING 15 rows skipped
INFO job finished
"""

ps.publish_view(log_text, label="Log", section="operations")
```

### Plot

```python
import matplotlib.pyplot as plt
import plotsrv as ps

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [120, 98, 143])
ax.set_title("Returned scripts")

ps.publish_view(fig, label="Returns plot", section="operations")
```

## Host and port

By default, plotsrv runs on:

```text
http://127.0.0.1:8000
```

You can choose a different host or port:

```bash
plotsrv run --host 127.0.0.1 --port 9000
```

Then publish to that port:

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="Status",
    section="example",
    host="127.0.0.1",
    port=9000,
)
```

!!! warning

    Be careful before binding plotsrv to `0.0.0.0` or exposing it outside your machine.

    For many server workflows, an SSH tunnel or reverse proxy with appropriate access controls is safer than exposing plotsrv directly.

## Watching files while the server runs

You can attach watched files when starting the server:

```bash
plotsrv run --watch app.log --watch results.csv
```

This is useful when your process already writes logs or output files to disk.

Read more: [Watch files](watch-files.md).

## Stop the server

If plotsrv is running in the terminal, stop it with:

```text
Ctrl+C
```

If you started it from Python with `ps.start_server()`, stop it with:

```python
import plotsrv as ps

ps.stop_server()
```

## Next steps

- [Use plotsrv interactively](interactive-use.md)
- [Watch files](watch-files.md)
- [Configuration basics](configuration-basics.md)
- [View labels and sections](../features/view-labels-and-sections.md)
