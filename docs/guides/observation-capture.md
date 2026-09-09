# Internal observation capture

This is the tested capture foundation for automatic observations. It does **not**
yet add `observe=True` to public publishing, generate summaries, send observations
to a server, or add a browser profile. Ordinary publishing and file watching keep
their existing behaviour.

The internal `plotsrv.observations` modules reserve capacity, inspect a bounded
part of a supported eager object, and retain only an immutable JSON byte envelope.
They add no dependencies, background threads, timers, network requests or idle
polling. Optional adapters use libraries already loaded by the application.

## Admission and ownership

Initialize `get_capture_engine()` during publisher setup, outside the measured
application boundary. It reads configuration once and initializes the adapters.
Use that one engine throughout a process; constructing separate engines bypasses
the aggregate limit and is intended for isolated tests.

`engine.submit(view_id, source, options)` returns a fixed outcome such as
`accepted`, `process_cadence`, `view_cadence`, `view_pending`, `overloaded`, `busy`
or `closed`. Rejected admission does not inspect the source. At most one capture
runs at a time. The call uses a nonblocking lock only around bounded bookkeeping;
sampling happens outside that lock. Runtime capture errors produce bounded reason
codes, without exception text, source representations or logging callbacks.
Application exceptions such as `KeyboardInterrupt` propagate after cleanup.

Queue reservations cover synchronous capture, queued bytes **and in-flight work**.
A future consumer calls `take()` and then `finish(work.token)` after processing,
releasing its work reference at the same time. A contended `finish` returns false;
the consumer must acknowledge again before taking more work. Dequeuing alone does
not make capacity available. There is no source object, native buffer, source-bound
callback, traceback or closure in a queued envelope.

An update for a view with outstanding work is skipped **before recapturing**.
This mailbox preserves the accepted sample instead of repeatedly copying newer
objects under congestion. It is not an event history or a latest-state guarantee.
The public observation integration must disclose gaps and must consume this
mailbox directly, without putting source objects into the existing publish queue.

`close()` abandons pending work. An active capture discards its result on return;
its reservation remains until then. In-flight leases remain charged until the
consumer acknowledges them. `reopen()` succeeds only after all reservations have
been released, so restart cannot overlap an abandoned capture. Close performs no
blocking drain. If close encounters a busy lock, its holder releases queued
payloads on exit; cleanup needs no later submission or idle polling. After a fork,
`get_capture_engine()` creates a fresh process-local engine and lock; direct
inherited engines reject work with `forked_instance`.
There is no autonomous worker or retry loop in this foundation.

## Default budgets

Internal settings live under `publish-settings.observe`. They have no effect on
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
| Scalar/index getter attempts (`max_elements`) | 1,024 | 1–4,096 |
| Typed value allocations (`max_nodes`) | 1,024 | 1–4,096 |
| Nested container depth (`max_depth`) | 6 | 1–8 |
| Variable value bytes (`max_value_bytes`) | 256 | 16–1,024 |
| Distinct retained string prefixes (`max_categories`) | 16 | 1–64 |
| Charged capture allocation (`max_capture_bytes`) | 256 KiB | 4 KiB–1 MiB |
| Encoded envelope (`max_output_bytes`) | 64 KiB | 4–256 KiB |
| Additional exploratory positions per sequence/column (`exploratory_rows`) | 4 | 0–16 |
| Dimensions / pandas blocks / Polars chunks | 8 / 32 / 8 | 1–8 / 1–32 / 1–8 |
| Soft capture deadline (`capture_ms`) | 10 ms | 0.1–50 ms |
| Average process / minimum view interval | 0.25 s / 1 s | 0.001–3,600 s / 0.01–3,600 s |
| Reservations (`max_pending`) | 8 | 1–32 |
| Reserved output bytes (`max_pending_bytes`) | 512 KiB | 4 KiB–4 MiB |
| Remembered view identities (`max_view_ids`) | 128 | 1–256 |

The dimension/block/chunk keys are `max_dimensions`, `max_blocks`, and
`max_chunks`; interval keys are `process_interval_s` and `view_interval_s`.
All budgets apply together: 32 rows × 16 fields is not a promise to capture all
512 cells. Nested cells, masks, index reads and failed typed getter attempts spend
the same aggregate allowance. Categories are bounded per table column, or across
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

The capture byte charge is a conservative allowance for working evidence, not an
allocator or whole-process RSS limit. String prefixes are sliced before encoding;
structural limits also bound serialization and its temporary copies. If the
encoded envelope exceeds its output allowance, samples and metadata are discarded
and `output_byte_budget` is recorded. The source is never converted a second time.
The elapsed deadline is checked between bounded operations; it cannot interrupt a
native call, preempt a page fault, or guarantee wall-clock latency. Serialization
and bookkeeping still have bounded work after a deadline. Raising limits or
capture frequency increases application CPU/memory cost.

## Supported storage and sample meaning

Only exact eager builtin/library types are eligible. Subclasses, unknown objects,
generators, lazy frames, foreign array owners and custom extension storage get
bounded omission reasons. There is no `repr`, protocol conversion, arbitrary
property traversal, user callback, device transfer or lazy computation fallback.

| Source | Bounded capture |
| --- | --- |
| `dict` | First bounded insertion-order fields; exact builtin string/integer keys; nested copies with cycle/depth guards |
| `list`, `tuple` | Deterministic distributed positions, recursively bounded values |
| Builtin scalar metrics | Null, bool, integer, float and bounded strings; typed nonfinite and large-integer values |
| Exact NumPy array | Logical positional indexing, including ordinary negative/noncontiguous/zero strides; no `ravel`, whole copy or proportional index vector |
| Exact pandas DataFrame | Bounded block inspection and positional reads from NumPy-backed columns; nullable integer/float/bool, Python-backed StringArray, datetime/timedelta array storage |
| Exact Polars DataFrame | Shape and positional numeric columns with bounded chunk count; other values remain explicitly missing-or-unsupported |

NumPy fixed-width strings whose cells exceed the value allowance are omitted
**before indexing**. Structured, complex, extended precision and unsafe foreign
storage are omitted. Standard ndarray/bytes/bytearray ownership chains are
supported; memmaps and foreign buffer wrappers are deliberately excluded.

Pandas uses a checked `BlockManager` layout and ordinary RangeIndex/NumPy-backed
Index axes. It avoids `iloc` bookkeeping that can build full-width block maps,
index hashing, full column/dtype lists, `memory_usage`, deep copies and whole-frame
conversions. Highly fragmented blocks, large irregular placements, custom indexes,
categorical/Arrow/custom extension storage are omitted. These restrictions also
apply to an otherwise small frame with just a few huge cells.

Polars numeric typed getters avoid materializing strings, lists, Object values or
nested dtype descriptions. Column names are not copied: they can themselves be
arbitrarily large. Choose columns by position. A null before any numeric type has
been established remains `missing_or_unsupported`, not an invented null or zero.
The private pandas/Polars layouts are checked and fail closed if incompatible;
the current tests exercise pandas 2.3.3, NumPy 2.3.5 and Polars 1.44.1. Broader
library-version/storage support requires the same safety checks, not a general
conversion fallback.

For positional sampling, with length `n` and `k = min(n, max_rows)`, positions are
`floor(i * (n - 1) / (k - 1))`; a single position uses index zero. These are
reproducible, evenly spaced positions including the ends, **not unbiased random
samples**. Mapping fields use insertion order. When the base has no usable values,
a small additional set of disjoint distributed positions may find non-null data.
Those probes live in `exploratory`, separate from `base_sample`, and must not enter
the base sample's statistical denominator. Partial evidence and omitted fields
are reported through coverage and reasons; a sample cannot establish that failures
or missing values do not exist elsewhere.

The envelope is internal schema version 1, with an explicit caller-supplied view
ID, known source-type label, capture time, cheap metadata, samples, coverage,
consistency and reasons. Its version is not a new transport protocol. Filesystem
paths and Python object addresses do not become automatic source identities.

## Selection, examples and concurrent mutation

Internal `CaptureOptions(fields=(...), path=(...), include_examples=False)` narrows
capture. Choose either field names or positions in one selection. Integer table fields are positions; pandas also matches exact names
among the bounded prefix of inspected columns. Dictionary field/path lookup
inspects at most `max_fields` entries, without invoking custom key equality.
A selected name/path outside that prefix is not evidence that it is absent.
Polars supports positional fields only. Field selection on arrays, sequences or
scalars is unsupported and fails closed without sampling; it is never silently
ignored. Use a nested path before inspecting an
unrelated large branch. Truncated strings are labelled and are not exact categories.

An envelope contains bounded **private working values**, including strings, for
the future local summary worker. `include_examples` defaults to false and is the
permission to export raw examples in that later integration; it does not mean
numeric/category evidence is never copied inside the publisher. Binary contents
are copied only when examples are enabled. These envelopes must not be passed
directly to HTTP publishing, logs or diagnostics. Nothing sends them in this
foundation. The summary/public API integration must enforce the examples flag at
its export boundary. Field names, categories and summaries can contain secrets;
bounds are not anonymisation or secret detection.

The capture never mutates an input and owns its resulting bytes. Mutating or
releasing a source after return cannot change a retained envelope. It detects
obvious length, manager, block-storage, shape, dtype and frame replacement changes
and discards inconsistent samples. It does not promise an atomic snapshot during
concurrent in-place writes of the same shape. Keep native memory/storage stable
for the short synchronous call; concurrent unsafe native resize/free is outside
the supported ownership contract. No source lock is held across later worker or
network activity.

## Reproducing the checks

```bash
python -m pytest -q tests/test_observation_capture.py tests/test_observation_admission.py
python -m pytest -q -s tests/benchmarks/test_bench_observation_capture.py \
  --benchmark-columns=min,median,max
```

The benchmark initializes sources and the engine before timing, measures accepted
`submit` calls with cadence reset between trials, and separately measures rejected
calls. Memory trials report Python traced peak, retained bytes and post-drain
bytes; they exclude input allocation and are not RSS/native-allocation measures.
Tracing itself changes execution time and can cause earlier soft-deadline exits.
See [Testing & Benchmarks](../about/testing-and-benchmarks.md) for a recorded run.
