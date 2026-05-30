---
icon: lucide/rocket
---

# EDA on a server

This example shows how to inspect data and plots when working on a server or terminal-based environment.

The example publishes:

- a DataFrame
- a summary object
- a matplotlib plot

## Install dependencies

```bash
pip install plotsrv polars matplotlib
```

or:

```bash
uv add plotsrv polars matplotlib
```

## Create the script

Create `eda_example.py`:

```python title="eda_example.py"
import matplotlib.pyplot as plt
import polars as pl
import plotsrv as ps


HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    df = pl.DataFrame(
        {
            "month": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
            "bookings": [120, 150, 170, 160, 210, 240],
            "returns": [115, 148, 165, 155, 205, 235],
        }
    )

    summary = {
        "rows": df.height,
        "total_bookings": df["bookings"].sum(),
        "total_returns": df["returns"].sum(),
        "max_bookings": df["bookings"].max(),
        "max_returns": df["returns"].max(),
    }

    fig, ax = plt.subplots()
    ax.plot(df["month"], df["bookings"], marker="o", label="bookings")
    ax.plot(df["month"], df["returns"], marker="o", label="returns")
    ax.set_title("Bookings and returns")
    ax.set_xlabel("Month")
    ax.set_ylabel("Count")
    ax.legend()

    ps.publish_view(
        df,
        label="monthly data",
        section="eda",
        host=HOST,
        port=PORT,
    )

    ps.publish_view(
        summary,
        label="summary",
        section="eda",
        host=HOST,
        port=PORT,
    )

    ps.publish_view(
        fig,
        label="plot",
        section="eda",
        host=HOST,
        port=PORT,
    )


if __name__ == "__main__":
    main()
```

## Start plotsrv

In one terminal:

```bash
plotsrv run eda_example.py --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Run the script

In another terminal:

```bash
python eda_example.py
```

The UI should show:

- the source data as a table
- summary values as JSON
- the matplotlib plot as an image view

## SSH workflow

For remote server work, use port forwarding from the local machine:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

Then run plotsrv on the server:

```bash
plotsrv run eda_example.py --host 127.0.0.1 --port 8000
```

Open locally:

```text
http://127.0.0.1:8000
```

This avoids exposing plotsrv directly to the network.

## Attached version

For a quick local check, use `launch_server=True` instead of `host` and `port`:

```python
ps.publish_view(
    df,
    label="monthly data",
    section="eda",
    launch_server=True,
)
```

Keep the process open at the end of the script:

```python
input("Open http://127.0.0.1:8000, then press Enter to stop...")
```

## What this example shows

plotsrv is useful when a script produces objects that are better inspected visually than printed:

- tables are easier to scan in a browser
- JSON summaries are easier to expand and inspect
- plots can be viewed on a headless server
- repeated script runs update the same UI
