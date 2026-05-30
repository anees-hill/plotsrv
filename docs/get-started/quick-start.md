---
icon: lucide/rocket
---

# Quick start

This page shows the quickest way to see what plotsrv does. It starts with a small interactive example, then moves to the server workflow used for scripts, jobs, and repeatable processes.

## Interactive check

> This first example is designed for a REPL, notebook, or interactive Python session.
>
> For scripts and repeatable jobs, use the server workflow in the next section.

Start Python:

```bash
python
```

Then run:

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
    section="quick start",
    launch_server=True,
)
```

Open:

```text
http://127.0.0.1:8000
```

The object appears as structured JSON.

`launch_server=True` starts an attached plotsrv server inside the current Python process.

## Server workflow

For scripts, jobs, pipelines, and repeatable processes, start plotsrv separately and publish to it from Python.

This keeps the browser UI running independently of the script that produces the output.

The pattern is:

```text
start plotsrv -> run Python script -> inspect output in browser
```

## Create a plotting script

Install dependencies if needed:

```bash
pip install matplotlib pandas
```

or:

```bash
uv add matplotlib pandas
```

> `polars` will also work here. Alternative plotting libraries such as `plotnine` and `seaborn` can also be used.

Create `quickstart_plot.py`:

```python title="quickstart_plot.py"
import matplotlib.pyplot as plt
import pandas as pd
import plotsrv as ps


HOST = "127.0.0.1"
PORT = 8000


df = pd.DataFrame({
    "hours_studied": [1, 2, 3, 4, 5, 6, 7],
    "score": [48, 52, 61, 66, 72, 78, 85],
})


@ps.view(label="scatter plot", section="demo", host=HOST, port=PORT)
def study_scatter_plot():
    fig, ax = plt.subplots()
    ax.scatter(df["hours_studied"], df["score"])
    ax.set_title("Study time and score")
    ax.set_xlabel("Hours studied")
    ax.set_ylabel("Score")
    return fig


if __name__ == "__main__":
    study_scatter_plot()
```

## Start plotsrv

In one terminal, run:

```bash
plotsrv run quickstart_plot.py --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

At this point, plotsrv is running and ready to receive output.

It will also have discovered known views from the script before data has been published.

## Run the script

In another terminal, run:

```bash
python quickstart_plot.py
```

The scatter plot appears in the browser UI.

Running the script again updates the same view.

## Labels and sections

This part of the script controls where the output appears in the UI:

```python
@ps.view(label="scatter plot", section="demo", host=HOST, port=PORT)
def study_scatter_plot():
    ...
```

`label` names the individual view.

`section` groups related views together.

For example:

| Section | Label |
|---|---|
| `demo` | `scatter plot` |
| `demo` | `source data` |
| `demo` | `summary` |
| `pipelines` | `daily import` |
| `models` | `latest metrics` |

When the decorated function is called, it returns the same object as usual and also publishes that object to the plotsrv server.

## Publish more views

Now extend `quickstart_plot.py` so the same script publishes a plot, a table, and a summary.

```python title="quickstart_plot.py"
import matplotlib.pyplot as plt
import pandas as pd
import plotsrv as ps


HOST = "127.0.0.1"
PORT = 8000


df = pd.DataFrame({
    "hours_studied": [1, 2, 3, 4, 5, 6, 7],
    "score": [48, 52, 61, 66, 72, 78, 85],
})


@ps.view(label="scatter plot", section="demo", host=HOST, port=PORT)
def study_scatter_plot():
    fig, ax = plt.subplots()
    ax.scatter(df["hours_studied"], df["score"])
    ax.set_title("Study time and score")
    ax.set_xlabel("Hours studied")
    ax.set_ylabel("Score")
    return fig


@ps.view(label="source data", section="demo", host=HOST, port=PORT)
def source_data():
    return df


@ps.view(label="summary", section="demo", host=HOST, port=PORT)
def summary():
    return {
        "rows": len(df),
        "average_score": round(df["score"].mean(), 1),
        "max_score": int(df["score"].max()),
    }


if __name__ == "__main__":
    study_scatter_plot()
    source_data()
    summary()
```

Run it again:

```bash
python quickstart_plot.py
```

The `demo` section now contains:

- a scatter plot
- an inspectable table
- a JSON summary

This is the core plotsrv pattern: useful Python outputs are surfaced together in a live browser UI.

## Add storage and freshness

Create a config file:

```bash
plotsrv config create
```

Edit `plotsrv.yaml` and enable storage and freshness:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  root_dir: .plotsrv/store
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20

freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h
```

Restart plotsrv with the config:


```bash
plotsrv run quickstart_plot.py --config plotsrv.yaml --host 127.0.0.1 --port 8000
```

> Note: If `plotsrv.yaml` exists in project root, it will be used by default. The --config flag allows the use of alternative config files (or allows us to be explicit, as we have done here).

Then run the script again:

```bash
python quickstart_plot.py
```

Storage allows plotsrv to keep recent history and restore the latest view after restart.

Freshness helps show whether a view has updated recently enough.

## What to try next

Run the script a few times and inspect the UI.

Try changing the data:

```python
"score": [48, 55, 63, 70, 76, 82, 90]
```

Then run:

```bash
python quickstart_plot.py
```

The same views update in the browser.

With storage enabled, recent versions can be inspected through the UI history controls.

## Next step

Continue to [Watch files](watch-files.md).
