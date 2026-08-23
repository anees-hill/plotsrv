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
