# Server-side checks

Checks evaluate bounded, already-published scalar evidence on the plotsrv server.
They work without a browser or snapshot storage and add no decorator arguments.
Configure them in the **server's** selected config file, then restart that server:

```yaml
checks-settings:
  enabled: true
  rules:
    - id: import-errors
      name: Import errors
      source: etl:metrics
      kind: state
      path: [errors]
      op: gt
      value: 0
      severity: critical

    - id: sampled-missing-net
      name: Missing net values in the observed sample
      source: etl:orders
      kind: state
      input: observation
      path: [net]
      metric: missing_fraction
      scope: base_sample
      op: gt
      value: 0.1
      severity: warning

    - id: failed-request
      source: web:events
      kind: event
      path: [status]
      op: ge
      value: 500
      severity: noteworthy
```

The first rule expects published JSON such as `{"errors": 3}`; the second expects
an `observe=True` DataFrame summary containing the `net` field. The third expects
accepted structured stream records such as `{"status": 503}`. Event paths address
the **accepted record**, not a table, HTTP profile aggregate or rendered text.
A text line that merely contains `status=503` is not automatically a structured
field for these checks.

For example, the existing Python API can publish a supplied metric dictionary:

```python
import plotsrv as ps

ps.publish_view(
    {"errors": error_count},
    view_id="etl:metrics",
    kind="artifact",
    artifact_kind="json",
)
```

Checks do not register new views or expand a locked catalogue. An unseen source
remains unknown until admitted live data arrives. Config errors fail setup clearly;
published records cannot supply rules, change severity or enable notifications.

## Configuration and scalar meaning

Required rule fields are `id`, `source`, `kind`, `path`, `op` and `value`. `name`
defaults to the ID; severity defaults to `warning`; `enabled` defaults to true.
The global enabled flag disables evaluation without bypassing config validation.
The ordinary default is `input: json`. Rules are fixed for the server generation,
with the normal config file/instance selection rules.

- IDs are unique. Logical source IDs are preserved exactly; filesystem paths have
  no special meaning. At most 64 rules and eight rules per source are accepted.
- Paths are lists of at most eight literal string keys or nonnegative integer
  indexes, for example `["a.b", 0, "/value"]`. `[]` selects the root scalar.
  There are no wildcards, dotted-path parsing, attribute access or expressions.
- Operators are `eq`, `ne`, `lt`, `le`, `gt`, `ge`. Threshold operators require
  numbers. Equality/inequality also support exact strings and booleans. Numeric
  strings and booleans do not become numbers; even `ne` on a wrong type is unknown.
- Numeric thresholds/values must be finite. Integers up to 1,024 bits retain exact
  comparison, including against finite floats and observation rational means.
  Large integers and rational results use type-tagged JSON in status/events to
  avoid browser rounding. Strings are limited to 256 UTF-8 bytes; oversized values
  are unavailable rather than silently truncated into a comparison.
- Null, missing, unsupported, nonfinite or uninspected values are unknown, not OK.
  Tables/plots are unavailable for scalar checks; publish a precomputed metric
  instead of expecting implicit aggregation.
- Optional `unit` is a declared unit for plain JSON scalar rules, with no conversion
  or lookup of a neighbouring unit field. Observation rules require an exact
  matching unit in their typed evidence. Most observation numbers have no unit;
  omit `unit` for these and for shape/length metadata. Incompatible units are unknown.
- Optional `notify` is reserved for notification destination references. Only an
  empty list is currently accepted: nonempty unresolved references fail setup.
  This slice sends no webhooks and adds no notification destination schema.

The existing JSON display document is also supported for bounded numeric/bool
leaves, including normal local Python publication. Selection follows only the
requested path, through at most 32 children per level. It never reparses
`raw_text`/`pretty_text`, reconstructs containers or scans a full tree. Truncated
parents, ambiguous paths and unsupported leaf types are unknown. Legacy display
string leaves normalize whitespace, so they cannot establish exact string checks;
use a supplied boolean/precomputed metric, an explicitly scoped observation scalar,
or native JSON evidence when exact string equality matters.

## Observation evidence

Use `input: observation` with an explicit `scope` and `metric`. `path` selects an
observation field by its nested literal path, or a DataFrame column name; `[]`
selects a single array/sequence field. Ambiguous names are unavailable. Field names
are resolved in bounded captured metadata; checks never read the original object.

Supported field metrics are `value`, `mean`, `min`, `max`, `missing_fraction`,
`missing_count` and `inspected`. Scopes are `supplied_value`, `base_sample` or
`complete_small_inspection`, and must match the received field. Statistics with
no inspected values are unavailable; `inspected` itself can report a known zero.
For cheap whole-source metadata use `scope: source_metadata`, `path: []`, and
`metric: length`, `rows` or `columns`, where that metadata is available.

`selection_path` defaults to `[]`. Set it explicitly when the publisher selects a
nested branch with `ObservationOptions(path=...)`; a different/unknown selected
branch invalidates the check. Summary/recipe version 1 is supported. Missing
selection provenance, changed scope, absent metrics and incompatible units remain
unknown. Ordinary JSON rules cannot bypass the explicit observation scope.

Sample checks describe their **captured sample metric**, with inspected and
uninspected counts carried into check state/events. They do not validate every row,
prove full-data quality or perform a statistical drift test. A configured
`base_sample` rule becomes unavailable if the publisher switches to complete-small
inspection. Configure the intended evidence contract, rather than silently merging
those meanings.

## State, occurrences and recovery

Evaluation state (`ok`, `triggered`, `unknown`, `disabled`) is independent of severity
(`noteworthy`, `warning`, `critical`). The first accepted state observation becomes
a baseline without a check event, even if triggered. An initial failure is still
visible in latest state. An unknown initial result is not a successful baseline.

Subsequent state changes produce `triggered`, `unavailable`, `available` or
`recovered` events. Repeated unchanged failures do not create new events. Recovery
requires a previously known triggered state followed by known OK evidence, without
an intervening coverage gap. Returning from unknown to OK is `available`, never a
fabricated recovery. Separate threshold rules are independent; there is no
escalation engine or relative-change calculation.

Event rules produce a `match` occurrence for each matching eligible accepted
record. Their latest evaluation is OK/unknown, not a persistent failure waiting
for recovery. Source receipt time, session, batch ID/sequence/position and server
record revision identify the accepted event. A bounded `timestamp` or
`event.source_timestamp`, when present, is retained separately as publisher-supplied
source time. Observation capture time is also separate from server receive time.

Evaluation occurs after stream retry deduplication. Raw stream retention can evict
records immediately without losing already-detached check evidence. Retried batches,
heartbeats, historical restoration and snapshot/Compare browsing do not evaluate
live rules or manufacture recovery. Restart creates a new check generation with
unknown states and no startup events; the next live state establishes a new baseline.
Checks leave freshness, stream lifecycle and snapshot policy unchanged.

## Resource limits and coverage gaps

With no enabled rules there is no check worker. Enabled checks use one process-wide
worker with an indefinite condition wait at rest. Capture hooks retain only detached
bounded scalars and receipt metadata, never an original object, raw stream row,
closure over source data or deferred parsing task. Sources are selected synchronously
through exact builtin containers; arbitrary protocols/callbacks are not invoked.

Admission is nonblocking on queue contention. Across all checks it permits at most
512 scalar projections per second with a burst of 256. Scalar selection shares a
soft CPU allowance of 20 ms per second, burst 4 ms, across sources. Each hook also
has a soft 2 ms thread-CPU budget and 4,096 inspection units. These are checked
between bounded operations, not cancellation or wall-clock guarantees. Scheduling,
GC, bookkeeping and one final operation can overrun a budget. Worker comparison,
event encoding, existing publication and browser work have separate bounded costs.

Dictionary backing storage is checked before iteration (at most 16 KiB per visited
dict); only the first 32 keys can be considered. Sparse/huge maps, custom containers
and out-of-budget paths degrade without a scan. This deliberate limitation may
require publishing a smaller metric dictionary or selecting an observation field.

The queue allows at most 256 jobs and reserves 8 KiB per job under a 256 KiB shared
budget, **including the in-flight job**; the byte budget therefore admits at most
32 jobs. Pending state updates for the same source coalesce. Event jobs never
coalesce. Queue/rate/CPU/work/lock overload records per-rule coverage loss; a later
dropped state prevents older in-flight work from declaring the latest value OK.
Counters are bounded, best effort under concurrency, and are not an audit ledger.
They describe missed rule evaluations, not lost source records; an unexpected
selection failure can conservatively invalidate the remaining batch's coverage.
A subsequent valid state can restore availability, but cannot claim recovery across
unknown coverage. Delivery is not guaranteed for every call/event.

Recent check history is ordered and capped at 256 events and 256 KiB of encoded
payloads, independent of snapshot storage. Latest state is bounded by configured
rules. Status/event bodies include only the selected scalar, threshold, scope and
receipt identifiers; names and values may still be sensitive. These limits are not
whole-process RSS limits. Shutdown abandons pending work, waits finitely when
requested and never overlaps an unfinished worker with its replacement.

## Read API and updates

`GET /checks?view=etl:metrics&after=0&generation=...` returns version 1 latest states,
a bounded event history, current `cursor`, `oldest_cursor`, `generation` and
`history_gap`. Omit `view` for all configured checks. `after` is exclusive; omitted
entries caused by retention or an old generation are explicitly reported. A history
gap does not mean there were zero matches. IDs combine generation and monotonic
cursor; seen-state consumers must retain generation as well as cursor.

The existing `/status` response includes current checks and a cursor, **without
retransmitting event history**. Both endpoints follow `status_local_only`; they
have the same dashboard read-access policy as status, not publisher-key-only access.
No credentials or whole records are included in check diagnostics.

Existing SSE carries coalesced check-status notices, at most four per second per
active source, with one trailing notice after a burst. There is no idle polling or
per-browser worker. A slow status fetch retains one pending refresh; check notices
do not replace pending data updates or reload a filtered/historical presentation.
The status-modal check display, attention marker and notification delivery are
separate later slices.
