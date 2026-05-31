---
icon: lucide/activity
---

# Freshness

Freshness helps show whether a view has updated recently enough.

This is useful when plotsrv is observing a process that should publish on a schedule, such as:

- an hourly import
- a daily report
- a repeated validation job
- a long-running monitor
- a batch process with expected checkpoints

Freshness is not about whether a view exists. It is about whether the view is recent.

## Enable freshness

Freshness is configured in `plotsrv.yaml`.

```yaml title="plotsrv.yaml"
freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h
```

This means:

| Setting | Meaning |
|---|---|
| `expected_every` | how often the view is expected to update |
| `warn_after` | when the view should be considered stale |
| `overdue_after` | when the view should be considered overdue |

## What appears in the UI

When freshness is enabled, plotsrv can show whether a view is:

| State | Meaning |
|---|---|
| Fresh | the view has updated recently |
| Stale | the view has not updated within the warning threshold |
| Overdue | the view has not updated within the overdue threshold |
| Unknown | plotsrv does not yet have enough information |
| Disabled | freshness is not enabled for the view |

This makes plotsrv useful as a lightweight status surface for repeated jobs.

## A simple example

Given a script like this:

```python title="daily_import.py"
import plotsrv as ps

ps.publish_view(
    {
        "job": "daily-import",
        "status": "ok",
        "rows_processed": 123,
    },
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
)
```

Create a config:

```bash
plotsrv config create
```

Enable freshness:

```yaml title="plotsrv.yaml"
freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h
```

Start plotsrv:

```bash
plotsrv run daily_import.py --config plotsrv.yaml
```

Run the script:

```bash
python daily_import.py
```

The view now has freshness information in the UI.

## Populate freshness config

For projects with several views, use the populate command:

```bash
plotsrv config populate freshness .
```

This scans for:

- `@ps.view(...)` decorators
- simple `publish_view(...)` calls

and adds per-view freshness entries where possible.

For example:

```python title="pipeline_views.py"
import plotsrv as ps

@ps.view(label="daily import", section="pipelines")
def daily_import_status():
    return {"status": "ok"}

@ps.view(label="validation summary", section="pipelines")
def validation_summary():
    return {"warnings": 2}
```

Run:

```bash
plotsrv config populate freshness pipeline_views.py
```

plotsrv can discover the views and create config entries for them.

## Merge generated entries

To merge generated freshness entries into an existing config:

```bash
plotsrv config populate freshness . --mode merge
```

To replace generated freshness entries:

```bash
plotsrv config populate freshness . --mode replace
```

To skip prompts:

```bash
plotsrv config populate freshness . --yes
```

A common pattern is:

```bash
plotsrv config create
plotsrv config populate freshness . --yes
```

Then edit the generated timings.

## Per-view freshness

Different views may update on different schedules.

For example:

| View | Expected update pattern |
|---|---|
| `pipelines:daily import` | every hour |
| `pipelines:nightly report` | once per night |
| `models:latest metrics` | after each training run |
| `logs:etl log` | frequently while the job is running |

Per-view freshness settings allow these expectations to differ.

For example, an hourly view might use:

```yaml
expected_every: 1h
warn_after: 90m
overdue_after: 2h
```

A nightly view might use:

```yaml
expected_every: 24h
warn_after: 26h
overdue_after: 30h
```

## Freshness with restored views

When storage is enabled, plotsrv can restore the latest live view after restart.

Freshness still uses the original update time.

That means a restored view from yesterday does not look fresh just because the server restarted today.

This is important for scheduled jobs, because restart recovery should not hide stale data.

## Next steps

- [Storage and history](storage-and-history.md)
- [CLI reference](cli.md)
- [Configuration basics](../get-started/configuration-basics.md)
