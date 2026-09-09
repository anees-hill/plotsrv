---
icon: lucide/gauge
---

# Testing and benchmarks

plotsrv has two complementary performance suites.

- The pytest microbenchmarks in `tests/benchmarks/` guard individual renderers
  and routes against small, local regressions.
- `benchmarks/pipeline_profile/` runs reproducible operational scenarios in
  fresh subprocesses. It is for deciding whether a change is genuinely safer
  for an ordinary pipeline or a shared plotsrv server.

The operational suite is deliberately not a runtime dependency. Install its
measurement dependency only when running it from a source checkout:

```bash
uv run --group benchmark python -m benchmarks.pipeline_profile --help
```

## What the operational suite measures

Each run records:

- wall time for the pipeline and server roles
- RSS and, where the OS exposes it, USS
- CPU time and sampled CPU percentage
- read/write I/O counters
- per-publish duration
- HTTP response status, response bytes, and duration for simulated clients
- an idle period after the activity, which is important for detecting a rising
  post-request memory plateau rather than a short-lived allocation spike

The run writes a self-contained directory containing:

| File | Purpose |
|---|---|
| `config.yml` | exact workload, safety settings, and plotsrv configuration |
| `run.json` | environment metadata, process exit codes, and summary metrics |
| `samples.csv` | timestamped server/pipeline/process-tree resource samples |
| `events.csv` | pipeline publish and client-request timing events |
| `logs/` | child-process output if a scenario fails |

The runner refuses to reuse an existing output directory. This prevents an
accidental overwrite of a useful comparison.

## Named release-gate cases

For the checks we expect to repeat across versions, use a named case rather
than retyping a long command:

```bash
uv run --group benchmark python -m benchmarks.pipeline_profile case list
uv run --group benchmark python -m benchmarks.pipeline_profile case run \
  watch.csv.file.large.repeated-clients --profile standard
```

Profiles are `quick`, `standard`, and `soak`.  Watch cases run clients in
separate cycles and write `watch_cycle_summary` into `run.json`.  Its
post-warm-up RSS and USS growth values answer the important question: whether
the server settles between visits, rather than merely recording its peak.

`watch.csv.file.overload` deliberately permits `503` responses. They are
evidence that plotsrv is applying bounded back-pressure, not an unexplained
benchmark error.

Async cases also write `timing.pipeline_work_s`, `timing.async_flush_s`, and
queue coalescing/rejection counters. Compare the first value to assess caller
interference; include the flush time when assessing eventual delivery.

## Optional ptop history

The benchmark harness does not depend on ptop. If ptop is installed, the
project-local `ptop.toml` provides short recipe aliases that add process-tree
history, Git/machine provenance and result JSONs:

```bash
ptop recipe run watch-file-large-cycles
ptop recipe run watch-file-large-cycles --set cycles=10
ptop trend --case watch.csv.file.large.repeated-clients
```

Use ptop comparisons only between runs with the same case fingerprint and
machine identity:

```bash
ptop compare 41 52 --require-comparable
```

The local `ptop.toml`, release manifest, `.ptop/` database, and manifest
outputs are ignored by git.

## Core scenarios

Run a no-plotsrv baseline first, then match it with a publishing mode:

```bash
uv run --group benchmark python -m benchmarks.pipeline_profile run \
  --scenario baseline \
  --table 25000x12 --json-items 2000 --plots 1 \
  --cpu-s 0.5 --iterations 3 \
  --output benchmark-results/baseline

uv run --group benchmark python -m benchmarks.pipeline_profile run \
  --scenario remote \
  --table 25000x12 --json-items 2000 --plots 1 \
  --cpu-s 0.5 --iterations 3 \
  --output benchmark-results/remote

uv run --group benchmark python -m benchmarks.pipeline_profile compare \
  --baseline benchmark-results/baseline \
  --candidate benchmark-results/remote
```

`attached` runs the server in the pipeline process. `remote` starts an
independent plotsrv server subprocess and publishes over HTTP, which separates
pipeline overhead from server RSS.

For the v0.5.0 watched-file question, use a file-backed CSV and concurrent
direct requests to the same table endpoint:

```bash
uv run --group benchmark python -m benchmarks.pipeline_profile run \
  --scenario watch-clients \
  --watch-csv 500000x20 \
  --watch-materialization file \
  --watch-max-mb 64 \
  --table-limit 100000 \
  --clients 10 --requests-per-client 3 \
  --idle-s 20 --max-rss-mb 1800 \
  --output benchmark-results/watch-v0-5-0
```

This intentionally reads and consumes the complete JSON response, as a browser
would. It is not a browser-rendering benchmark; it isolates the server request
path and makes memory growth attributable to plotsrv rather than a browser.

## Designing a representative case

The benchmark is configurable rather than hard-coded around one synthetic
table. Repeat `--table` or `--json-items` to model several outputs, and add
`--html-kb`, `--text-kb`, `--log-kb`, `--temporary-memory-mb`, `--cpu-s`,
`--iterations`, and `--publish-every` to approximate a real workflow.

Start with the smallest workload that resembles the pipeline you care about.
Increase one dimension at a time, retain each output directory, and compare
like with like. A performance claim should name the workload and configuration
used, not just a single machine-level RSS number.

## Safety watchdog

`--max-rss-mb` caps aggregate RSS across every benchmark child and its
descendants. If the ceiling is crossed, the runner terminates the complete
benchmark process tree, leaves samples and logs behind, and marks `run.json`
as `watchdog_terminated`. It is a safety guard for a development machine, not a
substitute for plotsrv's own runtime limits.

## Detached capture measurements

The [internal observation capture foundation](../guides/observation-capture.md)
has reproducible admission/capture microbenchmarks:

```bash
python -m pytest -q -s tests/benchmarks/test_bench_observation_capture.py \
  --benchmark-columns=min,median,max
```

A Linux/Python 3.13 development-machine run after the capture safety fixes on
2026-09-09 passed all 28 benchmark cases. With default budgets, 100 measured
rounds and five warmup rounds for accepted calls:

| Input | Median synchronous submit | Maximum in these trials | Traced peak | Traced retained | After drain |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rejected, closed mailbox | 3.24 µs | 34.59 µs | 392 B | 240 B | 32 B |
| Three scalar metrics | 91.87 µs | 499.71 µs | 7,445 B | 4,837 B | 332 B |
| NumPy broadcast array, 10 billion logical elements | 564.96 µs | 1.557 ms | 24,889 B | 19,737 B | 1,277 B |
| pandas frame, 100,000 rows × 8 float columns | 2.314 ms | 2.802 ms | 48,437 B | 26,319 B | 737 B |
| Dictionary with one 16 MB string | 74.09 µs | 376.57 µs | 6,703 B | 3,802 B | 332 B |

Inputs, library imports and engine initialization are outside measurement.
Admission cadence is reset outside the timed boundary so accepted calls are
measured; normal operation refills four tokens per second across the process,
with an initial burst of at most four and at most one capture per second per view.
The broadcast array tests logical shape/strides, not physical allocation of ten
billion elements; retention tests also use allocated parents/noncontiguous views.

Repeated runs varied enough to warrant a paired comparison. A separate local
measurement loaded baseline commit `498da87` and the fixed modules into the same
process, alternated which version ran first, and measured 300 calls each after 20
warmups with the same preallocated sources (setup/drain excluded, no tracing):

| Input | Baseline median | Fixed median | Baseline / fixed p95 |
| --- | ---: | ---: | ---: |
| Three scalar metrics | 82.40 µs | 90.49 µs | 115.28 / 124.37 µs |
| Broadcast array | 340.77 µs | 392.37 µs | 532.32 / 587.05 µs |
| 100,000 × 8 pandas frame | 1.237 ms | 1.567 ms | 1.617 / 2.013 ms |
| Dictionary with a 16 MB string | 60.79 µs | 65.17 µs | 103.90 / 107.83 µs |

Schema-first field sharing, distributed partial capture and stricter inspection
accounting add synchronous work; they do not promise a speedup. Samples now cover
more fields and include dtype metadata. No limits were raised to conceal cost.
These trials do not establish universal overhead or hard latency bounds; measure
representative pipelines before increasing capture frequency.

Memory is measured separately with tracemalloc, includes temporary Python
allocations, and excludes the existing source. It is not RSS, native allocator
usage, a hard latency bound, or whole-pipeline overhead. Tracing can cause earlier
soft-deadline exits, particularly for a frame; a partial sample remains labelled.
Single-envelope sizes were 876 B, 2,431 B, 4,897 B and 945 B respectively for the
four accepted inputs. Post-drain measurements retain bounded engine/cadence
bookkeeping and allocator effects.

A full-mailbox trial with oversized Unicode strings retained 97,415 B with a
114,099 B traced peak. After eight leases were acknowledged and work references
released, 1,888 B remained traced, including cadence entries. The ninth submission
was rejected before capture.

Cold layout trials construct fresh inputs outside each of ten timed calls, so a
warmed pandas placement cannot hide a first-call scan:

| Fresh input | Median capture | Maximum in these trials |
| --- | ---: | ---: |
| Dict: 100,000 slots, all but one deleted | 148.29 µs | 188.14 µs |
| Dict: 1,000,000 slots, all but one deleted | 166.29 µs | 258.02 µs |
| pandas: 100,000 columns after dtype selection, no cached maps | 178.23 µs | 206.98 µs |
| pandas: 1,000,000 columns after dtype selection, no cached maps | 211.36 µs | 269.76 µs |

These paths omit unsafe storage before iterator/placement access: zero dictionary
entries or dataframe values are read. pandas reads one bounded column label.
The extra cold-call latency includes allocator/cache/GC effects following fixture
creation; it does not demonstrate a proportional source scan.

Rejected-call trials run 100 rounds of 100 calls with frozen cadence time.
For 8- and 512-character identities respectively, median time was 1.23/1.30 µs
(view cadence), 2.38/2.46 µs (process cadence), 4.87/3.55 µs (full), and
1.09/0.82 µs (busy). Before caching valid identities in the bounded cadence table,
the 512-character view-cadence case measured 34.51 µs on the same machine.

Maximum-budget memory trials explicitly disable the supplemental deadline **in the
test only**, so tracing cannot stop them before structural limits are exercised.
They use 1 MiB capture allowance, 4,096 reads/nodes, depth 8, 128 rows, 32 fields,
1,024-byte values and 256 KiB output (4 KiB for forced output overflow):

| Input | Traced peak | Retained | After release | Encoded output |
| --- | ---: | ---: | ---: | ---: |
| Eight levels of 128-way nested sequences | 517,536 B | 80,864 B | 92 B | 56,935 B |
| Oversized Unicode strings | 143,197 B | 53,864 B | 92 B | 34,167 B |
| Strings requiring JSON escapes, forced output overflow | 429,128 B | 20,142 B | 92 B | 445 B |
| Binary values with examples enabled | 482,802 B | 164,997 B | 92 B | 142,244 B |

A separate Linux subprocess retained a four-million-row Polars frame with an
unmaterialized scalar column. The disabled adapter returned its fixed reason in
0.151 ms; current RSS, peak RSS and post-drain RSS each increased by 0 bytes in
that trial. Native-access trap tests also enforce that no shape/series getter is
called. This does not establish a native-memory bound for future Polars adapters.

These are development-machine observations, not universal latency or allocation
guarantees. The capture engine creates no idle threads, timers or network work.

## Public observation and summary measurements

Prompt 10 adds the public API and one event-driven consumer to the capture
foundation above. Reproduce its foreground, background and memory checks with:

```bash
python -m pytest -q -s tests/benchmarks/test_bench_observation_pipeline.py \
  --benchmark-columns=min,median,max
```

On the same Linux/Python 3.13 development environment (2026-09-09), interleaved
trials alternate capture-only and public `publish_view(..., observe=True)` calls
on the same source, with ten warmups and 100 measured pairs. Admission/drain resets
are outside timing, and the consumer is held out of foreground measurements.
This isolates Prompt 10's API overhead from the capture cost already present in
Prompt 09; it does not subtract capture from the actual pipeline overhead.

| Input | Capture-only median | Public-call median | Median paired extra cost | Public maximum in these trials |
| --- | ---: | ---: | ---: | ---: |
| Three supplied scalar metrics | 57.68 µs | 73.17 µs | 15.24 µs | 1.313 ms |
| pandas 100,000 rows × 8 numeric columns | 1.460 ms | 1.526 ms | 39.23 µs | 7.781 ms |
| NumPy broadcast, 10 billion logical elements | 318.28 µs | 331.65 µs | 15.06 µs | 1.520 ms |
| Dictionary containing one 16 MB string | 59.00 µs | 73.26 µs | 14.32 µs | 361.32 µs |

The paired delta is the median of individual differences, not subtraction of the
two medians. Separate microbenchmarks varied with scheduling/load: skipped public
calls measured roughly 12–21 µs median. A first inline call after library imports,
with empty default configuration and a stubbed delivery endpoint, measured
544 µs median / 812 µs maximum across 30 trials. That includes engine/routing/thread
setup but excludes imports and actual server/network work. Decoration prepares
these components before the function runs. None of these are hard deadlines.

A blocked-consumer trial submitted 1,000 changing view IDs with default budgets.
It retained four charged reservations (262,144 reserved capture bytes), measured
326,264 B traced peak, 324,494 B retained while blocked and 135,717 B after drain
and GC. The remaining memory includes the bounded routing/cadence caches; input
allocation and thread startup were outside tracing. Tracing shortened capture
through the soft deadline: the largest delivered summary in that trial was
4,531 B. A 100 ms idle interval consumed about 0.095 ms process CPU in that trial;
a deterministic test separately verifies condition waits have **no polling
timeout**. This is a short sanity check, not a promise about total server CPU.

Maximum-budget summary trials disable the capture deadline **only in tests** to
exercise structural limits, then trace summary preparation from an already
detached envelope. Examples are explicitly enabled:

| Captured evidence | Capture bytes | Exported summary | Summary traced peak | Retained summary/work allocations at return |
| --- | ---: | ---: | ---: | ---: |
| 16 columns of large integers | 92,985 B | 45,376 B | 1,371,509 B | 162,776 B |
| Oversized Unicode strings | 35,281 B | 37,070 B | 205,770 B | 66,156 B |
| Eight-level nested sequences | 56,928 B | 57,477 B | 1,018,676 B | 465,319 B |

These larger-budget runs took roughly 5–85 ms **with tracing**, in the background
summary stage. They are allocation probes, not untraced latency benchmarks. The
encoded 64 KiB limit does not imply a 64 KiB Python heap: decoded trees, arithmetic,
UTF-8 encoding and temporary JSON buffers also allocate. Only one consumer builds
summaries, pending/in-flight captures remain reserved, and decoded evidence is
released without depending on cyclic GC (verified with GC disabled). No original
pipeline object crosses the capture boundary.
