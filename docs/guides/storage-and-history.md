---
icon: lucide/rocket
---

# Storage and history

plotsrv keeps live views in memory by default.

That is simple and fast, but it means live views disappear when the server stops.

Storage adds persistence so plotsrv can:

- keep historical snapshots for browsing
- restore the latest view after restart
- limit how much history is kept

For most workflows, latest restore is just part of enabling storage.

## Enable storage

Storage is opt-in. Simply:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
```

Or with more control:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  root_dir: .plotsrv/store
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20
```

`storage-settings.enabled` is the main switch.

When storage is enabled, plotsrv can keep historical snapshots, depending on the retention settings. It can also persist the latest live view and restore it when the server starts again.

!!! note

    The above settings control global storage settings. For view-by-view settings, see below, including the `plotsrv config populate storage .` command

## What storage does

Storage has two effects:

| Behaviour | Meaning |
|---|---|
| Snapshot history | previous versions can be browsed through the UI history controls |
| Latest restore | the most recent live view can reappear after restart |

Snapshots appear in the history controls.

The latest restored view appears as the current live view.


## Snapshots

Snapshots keep previous versions of views.

They are used for history browsing in the UI.

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20
```

| Setting | Purpose |
|---|---|
| `default_keep_last` | how many snapshots to keep per view |
| `default_min_store_interval` | minimum time between stored snapshots for repeated updates |
| `max_snapshot_size_mb` | maximum size for a stored snapshot |

A common starting point is to keep a small number of recent snapshots:

```yaml
storage-settings:
  enabled: true
  default_keep_last: 5
```

For noisy or frequently updated views, add a minimum storage interval:

```yaml
storage-settings:
  enabled: true
  default_keep_last: 5
  default_min_store_interval: 1h
```

## Latest restore

When storage is enabled, plotsrv can restore the latest live content after restart.

This is useful for outputs that update occasionally, such as:

- daily imports
- scheduled reports
- validation jobs
- long-running monitors
- generated result tables
- status objects from batch processes

Restored content is marked in the UI, so it is clear that the view came from storage and is waiting for the next live update.

Freshness indicators, when enabled, still use the original update time rather than the restore time.

## Turning off latest restore

Latest restore can be turned off if a server should always start with an empty live UI.

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  latest:
    restore_on_startup: false
```

It can also be limited using `restore_scope`.

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  latest:
    restore_scope: discovered
```

Common values are:

| Value | Meaning |
|---|---|
| `discovered` | restore latest records matching views discovered for the current run |
| `all` | restore all latest records under the storage root |
| `none` | restore nothing |

`discovered` is a good default for project-specific server runs because it avoids restoring unrelated old views.

## Storage retention

Storage retention controls how much historical material is kept.

For example:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20
```

This means:

- keep up to 5 snapshots per view
- do not store snapshots more often than once per hour
- skip snapshots larger than 20 MB

Use conservative values at first. Storage is meant to be useful, not to become an unmanaged data store.

## Per-view storage settings

Global storage settings apply to all views by default.

For projects with several views, per-view settings can be generated with:

```bash
plotsrv config populate storage .
```

This scans for:

- `@ps.view(...)` decorators
- simple `publish_view(...)` calls

and adds storage entries for discovered views.

For example:

```python title="demo_pipeline.py"
import plotsrv as ps

@ps.view(label="daily import", section="pipelines")
def daily_import_status():
    return {"status": "ok"}
```

The discovered view identity is:

```text
pipelines:daily import
```

Per-view storage settings are useful when different views need different retention behaviour.

For example:

- keep more snapshots for important result tables
- keep fewer snapshots for large plots
- set a minimum snapshot interval for frequently updated views
- reduce storage for noisy or low-value outputs

## Populate storage config

To populate storage entries:

```bash
plotsrv config populate storage .
```

To scan a specific file:

```bash
plotsrv config populate storage demo_pipeline.py
```

To scan a source directory:

```bash
plotsrv config populate storage ./src
```

To merge generated entries into an existing config:

```bash
plotsrv config populate storage . --mode merge
```

To replace generated storage entries:

```bash
plotsrv config populate storage . --mode replace
```

To skip confirmation prompts:

```bash
plotsrv config populate storage . --yes
```

A common pattern is:

```bash
plotsrv config create
plotsrv config populate storage . --yes
```

Then edit generated entries where specific views need different retention behaviour.

## Storage CLI commands

plotsrv includes CLI commands for inspecting and clearing stored data.

Show storage statistics:

```bash
plotsrv store stats
```

List stored views or snapshots:

```bash
plotsrv store list
```

List one view:

```bash
plotsrv store list --view "pipelines:daily import"
```

Clear one view:

```bash
plotsrv store clear --view "pipelines:daily import"
```

Clear all stored material:

```bash
plotsrv store clear --all
```

!!! warning

    `plotsrv store clear --all` removes stored material, including latest restored state and snapshot history.

## Storage directory

By default, storage is written under:

```text
.plotsrv/store
```

This is controlled by:

```yaml
storage-settings:
  root_dir: .plotsrv/store
```

For local project use, `.plotsrv/` is usually a good candidate for `.gitignore`.

```gitignore
.plotsrv/
```

## Next steps

- [CLI reference](cli.md)
- [Freshness](freshness.md)
- [Configuration basics](../get-started/configuration-basics.md)
