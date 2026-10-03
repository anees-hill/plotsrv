---
icon: lucide/code
---

# Python API

Import the public API as `import plotsrv as ps`. For working examples, start with
[Publish from Python](../guides/publish-from-python.md). This page covers arguments,
routing, background delivery, server controls, and error handling.

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
@ps.view(label="result")
def my_function():
    ...
```

## Core publishing API

## `publish_view()`

Publish an object as a plotsrv browser view. An explicit
`destination="https://dashboard.example/team/"` preserves a proxy prefix and
targets an existing server. See [destination precedence and configuration](remote-publishing-and-security.md#configuration-and-precedence).

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

Use `description="Short purpose and scope"` to attach bounded plain-text source
metadata. Decorated functions can use their first docstring paragraph instead;
see [View descriptions](configuration.md#view-descriptions) for config precedence and privacy opt-outs.

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

## Bounded asynchronous live publishing

For a repeated status, table, or plot where the pipeline should not wait for
rendering, serialisation, or HTTP delivery, opt into asynchronous live
publishing:

```python
ps.publish_view(
    latest_status,
    label="status",
    section="pipeline",
    host="127.0.0.1",
    port=8000,
    async_=True,
)
```

`async_=True` is deliberately for **live views**, whose meaning is “show the
newest useful state”. Pending updates are bounded and latest-wins per
destination/view: an older pending update may be coalesced or rejected under
pressure. The function returning therefore means “accepted for best-effort
queue admission was attempted”, not “already visible in the browser”. Use the
queue counters below to distinguish accepted, coalesced, rejected, and failed
delivery work.

The default remains synchronous. To make the bounded worker the default for a
process, use the optional configuration below; `async_=False` always keeps one
call synchronous.

For `@view`, the config default changes delivery mode only when the decorator
is already active through `host`, `port`, `launch_server`, or a configured remote
destination. Explicit `async_=True` also activates ordinary publishing. A config
default for asynchronous delivery alone does not activate a metadata-only decorator.

At the end of a short script or batch job, give accepted updates a bounded
opportunity to finish:

```python
ps.flush_views(timeout=1.0)
```

`flush_views()` returns `True` when the queue drained and `False` on timeout.
`stop_server()` performs the same short flush before stopping its workers.

The decorator accepts the same explicit option:

```python
@ps.view(
    label="status",
    section="pipeline",
    host="127.0.0.1",
    port=8000,
    async_=True,
)
def status() -> dict[str, object]:
    return {"state": "running"}
```

Queue counters and the last delivery error are available from the server's
`/status` response under `publish_queue`. They make coalescing, rejection, and
remote delivery failures visible without storing large response payloads.

## Rejected publishes

When a normal Python publish exceeds a hard limit, plotsrv creates a visible
`publish_error` artifact in the target view. Attached DataFrame publishes check
the table row and column limits before retaining the frame or converting Polars
to pandas. Remote publishes also pass through the HTTP limits.

The browser message names the failed limit and its config key. Direct
`refresh_view()` calls raise the rejection; `publish_view()` follows its normal
error handling and raises only when `PLOTSRV_DEBUG=1`.

Hard publish limits are configured under:

```yaml title="plotsrv.yaml"
limits:
  published_objects:
    max_plot_bytes: 5242880
    max_table_rows: 100000
    max_table_columns: 200
    max_artifact_text_chars: 6000000
    max_json_container_items: 100000
```

Display/preparation truncation is separate:

```yaml title="plotsrv.yaml"
limits:
  truncate_after:
    text: 1000000
    markdown: 1000000
    html: off
    table_rows: 100000
    table_columns: 200
```

Generated plotsrv error artifacts use internal text-like artifact kinds such as `publish_error` and `watch_error`. They are not truncated by normal text truncation settings, so the useful error message remains visible.

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
| `artifact_kind` | force artifact renderer, such as `markdown`, `html`, `json`, or `text`; `watch_error` and `publish_error` are internal error artifact kinds |
| `update_limit_s` | limit how often a view should update |
| `force` | force an update even when an update limit applies |
| `destination` | remote HTTP(S) URL or `PublishTarget`; conflicts with explicit host/port or local launch |
| `async_` | `None` follows config; `True` uses bounded background delivery; `False` is synchronous |
| `observe` | `False` by default; `True` or `ObservationOptions` captures a bounded summary in the background |
| `description` | bounded plain-text explanation of the source |
| `mode` | legacy `auto`, `local`, or `remote` routing; prefer explicit launch or destination options |

Only `obj` is positional. `publish_view` returns `None`, including when an update
is skipped or fails under normal best-effort error handling.

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

Enable traceback publishing in the producer's config and traceback rendering in
the server's config (they can use the same file):

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
| `view_id` | stable identity independent of the label |
| `async_` | explicit `True` activates ordinary publishing in the background; `None` follows config once active |
| `observe` | `True` or `ObservationOptions` observes a function's return value; always background delivery |

All decorator arguments are keyword-only. `view` has no `destination` argument;
use publisher config or `host`/`port` for a remote server.

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
| `quiet` | suppress startup messages while retaining HTTP 4xx/5xx logs (default: `True`) |
| `verbose` | log every HTTP request with Uvicorn's access log, including successful requests and query strings; overrides `quiet` for logging |
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
            read_mode="tail",
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

In a REPL, start the server with that config. The helper itself does not start
one. This example suppresses the demonstration exception so the session stays
available; the default is `reraise=True`.

```python
import plotsrv as ps

ps.start_server(config="plotsrv.yaml")
with ps.capture_exceptions(view_id="job error", reraise=False):
    raise RuntimeError("Example failure")
```

Open **job error**. Without host/port or a configured destination, the traceback
helpers write to the selected `view_id` in the current process, or to the active
view if the ID is omitted. In that path, `label` and `section` do not create a
named catalogue entry; use an explicit `view_id` to select the output.

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
@ps.view(label="result")
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
            read_mode="tail",
        )
    ]
)
```

Watched-file publishes are source-aware. Global freshness does not mark watched-file views stale by default, and storage snapshots for watched files are disabled unless `storage-settings.watch_enabled` or a per-view `watch_enabled` override opts them in.

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

## Streams

```python
ps.stream_view(
    source="events.jsonl",
    format="jsonl",  # jsonl, text, uvicorn, or auto
    label=None, section=None, view_id=None,
    host=None, port=None, destination=None,
    client_id=None, session_id=None,
)
```

`source` is required and keyword-only. `stream_view` requires an existing receiver;
it does not implicitly launch a local server. It returns a `StreamHandle` and
starts a local daemon follower. Existing files begin at registration EOF; a missing
file starts at byte zero once created. `destination` follows the same routing and
credential precedence as ordinary publication.

A `StreamHandle` exposes `source`, `label`, `section`, `view_id`, `client_id`,
`session_id`, `observation_started_at`, `source_existed_at_start`, and
`initial_offset`. Inspect `is_observing`, `health`, `acknowledged_source_offset`,
`candidate_source_offset`, and `accounted_source_offset` for source/delivery state.
`session_id` can change after a receiver restart. These are observer properties,
not proof of application health.

Call `handle.stop(timeout=2)` to stop the follower, attempt a bounded final drain,
and report an ended or incomplete session. Omitting `timeout` uses stream config;
an explicit timeout must be finite and positive. Stop is idempotent. See
[Streams and log formats](streams.md) for record and continuity rules.

## Observation options and diagnostics

`ObservationOptions(fields=(), path=(), include_examples=False)` is a public
configuration object. `fields` and `path` are tuples of supported literal names or
indexes, not expressions. Pass it as `observe=options` to `publish_view` or `view`.

`get_observation_stats()` returns process-wide capture, queue, and delivery
counters. `flush_views(timeout=None)` returns whether ordinary async publication
and observation work drained within the available timeout. A false result is not
a delivery acknowledgement. See [Observation reference](observation.md).

## Bounded observation of pipeline results

```python
@ps.view(observe=True, view_id="etl:orders", label="Orders")
def transform_orders(frame):
    return frame.assign(net=frame["gross"] - frame["discount"])

ps.publish_view(metrics, observe=True, view_id="etl:metrics")
```

`observe=True` captures bounded detached evidence in the caller and prepares and
publishes summaries asynchronously. The decorator returns the same result object,
including for async functions, and preserves the original exception/cancellation.
It does not profile whole inputs. `async_=False` with observation is a setup error;
the ordinary global async default cannot make observation synchronous.

Use `ps.ObservationOptions(fields=("rows", "seconds"), path=("import",))` in place
of `True` to narrow capture. Examples are off by default, but supplied scalar
metrics, field names and bounded category prefixes are still exported. Unsupported
storage types produce omission reasons, including Polars at present.

`ps.flush_views(timeout=0.5)` provides a bounded best-effort drain;
`ps.get_observation_stats()` reports drops/failures and queue state. See
[bounded observations](observation.md) for setup costs, sample meaning,
privacy, destination rules, supported storage and resource limits.


## Traceback options

`TracebackPublishOptions(context_lines=2, max_frames=50)` controls source context
and frame count for `publish_traceback(..., options=...)`. Enable traceback
publishing on the producer and permit traceback rendering on the receiver where
appropriate. Tracebacks can contain private source, paths, and exception text.
No locals are captured by the traceback formatter.

All documented public names are exported from `plotsrv`; connection objects such
as `PublishTarget` live in their explicit submodule and are not top-level exports.
For an introduction, see [Publish from Python](../guides/publish-from-python.md).
