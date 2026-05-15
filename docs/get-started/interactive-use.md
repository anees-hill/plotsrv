---
icon: lucide/terminal
---

# Use plotsrv interactively

plotsrv is useful when you are working in a Python session and want to inspect objects in a browser.

This is especially helpful when you are:

- working over SSH
- using a headless server
- exploring data in a terminal session
- checking plots where rich local tooling is awkward
- inspecting tables, logs, or JSON-like objects repeatedly

The simplest interactive workflow is:

```python
ps.refresh_view(obj)
```

`refresh_view()` publishes the object from the current Python process and starts a local plotsrv server automatically if one is not already running.

## Start with a table

```python title="interactive_table.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
    "group": ["A", "A", "B"],
})

ps.refresh_view(df)
```

Then open:

```text
http://127.0.0.1:8000
```

You should see the table in the plotsrv UI.

!!! note

    DataFrames are rendered as tables. The table view includes search, filters, column controls, pagination, and export.

## Add labels and sections

When you have more than one view, add a label and section.

```python title="interactive_labelled_table.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
    "group": ["A", "A", "B"],
})

ps.refresh_view(df, label="Example table", section="eda")
```

- `label` is the display name for the view.
- `section` groups related views together.

This is useful when you are publishing several objects during an analysis.

## Refresh the same view

Calling `refresh_view()` again with the same label and section updates the same view.

```python title="interactive_refresh.py"
import polars as pl
import plotsrv as ps

df1 = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df1, label="Current data", section="eda")

df2 = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [12, 18, 35],
})

ps.refresh_view(df2, label="Current data", section="eda")
```

The browser view updates to show the latest object.

## Publish a plot

```python title="interactive_plot.py"
import matplotlib.pyplot as plt
import plotsrv as ps

fig, ax = plt.subplots()
ax.plot([1, 2, 3, 4], [10, 20, 15, 30])
ax.set_title("Example metric")
ax.set_xlabel("Run")
ax.set_ylabel("Value")

ps.refresh_view(fig, label="Metric plot", section="eda")
```

The plot renderer displays the figure as an image and provides an export button.

## Publish JSON-like objects

Dictionaries and lists are shown with the JSON renderer.

```python title="interactive_json.py"
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

ps.refresh_view(metadata, label="Model metadata", section="eda")
```

The JSON renderer gives you an expandable tree, search controls, pinned values, and text view.

## Publish text or logs

Strings are shown with the text renderer.

```python title="interactive_text.py"
import plotsrv as ps

log_text = """INFO started analysis
INFO loaded 10000 rows
WARNING 15 rows skipped
INFO finished analysis
"""

ps.refresh_view(log_text, label="Analysis log", section="eda")
```

The text renderer includes copy, wrap, reverse lines, and lightweight log styling.

## Publish a generic Python object

Objects that do not match a more specific renderer are shown using a Python/repr-style view.

```python title="interactive_python_object.py"
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

ps.refresh_view(config, label="Run config", section="eda")
```

This can be useful when debugging object state.

## Start and stop the server explicitly

You usually do not need to start the server manually when using `refresh_view()`.

But you can:

```python title="manual_server.py"
import plotsrv as ps

ps.start_server()
```

Then publish objects:

```python
ps.refresh_view({"status": "ok"}, label="Status", section="manual")
```

Stop the server with:

```python
ps.stop_server()
```

## Use a context manager

For scripts, you can use `plot_session()`:

```python title="plot_session_example.py"
import polars as pl
import plotsrv as ps

with ps.plot_session():
    df = pl.DataFrame({
        "name": ["alpha", "beta", "gamma"],
        "value": [10, 20, 30],
    })

    ps.refresh_view(df, label="Session table", section="example")

    input("Open http://127.0.0.1:8000, then press Enter to stop...")
```

When the context exits, plotsrv stops the background server.

## Working over SSH

If plotsrv is running on a remote server, SSH port forwarding is often the simplest way to view it safely.

On your local machine:

```bash
ssh -L 8000:127.0.0.1:8000 user@your-server
```

On the server, run your Python code as normal.

Then open this on your local machine:

```text
http://127.0.0.1:8000
```

!!! warning

    Avoid exposing plotsrv directly to the public internet unless you have thought through access controls, network boundaries, and deployment security.

## When to use `refresh_view()` vs `publish_view()`

Use `refresh_view()` when you are publishing from the same Python process that owns the in-process plotsrv server.

```python
ps.refresh_view(df)
```

Use `publish_view()` when a plotsrv server is already running and your Python process should publish to it over HTTP.

```python
ps.publish_view(df, label="Example table", section="eda")
```

For interactive use, `refresh_view()` is usually the simplest starting point.

## Next steps

- [Run a plotsrv server](run-a-plotsrv-server.md)
- [Watch files](watch-files.md)
- [Renderer overview](../renderers.md)
