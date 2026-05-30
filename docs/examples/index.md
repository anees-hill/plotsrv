---
icon: lucide/flask-conical
---

# Examples

These examples show small, copy-pasteable ways to use plotsrv.

The examples are intentionally simple. They are designed to show the pattern rather than build a full application.

## Example types

| Example | Shows |
|---|---|
| [ETL pipeline](etl-pipeline.md) | publishing status, tables, logs, and validation summaries |
| [EDA on a server](eda-on-a-server.md) | inspecting data and plots from a headless or SSH workflow |

## Two patterns

Most examples use one of two patterns.

### Attached server

For quick local use:

```python
ps.publish_view(
    obj,
    label="result",
    launch_server=True,
)
```

This starts plotsrv inside the current Python process.

### Server workflow

For scripts and jobs:

```bash
plotsrv run script.py --host 127.0.0.1 --port 8000
```

Then publish from Python:

```python
ps.publish_view(
    obj,
    label="result",
    host="127.0.0.1",
    port=8000,
)
```

This keeps the plotsrv UI separate from the script producing the output.

## What next?

Start with:

- [ETL pipeline](etl-pipeline.md)

It shows the main plotsrv pattern:

```text
script produces output -> plotsrv renders output -> browser UI shows current state
```
