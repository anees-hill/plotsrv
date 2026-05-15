---
icon: lucide/rocket
---

# Quick start

This page shows the fastest way to see something in plotsrv.

You will publish a small table from Python and view it in your browser.

## Publish a table

Start a Python session and run:

```python title="quickstart.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df)
```

Then open:

```text
http://127.0.0.1:8000
```

You should see the DataFrame rendered as a table.

!!! note

    `ps.refresh_view()` is the quickest way to send an object to plotsrv from a Python session.

??? info "What happened?"

    plotsrv inspected the object, chose a renderer, stored the latest value in memory, and started the local browser UI if needed.

    Because the object was a DataFrame, plotsrv rendered it as a table.

## Add a label and section

You can give the view a label and section.

```python title="labelled_table.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df, label="Example table", section="quickstart")
```

Labels and sections make the UI easier to navigate when you have more than one view.

- `label` is the display name for the view.
- `section` groups related views together.
- Together, they help organise the view selector in the browser UI.

## Publish JSON

Dictionaries and lists are shown as structured JSON views.

```python title="json_example.py"
import plotsrv as ps

summary = {
    "job": "daily-import",
    "status": "ok",
    "checks": {
        "rows_in": 10000,
        "rows_out": 9985,
        "warnings": ["15 rows skipped"],
    },
}

ps.refresh_view(summary, label="Job summary", section="quickstart")
```

The JSON renderer gives you an expandable tree view, search controls, and different viewing modes.

## Publish text

Strings are shown with the text renderer.

```python title="text_example.py"
import plotsrv as ps

log_text = """INFO extract complete
INFO transform complete
WARNING 15 rows skipped
INFO load complete
"""

ps.refresh_view(log_text, label="Job log", section="quickstart")
```

The text renderer includes controls for copying, wrapping, reversing lines, and lightweight log styling.

## Publish a plot

matplotlib figures are shown as plot views.

```python title="plot_example.py"
import matplotlib.pyplot as plt
import plotsrv as ps

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [10, 20, 15])
ax.set_title("Example metric")

ps.refresh_view(fig, label="Metric plot", section="quickstart")
```

The plot renderer displays the figure as an image in the browser and includes an export button.

## Publish more than one view

You can publish several views into different labels and sections.

```python title="multiple_views.py"
import polars as pl
import plotsrv as ps

checks = pl.DataFrame({
    "check": ["source rows", "loaded rows", "warnings"],
    "value": [10000, 9985, 15],
})

summary = {
    "job": "daily-import",
    "status": "warning",
    "message": "15 rows were skipped",
}

log_text = """INFO extract complete
INFO transform complete
WARNING 15 rows skipped
INFO load complete
"""

ps.refresh_view(checks, label="Checks", section="etl")
ps.refresh_view(summary, label="Summary", section="etl")
ps.refresh_view(log_text, label="Log", section="etl")
```

The browser UI will show these as separate views in the view selector.

## Stop the server

If you started plotsrv from Python, you can stop it with:

```python
import plotsrv as ps

ps.stop_server()
```

If plotsrv was started from the command line, stop it from the terminal with `Ctrl+C`.

## Next steps

Once the quick start works, read:

- [Ways to use plotsrv](ways-to-use.md)
- [Run a plotsrv server](run-a-plotsrv-server.md)
- [Use plotsrv interactively](interactive-use.md)
- [Watch files](watch-files.md)
