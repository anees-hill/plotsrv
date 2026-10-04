
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

The recipes and manifests are versioned. Campaign manifests live in
`benchmarks/ptop/`; `ptop.toml` stays at the checkout root so ptop can discover
recipes without `--file`. Run the commands below from the checkout root.
The `.ptop/` database and `ptop-manifest-results/` outputs are local generated state.

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

The [internal observation capture foundation](../reference/observation.md)
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

## Observation presentation and recent history

Run `python -m pytest -q -s tests/benchmarks/test_bench_observation_presentation.py
--benchmark-columns=min,median,max`. The source is constructed and captured before
timing: a 100,000 × 8 integer DataFrame, default structural budgets, 50 ms capture
deadline for repeatable preparation. Receipt uses the shared server boundary with
storage disabled. Rendering uses only its exported summary and up to 16 compact
entries; cached rendering uses the existing artifact cache.

Recorded on 2026-09-09, Python 3.13, 100 trials per operation:

| Server operation | Median | Maximum |
| --- | ---: | ---: |
| Receipt, recent-history append disabled for comparison | 2.267 ms | 9.572 ms |
| Receipt with bounded recent history | 2.307 ms | 8.853 ms |
| Uncached observation presentation | 3.608 ms | 19.403 ms |
| Cached artifact response | 13.431 µs | 2.166 ms |

Browser regression checks were running concurrently. An earlier, less contended
run measured receipt medians of 1.194 / 1.236 ms without/with history and uncached
rendering at 1.575 ms. These independent medians are not a paired measurement of
overhead or latency guarantees. Receipt/rendering run on the consumer/server side,
not the observed function's capture boundary. Presentation adds no source scan,
timer, retry loop or worker thread.

An 8,192-append memory trial (256 source IDs × 32 revisions) reached the shared
encoded cap: 4,191,708 B retained across 978 entries / 62 sources. Python tracing
measured 4,294,550 B retained, 4,313,166 B peak and 308 B after clearing and GC.
The entry/source caps are simultaneous, so byte pressure can retain fewer than
128 sources or 16 entries each. Thread identities were unchanged. This is the new
history cache alone, excluding sources, current summaries and existing render
caches, not total server RSS.

Rendering the prepared eight-field observation produced 54,948 B HTML, with
267,302 B traced peak, 123,586 B retained at return and 142 B after release/GC.
The browser projection has an independent 192 KiB encoded bound, at most 32 fields,
eight distributions, four scalar-history columns and 16 optional examples. Whole
HTML and temporary decoded/escaped trees also allocate. The tests additionally
exercise wide Unicode evidence, per-source/global eviction, missing history
admission, incompatible schemas/scopes, remote authentication and storage on/off.

The existing warm capture-boundary benchmark was rerun separately (100 trials):
median 3.035 µs for closed-engine rejection, 55.713 µs for a small metrics dict,
55.588 µs for a huge string cell, 315.549 µs for a broadcast large array and
1.567 ms for a 100,000 × 8 DataFrame. Observed maxima ranged up to 10.323 ms for
the frame. These are measured captures/rejections with setup outside timing,
not public cold-start costs or hard cancellation deadlines.

## Server-side checks

Run `python -m pytest -q -s tests/benchmarks/test_bench_checks.py
--benchmark-columns=min,median,max`. Inputs/configuration are prepared outside the
measurement. The admission benchmark deliberately resets cadence, CPU credit and
pending work between trials; it measures one check's hook cost, not a sustainable
rate that bypasses the production budgets.

Recorded on 2026-09-09, Python 3.13, 100 rounds per operation:

| Admission case | Median | Maximum |
| --- | ---: | ---: |
| No enabled checks | 0.581 µs | 0.661 µs |
| One supplied numeric scalar | 15.605 µs | 36.420 µs |
| Million-key dictionary rejected before iteration | 11.682 µs | 37.332 µs |
| One supplied observation metric | 96.231 µs | 189.405 µs |
| Observed mean in a captured 100,000 × 8 frame summary | 411.910 µs | 568.408 µs |
| Already overloaded 100-record event batch | 5.180 µs | 29.776 µs |

These are hook measurements, not total publisher/HTTP latency, and concurrent
regression activity affects results (scalar medians varied around 15–29 µs across
runs). The frame source was summarized before timing; the measured hook selects
from detached evidence only. Selection has a shared soft CPU allowance of
20 ms/s (4 ms burst), in addition to per-hook work/CPU and rate/queue limits. No
budget promises preemption or a wall-clock deadline. Comparison, bounded event
encoding, SSE delivery and browser reads also consume resources separately.

A structural queue stress trial prepared 100 records with large ignored fields,
then attempted 100 batches while resetting admission credit in the benchmark.
The queue plateaued at 32 jobs / 262,144 reserved bytes. It retained 28,976 traced
bytes, peaked at 30,056 B and retained 22,627 B after drain/GC (including bounded
latest state and event history). The original records were outside tracing;
separate weak-reference tests prove ignored source objects are not retained.
Reservations are conservative accounting, not heap/RSS measurements. This one-rule
trial uses minimal receipt metadata, not the maximum configuration.

The drained worker consumed about 0.071 ms process CPU during a 100 ms idle interval
in that run. This short observation is not a universal idle-CPU guarantee; the
worker's indefinite idle condition wait and absence of a worker when disabled are
also tested. Only a pending trailing SSE notice uses a timed wait. Shutdown joins
the worker finitely and restart is fenced until it exits.

Failure tests cover queue/CPU/lock overload, coalescing and stale in-flight work,
invalid/large numeric values, native and display-model JSON, scoped observation
metrics, authenticated HTTP/local producers, stream deduplication/raw eviction,
restored history and snapshot browsing. SSE tests stall an event loop across
10,000 notices: at most one dispatch callback and four pending event classes remain
per subscriber; slow status fetches retain one trailing refresh without changing
the displayed data.

## Browser check attention

Run `python -m pytest -q -s tests/test_check_status_browser.py` with Playwright
Chromium installed. The tests mount the real status/modal markup and assets,
using evidence produced by the actual check engine; history replies are controlled
to exercise races and failures without a network service.

The bounded-history case renders 256 retained events plus one current-state card.
It makes one history request and stores 45 characters of seen-watermark JSON for
that fixture. Closing releases all 257 cards; subsequent idle time adds no request.
One thousand repeated status deliveries took 79 ms in Chromium during a concurrent
regression run on 2026-09-09. This is browser handling time for already-decoded
status, not network, Python ingestion or full history rendering time; it is not a
hard latency guarantee or an idle CPU/RSS measurement.

Production limits remain 256 events / 256 KiB server history, at most eight rules
for a source and 128 browser-local seen entries. History reads have one active
request, a ten-second deadline and no automatic retries. The browser stores IDs,
generation and cursors, never check values, and releases the rendered history on
close. SSE supplies live notices through the existing coalescing status path;
there is no new polling loop or publisher-side worker in this UI feature.

## Webhook delivery

Run `python -m pytest -q -s tests/benchmarks/test_bench_webhooks.py
--benchmark-columns=min,median,max`. This separates foreground check admission
from notification encoding/admission on the checks worker. Sources/configuration
are prepared outside timing; admission credit and pending jobs are reset between
100 rounds, as in the existing checks benchmark. It is not a sustainable rate
that bypasses production quotas.

Measured on 2026-09-09, Python 3.13:

| Operation | Median | Maximum |
| --- | ---: | ---: |
| Foreground scalar check admission, no notifications | 16.547 µs | 38.654 µs |
| Same admission while the notification sender is blocked | 16.167 µs | 49.054 µs |
| Background notification encode/queue admission | 10.756 µs | 29.166 µs |

The foreground trial does not include source creation or notification encoding;
its check worker is held for repeatable capture measurement. The notification
worker is independently blocked in a fake sender. These figures do not measure
TLS handshake/DNS/server latency or assert that notifications improve performance.
The public HTTP test separately verifies that accepted publication and genuine
check recovery complete while the notification sender is blocked.

A 1,001-event overload trial plateaued at 64 items / 34,670 encoded bytes for one
rule's small scalar payload. It retained 56,138 traced bytes and peaked at 58,419 B;
after bounded close and sender release, 208 traced bytes remained. Configuration,
the worker and its first in-flight item were created before tracing; these are
incremental Python allocations, not RSS or the maximum-payload case. The enforced
aggregate cap is 256 KiB, including in-flight data, and individual payloads cap at
8 KiB. Queue slots and payloads are reused for retries rather than accumulating
attempts. A drained worker's 100 ms idle interval used about 0.059 ms of process CPU
in this run; indefinite condition waits and absence of an unreferenced worker are
also tested. Native DNS is not hard-cancellable, as documented in
[Generic webhooks](../reference/webhooks.md).

## Browser loading and connection lifecycle

With Playwright Chromium installed, run:

```bash
python -m pytest -q tests/test_browser_connection_lifecycle.py tests/test_content_loading_browser.py tests/test_browser_refresh_assets.py
```

The connection tests start an isolated HTTP/1 server and open eight tabs. They
exercise foreground/background transitions, deferred initial content, reconnect
catch-up, navigation and page-cache restoration. Headless Chromium reports all
tabs as visible, so the tests explicitly drive visibility changes while retaining
real network connections. Mocked HTTP routes alone cannot detect connection-pool
starvation. Separate cases hold status/catalogue replies, advance their deadlines,
and check that content finishes independently and late replies cannot replace
newer status. Retry tests use a controlled clock to check backoff and cleanup.

The browser opens its update stream after the first content attempt, closes it
when hidden or leaving the page, and reconciles on return. Disconnected visible
pages retry with a 2–30 second backoff. A visible connection has one 20-second
liveness timer; a healthy idle connection does not trigger HTTP polling. Status
and catalogue requests coalesce independently, time out after ten seconds and
are cancelled when hidden or leaving the page.

This reclaims connections from background tabs; it does not multiplex multiple
simultaneously visible dashboard windows. Enough visible windows on the same
HTTP/1 origin can still exhaust the browser connection pool. Keep that case
separate from the foreground/background regression test when measuring many
dashboards. It remains a transport limitation, not a guarantee covered by these
tests.

## Concurrent browsing rehearsal (0.8.0+)

Start with this command from the plotsrv checkout (installed **ptop 0.5.0**):

```bash
ptop --db .ptop/conference.sqlite3 recipe run server-browser-concurrent --no-tui
```

It starts a fresh loopback receiver and six simulated visitors. Each holds an
`/updates` stream while concurrent first reads and repeated reads exercise one
published table and JSON artifact. Independent probes request the page, status,
and a published PNG. A publication overlaps reads, followed by checks that every
table row and the artifact contain the new revision and every visitor receives a
new update notice. The default 22-second settling period permits an idle SSE
heartbeat. The generated table has 1,680 rows, 12 data columns and a revision
column; it approximates the retail table's size, not its exact contents.

Other useful commands:

```bash
# One visitor, twenty visitors, and six visitors reading a 15,000-row table:
ptop --db .ptop/conference.sqlite3 recipe run server-browser-single --no-tui
ptop --db .ptop/conference.sqlite3 recipe run server-browser-burst --no-tui
ptop --db .ptop/conference.sqlite3 recipe run server-browser-large --no-tui

# Set a latency goal only after choosing it for the intended machine:
ptop recipe run server-browser-concurrent --set cheap_p95_ms=250 --no-tui

# Preview then run three repetitions per workload against PyPI 0.8.0 and local source:
ptop manifest plan benchmarks/ptop/plotsrv-conference.toml
PLOTSRV_MANIFEST_FILE="$PWD/benchmarks/ptop/plotsrv-conference.toml" scripts/run_plotsrv_manifest.sh

# The harness also works without ptop:
uv run --group benchmark python -m benchmarks.browser_profile \
  --clients 6 --output benchmark-results/my-browser-run
```

`benchmarks/ptop/plotsrv-release.toml` now compares PyPI 0.8.0 with the local checkout and retains
the CLI, watched-file overload/settling and asynchronous publishing checks. Its
obsolete artifact case is replaced by the browsing rehearsal. Conference load
levels have separate recipe names because ptop 0.5.0 groups report medians by
recipe and target, regardless of settings. Use the same settings for comparisons.
The complete conference manifest is 24 attempts, each with a 22-second settling
period, plus setup and traffic. Avoid running other benchmarks simultaneously.

Read the output directory's `run.json` for **per-phase, per-route** p50/p95/p99,
sample counts, response bytes, status counts (including 429/503) and errors.
`requests.json` retains individual HTTP observations; `samples.csv` contains
receiver CPU/RSS/USS samples; `server.log` captures receiver diagnostics.
`streams` in `run.json` records heartbeat counts, message gaps (including the final
quiet interval), publication-notice times and stream failures. An SSE notice
latency starts before the publishing request, so includes publication processing.
The ptop `ptop-result.json` and database contain resource history for the complete
process tree; ptop's manifest report does **not** summarize HTTP latency itself.
Small phase sample counts make p95/p99 effectively maxima, not reliable tail
estimates. Latency excludes client JSON validation, but client generation/parsing
still competes for this host's CPU. Requests use HTTP clients with connection
reuse; they do not execute browser JS or download static assets.

A nonzero exit records HTTP/content/SSE failures, receiver exit, the sampled
512 MiB receiver RSS watchdog, or the 180-second workload deadline. ptop adds a
1,500 MiB process-tree watchdog. Set `max_server_rss_mb=320` to rehearse the demo's
nominal memory allowance, but a sampled RSS limit is **not equivalent** to cgroup
`MemoryMax=320M`; brief peaks and charged filesystem memory differ. The harness
bounds generated table payload estimates to 24 MiB. No latency threshold is
imposed unless `cheap_p95_ms` is set. Keepalive counts and gaps are observations,
not an automatic liveness deadline. This is a bounded burst test with closed-loop
request waves, not a sustained arrival-rate or maximum-throughput test.

### What the current receiver rebuilds

In 0.8.0, current table reads call `DataFrame.to_dict(orient="records")` and
framework JSON encoding on every request. Tables are not protected by the
watched-file admission budget. Current artifacts cache rendered dictionaries by
revision, but misses do not coordinate concurrent renders and responses still
need JSON encoding. Published PNG reads reuse bytes. Index requests rebuild the
HTML page, but do not rerun publishers or data generators. Synchronous handlers
can overlap in threads; CPU-heavy Python conversion/rendering still competes for
the interpreter. Multiple Uvicorn workers cannot safely share the current
process-local views and update subscriptions without further architecture work.

The most useful prospective optimization is a bounded cache of **encoded current
table responses**, with one build per revision/parameter combination, publication
consistency and invalidation tests. Establish these measurements before changing
that path. File-backed views, snapshots, exports, streams and remote-watch status
have distinct semantics and need their own coverage.

### Deployment follow-up

The rehearsal uses one receiver, memory-only publications and one loopback source
IP with the demo's 96-total/64-per-client SSE limits. It does not reproduce the
three populated demos, retained history, stream ingestion, scan report publishing,
Caddy/Cloudflare, conference NAT, cgroup pressure, or browser rendering. Rehearse
those on an isolated copy of the deployed VM: start with six visitors, then
bursts of 5/10/20 distributed across the demos, while live ingestion and a scan
publication continue. Measure cgroup memory and OOM/restarts alongside HTTP
latency, SSE gaps, and proxy rejection counts. Agree the ordinary-navigation p95
target for that machine before treating the run as a capacity acceptance test.

The ptop checkout at `~/Projects/ptools/projects/ptop` currently declares **0.2.0**
and lacks recipe/manifest commands; the installed 0.5.0 wheel has them. Resolve
that source/version mismatch before working on ptop's interface. Future useful
ptop improvements include grouping comparisons by workload settings, surfacing
HTTP/SSE results alongside process metrics, and a single concise rehearsal report.

### Local observations, 3 October 2026

Single sequential attempts on the development machine with the local 0.8.0
checkout, five repeated-read waves, and ptop recording the process tree:

| Visitors | Table rows | Repeated table p95 | Cold artifact p95 | Receiver peak RSS |
| --- | --- | --- | --- | --- |
| 1 | 1,680 | 27 ms | 94 ms | 209 MiB |
| 6 | 1,680 | 187 ms | 507 ms | 228 MiB |
| 20 | 1,680 | 529 ms | 1,210 ms | 251 MiB |
| 6 | 15,000 | 1,433 ms | 507 ms | 378 MiB |

All four admitted workloads completed without HTTP errors or unexpected SSE
closure; every connection received a keepalive. During publication in the
20-visitor case, cheap-route observed p95 reached about 695 ms. The large-table
case exceeded the deployed receiver's **320 MiB** nominal memory allowance even
on this development host. It was run under the rehearsal's 512 MiB RSS watchdog,
not the deployed cgroup. This supports measuring per-demo headroom before relying
on that deployment ceiling; it does not show that the retail demo needs 378 MiB.

The original 20,000-row/12-column string fixture was rejected with 413 during
setup: its JSON structure exceeds the receiver's 500,000-token ingestion bound.
The checked-in large recipe uses 15,000 rows to reach the read path within that
bound. Run directories are `benchmark-results/conference-1`, `conference-6`,
`conference-20`, and `conference-large-admitted` (generated files are local).
These are exploratory single attempts with small tail samples, not conference VM
capacity measurements or a completed repeated manifest comparison.

Validation: both manifests resolved with `ptop manifest plan`. A separate
single-attempt ptop manifest installed **PyPI plotsrv 0.8.0** into an isolated
environment and passed the six-visitor case, including publication notices and
six keepalives. Its repeated table p95 was 180 ms. The focused harness tests passed
**24 tests**, including real receiver/SSE traffic, timeout failure reporting and
receiver cleanup. The full 24-attempt conference matrix has not been run.

## Table response cache acceptance campaign

The candidate caches final JSON bytes only for ordinary current tables decoded
by HTTP publication. Local caller-owned DataFrames, watches (including their
changing metadata), restored tables, historical snapshots and exports keep their
existing read paths. Readers overlapping a publication may receive their coherent
captured revision. A completed older build cannot enter the cache after the view
is replaced or reset. Retained bytes are limited to 16 MiB, 32 entries and 8 MiB
per entry. Concurrent readers share a build without occupying worker threads;
coordination is capped at 32 keys and 128 readers, with uncached fallback instead
of a new HTTP rejection. These are cache bounds, not total receiver memory limits.

Prepare a reproducible baseline **before changing receiver source**, using the
checkout's benchmark environment. The baseline source is archived under `.ptop`
so pytest does not collect its duplicate test tree. The preparation command
preserves an existing baseline and refuses to overwrite different dependency
constraints:

```bash
uv sync --group test --group benchmark
.venv/bin/python scripts/prepare_table_cache_campaign.py --baseline-ref BASELINE_GIT_REVISION
ptop manifest plan benchmarks/ptop/plotsrv-table-cache.toml
ptop --db .ptop/table-cache.sqlite3 manifest run benchmarks/ptop/plotsrv-table-cache.toml
.venv/bin/python -m benchmarks.table_cache_report ptop-manifest-results/MANIFEST_DIRECTORY
```

Run from the checkout root. Both manifest targets use Python 3.13.7 and the same
saved dependency constraints; change both Python selections together if preparing
on a different interpreter. The source baseline for this change is
`537d4731a21ec4fec191fc2768a0167e0a07bdaf`. Each receiver records its installed
source hash and path. The harness records its hash, settings, Python, and package
versions so comparisons can reject mismatched inputs.

The manifest makes **70 sequential attempts**: five per target for each of seven
workloads. Those are table-only browsing with 1/6/20 visitors, six visitors reading
15,000 rows, mixed browsing, ten publications overlapping readers, and a ten-minute
soak. Each attempt has 50 warm-read waves. Table-only cases omit artifact traffic
and cheap-route probes for clear CPU-per-table measurements; the mixed case keeps
independent page/status/plot probes. The soak cycles forty views and request limits
and republishes periodically to exercise eviction. SSE streams reconnect at their
configured 600-second lifetime; earlier closes or a changed receiver instance are
failures. A short-lifetime regression test validates reconnection separately.

`phase_metrics` records receiver CPU time and memory at workload boundaries;
`cpu_per_table_s` divides phase CPU by successful table reads. Soak memory is
sampled in repeated windows, and `cache_samples` records private cache accounting.
The report writes `table-cache-comparison.json` and `.md`, retaining each attempt's
measurements alongside medians. Gates require at least 50% lower warm CPU/read and
30% lower warm table p95 for six visitors. Cheap-route/publication p95 increases
exceeding both 10% and 5 ms require repeating the affected comparison; a persistent
regression blocks acceptance. Peak RSS increases beyond the 16 MiB cache allowance
and continuing soak USS growth require investigation. Cache accounting violations
and functional failures always fail the campaign.

These local measurements do not authorize deployment or establish cgroup/VM
capacity. Repeat the populated-demo/proxy rehearsal on the intended isolated VM
before rollout. In particular, tables restored from disk remain uncached in this
first change; republishing through HTTP enables caching for their new revision.

For the shorter campaign agreed during implementation, use
`benchmarks/ptop/plotsrv-table-cache-focused.toml` and pass `--focused` to the comparison report.
It has 18 attempts: three per target for six-visitor table-only and mixed browsing,
then one per target for twenty visitors, the large table, and a two-minute soak.
Ordinary attempts settle for one second; the soak checks sustained connections
during activity. Separate lifecycle tests cover idle keepalives, and the
short-lifetime regression test covers connection-lifetime reconnection.
The same CPU/latency improvement gates apply. Stress/soak findings are single
attempts and do not replace the longer campaign's repeated endurance evidence.

```bash
ptop --db .ptop/table-cache.sqlite3 manifest run benchmarks/ptop/plotsrv-table-cache-focused.toml
.venv/bin/python -m benchmarks.table_cache_report --focused ptop-manifest-results/MANIFEST_DIRECTORY
```

### Local implementation results (2026-10-04)

Both targets report plotsrv **0.8.0**: the baseline is the frozen source above,
and the candidate is that source plus the table cache. This comparison does not
use older plotsrv releases. The focused campaign completed all 18 attempts in
`ptop-manifest-results/2026-10-04T184830.837+0000-2`, with no functional failures.
Its generated `table-cache-comparison.json` retains the individual measurements.

| Workload | Warm CPU/read before → after | Warm table p95 before → after |
| --- | --- | --- |
| Six visitors (median of three) | 21.50 → 1.47 ms | 177.86 → 53.25 ms |
| Mixed browsing (median of three) | 27.83 → 6.17 ms | 229.84 → 64.49 ms |
| Twenty visitors (one attempt) | 20.95 → 1.70 ms | 551.78 → 203.66 ms |
| Large table (one attempt) | 156.83 → 3.50 ms | 1413.71 → 487.40 ms |

The primary improvement gates passed (93% lower CPU/read and 70% lower p95).
No cheap-route or publication latency crossed the regression investigation
threshold. The first soak did flag peak RSS: 216.94 → 235.54 MiB, an 18.60 MiB
increase against the 16 MiB investigation threshold. Cache accounting remained
bounded (32 entries, peak 12.85 MiB of encoded bytes), and post-warmup USS fell
by 1.20 MiB by the final checkpoint. The report therefore retains its
`investigate` status rather than treating the performance gains as full acceptance.

A separate two-attempt soak repeat is preserved under
`ptop-manifest-results/2026-10-04T185712.165+0000-3`, including
`table-cache-soak-comparison.json`. It again completed without functional failures,
but peak RSS increased by 19.97 MiB (230.43 → 250.41 MiB). Candidate USS rose
2.68 MiB between the second and final checkpoints; baseline rose 1.50 MiB.
Soak publication p95 also crossed the investigation threshold on this repeat
(118.7 → 133.9 ms); that latency flag was absent from the initial comparison.
Encoded cache bytes remained bounded at the same 12.85 MiB peak. The short
observations cannot distinguish allocator retention from continuing growth.
Memory overhead is therefore a repeated finding, and rollout acceptance remains
open. The implementation has not been deployed. A smaller retained-byte budget
and a focused memory follow-up are the next candidates for investigation; the
existing thresholds have not been relaxed to make these results pass.

Validation included exact response bytes, invalidation races, concurrent readers,
failure/cancellation cleanup, mutable/watch/history bypasses and browser lifecycle
coverage. The broad pytest run with `--benchmark-disable` recorded 2,577 passes
and eight failures in benchmark tests whose assertions require repeated calls.
Rerunning their entire module with benchmarking enabled passed all 22 tests.
The browser lifecycle/refresh group passed 28 tests; the cache/report/profile
group passed 27, with the subsequently added SSE reconnection test and all four
final report tests also passing. `git diff --check` passed. The long campaign
and deployment VM/proxy rehearsal remain unrun.

## Non-table renderer response cache

Ordinary current artifacts now reuse their final encoded HTTP response. JSON,
Markdown, HTML, text, code/Python, images, tracebacks and error artifacts share
this path. Simultaneous first readers share one render and encoding operation;
waiting readers do not occupy worker threads. Publication, kind changes, watch
metadata changes and reset invalidate retained responses. Completion checks
prevent a late old render from replacing a newer cached revision.

Encoded responses **replace** dictionary entries in the existing artifact cache.
The existing limits remain 32 entries, 32 MiB total and 24 MiB per entry; no
additional response-storage allowance is introduced. Encoded entries count their
complete byte object size. Build coordination reuses the table cache's tested
implementation with retention disabled, leaving the table cache itself unchanged.
Coordination has the same 32-build/128-reader limits and uncached fallback.
These are retained-cache bounds, not a ceiling on total process memory.

Historical snapshots, watched artifacts, changing remote-watch notices and
observation reports retain their existing paths. Direct internal Python calls
still return dictionaries. Alternating internal dictionary calls with HTTP reads
can replace the cached representation and cause a rebuild. `/plot` already serves
published PNG bytes and was not changed; table rendering was also left unchanged.

The short real-HTTP rehearsal publishes each of seven artifact types three times,
with six simultaneous readers on each cold revision and ten subsequent warm
waves. It checks current content, records full-response hashes and receiver CPU
and memory, and probes `/status` during cold reads. It does not exercise browser
JavaScript or replace the deferred long memory soak. A 512 MiB receiver watchdog
and a 1,500 MiB ptop process-tree watchdog bound each run.

```bash
.venv/bin/python scripts/prepare_table_cache_campaign.py --campaign artifact-cache --baseline-ref 75d92b8
ptop manifest plan benchmarks/ptop/plotsrv-artifact-cache.toml
ptop --db .ptop/artifact-cache.sqlite3 manifest run benchmarks/ptop/plotsrv-artifact-cache.toml
```

The manifest compares three attempts per target using matching dependency
constraints and Python 3.13.7. The baseline includes the committed table work;
the candidate adds only the non-table renderer changes. The source hash and
import path are recorded for each receiver. For a standalone current-code run:

```bash
.venv/bin/python -m benchmarks.artifact_profile --output benchmark-results/artifacts
```

### Local renderer results (2026-10-04)

All six attempts completed in
`ptop-manifest-results/2026-10-04T194146.062+0000-1`. Workload settings, dependency
versions, host/Python information and harness hashes matched. The candidate
source hash matched the working source. Every artifact response hash matched
across all baseline/candidate attempts, including each republished revision.
`artifact-comparison.json` and `.md` preserve the detailed local comparison.

Medians of three independent runs, with six readers:

| Renderer | Cold response p95 before → after | Warm response p95 before → after | Warm CPU/read before → after |
| --- | --- | --- | --- |
| JSON | 2,618.51 → 835.32 ms | 360.59 → 344.15 ms | 11.22 → 3.11 ms |
| Markdown | 1,131.69 → 233.10 ms | 18.10 → 14.38 ms | 1.28 → 1.00 ms |
| HTML | 16.73 → 15.31 ms | 17.95 → 13.38 ms | 1.22 → 0.89 ms |
| Text | 17.58 → 22.51 ms | 16.30 → 15.28 ms | 1.17 → 0.94 ms |
| Code | 20.16 → 18.55 ms | 18.62 → 15.15 ms | 1.44 → 1.00 ms |
| Image | 18.19 → 20.08 ms | 15.70 → 14.04 ms | 1.11 → 0.94 ms |
| Traceback | 22.85 → 18.58 ms | 17.21 → 17.05 ms | 1.28 → 0.94 ms |

Median peak process RSS fell from 243.27 to 183.47 MiB; sampled peak retained
artifact-cache size fell from 17.38 to 4.74 MiB. Accounting stayed within the
existing cache limits. The largest benefits are shared first renders for JSON
and Markdown and reduced JSON encoding CPU. Small-response timings do not all
improve. These measurements do not establish long-running memory stability.

The first comparison flagged cold `/status` p95 for JSON (91.2 → 119.0 ms) and
text (14.1 → 22.1 ms). Each run had only three such samples; the JSON maximum
always occurred on the first revision. A targeted twelve-publication repeat is
recorded separately under `benchmark-results/artifact-status-repeat`.
Both repeat runs completed with matching workloads, dependencies and source
revisions. JSON status p95 improved from 51.37 to 25.45 ms; text changed from
22.07 to 24.16 ms, below the investigation threshold. Publication p95 was
57.22 → 27.66 ms for JSON and 8.76 → 9.80 ms for text. The initial status flags
were therefore not reproduced as meaningful regressions. This is a short local
follow-up, not a general guarantee of responsiveness under arbitrary load.

Validation: **389 targeted tests passed**, covering the renderers, HTTP routes,
snapshots, remote watches, observation reports, source syntax, checks and the
table cache. This includes 21 new artifact-cache tests and a real-HTTP rehearsal
test. The earlier browser lifecycle/refresh group also passed all 28 tests.
Two renderer-registry test modules now restore their original registry after
each test; previously their dummy renderers leaked into later route tests.
