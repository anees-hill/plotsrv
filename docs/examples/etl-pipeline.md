---
icon: lucide/workflow
---

# ETL pipeline example

This example shows a small business ETL-style script that publishes:

- a status summary
- a transformed orders table
- a validation summary
- a log

The example uses generated data, so no external files are needed.

## Install dependencies

```bash
pip install plotsrv polars
```

or:

```bash
uv add plotsrv polars
```

## Create the script

Create `etl_example.py`:

```python title="etl_example.py"
import datetime as dt

import polars as pl
import plotsrv as ps


HOST = "127.0.0.1"
PORT = 8000
SECTION = "business etl"


def extract_orders() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "order_id": [10001, 10002, 10003, 10004, 10005, 10006],
            "customer": [
                "Northwind Ltd",
                "Blue Ocean Co",
                "Northwind Ltd",
                "Riverbank PLC",
                "Summit Retail",
                "Blue Ocean Co",
            ],
            "region": ["North", "South", "North", "East", "West", "South"],
            "order_value": [1250.00, 840.50, 430.00, 2200.00, 0.00, 1560.75],
            "items": [5, 3, 2, 8, 0, 6],
            "shipped": [True, True, False, True, False, True],
        }
    )


def transform_orders(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        [
            pl.when(pl.col("order_value") >= 1000)
            .then(pl.lit("high value"))
            .when(pl.col("order_value") > 0)
            .then(pl.lit("standard"))
            .otherwise(pl.lit("review"))
            .alias("order_band"),
            pl.when(pl.col("shipped"))
            .then(pl.lit("complete"))
            .otherwise(pl.lit("open"))
            .alias("fulfilment_status"),
        ]
    )


@ps.view(
    label="status",
    section=SECTION,
    host=HOST,
    port=PORT,
)
def pipeline_status(df: pl.DataFrame) -> dict:
    return {
        "job": "business-etl-example",
        "status": "complete",
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        "rows_processed": df.height,
        "total_order_value": round(df["order_value"].sum(), 2),
    }


@ps.view(
    label="transformed orders",
    section=SECTION,
    host=HOST,
    port=PORT,
)
def transformed_orders_table(df: pl.DataFrame) -> pl.DataFrame:
    return df


@ps.view(
    label="validation checks",
    section=SECTION,
    host=HOST,
    port=PORT,
)
def validation_checks(df: pl.DataFrame) -> dict:
    return {
        "rows": df.height,
        "missing_order_ids": df["order_id"].null_count(),
        "zero_value_orders": df.filter(pl.col("order_value") <= 0).height,
        "unshipped_orders": df.filter(~pl.col("shipped")).height,
        "high_value_orders": df.filter(pl.col("order_band") == "high value").height,
    }


@ps.view(
    label="log",
    section=SECTION,
    host=HOST,
    port=PORT,
)
def pipeline_log() -> str:
    return """INFO extract complete
INFO transform complete
INFO validation complete
INFO publish complete
"""


def main() -> None:
    raw_orders = extract_orders()
    transformed_orders = transform_orders(raw_orders)

    pipeline_status(transformed_orders)
    transformed_orders_table(transformed_orders)
    validation_checks(transformed_orders)
    pipeline_log()


if __name__ == "__main__":
    main()
```

## Start plotsrv

In one terminal:

```bash
plotsrv run etl_example.py --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

plotsrv scans the script for `@ps.view(...)` decorators and pre-populates the UI where possible.

## Run the ETL script

In another terminal:

```bash
python etl_example.py
```

The UI should show four views under the `business etl` section:

- `status`
- `transformed orders`
- `validation checks`
- `log`

Run the script again to update the views.

## How the decorated views work

Each decorated function still behaves like an ordinary Python function.

For example:

```python
@ps.view(
    label="validation checks",
    section=SECTION,
    host=HOST,
    port=PORT,
)
def validation_checks(df: pl.DataFrame) -> dict:
    return {
        "rows": df.height,
        "zero_value_orders": df.filter(pl.col("order_value") <= 0).height,
    }
```

When `validation_checks()` is called:

- the function runs normally
- the return value is published to plotsrv
- the same value is returned to Python

The `label` names the individual view.

The `section` groups related views together in the UI.

## Add storage

To keep recent history and restore the latest view after restart, create a config file:

```bash
plotsrv config create
```

Edit `plotsrv.yaml`:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  root_dir: .plotsrv/store
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20
```

Start plotsrv with the config:

```bash
plotsrv run etl_example.py --config plotsrv.yaml --host 127.0.0.1 --port 8000
```

Run the script again:

```bash
python etl_example.py
```

With storage enabled, recent versions can be inspected through the UI history controls.

## Add freshness

For a repeated ETL process, freshness can show whether the view is updating on time.

```yaml title="plotsrv.yaml"
freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h
```

Per-view freshness entries can be generated with:

```bash
plotsrv config populate freshness etl_example.py --yes
```

## Attached version

For a quick self-contained demo, replace `host` and `port` in the decorators with `launch_server=True`:

```python
@ps.view(
    label="status",
    section=SECTION,
    launch_server=True,
)
def pipeline_status(df: pl.DataFrame) -> dict:
    return {
        "status": "complete",
        "rows_processed": df.height,
    }
```

For scripts and repeatable jobs, the server workflow shown above is usually a better fit.

## What this example shows

This example keeps the ETL code ordinary.

The script still:

- extracts data
- transforms data
- validates data
- finishes normally

plotsrv adds a browser UI onto the useful objects already produced by the script.

The result is a lightweight observability surface for a business data process, without building a dashboard or manually opening output files.
