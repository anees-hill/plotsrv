# Publish from Python

Start a server in one terminal:

```bash
plotsrv serve
```

Then run this in your application or a second Python session:

```python
import plotsrv as ps

ps.publish_view({"rows": 123, "errors": 0}, label="orders", port=8000)
```

Open **<http://127.0.0.1:8000>**. The `port` argument sends the object to the existing
server. Omit publishing options for an attached local server, or use
`launch_server=True` explicitly when trying things interactively.

## Give each output a name

```python
ps.publish_view({"rows": 123}, label="orders", section="daily", port=8000)
ps.publish_view("Import complete", label="log", section="daily", port=8000)
```

Labels identify outputs within a section. Publishing again to `daily:orders`
updates that view. Sections group related outputs in the selector.

Use an explicit ID if the label might change:

```python
ps.publish_view(
    {"rows": 123},
    view_id="daily:orders",
    label="Orders imported",
    description="Rows accepted by the daily import, after validation.",
    port=8000,
)
```

Readers can open **About this view** to see the description. It is plain text;
do not include secrets. Decorated functions can supply a description through
their docstring. Exact precedence and opt-outs are in the
[description settings](view-descriptions.md).

## Show a table or plot

```python
import pandas as pd
import matplotlib.pyplot as plt

orders = pd.DataFrame({"region": ["North", "South"], "rows": [123, 87]})
ps.publish_view(orders, label="orders table", port=8000)

fig, ax = plt.subplots()
ax.bar(orders["region"], orders["rows"])
ps.publish_view(fig, label="orders plot", port=8000)
plt.close(fig)
```

DataFrames open as tables. Matplotlib figures become images. The browser can
also make plots directly from table data; see [supported outputs](renderers.md).

## Publish a file

```python
from pathlib import Path

ps.publish_view(Path("report.md"), label="report", port=8000)
```

This reads an existing file once. A plain string is text, not a filename.
To keep following changes, [watch the file](../get-started/watch-files.md).

HTML reports can run scripts under the default rendering settings. Only publish
HTML you trust. Tracebacks are disabled by default because they can expose source
and paths; see the [security settings](configuration-reference.md#security-settings).

## Publish a function’s return value

```python
@ps.view(label="validation", section="daily", port=8000)
def validate_orders():
    return {"errors": 0, "duplicates": 2}

result = validate_orders()
```

The function returns its result as usual. See [Use plotsrv in a project](../get-started/use-in-a-project.md)
for discovery, calling conventions, and keeping the server running.

If you want a small summary of a large result instead, use
[Observe function output](observe-function-output.md).

## Keep publishing out of the way

For frequent updates, opt into background delivery:

```python
ps.publish_view({"progress": 42}, label="progress", port=8000, async_=True)
finished = ps.flush_views(timeout=1.0)
```

The worker keeps the newest pending update for a view. Intermediate updates can
be replaced or dropped; this is not a durable event queue. Do not mutate an object
while ordinary asynchronous publishing is still using it. `flush_views` is a
bounded best-effort wait; check its result when finishing a short script.

For routing to another machine, see [remote publishing](remote-publishers.md).
For exact arguments, error behaviour, and limits, see [Python API](python-api.md).
