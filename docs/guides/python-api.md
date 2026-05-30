---
icon: lucide/code
---

# Python API

This page covers the main Python functions exposed by `plotsrv`.

The core plotsrv functions are:

- `publish_view()`
- `@view`

These two functions enable content to be pushed to the plotsrv server (and launch the server itself, if desired).

The remaining functions are useful for controlling the server, managing sessions, publishing tracebacks, or working with advanced metadata.

## Import convention

Most examples use:

```python
import plotsrv as ps
```

Then call functions as:

```python
ps.publish_view(...)
```

or:

```python
@ps.view(...)
def my_function():
    ...
```

## Core publishing API

## `publish_view()`

Publish an object as a plotsrv browser view.

```python
ps.publish_view(
    obj,
    label="summary",
    section="demo",
    launch_server=True,
)
```

`publish_view()` accepts common Python outputs, including:

- pandas and Polars DataFrames
- matplotlib and plotnine plots
- dictionaries, lists, tuples, and sets
- strings and bytes
- markdown and HTML
- image payloads
- path-like files
- generic Python objects

plotsrv chooses an appropriate renderer where possible.

## Attached server

For quick interactive use, pass `launch_server=True`:

```python
import plotsrv as ps

summary = {
    "status": "ok",
    "rows_processed": 123,
}

ps.publish_view(
    summary,
    label="summary",
    section="demo",
    launch_server=True,
)
```

This starts an attached plotsrv server inside the current Python process if one is not already running.

Open:

```text
http://127.0.0.1:8000
```

## Existing server

For scripts, jobs, and repeatable processes, start plotsrv separately:

```bash
plotsrv run script.py --host 127.0.0.1 --port 8000
```

Then publish to that server:

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="status",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
)
```

With `host` and `port`, `publish_view()` sends the object to an existing plotsrv server.

It does not start a server.

## Common parameters

| Parameter | Meaning |
|---|---|
| `obj` | object to publish |
| `label` | name of the view in the UI |
| `section` | group for related views |
| `view_id` | explicit stable view identifier |
| `launch_server` | start/use an attached in-process server |
| `host` | server host for HTTP publishing |
| `port` | server port for HTTP publishing |
| `kind` | force broad view kind: `plot`, `table`, or `artifact` |
| `artifact_kind` | force artifact renderer, such as `markdown`, `html`, `json`, or `text` |
| `update_limit_s` | limit how often a view should update |
| `force` | force an update even when an update limit applies |

## Forcing a renderer

Most of the time, automatic renderer selection is enough.

For markdown:

```python
ps.publish_view(
    "# Report\n\nEverything completed successfully.",
    label="report",
    section="demo",
    artifact_kind="markdown",
    launch_server=True,
)
```

For HTML:

```python
ps.publish_view(
    "<h1>Report</h1><p>Status: <strong>ok</strong></p>",
    label="html report",
    section="demo",
    artifact_kind="html",
    launch_server=True,
)
```

For a table:

```python
ps.publish_view(
    df,
    label="source data",
    section="demo",
    kind="table",
    host="127.0.0.1",
    port=8000,
)
```

## Publishing files

Use a `Path` object to publish a file.

```python
from pathlib import Path
import plotsrv as ps

ps.publish_view(
    Path("results.csv"),
    label="results",
    section="files",
    launch_server=True,
)
```

A path-like object tells plotsrv to read the file and infer a renderer from the file type.

A plain string is treated as text:

```python
ps.publish_view(
    "results.csv",
    label="literal text",
    section="files",
    launch_server=True,
)
```

## `@view`

`@ps.view(...)` marks a function or class as a plotsrv view producer.

It is useful when code already has a function that returns something worth inspecting.

```python
import plotsrv as ps

@ps.view(
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
)
def daily_import_status():
    return {
        "status": "ok",
        "rows_processed": 123,
    }

daily_import_status()
```

When the function is called:

- the function runs normally
- the return value is published to plotsrv
- the same return value is returned to Python

## Metadata-only usage

With only `label` and `section`, `@view` acts as metadata for discovery.

```python
import plotsrv as ps

@ps.view(label="daily import", section="pipelines")
def daily_import_status():
    return {"status": "ok"}
```

This lets plotsrv discover the view when running:

```bash
plotsrv run script.py
```

In metadata-only mode, calling the function does not actively publish.

## Publish to an existing server

To publish when the function is called, provide `host` and `port`:

```python
@ps.view(
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
)
def daily_import_status():
    return {"status": "ok"}
```

Then:

```python
daily_import_status()
```

publishes the return value to the running plotsrv server.

## Attached server with `@view`

For quick interactive use:

```python
@ps.view(
    label="summary",
    section="demo",
    launch_server=True,
)
def summary():
    return {"status": "ok"}

summary()
```

This starts or uses an attached plotsrv server inside the current Python process.

## `@view` error behaviour

`@view` can publish tracebacks when a decorated function fails.

```python
@ps.view(
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
    on_error="publish_and_raise",
)
def daily_import_status():
    raise RuntimeError("Import failed")
```

Common values:

| `on_error` | Behaviour |
|---|---|
| `raise` | raise the exception normally |
| `publish` | publish the traceback and suppress the exception |
| `publish_and_raise` | publish the traceback, then raise the exception |

Traceback rendering must be enabled in config:

```yaml title="plotsrv.yaml"
security-settings:
  tracebacks_enabled: true
```

## `@view` parameters

| Parameter | Meaning |
|---|---|
| `label` | name of the view in the UI |
| `section` | group for related views |
| `host` | server host for HTTP publishing |
| `port` | server port for HTTP publishing |
| `launch_server` | start/use an attached in-process server |
| `update_limit_s` | limit how often the view should update |
| `on_error` | error handling behaviour |

## Choosing `publish_view()` or `@view`

Use `publish_view()` when the object already exists:

```python
result = {"status": "ok"}

ps.publish_view(
    result,
    label="result",
    section="demo",
    host="127.0.0.1",
    port=8000,
)
```

Use `@view` when a function already returns something useful:

```python
@ps.view(
    label="result",
    section="demo",
    host="127.0.0.1",
    port=8000,
)
def build_result():
    return {"status": "ok"}
```

Both approaches publish to the same UI.

## Server and session API

## `start_server()`

Start a plotsrv server from Python.

```python
import plotsrv as ps

ps.start_server(
    host="127.0.0.1",
    port=8000,
    announce=True,
)
```

Open:

```text
http://127.0.0.1:8000
```

This is the Python equivalent of starting the server from the CLI.

## Common `start_server()` options

```python
ps.start_server(
    host="127.0.0.1",
    port=8000,
    config="plotsrv.yaml",
    name="local",
    announce=True,
)
```

| Parameter | Meaning |
|---|---|
| `host` | host to bind |
| `port` | port to bind |
| `config` | path to `plotsrv.yaml` |
| `name` | runtime instance name |
| `auto_on_show` | patch `plt.show()` so it updates plotsrv |
| `quiet` | reduce server logging |
| `truncate` | runtime truncation override |
| `no_truncate` | disable text/html/markdown truncation |
| `watches` | files to watch from Python |
| `restore_latest` | restore latest persisted views on startup |
| `announce` | print the server URL when started |

## Start with config

```python
ps.start_server(
    config="plotsrv.yaml",
    announce=True,
)
```

## Start with watched files

```python
from plotsrv import WatchConfig
import plotsrv as ps

ps.start_server(
    watches=[
        WatchConfig(
            path="logs/job.log",
            label="job log",
            section="files",
            tail=True,
        )
    ],
    announce=True,
)
```

## `stop_server()`

Stop an attached plotsrv server started from Python.

```python
ps.stop_server()
```

To wait for the server thread to exit:

```python
ps.stop_server(join=True)
```

## `plot_session()`

Use `plot_session()` as a context manager.

```python
import plotsrv as ps

with ps.plot_session(announce=True):
    ps.publish_view(
        {"status": "ok"},
        label="summary",
        section="demo",
    )
```

The server starts on entry and is stopped on exit.

This is useful for tests, demos, and short-lived scripts where the server lifetime should be scoped.

## Exception helpers

## `capture_exceptions()`

Publish exceptions raised inside a block.

```python
import plotsrv as ps

with ps.capture_exceptions(
    label="job error",
    section="errors",
    host="127.0.0.1",
    port=8000,
):
    raise RuntimeError("Example failure")
```

Traceback rendering must be enabled in config:

```yaml title="plotsrv.yaml"
security-settings:
  tracebacks_enabled: true
```

## Attached traceback example

```python
with ps.capture_exceptions(
    label="job error",
    section="errors",
    launch_server=True,
):
    raise RuntimeError("Example failure")
```

## `publish_traceback()`

Catch an exception and publish it manually.

```python
import plotsrv as ps

try:
    raise ValueError("Validation failed")
except Exception as exc:
    ps.publish_traceback(
        exc,
        label="validation error",
        section="errors",
        host="127.0.0.1",
        port=8000,
    )
    raise
```

This is useful when exception handling also needs to publish a status object, clean up resources, or continue custom error handling.

## Advanced API

The following functions and classes are part of the public surface but are less commonly needed.

## `refresh_view()`

`refresh_view()` is a lower-level in-process helper.

It updates the in-process plotsrv store directly and is mainly retained for compatibility and specialised usage.

For most new code, prefer:

```python
ps.publish_view(...)
```

or:

```python
@ps.view(...)
def my_view():
    ...
```

## `get_plotsrv_spec()`

Return the plotsrv metadata attached to a decorated function.

```python
spec = ps.get_plotsrv_spec(daily_import_status)
```

This is mainly useful for introspection, testing, and tooling.

## `PlotsrvSpec`

Metadata object attached by `@ps.view(...)`.

It contains information such as:

- label
- section
- host
- port
- update limit
- error behaviour
- attached-server behaviour

Most users do not need to construct this directly.

## `WatchConfig`

Configuration object for Python-defined file watches.

```python
from plotsrv import WatchConfig
```

It is useful when starting plotsrv from Python with watched files:

```python
ps.start_server(
    watches=[
        WatchConfig(
            path="logs/job.log",
            label="job log",
            section="files",
            tail=True,
        )
    ]
)
```

## `set_table_view_mode()`

Set the table rendering mode at runtime.

```python
ps.set_table_view_mode("rich")
```

This is a specialised runtime configuration helper. Most projects should prefer configuring table behaviour in `plotsrv.yaml`.

## Legacy compatibility

Some older examples may use `mode="local"`, `mode="remote"`, or `mode="auto"` with `publish_view()`.

New code should prefer the clearer forms:

```python
ps.publish_view(obj, launch_server=True)
```

for attached-server use, and:

```python
ps.publish_view(obj, host="127.0.0.1", port=8000)
```

for publishing to an existing server.

## Recommended starting points

For quick interactive use:

```python
ps.publish_view(obj, label="result", launch_server=True)
```

For scripts and jobs:

```python
ps.publish_view(
    obj,
    label="result",
    section="demo",
    host="127.0.0.1",
    port=8000,
)
```

For functions that already return useful objects:

```python
@ps.view(
    label="result",
    section="demo",
    host="127.0.0.1",
    port=8000,
)
def build_result():
    return {"status": "ok"}
```

## Next steps

- [CLI reference](cli.md)
- [Renderers](renderers.md)
- [Tracebacks](tracebacks.md)
