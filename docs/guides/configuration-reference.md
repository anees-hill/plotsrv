---
icon: lucide/sliders-horizontal
---

# Configuration reference

This page describes the main `plotsrv.yml` / `plotsrv.yaml` settings.

For publisher destinations, role-owned setup contracts, precedence and metadata
bounds, see [Publisher and server contracts](../about/publisher-contracts.md).
The enforced key policy, catalogue bootstrap transaction and HTTP limits are
documented in [Publisher ingestion](publisher-ingestion.md). For `plotsrv serve`
and directly publishing applications, see [Remote publishers](remote-publishers.md).
For configured targets, watches, selection and scan bounds, see
[Configured sources](configured-sources.md).
For foreground catalogue registration and remote watch lifecycle, see
[Publisher agent](publisher-agent.md).
For bounded server-side scalar and accepted-event rules under `checks-settings`,
see [Server-side checks](checks.md). Checks are separate from freshness and snapshot
storage, and are not configured through decorator arguments. Optional named destinations
under `webhook-settings` are documented in [Generic webhooks](webhooks.md).

Short source explanations and publisher docstring opt-outs use
`description-settings`; see [View descriptions](view-descriptions.md) for precedence,
privacy and examples.

Create a starter config with:

```bash
plotsrv config create
```

The default file is intentionally compact and exposes the main settings:
storage, watched-file materialisation, async publishing, safety limits,
freshness checks, and concise browser errors. Storage is off by default. For
less commonly adjusted storage queue and rendering controls, use:

```bash
plotsrv config create --expanded
```

plotsrv still runs without a config file. Add config when you want stable limits, storage, freshness, rendering, or security behaviour across runs.

## Starter layout

A compact starter config looks like this:

```yaml title="plotsrv.yaml"
# Storage is off by default. Enable it for latest restore and history.
storage-settings:
  enabled: false
  watch_enabled: false
  root_dir: .plotsrv/store
  max_snapshot_size_mb: 20.0
  default_keep_last: 2
  default_min_store_interval: off
  latest:
    enabled: true
    restore_on_startup: true
    restore_scope: discovered

watch-settings:
  # auto = memory below file_threshold_mb, file-backed at or above it.
  materialization: auto
  file_threshold_mb: 10

publish-settings:
  live:
    async_enabled: false

limits:
  published_objects:
    max_plot_bytes: 5242880
    max_table_rows: 100000
    max_table_columns: 200
  watched_files:
    max_mb: 500
  truncate_after:
    text: 1000000
    markdown: 100000
    html: off
    table_rows: 100000
    table_columns: 200

freshness-settings:
  enabled: false

security-settings:
  tracebacks_enabled: false
```

The `--expanded` form adds storage queue bounds and rendering settings shown
throughout this reference.

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
The default 500 MiB local read cap matches v0.5.0. It bounds preview bytes,
not the size of a file that can be watched. Remote publisher watches also have
a fixed 256 KiB capture cap, independent of this setting; see
[remote watched-file limits](publisher-agent.md#resource-and-ordering-limits).

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
The default was 20 MiB in v0.5.0 and was deliberately reduced to 10 MiB
during later resource tuning so large local watches switch to on-demand
previews sooner. Automatic mode also switches at the 8 MiB publish request
cap if that is lower than the configured threshold. This chooses a
representation; it is not a file size rejection limit and does not change
`limits.watched_files.max_mb`.

```yaml
watch-settings:
  materialization: auto
  file_threshold_mb: 10
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

## `publish-settings`

Live publishing is synchronous by default. This preserves existing behaviour
and needs no configuration for ordinary scripts.

For high-frequency live status/table/plot updates, this optional section makes
the bounded latest-wins worker the default when callers leave `async_` unset:

```yaml
publish-settings:
  live:
    async_enabled: true
    max_pending_views: 32
    max_pending_mb: 64
    flush_timeout_s: 1.0
```

| Key | Meaning |
|---|---|
| `async_enabled` | default for `publish_view(..., async_=None)`; `false` by default |
| `max_pending_views` | maximum distinct destination/view updates retained before processing |
| `max_pending_mb` | maximum estimated memory retained by pending source objects |
| `flush_timeout_s` | short default timeout used by `flush_views()` and attached-server shutdown |

The queue is for replaceable live views only. For one destination/view, a newer
pending update replaces the older one. New views are rejected once either budget
is full. Inspect `/status` for `publish_queue` counters rather than assuming
that a high-volume update was delivered.

For `@view`, this setting selects synchronous or asynchronous delivery only
after the decorator is active through `host`, `port`, or `launch_server`. It
does not turn a metadata-only `@view(...)` declaration into a publisher.

## `stream-settings`

Stream source polling and remote upload accounting run in the publisher
process; live raw retention applies in the receiving server. No
records-per-second quota is imposed.

```yaml
stream-settings:
  poll_interval_s: 0.1
  heartbeat_interval_s: 10
  heartbeat_timeout_s: 30
  remote_upload_max_mb_per_day: 100
  retention:
    max_raw_records: 1000
    max_raw_mb: 16
    max_total_raw_mb: 128
    max_raw_age_s: null
    fine_window_s: 60
    max_fine_summary_windows: 32
    max_coarse_summary_windows: 24
    max_noteworthy_items: 64
```

The server evicts a raw row when either the row or byte limit is exceeded and
adds the evicted observation to bounded derived summaries. `max_raw_mb` counts
canonical encoded row bytes, not the server's total Python memory; one MB here
is 1,024² bytes. Existing `max_raw_bytes` configurations still work, but
`max_raw_mb` takes precedence if both keys are supplied. The shared
`max_total_raw_mb` ceiling covers current, non-historical stream raw windows;
under pressure plotsrv evicts an oldest row from the largest window first.
It does not limit derived summaries, restored historical rows or Python object
overhead. Increasing these limits also increases the potential first browser
response for a stream view.

`remote_upload_max_mb_per_day` is an estimated daily budget, shared by stream
clients in one publisher process and reset at midnight UTC. It applies only
when the destination is not provably loopback (`localhost`, `127.0.0.1`, or
`::1`); use a loopback URL for a same-machine publisher. It counts attempted
stream POST bodies plus a per-request envelope allowance, including retries
and heartbeats. It does not meter TLS, retransmissions, capability handshakes,
browser downloads, other plotsrv features, or other processes. A publisher
restart resets this in-memory counter, so deploy an external network quota if
you need a strict billable-traffic limit. Set the value to `off` to disable
the guard.

When the budget is reached, the follower retains one unacknowledged batch and
stops advancing through the source log until the next UTC day. The original
logging process is not paused; its file can continue growing. The publisher
uses a portion of the budget for control heartbeats so the browser can show
`Stream held` and explain how to change the publisher-side setting. If even
control traffic exhausts the total budget, heartbeats stop and the receiver
eventually reports an incomplete stream. The 10-second heartbeat and
30-second timeout defaults keep idle 24/7 streams from producing a request
every second; tune both together if faster disconnect detection matters.

## `render-settings`

`render-settings.default` controls renderer behaviour.

```yaml
render-settings:
  default:
    plot_dpi: 200
    plot_default_figsize_in: "12,6"
    plot_bbox_tight: true
    plot_pad_inches: 0.10
    table_plot_max_points: 5000
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
| `table_plot_max_points` | maximum SVG points in a browser table plot (default `5000`, hard-capped at `25000`); larger plots offer browser-side sampling |
| `table_view_mode` | `rich` or `simple` table mode |
| `html_sanitize` | opt-in sanitization of HTML artifacts; removes scripts and styles, default `false` |
| `markdown_sanitize` | sanitize rendered markdown HTML |
| `html_sandbox` | optional HTML sandbox tokens; empty means no sandbox for trusted reports; also applied to direct watched HTML responses |

Snapshot and latest-state writes use `v2-<SHA-256 of the exact view ID>`
directories to keep IDs such as `a:b` and `a/b` independent. Existing slug-based
directories remain readable after exact identity validation; no automatic
destructive migration takes place. Retention and deletion affect only the
requested identity. Corrupt legacy metadata is left for operator inspection
because its ownership cannot be verified. Stored absolute payload paths are
ignored in favour of validated filenames within the view directory.

Before rolling back to a release using only the old storage layout, back up
the storage directory. That release will not discover new hashed directories;
the files remain on disk. Do not share a storage root between running server
processes or give other users write access to it.
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
  streams:
    enabled: true
    compact_min_interval_s: 10
    summary_retention: 32
    noteworthy_keep_last: 32
    keep_last_sessions: 4
    max_bytes_per_view_mb: 16
    max_total_mb: 256
    # Omit or set to null for compact-only history.
    raw_retention: null
  default_keep_last: 2
  default_min_store_interval: off
  max_snapshot_size_mb: 20.0
  max_pending_tasks: 32
  max_pending_mb: 64
```

`storage-settings.enabled` is the master switch. If it is `false`, storage is off even if nested settings are present.

Latest-state persistence has independent limits:

- `storage-settings.latest.max_size_mb`: maximum serialized latest payload;
  default 20 MiB. Oversized writes leave the previous persisted state intact.
- `storage-settings.latest.min_store_interval_s`: minimum time between latest
  writes per view; default `0` preserves existing write-on-update behaviour.
  A public demo with persistence should use a positive interval, such as `5`.
  Updates inside that interval are skipped, so restored state can lag the live
  view; there is no delayed flush of skipped updates.
- `storage-settings.views.<view_id>.latest_enabled: false`: exclude that view from future latest
  writes independently of snapshot retention. Existing files are not erased.

`storage_queue.latest_skipped` counts latest writes skipped by these controls.
They do not remove or truncate the live view. These per-payload controls are
not a total disk quota: use a dedicated quota-limited storage volume, finite
snapshot retention and a fixed view catalogue for continuous public demos.

The legacy `/history` endpoint now returns at most 100 records per page, with
`next_cursor` for the next request's `before` parameter and `count` for the
total matching records. It uses the same bounded metadata scan as
`/history/navigation` and avoids scanning when history storage is disabled.

`max_pending_tasks` and `max_pending_mb` bound best-effort latest/snapshot
serialisation work. Rejections are exposed as `storage_queue` counters in
`/status`; they never affect the in-memory live view that has already been
accepted.

### Stream-session storage

`storage-settings.streams` controls bounded persistence for structured stream
sessions. `storage-settings.enabled` remains the master switch. A compact
session stores metadata, derived summaries, and noteworthy/continuity items;
it does not turn a restarted producer into a live session.

| Key | Meaning |
|---|---|
| `enabled` | Enable compact stream persistence while master storage is enabled. |
| `compact_min_interval_s` | Minimum time between compact-only checkpoints (default 10 seconds); registration and close always write, and explicitly enabled raw blocks are never coalesced. Set to `0` for a checkpoint on every request. |
| `summary_retention` | Maximum derived windows retained for each session. |
| `noteworthy_keep_last` | Maximum noteworthy/continuity items retained for each session. |
| `keep_last_sessions` | Softer count limit for retained sessions per logical stream. |
| `max_bytes_per_view_mb` | Hard combined ceiling for compact files, markers, and raw blocks for one logical stream. |
| `max_total_mb` | Shared ceiling for generated stream-session files across all views (default 256 MiB). |
| `raw_retention` | Explicit raw-segment policy; `null` disables raw persistence. |

`raw_retention`, when present, accepts `max_blocks`, `max_bytes_mb`, and
optional `max_age_s`. The hard `max_bytes_per_view_mb` ceiling wins whenever
these policies conflict. A per-view override belongs at
`storage-settings.views.<view_id>.stream` (the early `streams` spelling is
also accepted).

The shared cap prunes old raw blocks first, then older closed sessions. Active
sessions are not evicted to admit another active stream's checkpoint: when
there is no safe space, persistence is rejected and shown as incomplete while
live observation continues. On server startup, all stored sessions are
historical, so the shared cap can also prune old previously active runs.

Compact checkpoints are best-effort observation history, not a lossless audit
log. A crash can lose accepted observations after the last checkpoint; on
restore, a session last stored as active is marked incomplete rather than
presented as a complete run. A normally closed session gets a final checkpoint.

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


`code-settings` controls source-language and initial styling overrides. See
[Watched source code and raw config text](renderers.md#watched-source-code-and-raw-config-text)
for supported suffixes, browser precedence and fixed highlighting limits.
