# ETL pipeline

This job cleans a small orders table, publishes its result, and reports validation
counts. It uses generated data, so there is nothing to download.

## Run it

Install plotsrv in your environment:

```bash
python -m pip install plotsrv
```

Save this as `etl_pipeline.py`:

```python
import pandas as pd
import plotsrv as ps

@ps.view(label="orders", section="daily", port=8000)
def clean_orders():
    """Accepted orders after dropping duplicate IDs."""
    raw = pd.DataFrame({
        "order_id": [1, 2, 2, 3, 4],
        "region": ["North", "South", "South", "North", "West"],
        "revenue": [120.0, 80.0, 80.0, 240.0, 60.0],
    })
    return raw.drop_duplicates("order_id")

@ps.view(label="metrics", section="daily", port=8000)
def validate(orders):
    """Validation counts for accepted orders."""
    return {
        "rows": len(orders),
        "errors": int((orders["revenue"] < 0).sum()),
        "revenue": float(orders["revenue"].sum()),
    }

if __name__ == "__main__":
    orders = clean_orders()
    metrics = validate(orders)
    ps.publish_view("Import complete", label="log", section="daily", port=8000)
    print(metrics)
```

Start plotsrv in one terminal:

```bash
plotsrv run etl_pipeline.py
```

Run the job in another:

```bash
python etl_pipeline.py
```

Open **<http://127.0.0.1:8000>**. Inspect **daily → orders**, filter a region, then
look at **metrics**. Both functions returned normally to the calling code.
The server stays available after the script exits.

## Keep versions and check the result

Save this as `plotsrv.yml` and restart the server with
`plotsrv run etl_pipeline.py --config plotsrv.yml`:

```yaml
storage-settings:
  enabled: true
  default_keep_last: 5

freshness-settings:
  enabled: true
  expected_every: 1d
  warn_after: 25h
  overdue_after: 30h

checks-settings:
  rules:
    - id: invalid-orders
      source: daily:metrics
      kind: state
      path: [errors]
      op: gt
      value: 0
      severity: warning
```

Run the job again. It now has stored history and a check on the supplied error
count. Freshness tracks arrivals; it does not schedule the job.

For notification setup and its limits, see [Keep an eye on a job](../guides/keep-an-eye-on-a-job.md).
For a small summary of a large DataFrame instead of its table, see
[Observe function output](../guides/observe-function-output.md).
