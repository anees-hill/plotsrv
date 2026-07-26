---
icon: lucide/sliders-horizontal
---

# Configuration reference

This page describes the main `plotsrv.yaml` settings.

Create a starter config with:

```bash
plotsrv config create
```

plotsrv still runs without a config file. Add config when you want stable limits, storage, freshness, rendering, or security behaviour across runs.

## Starter layout

A current starter config looks like this:

```yaml title="plotsrv.yaml"
limits:
  published_objects:
    # Hard safety limits for objects sent to the plotsrv server.
    max_plot_bytes: 5242880
    max_table_rows: 100000
    max_table_columns: 200
    max_artifact_text_chars: 200000
    max_json_container_items: 20000

  watched_files:
    # Maximum amount plotsrv reads from each watched file preview.
    # Use "off" to allow full-file reads.
    max_mb: 500

  truncate_after:
    # Preparation/display limits.
    # These truncate what plotsrv prepares for display.
    text: 1000000
    markdown: 100000
    html: off
    table_rows: 100000
    table_columns: 200

storage-settings:
  enabled: false
  watch_enabled: false
  root_dir: .plotsrv/store
  max_snapshot_size_mb: 20.0
  default_keep_last: 3
  default_min_store_interval: off

watch-settings:
  # auto = file-backed when the watched file is at/above file_threshold_mb.
  # memory = always publish watched-file content into memory.
  # file = always keep watched files file-backed and preview from disk on demand.
  materialization: auto
  file_threshold_mb: 50
  active_loads:
    max_concurrent: 2
    wait_timeout_s: 1.0

freshness-settings:
  enabled: false
  expected_every: 60s
  warn_after: 2m
  overdue_after: 10m

render-settings:
  default:
    plot_dpi: 200
    plot_default_figsize_in: "12,6"
    plot_bbox_tight: true
    plot_pad_inches: 0.10
    table_view_mode: rich
    html_sanitize: false
    markdown_sanitize: true
    html_sandbox: ""
    markdown_sandbox: ""

security-settings:
  tracebacks_enabled: false
```

## `limits`

`limits` is split into three concepts:

| Section | Purpose |
|---|---|
| `published_objects` | hard safety limits for objects sent to `/publish` |
| `watched_files` | how much plotsrv reads from watched files |
| `truncate_after` | how much plotsrv prepares/displays |

### `limits.published_objects`

These are hard server-side safety limits.

If a normal Python publish exceeds one of these values, the request is rejected. The browser UI also receives a visible `publish_error` artifact explaining what failed and which key to adjust.

```yaml
limits:
  published_objects:
    max_plot_bytes: 5242880
    max_table_rows: 100000
    max_table_columns: 200
    max_artifact_text_chars: 200000
    max_json_container_items: 20000
```

| Key | Meaning |
|---|---|
| `max_plot_bytes` | maximum decoded plot/image payload size |
| `max_table_rows` | maximum table rows accepted by `/publish` |
| `max_table_columns` | maximum table columns/fields accepted by `/publish` |
| `max_artifact_text_chars` | maximum text representation accepted for text-like artifacts |
| `max_json_container_items` | maximum item count for JSON-like containers |

`publish-limits` is still accepted as a legacy fallback, but new configs should use `limits.published_objects`.

### `limits.watched_files`

Controls how much plotsrv reads for watched-file previews.

```yaml
limits:
  watched_files:
    max_mb: 500
```

| Key | Meaning |
|---|---|
| `max_mb` | maximum amount read for each watched-file preview |

Use `off` to allow full-file reads:

```yaml
limits:
  watched_files:
    max_mb: off
```

`max_bytes` is still accepted as a legacy alias, but new configs should use `max_mb`.

The equivalent CLI option is:

```bash
plotsrv watch ./logs/job.log --max-mb 25
```

`--max-bytes` remains available as a legacy/advanced CLI option.

#### Watched-file materialization

Watched files can be memory-backed or file-backed.

| Mode | Behaviour |
|---|---|
| `memory` | reads watched-file content and publishes a normal in-memory view |
| `file` | stores watched-file metadata and reads bounded previews from disk on demand |
| `auto` | uses `file_threshold_mb` to choose between `memory` and `file` |

In `auto` mode, files at or above `file_threshold_mb` become file-backed.

```yaml
watch-settings:
  materialization: auto
  file_threshold_mb: 50
```

You can force a mode from the CLI:

```bash
plotsrv watch ./logs/job.log --materialization file
```

or for watched files attached to `plotsrv run`:

```bash
plotsrv run . \
  --watch ./logs/job.log \
  --watch-materialization file
```

File-backed watched views are useful for large logs and CSVs because plotsrv does not retain the full file content in server memory.

#### File-backed active loads

`watch-settings.active_loads` bounds concurrent on-demand preview work for
file-backed views. It does not change what users may see: table display limits
remain under `limits.truncate_after`.

```yaml
watch-settings:
  active_loads:
    max_concurrent: 2
    wait_timeout_s: 1.0
```

When all slots are active, plotsrv responds with a temporary `503` and
`Retry-After` header. The browser retries briefly; API clients can make the
same decision explicitly.

### `limits.truncate_after`

Controls preparation/display truncation.

```yaml
limits:
  truncate_after:
    text: 1000000
    markdown: 100000
    html: off
    table_rows: 100000
    table_columns: 200
```

| Key | Meaning |
|---|---|
| `text` | maximum characters prepared for normal text artifacts |
| `markdown` | maximum characters prepared for markdown artifacts |
| `html` | maximum characters prepared for HTML artifacts; `off` disables truncation |
| `table_rows` | maximum table rows prepared for display |
| `table_columns` | maximum table columns prepared for display |

Generated plotsrv error artifacts use `watch_error` or `publish_error` and are not truncated by normal text limits. This keeps actionable error messages visible even when `text` truncation is low.

Legacy `limits.render`, `limits.tables`, and top-level `truncation` settings are still accepted where possible, but new configs should use `limits.truncate_after`.

## `render-settings`

`render-settings.default` controls renderer behaviour.

```yaml
render-settings:
  default:
    plot_dpi: 200
    plot_default_figsize_in: "12,6"
    plot_bbox_tight: true
    plot_pad_inches: 0.10
    table_view_mode: rich
    html_sanitize: false
    markdown_sanitize: true
    html_sandbox: ""
    markdown_sandbox: ""
```

| Key | Meaning |
|---|---|
| `plot_dpi` | DPI used when rendering static plot images |
| `plot_default_figsize_in` | default matplotlib-style figure size |
| `plot_bbox_tight` | save plots with tight bounding boxes |
| `plot_pad_inches` | plot padding when tight bounding boxes are used |
| `table_view_mode` | `rich` or `simple` table mode |
| `html_sanitize` | sanitize HTML artifacts before rendering |
| `markdown_sanitize` | sanitize rendered markdown HTML |
| `html_sandbox` | optional iframe sandbox value for HTML |
| `markdown_sandbox` | optional iframe sandbox value for markdown |

Legacy `table-settings` and `artifact-render-settings` are still readable, but new config should use `render-settings.default`.

## `storage-settings`

Storage controls latest restore and historical snapshots.

```yaml
storage-settings:
  enabled: true
  watch_enabled: false
  root_dir: .plotsrv/store
  latest:
    enabled: true
    restore_on_startup: true
    restore_scope: discovered
  default_keep_last: 3
  default_min_store_interval: off
  max_snapshot_size_mb: 20.0
```

`storage-settings.enabled` is the master switch. If it is `false`, storage is off even if nested settings are present.

### Source-aware storage

Watched-file snapshots are disabled by default.

File-backed watched files are always skipped by storage. They are represented by metadata and previewed from the source file on demand, so plotsrv does not write latest-state payloads or snapshots for them.

```yaml
storage-settings:
  enabled: true
  watch_enabled: false
```

To snapshot memory-backed watched files globally:

```yaml
storage-settings:
  enabled: true
  watch_enabled: true
```

To opt in one memory-backed watched view:

```yaml
storage-settings:
  enabled: true
  watch_enabled: false
  views:
    "files:job log":
      watch_enabled: true
```

Normal Python publishes use `views.<view_id>.enabled`; watched-file publishes use `views.<view_id>.watch_enabled`.

## `freshness-settings`

Freshness shows whether a view has updated recently enough.

```yaml
freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h
```

| Key | Meaning |
|---|---|
| `expected_every` | expected update cadence |
| `warn_after` | threshold for stale/warning state |
| `overdue_after` | threshold for overdue/error state |

### Source-aware freshness

Global freshness applies to normal Python publishes.

Watched-file views are not marked stale by global freshness settings by default. To apply freshness to a watched file, opt that specific view in:

```yaml
freshness-settings:
  enabled: true
  views:
    "files:job log":
      enabled: true
      expected_every: 5m
      warn_after: 10m
      overdue_after: 30m
```

This avoids marking static but valid watched files as stale.

## `security-settings`

Security settings control optional routes and local-only behaviour.

```yaml
security-settings:
  tracebacks_enabled: false
  docs_enabled: false
  openapi_enabled: false
  shutdown_enabled: false
  control_local_only: true
  internal_read_local_only: false
  status_local_only: false
  history_local_only: false
  views_local_only: true
```

The generated starter config only includes `tracebacks_enabled`, but the full set can be added when needed.

## Populating config

plotsrv can scan Python code for discoverable views:

```bash
plotsrv config populate freshness .
plotsrv config populate storage .
plotsrv config populate limits .
```

For limits, generated entries use the current schema:

```yaml
limits:
  published_objects:
    max_plot_bytes: 5242880
    max_table_rows: 100000
    max_table_columns: 200
    max_artifact_text_chars: 200000
    max_json_container_items: 20000
  watched_files:
    max_mb: 500
  truncate_after:
    text: 1000000
    markdown: 100000
    html: off
    table_rows: 100000
    table_columns: 200
  views:
    "pipelines:daily import":
      truncate_after:
        text: 1000000
        markdown: 100000
        html: off
```

Use `--mode merge` to preserve existing entries and add new ones, or `--mode replace` to regenerate the discovered entries.

## Legacy compatibility

The following legacy sections remain readable for compatibility:

```yaml
publish-limits:
limits:
  watched_files:
    max_bytes:
  render:
  tables:
truncation:
table-settings:
artifact-render-settings:
```

New documentation and generated configs use the newer layout.
