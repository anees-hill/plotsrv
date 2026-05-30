---
icon: lucide/bug
---

# Tracebacks

plotsrv can publish Python tracebacks into the browser UI.

This is useful for internal development, batch jobs, ETL scripts, demos, and process observability where failures should be visible alongside other outputs.

Traceback rendering is disabled by default because tracebacks can expose file paths, source code, environment details, and implementation context.

## Enable traceback rendering

Enable tracebacks in `plotsrv.yaml`:

```yaml title="plotsrv.yaml"
security-settings:
  tracebacks_enabled: true
```

Then start plotsrv with that config:

```bash
plotsrv run --config plotsrv.yaml
```

!!! warning

    Tracebacks may contain sensitive information.

    Enable traceback rendering only where that information is acceptable to show in the plotsrv UI.

## Capture exceptions

Use `capture_exceptions()` around code that may fail.

```python title="traceback_example.py"
import plotsrv as ps

with ps.capture_exceptions(
    label="job error",
    section="errors",
    host="127.0.0.1",
    port=8000,
):
    raise RuntimeError("Example failure")
```

Start plotsrv:

```bash
plotsrv run traceback_example.py --config plotsrv.yaml
```

Run the script:

```bash
python traceback_example.py
```

The traceback appears in the browser UI.

## Use with the attached server

For quick local use, use `launch_server=True`:

```python title="attached_traceback.py"
import plotsrv as ps

with ps.capture_exceptions(
    label="job error",
    section="errors",
    launch_server=True,
):
    raise RuntimeError("Example failure")

input("Open http://127.0.0.1:8000, then press Enter to stop...")
```

This starts an attached plotsrv server inside the current Python process if one is not already running.

## Publish an exception manually

For more control, catch the exception and publish it manually.

```python title="manual_traceback.py"
import plotsrv as ps

try:
    raise ValueError("Example validation failure")
except Exception as exc:
    ps.publish_traceback(
        exc,
        label="validation error",
        section="errors",
        host="127.0.0.1",
        port=8000,
    )
```

This is useful when exception handling needs to do other work as well, such as logging, cleanup, or setting a process status.

## Use with `@view`

The `@ps.view(...)` decorator can publish tracebacks when a decorated function fails.

```python title="view_traceback.py"
import plotsrv as ps

@ps.view(
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
    on_error="publish_and_raise",
)
def daily_import():
    raise RuntimeError("Import failed")

daily_import()
```

The `on_error` argument controls what happens when the function raises.

| Value | Behaviour |
|---|---|
| `raise` | raise the exception normally |
| `publish` | publish the traceback and suppress the exception |
| `publish_and_raise` | publish the traceback, then raise the exception |

`publish_and_raise` is often the safest choice for scripts and jobs, because the failure remains visible to Python while also appearing in plotsrv.

## Attached `@view` traceback example

For an attached server:

```python title="attached_view_traceback.py"
import plotsrv as ps

@ps.view(
    label="demo failure",
    section="errors",
    launch_server=True,
    on_error="publish_and_raise",
)
def demo_failure():
    raise RuntimeError("Something went wrong")

demo_failure()

input("Open http://127.0.0.1:8000, then press Enter to stop...")
```

## What appears in the UI

The traceback renderer shows structured error information, including:

- exception type
- exception message
- stack frames
- file names
- line numbers
- source-code context where available

This makes failures easier to inspect than plain terminal output, especially when plotsrv is already showing related tables, logs, and status objects.

## Tracebacks and production scripts

For production-like jobs, traceback publishing should normally be treated as an internal observability feature.

A useful pattern is:

1. keep normal logging in place
2. publish status objects for expected states
3. publish tracebacks for unexpected failures
4. keep traceback rendering behind trusted network boundaries

Example:

```python title="job_with_error_reporting.py"
import plotsrv as ps

HOST = "127.0.0.1"
PORT = 8000

try:
    # Replace this with the real job.
    raise RuntimeError("Load step failed")
except Exception as exc:
    ps.publish_view(
        {"status": "failed", "step": "load"},
        label="job status",
        section="pipelines",
        host=HOST,
        port=PORT,
    )

    ps.publish_traceback(
        exc,
        label="job traceback",
        section="pipelines",
        host=HOST,
        port=PORT,
    )

    raise
```

The status view gives a simple summary. The traceback view gives the debugging detail.

## Keep tracebacks disabled by default

A conservative config is:

```yaml title="plotsrv.yaml"
security-settings:
  tracebacks_enabled: false
```

Enable tracebacks only for trusted environments:

```yaml title="plotsrv.yaml"
security-settings:
  tracebacks_enabled: true
```

## Next steps

- [Freshness](freshness.md)
- [Storage and history](storage-and-history.md)
- [CLI reference](cli.md)
