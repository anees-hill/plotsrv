---
icon: lucide/settings
---

# Configuration basics

plotsrv works without a config file.

You can install it, run it, and publish objects immediately:

```python
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df)
```

A config file becomes useful when you want to control behaviour such as:

- table limits
- watched-file limits
- storage and historical snapshots
- freshness indicators
- UI customisation
- security-related options
- per-view settings

## Create a config file

Create a starter config file with:

```bash
plotsrv config create
```

This creates:

```text
plotsrv.yml
```

in the current directory.

If the file already exists, plotsrv will not overwrite it unless you pass `--force`:

```bash
plotsrv config create --force
```

!!! warning

    `--force` overwrites the existing config file.

    Use it carefully if you have already customised `plotsrv.yml`.

## How plotsrv finds config

By default, plotsrv looks for a config file in the current working directory:

```text
plotsrv.yml
plotsrv.yaml
```

You can also pass a config path explicitly.

From the CLI:

```bash
plotsrv run --config path/to/plotsrv.yml
```

From Python:

```python
import plotsrv as ps

ps.start_server(config="path/to/plotsrv.yml")
```

You can also use the `PLOTSRV_CONFIG` environment variable.

```bash
PLOTSRV_CONFIG=path/to/plotsrv.yml plotsrv run
```

## A small config file

A minimal useful config might look like this:

```yaml title="plotsrv.yml"
limits:
  watched_files:
    max_bytes: 5000000

table-settings:
  table_view_mode: rich
  max_table_rows_rich: 1000

storage-settings:
  enabled: false

freshness-settings:
  enabled: false
```

You do not need to configure everything at once. Start with the settings you need.

## Table settings

Table settings control how many rows plotsrv shows in table views.

```yaml title="plotsrv.yml"
table-settings:
  table_view_mode: rich
  max_table_rows_simple: 200
  max_table_rows_rich: 1000
```

`table_view_mode` can be:

- `rich`
- `simple`

`rich` mode gives you the interactive table renderer with search, filters, column controls, pagination, and export.

`simple` mode renders a simpler static HTML table.

!!! note

    Table display limits are there to keep the browser UI responsive.

    They do not mean your original Python object has been changed.

## Watched-file limits

Watched-file limits control how much data plotsrv reads from files on disk.

```yaml title="plotsrv.yml"
limits:
  watched_files:
    max_bytes: 5000000
```

Use `off` to read the whole file:

```yaml title="plotsrv.yml"
limits:
  watched_files:
    max_bytes: off
```

This is useful for small files, but can be expensive for very large logs or CSV files.

## Renderer limits

Renderer limits control how much text-like content is displayed in the browser.

```yaml title="plotsrv.yml"
limits:
  render:
    text: 1000000
    html: off
    markdown: off
```

These settings apply to text-like renderers:

- text
- HTML
- markdown

Use `off` to disable the render limit for that type.

!!! note

    Watched-file limits and renderer limits are different.

    Watched-file limits control how much plotsrv reads from disk.

    Renderer limits control how much plotsrv displays in the browser.

## Table publish limits

Table publish limits control how much table data plotsrv accepts and stores for rendering.

```yaml title="plotsrv.yml"
limits:
  tables:
    max_rows: 10000
    max_columns: 200
```

These limits help protect the UI and server from very large table payloads.

## Storage and historical snapshots

Storage is disabled by default.

Enable it if you want plotsrv to keep recent historical snapshots.

```yaml title="plotsrv.yml"
storage-settings:
  enabled: true
  root_dir: .plotsrv/store
  default_keep_last: 5
  max_snapshot_size_mb: 20
```

When storage is enabled, plotsrv can show previous versions of plots, tables, and artifacts through the history controls in the UI.

`default_keep_last` controls how many snapshots are kept per view.

```yaml title="plotsrv.yml"
storage-settings:
  enabled: true
  default_keep_last: 5
```

Use `default_keep_last: null` if you want to keep snapshots indefinitely.

!!! warning

    Keeping snapshots indefinitely can use a lot of disk space.

    Prefer a small `default_keep_last` value unless you have a reason to keep more.

## Freshness indicators

Freshness indicators are disabled by default.

Enable them when a view is expected to update regularly.

```yaml title="plotsrv.yml"
freshness-settings:
  enabled: true
  expected_every: 60s
  warn_after: 90s
  overdue_after: 180s
```

This lets plotsrv show whether a view is:

- fresh
- stale
- overdue

Freshness is useful for repeated jobs, scheduled processes, and monitoring-style workflows.

## UI customisation

You can customise the page title, header text, logo, favicon, and some UI controls.

```yaml title="plotsrv.yml"
ui-settings:
  page_title: "My plotsrv"
  header_text: "Operations monitor"
  header_fill_colour: "#ffffff"
  logo: "logo.png"
  favicon: "favicon.png"
```

Logo and favicon paths are resolved relative to the config file.

## Security-related settings

Some routes and features are controlled by security settings.

```yaml title="plotsrv.yml"
security-settings:
  docs_enabled: false
  openapi_enabled: false
  shutdown_enabled: false
  control_local_only: true
  tracebacks_enabled: false
```

For example:

- `docs_enabled` controls FastAPI docs routes.
- `openapi_enabled` controls the OpenAPI JSON route.
- `shutdown_enabled` controls the browser-triggered shutdown endpoint.
- `control_local_only` restricts control routes to local requests.
- `tracebacks_enabled` controls whether traceback artifacts can be published and displayed.

!!! warning

    Tracebacks can expose file paths and source-code context.

    They are disabled by default. Only enable them where that is acceptable.

## Named config instances

plotsrv supports named config instances.

This is useful when the same config file should behave differently for different environments or processes.

```yaml title="plotsrv.yml"
table-settings:
  default:
    table_view_mode: rich
    max_table_rows_rich: 1000

  instances:
    local:
      max_table_rows_rich: 5000

    production:
      max_table_rows_rich: 1000
```

Run with a name:

```bash
plotsrv run --name local
```

Or from Python:

```python
import plotsrv as ps

ps.start_server(name="local")
```

The named instance is merged over the default settings for that section.

## Automatically populate per-view config

If you use `@ps.view(...)`, plotsrv can discover your views and populate parts of the config file.

For freshness settings:

```bash
plotsrv config populate freshness .
```

For storage settings:

```bash
plotsrv config populate storage .
```

For render limits:

```bash
plotsrv config populate limits .
```

These commands scan for `@ps.view(...)` decorators and add per-view entries.

For example:

```python title="views.py"
import plotsrv as ps

@ps.view(label="Daily checks", section="etl")
def daily_checks():
    return {"status": "ok"}
```

may produce a per-view config entry for:

```text
etl:Daily checks
```

!!! note

    Automatic config population is useful once your project has several views.

    You can start without it and add it later.

## Config from Python

Some runtime options can be supplied when starting plotsrv from Python.

```python
import plotsrv as ps

ps.start_server(
    config="plotsrv.yml",
    name="local",
    truncate=1000000,
)
```

You can also disable text-like render truncation at runtime:

```python
import plotsrv as ps

ps.start_server(no_truncate=True)
```

## Config from the CLI

Common CLI config options include:

```bash
plotsrv run --config plotsrv.yml
```

```bash
plotsrv run --name local
```

```bash
plotsrv run --truncate 1000000
```

```bash
plotsrv run --no-truncate
```

These runtime options are useful when you want to test a different config without editing the file.

## Recommended path

Start simple:

```bash
plotsrv config create
```

Then edit only the section you need.

A common progression is:

- adjust table or watched-file limits
- enable storage if you want historical snapshots
- enable freshness if views should update on a schedule
- customise the UI once the basic workflow is working
- use automatic config population when you have several `@ps.view(...)` views

## Next steps

- [Watch files](watch-files.md)
- [Renderer overview](../renderers.md)
- [Freshness indicators](../features/freshness-indicators.md)
- [Historical snapshots](../features/historical-snapshots.md)
- [Automatic config](../features/automatic-config.md)
