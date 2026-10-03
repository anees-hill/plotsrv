# Observation reference

For a working introduction, see [Observe function output](../guides/observe-function-output.md).

Use `observe=True` to publish a compact summary of a pipeline result while returning
that same object unchanged:

```python
import plotsrv as ps

@ps.view(observe=True, view_id="etl:orders", label="Orders")
def transform_orders(frame):
    return frame.assign(net=frame["gross"] - frame["discount"])

# Or observe an intermediate result explicitly:
ps.publish_view(frame, observe=True, view_id="etl:intermediate")

# Select a few fields, or one nested branch, before capture:
ps.publish_view(
    metrics,
    observe=ps.ObservationOptions(path=("import",), fields=("rows", "seconds")),
    view_id="etl:metrics",
)

# Optional at a script boundary, never inside the measured hot loop:
finished = ps.flush_views(timeout=0.5)
print(ps.get_observation_stats())
```

Observation is opt-in. Ordinary publishing keeps its existing defaults and accepts
its existing reports/plots/tables. Observation always summarizes and delivers in
one background consumer, even when ordinary async publishing is disabled.
`observe=True, async_=False` is a setup error. Observed functions execute once;
sync functions stay sync, async functions are awaited once, return identity and
signature metadata remain intact, and original exceptions/cancellation propagate.
Observation decorators require the default `on_error="raise"` and decorate
functions, not classes. There is no tracing of locals or automatic error report.

Only admission and bounded detached capture run in the caller. Summaries, server
startup and HTTP run in the consumer. Decoration prepares routing and the worker
outside function calls. The first inline `publish_view(..., observe=True)` also
initializes configuration/adapters/routing and starts the worker; that cold setup
cost is separate from warm capture measurements. Import/setup should happen
outside a latency-sensitive pipeline. One process-wide engine owns the budgets.

Without a configured remote destination, observation starts/uses the attached
local server in the background; it does not restore persisted history on implicit
startup. Start a local server explicitly first if restoration is wanted. A remote
`destination="https://dashboard.example/team/"`, host/port or configured
`publisher-settings.destination` uses the existing HTTP(S) transport, bearer
credentials and catalogue admission. Decorators use host/port or the configured
destination. There is no shared-filesystem assumption or automatic remote fallback.
Remote servers must advertise `observation-v1`; older servers reject observation
without receiving a raw-object replacement payload. The transport protocol stays
at version 1; the summary and recipe have their own version 1.

The server keeps the current bounded summary as a JSON artifact using the existing
logical view ID, including catalogue-locked admission. Its observation overview
shows known shape, captured coverage, scoped field evidence and compatible changes.
Suggested presentations use the normal table/plot controls and browser-local My
views. Ordinary custom scalars, dictionaries, tables and plots retain their existing
renderers and source descriptions; they do not need observation to be useful.

## Observation views and recent changes

The default Fields / structure table shows supplied metrics, inspected and
uninspected counts, missingness and available observed ranges/means. The overview
distinguishes cheap whole-source shape from sample findings. An all-null sample is
useful missingness evidence; an unsupported/uninspected field has no missingness
denominator. Neither creates a collection of empty charts.

Choose **Suggested views** for field overview, observed missingness, up to three
observed distributions, or up to three compatible scalar histories when available.
These are ordinary transient ViewSpecs: change filters/columns/plot settings, then
**Save view** to keep that presentation in **My views** on this browser. Saving does
not publish a new source or store observation data in browser settings. Saved
distributions and scalar plots bind to the captured field's identity, selected
branch, schema and units. If that meaning disappears, the presentation pauses
instead of following a different field. Explicit filters and plot inspection keep
the existing smart-update protections; the default overview can update live.

Distributions use at most eight captured bins/categories for at most eight fields;
category prefixes can combine distinct original values. Counts describe retained
observed evidence, not whole-source frequencies. Examples appear only when
explicitly allowed and retained, with at most 16 displayed values. Space is reserved
for exploratory probes; those remain separate from base statistics. Capture details
disclose limits, omissions and provenance without embedding excluded raw samples.

The server retains compact recent evidence, with fixed limits of 16 entries and
256 KiB per source, 128 sources and 4 MiB of encoded evidence overall. Each entry is
at most 24 KiB; oversized comparison evidence is omitted, not treated as zero.
Recent entries exclude examples, categories and histograms. Limits cover encoded
bytes, not total Python heap or the separate existing current-artifact/render caches.
There are no new background threads, timers, polling, network requests or source
reads. History receipt is best effort; lock contention drops evidence and a missed
revision prevents comparison across that gap.

This recent window belongs to the current server process and can be evicted earlier
under shared memory pressure. Optional disk persistence uses existing
`storage-settings` and snapshot retention/admission, with the bounded exported
summary as its payload. Stored snapshots are fixed historical evidence; browsing
does not capture/publish again or load a prior baseline automatically. A missing
snapshot stays historical and requires an explicit return to Latest.

Changes compare only compatible publisher sessions, selected source scope, summary
recipe, sampling policy, captured schema and metric identity/units. Older summaries
without selection provenance remain readable but cannot establish compatible
changes. Known shape/schema changes are descriptive. Supplied numeric metrics get
simple deltas; observed mean/missingness changes retain their sample labels and are
**not statistical drift tests**. The comparison window stops at an incompatible,
repeated or out-of-order capture. Scalar plots show irregular server receipt times
without interpolation, zero filling or summing repeated cumulative values. Large
integers/rationals remain exact text when the shared plot cannot represent them
without loss. Publisher skipped/dropped/coalesced/failed diagnostics are labelled
process-wide and best effort, not counts of missing runs for this source.

Deliberately deferred: distribution-to-distribution drift tests, correlations,
automatic business reconciliation, persisted-baseline joins and complete-run
ledgers. Supply domain-specific metrics yourself and publish them normally or
observe the bounded metric dictionary.

## Default budgets

Capture settings live under `publish-settings.observe`. They have no effect on
ordinary publication. For example:

```yaml
publish-settings:
  observe:
    max_rows: 32
    max_fields: 16
    max_value_bytes: 256
    process_interval_s: 0.25
    view_interval_s: 1.0
```

| Budget | Default | Valid range |
| --- | ---: | ---: |
| Base positions per sequence/column (`max_rows`) | 32 | 1–128 |
| Fields inspected (`max_fields`) | 16 | 1–32 |
| Element reads + placement scan allowance (`max_elements`) | 1,024 | 1–4,096 |
| Typed value allocations (`max_nodes`) | 1,024 | 1–4,096 |
| Nested container depth (`max_depth`) | 6 | 1–8 |
| Variable value bytes (`max_value_bytes`) | 256 | 16–1,024 |
| Distinct retained string prefixes (`max_categories`) | 16 | 1–64 |
| Charged capture work/inspection (`max_capture_bytes`) | 256 KiB | 4 KiB–1 MiB |
| Encoded envelope (`max_output_bytes`) | 64 KiB | 4–256 KiB |
| Additional exploratory positions per sequence/column (`exploratory_rows`) | 4 | 0–16 |
| Dimensions / pandas blocks | 8 / 32 | 1–8 / 1–32 |
| Soft capture deadline (`capture_ms`) | 10 ms | 0.1–50 ms |
| Average process / minimum view interval | 0.25 s / 1 s | 0.001–3,600 s / 0.01–3,600 s |
| Reservations (`max_pending`) | 8 | 1–32 |
| Reserved output bytes (`max_pending_bytes`) | 512 KiB | 4 KiB–4 MiB |
| Remembered view identities (`max_view_ids`) | 128 | 1–256 |

The dimension/block keys are `max_dimensions` and `max_blocks`; interval keys
are `process_interval_s` and `view_interval_s`.
All budgets apply together: 32 rows × 16 fields is not a promise to capture all
512 cells. Schema is captured before table values. Each supported selected field
gets an equal share of the remaining read/node/byte allowance; unused capacity is
available to later fields. Large nested cells cannot consume later fields' shares.
Nested cells, null masks and index reads spend the same aggregate allowance. Categories are bounded per table column, or across
a builtin object/array. Fields and depth also bound traversal overhead.

Booleans, infinities, unknown keys and out-of-range numbers are invalid settings.
Validation raises a configuration error during setup without echoing values;
it never replaces stricter valid limits with larger defaults when another
setting is invalid. Output reservations must fit at least one maximum
envelope. An identity whose cadence has not expired is not evicted to admit a
new identity; many different IDs cannot bypass the process cadence or grow a cache.

Process cadence uses a token bucket: at most four captures can start together
(fewer if queue count/byte limits require it), refilling at one token per
`process_interval_s`. Waiting view IDs get bounded retry priority so a stable
call order cannot always select only the first view. A caller yields once to an
absent waiter before using an available token; an inactive view cannot permanently
block active views. There are no queued sources or timer-driven retries. View
cadence still enforces a minimum gap for each accepted identity.

The capture byte charge is a conservative combined allowance for working evidence
and inspected dictionary backing storage, not actual copied bytes, an allocator
limit, or whole-process RSS. CPython dictionaries with many deleted slots can take
a long time to advance even a single iterator entry. Before iteration, the entire
backing table size is charged using constant-time `dict.__sizeof__`, including for
nested dictionaries and path lookup. Oversized tables are omitted with
`mapping_storage_budget`; other Python implementations omit dictionary inspection.
`elements_read` counts explicit getter/iterator attempts, including metadata and
masks; `placement_scan_allowance` records the conservative native placement scan
reservation. Their sum, `element_units_charged`, is limited by `max_elements`.
None is an exact native CPU or dictionary-slot count. String prefixes are sliced before encoding;
structural limits also bound serialization and its temporary copies. If the
encoded envelope exceeds its output allowance, samples and metadata are discarded
and `output_byte_budget` is recorded. The source is never converted a second time.
The elapsed deadline is checked between bounded operations; it cannot interrupt a
native call, preempt a page fault or garbage collection, or guarantee wall-clock
latency. Serialization
and bookkeeping still have bounded work after a deadline. Raising limits or
capture frequency increases application CPU/memory cost.

## Supported storage and sample meaning

Only exact eager builtin/library types are eligible. Subclasses, unknown objects,
generators, lazy frames, foreign array owners and custom extension storage get
bounded omission reasons. There is no `repr`, protocol conversion, arbitrary
property traversal, user callback, device transfer or lazy computation fallback.

| Source | Bounded capture |
| --- | --- |
| CPython `dict` | Bounded backing storage checked before iteration; insertion-order fields with exact builtin string/integer keys; cycle/depth guards |
| `list`, `tuple` | Deterministic distributed positions, recursively bounded values |
| Builtin scalar metrics | Null, bool, integer, float and bounded strings; typed nonfinite and large-integer values |
| Exact NumPy array | Logical positional indexing, including ordinary negative/noncontiguous/zero strides; no `ravel`, whole copy or proportional index vector |
| Exact pandas DataFrame | Bounded block inspection and positional reads from NumPy-backed columns; nullable integer/float/bool, Python-backed StringArray, datetime/timedelta array storage |
| Exact Polars DataFrame | Type label and `polars_capture_unavailable`; no native access, shape lookup or materialization |

NumPy fixed-width strings whose cells exceed the value allowance are omitted
**before indexing**. Structured, complex, extended precision and unsafe foreign
storage are omitted. Standard ndarray/bytes/bytearray ownership chains are
supported; memmaps and foreign buffer wrappers are deliberately excluded.

Pandas uses a checked `BlockManager` layout with RangeIndex, NumPy-backed Index,
DatetimeIndex, TimedeltaIndex and MultiIndex axes. MultiIndex length comes from
existing codes, without expanding or hashing levels; MultiIndex column names are
omitted and columns remain accessible by position. Only exact supported blocks
are read. Datetime/timedelta blocks work alongside numeric fields; an unsupported
column does not invalidate unrelated columns. Field metadata reports cheap dtype
kind/item size, nullable storage and temporal units. Timezone-aware column ticks
are identified as UTC storage, without invoking arbitrary timezone formatting.

Pandas avoids `iloc` bookkeeping that can build full-width block maps, index
hashing, full column/dtype lists, `memory_usage`, deep copies and whole-frame
conversions. Even a placement's `indexer` accessor can scan its full array. Existing validated column maps can be used directly. Otherwise each block's
placement is accessed only after charging the whole frame width against the
remaining element and byte allowances, then reused within the synchronous call.
This bounds even a cold placement's potential scan while supporting modest-width
frames without creating full maps. If that width cannot fit, the frame retains
bounded labels/shape and `placement_budget`, without reading placements.
Excessive blocks, unknown indexes and categorical,
Arrow or custom extensions remain restricted. A few rows do not exempt huge cells
from these checks.

Polars capture is currently disabled. The inspected Python/native interface can
materialize an entire scalar column when looking up a series, and even shape
getters can wait on native locks. Guessing types with native getters also exposed
native panic paths during replacement. The adapter therefore touches no native
state; the unused chunk-budget option has been removed. Broader Polars support
requires a demonstrably bounded, nonblocking storage interface, not more fallback
conversions or exception handling.

Private pandas layout checks are only part of the safety argument: every permitted
access must also have bounded cost and safe semantics. Tests exercise pandas 2.3.3,
NumPy 2.3.5 and the disabled Polars 1.44.1 adapter. Library-version/storage changes
require fresh inspection and regression checks.

For positional sampling, with length `n` and `k = min(n, max_rows)`, positions are
`floor(i * (n - 1) / (k - 1))`; a single position uses index zero. These are
reproducible, evenly spaced positions including the ends, **not unbiased random
samples**. Positions are visited endpoints first, then by bisecting interior
spans, so partial captures still cover separated regions. Results are stored in
position order. Mapping fields use insertion order. When the base has no usable
values (including all NaN/NaT), a small set of disjoint probes distributed across
the whole source may find useful data. Probes use the same remaining hard budgets;
there is no extra scan or guarantee of finding a rare value.
Those probes live in `exploratory`, separate from `base_sample`, and must not enter
the base sample's statistical denominator. Partial evidence and omitted fields
are reported through coverage and reasons; a sample cannot establish that failures
or missing values do not exist elsewhere.

The envelope is internal schema version 1, with an explicit caller-supplied view
ID, known source-type label, capture time, cheap metadata, samples, coverage,
consistency and reasons. Its version is not a new transport protocol. Filesystem
paths and Python object addresses do not become automatic source identities.

## Reading summary evidence

Every field has an explicit scope: `supplied_value` for a supplied scalar metric,
`complete_small_inspection` for full positional coverage of a small container,
`base_sample` for sampled positions, or `captured_structure` for structure only.
Full positional coverage is not an atomic snapshot or a claim that omitted cells
were inspected. `values_inspected`, `not_inspected`, missingness denominators,
coverage and omission reasons remain visible. Nulls count as missing; unsupported
values do not. A missing numeric section means no suitable finite values were
captured, not zero. NaN and infinities are represented explicitly.

Numeric ranges, means, nearest-rank quantiles and at most eight histogram bins
use captured finite values only. Distinct counts mean **distinct values observed**,
never full-data cardinality. Integer arithmetic stays exact: large integers use
decimal strings with type tags, and non-integral integer means/bin edges use
rational numerator/denominator tags. Float means are explicitly approximate;
mixed large integers/floats omit calculations that would lose integer precision.
Histogram bins describe observed counts, not predicted whole-data frequencies.
String categories retain at most 16 typed prefixes/counts and explicitly flag
truncation or capping; these are not exact categories when prefixes were shortened.
Exploratory useful-value counts and optional examples are separate from base
statistics and never enlarge their denominator.

Each exported summary includes source type, cheap shape/schema, capture time,
publisher session, selected fields/path, consistency, recipe/version, sampling limits and omission
reasons. Payloads are at most 64 KiB (or the configured lower output limit), and
whole requests at most 80 KiB. Oversize summaries remove examples first and then
bounded sections with an explicit reason; they never serialize the original
object again. Working trees and serialization copies have additional bounded
allocation; the byte budget is not a whole-process RSS cap.

Examples are disabled by default, but scalar values, selected field/path names, category
prefixes and aggregates are still exported and **may contain sensitive data**.
Selection narrows what is captured; this is not redaction or secret detection.
Enable `ObservationOptions(include_examples=True)` only when bounded sampled
values may also leave the publisher. Binary examples obey the same explicit flag.

## Selection, examples and concurrent mutation

Public `ObservationOptions(fields=(...), path=(...), include_examples=False)`
narrows capture (`CaptureOptions` remains an internal alias). Choose either field names or positions in one selection. Integer table fields are positions; pandas also matches exact names
among the bounded prefix of inspected columns. Dictionary field/path lookup
inspects at most `max_fields` entries, without invoking custom key equality.
A selected name/path outside that prefix is not evidence that it is absent;
unmatched selections carry `field_not_inspected_or_absent` or
`path_not_inspected_or_absent`. Field selection on arrays, sequences or
scalars is unsupported and fails closed without sampling; it is never silently
ignored. Use a nested path before inspecting an
unrelated large branch. Truncated strings are labelled and are not exact categories.

An envelope contains bounded **private working values**, including strings, for
the local summary worker. `include_examples` defaults to false and is the
permission to export raw examples; it does not mean
numeric/category evidence is never copied inside the publisher. Binary contents
are copied only when examples are enabled. These envelopes must not be passed
directly to HTTP publishing, logs or diagnostics. The summary builder removes
base samples and exploratory values from the exported document unless examples
are explicitly enabled. Field names, categories and summaries can contain secrets;
bounds are not anonymisation or secret detection.

The capture leaves input values and schema unchanged and owns its resulting
bytes. pandas may warm its small placement cache within the charged inspection
bound; no whole-frame maps or materialized columns are created. Mutating or
releasing a source after return cannot change a retained envelope. It detects
obvious length, manager, block-storage, shape, dtype and frame replacement changes
and discards inconsistent samples. It does not promise an atomic snapshot during
concurrent in-place writes of the same shape. Keep native memory/storage stable
for the short synchronous call; concurrent unsafe native resize/free is outside
the supported ownership contract. No source lock is held across later worker or
network activity.


For queue ownership, shutdown guarantees, and measurement instructions, see [Observation internals](../development/observation-internals.md).
