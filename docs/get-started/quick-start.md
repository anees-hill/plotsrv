# Quick start

## Install

Use Python 3.11 or newer. Install into the environment where your code runs:

=== "pip"

    ```bash
    python -m pip install plotsrv
    ```

=== "uv"

    ```bash
    uv add plotsrv
    ```

No config file is needed.

## Show an object

Start an interactive Python session (`python`, or `uv run python` in a uv project):

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok", "rows": 123},
    label="status",
    launch_server=True,
)
```

Open **<http://127.0.0.1:8000>**. Expand the dictionary to inspect its values.
The server runs in this Python process; leave the session open.

Publish again with the same label to replace that view:

```python
ps.publish_view({"status": "done", "rows": 456}, label="status")
```

## Try a table

In the same session:

```python
import pandas as pd

orders = pd.DataFrame({
    "region": ["North", "South", "North"],
    "orders": [12, 18, 9],
    "revenue": [240, 540, 180],
})
ps.publish_view(orders, label="orders")
```

Choose **orders** in the view selector. Search the rows or click a column to
sort them. pandas is installed with plotsrv’s table dependencies.

That’s enough to try it. When finished:

```python
ps.stop_server(join=True)
```

## Next

- [Use plotsrv in a project](../guides/cli.md#what-plotsrv-run-does) to keep a server running between jobs.
- [Watch files](watch-files.md) if your program already writes the output you need.
- [See supported outputs](../guides/renderers.md) for plots, reports, images, and other types.

The [ETL example](../examples/etl-pipeline.md) shows a complete script. Unlike the
interactive example above, it publishes to a separate server so the browser
remains available after the script finishes.
