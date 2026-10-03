
# Storage and history reference

For the normal setup, start with the [guide](../guides/keep-history.md).

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
| Stream-session history | bounded observed stream sessions can be selected after restart |

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

## Stream-session history

When a JSONL stream is used with storage enabled, plotsrv stores bounded
session metadata, derived summary windows, and noteworthy/continuity
observations beneath the dedicated `streams/` storage namespace. Once a
producer run is superseded, its successfully stored session appears in the
stream view's **Run** selector without requiring a server restart. Retained
runs are restored there after later restarts as well. A stored run is marked as
historical and is never presented as a live producer.

If the server restarts while a producer is still observing its source, the
producer reconnects using a new transport session. Its logical view and client
identity stay the same, and its pending batch is retried in the new session.
The observer continues from its acknowledged source position; it does not
replay the whole log. If an acknowledgement was lost just before the restart,
that batch may appear in both the old stored session and the new one. Retries
within the same server session remain deduplicated. `StreamHandle.session_id`
reflects the current transport session after reconnection.

Raw source rows remain opt-in. They can be retained only with a finite raw
block policy; the history view shows those explicitly retained segments, not a
source-log replay.
The Run selector labels runs with retained rows and runs with only compact
insights. A compact-only run opens with an empty table and its retained insights;
a run with only a persistence-gap marker is shown as unavailable. With stream
storage disabled, past runs cannot be reopened.

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  streams:
    keep_last_sessions: 4
    summary_retention: 32
    noteworthy_keep_last: 32
    # This is a hard ceiling for every retained session and optional raw block
    # for one logical stream view. It overrides the softer count policies.
    max_bytes_per_view_mb: 16
    raw_retention:
      max_blocks: 8
      max_bytes_mb: 4
      max_age_s: 24h
```

Use `raw_retention: null` (the default) to keep compact history only. A
persistence gap remains visible on the restored historical session; storage is
observational history, not an audit guarantee.
If a hard byte ceiling can retain only the small persistence-gap marker, the
session still appears as an incomplete stored session with its compact details
unavailable rather than disappearing or being shown as complete.

To override one logical stream without changing snapshot settings for that
view, put a nested `stream` mapping under `storage-settings.views`:

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  views:
    "logs:worker stream":
      stream:
        keep_last_sessions: 2
        max_bytes_per_view_mb: 4
```

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

Ordinary published views inherit global storage settings. Watched files require explicit storage opt-in. Stream retention has its own settings.

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

List stored views, snapshots, and stream history:

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

    `plotsrv store clear --all` removes stored material, including latest restored state, snapshot history, and stream-session history. `--view` clears all three kinds only for that logical view.

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
- [Freshness](configuration.md#freshness-settings)
- [Configuration basics](../guides/configure-plotsrv.md)

## Quick snapshot navigation

Use the adjacent arrows to the right of **Snapshots** to move older or newer. From the
newest stored snapshot, Newer returns to **Live (latest)**: the current server
state. Live is a separate choice even when a stored version looks identical.
Existing metadata cannot prove that a snapshot has the same content as Live;
creation timestamps never establish equivalence. Ordering uses creation time
in UTC, then snapshot ID to break ties. Selector labels use the browser's local
time; hover for a precise UTC timestamp. The History timeline uses UTC throughout.

The selector keeps one page of 50 metadata entries, with **Older snapshots…**
and **Newest snapshots…** choices to change pages without loading bodies. The
selected snapshot stays available in the selector even outside that page.
Only selecting a version loads its content. Browsing does not publish data,
change source arrival timestamps, evaluate checks or send notifications.

When storage is unavailable, the ordinary selector stays visible but greyed out.
Hover over it for an explanation of snapshots and why they are unavailable;
the navigation arrows are hidden.
Enabled but empty storage says **No snapshots yet**. Streams retain their
separate session-history controls. If a selected version was removed, is
unreadable or fails to load, its URL/selection stays in place. Previous content
is retained where possible, with an explicit notice; exports are disabled
until a coherent selection loads. Choose another version or Latest to recover.
Normal table/plot settings remain in place.

### Metadata API for navigation clients

`GET /history/navigation?view=<logical-id>&limit=50` returns `snapshots`,
`count`, `next_cursor`, `capability` and `result`. Pass `before=<next_cursor>`
for the next older page (limit 1–100). Pass `selected=<snapshot-id>` to obtain
its metadata and its immediate `older`/`newer` neighbours independently of the
page. A null `newer` with `can_return_latest: true` means the next choice is
Latest; `selection_state: unavailable` identifies missing selected metadata.
Bodies can still disappear between metadata lookup and selection.

Optional ISO `start` (inclusive) and `end` (exclusive) boundaries provide
metadata pages/counts for a date range; naive boundaries mean UTC. Pagination
is a keyset traversal of current retention, not a frozen transaction: new
snapshots or concurrent retention may change subsequent pages. No payload is
opened to order, count or filter metadata. The existing `/history` response
shape remains available for older callers, but new clients should use this
bounded endpoint. Both use the existing history read permission.

There is no new index, worker, background polling or idle cache. On each
metadata request the server retains at most one page plus selection/neighbours,
with two concurrent readers and no waiting queue. Each scan allows 10,000
directory entries, 8 MiB of metadata, 32 KiB per metadata file (checked before
JSON parsing) and a cooperative 500 ms deadline between filesystem operations.
Exceeding a budget, busy readers or malformed metadata produces an explicit
503 rather than incomplete ordering. A slow filesystem operation itself
cannot be cancelled by that deadline. Use modest retention; history beyond
these scan budgets cannot be navigated with this endpoint. Browser requests
have a 10-second abort deadline and rapid version choices coalesce; no automatic
retry loop is added. These limits apply to navigation metadata, not existing
snapshot-body rendering or the legacy `/history` endpoint.

For other browser surfaces, `PLOTSRV.core.snapshotNavigation` exposes shared
`state`, `select(idOrNull)`, `move("older"|"newer")` and
`loadMetadata(beforeCursor)` functions. They work without toolbar markup and
share selection errors, latest-wins loading and pending-update protection.

## Compare stored versions

**History** beside the snapshot arrows opens a timeline for the current source.
It shows one version at a time using the normal renderer and snapshot navigator.
Streams have their own **Run** selector. History becomes available when snapshot
storage is permitted and stored versions exist; source-backed files have separate
snapshot restrictions.

Use the previous/next snapshot arrows to move between versions. **Latest** returns
to the live view. Closing History keeps the selected historical version; changing
source closes History. Filters, grouping, plot settings, export scope, and saved
presentation settings remain where compatible with the selected data.

Use the previous/next day buttons or calendar to browse dates. Calendar dots mark
dates with snapshots; arrow keys move focus between days. Changing the displayed
date does not select another version. Click a point or use the snapshot arrows to
select one. Exact UTC timestamps appear on hover and in the selected-version
control. Use the arrows for snapshots too close together to distinguish visually.

History uses **UTC**, independent of the browser timezone. Each timeline runs from
UTC midnight to the next UTC midnight. The status modal can still display local
times; it is separate from the history date axis.

**Older on this day** replaces the current metadata page. **First page** reloads
its newest metadata. Each page has at most 100 snapshots, with total and displayed
counts shown. These are stored versions, not every published update. Browsing
metadata does not load snapshot bodies; selecting a version does. Retention can
remove a version between those reads. A failed selection keeps historical mode,
disables Export, and asks for an explicit choice.

### Collapse the controls

Collapse the ordinary bottom bar to leave a small restore button. Its preference
uses a small dashboard/path-scoped `sessionStorage` entry; denied storage still
permits page-local operation. Opening History expands the controls. History and
expanded view are mutually exclusive and preserve the underlying selection when
switching. The current UI has no separate List mode, pin control, or captured-Latest
mode: choosing Latest returns to live data.

### Bounded latest-response endpoint

The server still exposes `/compare/latest` for a bounded, coherent response of the
current published content. The browser's History controls do not use it. This
endpoint neither stores a snapshot nor pins a view on the server. A client must
keep the response itself if it wants a fixed representation. Source status and
checks remain live and are not evaluated or advanced by this read.

`GET /compare/latest?view=<id>` returns a version-1 envelope containing the source,
render revision, the artifact's content timestamp/status, scope and rendered data.
Later success/error status updates do not relabel that content timestamp; restored
artifacts retain their original timestamp. Observation captures include the same
bounded, revision-aware recent evidence used by the live renderer. It
uses existing history/status read permissions and snapshot admission. Two
nonwaiting readers prepare data outside the publication lock, then verify the
revision before returning it. A concurrent publication produces 409 and requires
an explicit retry. There is no automatic capture retry loop.

Limits are deliberately conservative: at most 1,000 table rows, 64 columns,
20,000 inspected nodes, depth 16, 128 Ki characters per string, 1 MiB estimated
input text/plot bytes and 4 MiB response bytes. Wider/nested tables can hit the
node limit sooner. Table counts and the preview scope disclose omitted rows.
Unsupported values, extension dtypes or oversized text/plots are refused before
unbounded conversion; arbitrary repr/materialisation hooks are not invoked.
Non-finite numbers (including NaN and infinities) are refused rather than silently
converted to null. Datetime timezones must be absent, an exact standard-library
`datetime.timezone`, or an exact `zoneinfo.ZoneInfo`; custom timezone callbacks
are never invoked. Generic JSON has a stricter 256-node preparation limit before
rich HTML rendering, including keys and container nodes, because its markup can
be much larger than its input. Validated observation summaries use their existing
bounded renderer instead. The stricter cap also covers structured artifacts with
a different kind hint, since renderer selection can fall back to JSON.
Recent observation context shares the capture budget;
busy history or excessive context requires an explicit retry or smaller input.
Published objects should not be mutated in place after publication; the revision
check detects store publications, not unannounced writes to a caller-owned object.
The 250 ms preparation deadline is cooperative, not cancellation of a renderer.
An active capture can temporarily retain its published source reference while
preparing the detached bounded result; there is no retained background source.

`GET /history/month?view=<id>&month=YYYY-MM` returns UTC date/count availability
for one month. Day pages reuse `/history/navigation` with UTC `start`/`end` and
its existing ordering, permissions and scan limits: two readers, 10,000 directory
entries, 8 MiB metadata, 32 KiB per file and a cooperative 500 ms filesystem
budget. Month/day requests scan metadata on demand; no idle index or unbounded
history cache is added. The browser retains one month and one page, with one
active metadata job and one replaceable intent. Large/corrupt histories can be
refused explicitly instead of showing incomplete ordering as complete.
