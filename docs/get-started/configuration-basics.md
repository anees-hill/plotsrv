---
icon: lucide/settings
---

# Configuration basics

plotsrv works without a config file.

A config file becomes useful when behaviour needs to be kept consistent across runs, especially for:

- storage
- history
- freshness checks
- table limits
- watched-file limits
- UI settings
- per-view settings

## Create a config file

To create a starter config:

```bash
plotsrv config create
```

This creates a plotsrv config file in the current directory.

The starter config is written from plotsrv’s built-in config template.

!!! note

    If `plotsrv.yaml` exists in project root, it will be used by default. When running `plotsrv run`, the --config flag allows the use of alternative config files (or allows us to be explicit, as we have done here).

## Use a config file

To start plotsrv with a config file:

```bash
plotsrv run --config plotsrv.yaml
```

A config file can also be used when starting plotsrv from Python:

```python
import plotsrv as ps

ps.start_server(config="plotsrv.yaml")
```

## Create per-view config automatically

For projects with several views, plotsrv can scan code and populate config entries automatically.

For freshness settings:

```bash
plotsrv config populate freshness .
```

For storage settings:

```bash
plotsrv config populate storage .
```

For render and table limits:

```bash
plotsrv config populate limits .
```

The target can be a script, module, package, or directory:

```bash
plotsrv config populate freshness demo_pipeline.py
```

```bash
plotsrv config populate storage ./src
```

plotsrv scans for:

- `@ps.view(...)` decorators
- simple `publish_view(...)` calls with literal labels, sections, or view IDs

For example:

```python title="demo_pipeline.py"
import plotsrv as ps

@ps.view(label="daily import", section="pipelines")
def daily_import_status():
    return {"status": "ok"}
```

or:

```python title="demo_pipeline.py"
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
)
```

Both can give plotsrv enough information to add per-view config for:

```text
pipelines:daily import
```

## Populate freshness settings

Freshness checks show whether a view has updated recently enough.

To add freshness entries for discovered views:

```bash
plotsrv config populate freshness .
```

This is useful for scripts, jobs, and pipelines where outputs are expected to update on a schedule.

For example, a generated config might include entries based on discovered views, alongside the global freshness settings:

```yaml title="plotsrv.yaml"
freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h
```

Freshness is useful when a view should not just exist, but should be recent.

For example:

- an hourly import
- a nightly report
- a repeated validation job
- a long-running monitor
- a process expected to publish regular status updates

When content is restored from storage, freshness is still based on the original update time, not the restore time.

## Populate storage settings

Storage controls latest restore and historical snapshots.

To add storage entries for discovered views:

```bash
plotsrv config populate storage .
```

This is useful when different views need different retention behaviour.

For example:

- keep more snapshots for important result tables
- keep fewer snapshots for large plots
- apply a minimum snapshot interval to frequently updated views
- disable or reduce storage for noisy outputs

A basic storage section looks like this:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  root_dir: .plotsrv/store
  latest:
    enabled: true
    restore_on_startup: true
    restore_scope: discovered
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20
```

`storage-settings.enabled` is the master switch.

Even if `latest.enabled` is present in the config, storage remains off unless `storage-settings.enabled` is `true`.

## Populate limits

Limits help keep the UI responsive.

To add limit entries for discovered views:

```bash
plotsrv config populate limits .
```

This is useful when some views are expected to be much larger than others.

For example:

- a large DataFrame might need a higher table row limit
- a log view might need a larger text render limit
- an HTML or markdown report might need different render limits
- a noisy view might need stricter limits than the default

Global limit settings look like this:

```yaml title="plotsrv.yaml"
limits:
  watched_files:
    max_bytes: 5000000

  tables:
    max_rows: 10000
    max_columns: 200
```

For first use, the defaults are usually enough. Populate limits once there are several views with different size expectations.

## Merge or replace generated entries

Config population can merge generated entries into an existing config.

```bash
plotsrv config populate freshness . --mode merge
```

It can also replace the generated section:

```bash
plotsrv config populate freshness . --mode replace
```

`merge` is usually safer for existing config files.

`replace` is useful when regenerating a section from scratch.

To skip confirmation prompts:

```bash
plotsrv config populate freshness . --yes
```

## Latest restore

Latest restore lets plotsrv restore the most recent live view after restart.

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  latest:
    enabled: true
    restore_on_startup: true
    restore_scope: discovered
```

With this enabled, plotsrv can bring back the last live content when the server starts again.

Restored content is marked in the UI, so it is clear that it came from storage and is waiting for the next live update.

## Restore scope

`restore_scope` controls which latest records are restored.

```yaml
storage-settings:
  latest:
    restore_scope: discovered
```

The common options are:

| Value | Meaning |
|---|---|
| `discovered` | restore only latest records matching already registered/discovered views |
| `all` | restore all latest records |
| `none` | restore nothing |

`discovered` is the safest default for most workflows.

It avoids unexpectedly filling the UI with unrelated old views from earlier runs.

## Snapshots

Snapshots are different from latest restore.

| Concept | Purpose |
|---|---|
| Latest restore | restores the current live view after restart |
| Snapshots | keeps previous versions for history browsing |

Snapshot retention is controlled with settings such as:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20
```

`default_keep_last` controls how many snapshots are kept.

`default_min_store_interval` controls how often snapshots are stored for repeated updates.

`max_snapshot_size_mb` limits the size of stored snapshots.

## Watched-file limits

Watched-file limits control how much of a file plotsrv reads from disk.

```yaml title="plotsrv.yaml"
limits:
  watched_files:
    max_bytes: 5000000
```

To read the whole watched file:

```yaml
limits:
  watched_files:
    max_bytes: off
```

Keeping a limit is usually better for logs and large files.

## UI settings

The config file can also customise the UI.

For example:

```yaml title="plotsrv.yaml"
ui-settings:
  page_title: "plotsrv"
  header_text: "plotsrv"
```

More detailed UI customisation is covered in the guide pages.

## A practical starter config

For a small server workflow, a practical starting point is:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  root_dir: .plotsrv/store
  latest:
    enabled: true
    restore_on_startup: true
    restore_scope: discovered
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20

freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h

limits:
  watched_files:
    max_bytes: 5000000
  tables:
    max_rows: 10000
    max_columns: 200
```

Then populate per-view entries from discovered views:

```bash
plotsrv config populate freshness . --yes
plotsrv config populate storage . --yes
plotsrv config populate limits . --yes
```

This gives a useful pattern:

1. create a starter config
2. enable the broad features needed
3. let plotsrv populate per-view entries from the codebase
4. edit the generated entries where specific views need different behaviour

## Next steps

For more detail:

- [Storage and history](../guides/storage-and-history.md)
- [CLI reference](../guides/cli.md)
- [Renderers](../guides/renderers.md)
