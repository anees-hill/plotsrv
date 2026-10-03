---
icon: lucide/database
---

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
in UTC, then snapshot ID to break ties. Labels include precise UTC timestamps.

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

**Compare** beside the snapshot arrows opens a compact Timeline/List dock for
one source. It displays one version at a time using the same renderer and
snapshot navigator as the normal bar. Streams keep their separate Run history.
The button becomes available when snapshot storage is admitted and versions
exist; source-backed file views retain their existing separate capability.

Previous selects the immediately older stored version. Next moves toward newer
versions and eventually **Latest**, the current server state. Exact timestamps
and stable snapshot IDs distinguish versions, including timestamp ties. Leaving
Compare retains the selected historical version. Changing source exits Compare.
Filters, grouping, plot presentation, Export scope and My view context remain
with the existing renderer where compatible with the selected data.

Use the date field, previous/next day, or calendar to browse stored metadata.
The calendar marks dates with snapshots using dots. Its arrow keys move between
days; List and previous/next snapshot controls provide precise keyboard access.
Changing the displayed day does not change the viewed version. Empty dates,
unavailable metadata and a selection outside the displayed day are explicit.
The calendar can be tucked away to keep the dock low.

All Compare dates and exact timestamps use **UTC (+00:00)**, independent of the
browser timezone. Day boundaries are UTC midnight to the next calendar midnight.
UTC has no daylight-saving transition: Europe/London's 23-hour/25-hour local days
are deliberately not the displayed day. Repeated local times with different
offsets become distinct UTC times. The existing live status modal can still show
local source times; it is separate from the Compare date axis.

Timeline plots the current metadata page within that fixed UTC day. List shows
the exact timestamp, snapshot ID and kind for every item on the page. **Older on
this day** replaces the current page; **First page** reloads its newest metadata.
Pages contain at most 100 items, with the total count and displayed count shown.
Dense coincident points remain distinct in List. These are stored snapshots,
not a claim that every published update was saved. Metadata browsing never loads
payloads; a body is read only when selected. Retention can remove one between
those reads. A failed selection leaves the previous content where possible,
keeps the requested selection, disables Export, and asks for an explicit choice.

### Floating, pinned and collapsed bars

The normal bar, Timeline and List share the same pin and collapse controls.
**Pin bar to bottom** docks it to the viewport edge; **Unpin bar** returns the
centred floating treatment. **Collapse bar** releases its reserved layout space
and leaves a small bottom-centre restore handle. Restore keeps the current
presentation, date, selection and pin state. Pin/collapse preferences use one
small dashboard/path-scoped `sessionStorage` entry; denied storage still permits
page-local operation. Compare selection itself is not persisted as a server
session. Expanded view and Compare are mutually exclusive; handoff preserves
the underlying selection and presentation.

### Captured Latest and resource limits

Inside Compare, **Latest** explicitly captures one coherent published
representation. Later publications may show **New data available**, but cannot
replace it, even through a forced browser update. Choose Latest again to capture
current data. Exiting Compare keeps that captured representation protected;
**Return to latest** in the normal bar releases it. Reloading the page starts
normal navigation again. The header says **Latest captured** rather than claiming
that this is a stored snapshot. Live source status and checks remain separately
labelled and are never evaluated or advanced by Compare reads.

The browser holds the bounded representation. There is no server pin cache,
background capture, new persistent snapshot, timer-driven refresh or publication
hook. Captured HTML fixes the served source; its own scripts and external assets
retain their existing sandbox behavior. One candidate and the previous rendered representation may coexist while
loading; superseded choices coalesce. Export uses the captured plot/artifact or
table preview, not a later live source download. A table's captured Export option
is labelled **Captured table preview**; filtered Export retains its existing scope.

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
