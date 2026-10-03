# Observation internals

Implementation notes for maintainers. Public behaviour belongs in [Observation reference](../reference/observation.md).

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
The internal manual consumer calls `take()` and then `finish(work.token)` after processing,
releasing its work reference at the same time. A contended `finish` returns false;
the consumer must acknowledge again before taking more work. Dequeuing alone does
not make capacity available. There is no source object, native buffer, source-bound
callback, traceback or closure in a queued envelope.

An internal submission without a route skips outstanding work before recapture.
Public observation coalesces pending envelopes per destination/view, subject to
both cadence budgets. It releases the old pending bytes before capturing their
replacement within the same reservation. If replacement capture fails, the old
sample is also lost. In-flight updates for the same destination/view are skipped
before recapture; different destinations share the process budget. This is
best-effort latest-wins among admitted pending updates, not an event history or a
promise to deliver the final call. Ordered streams keep their separate machinery.
No observation enters the ordinary source-retaining `PublishTask` queue.

`close()` abandons pending work. An active capture discards its result on return;
its reservation remains until then. In-flight leases remain charged until the
consumer acknowledges them. `reopen()` succeeds only after all reservations have
been released, so restart cannot overlap an abandoned capture. Close performs no
blocking drain. If close encounters a busy lock, its holder releases queued
payloads on exit; cleanup needs no later submission or idle polling. After a fork,
`get_capture_engine()` creates a fresh process-local engine and lock; direct
inherited engines reject work with `forked_instance`.
The public consumer waits on a condition with no idle timeout, polling or retry
thread. `flush_views` shares one finite deadline between ordinary and observation
queues; true means accepted work drained, **not that every delivery succeeded**.
`get_observation_stats()` exposes bounded best-effort accepted, skipped, processed,
failed, dropped and coalesced counters plus a fixed last-error code. Counters
saturate rather than grow indefinitely. Calling diagnostics explicitly may take
the bookkeeping lock; capture never waits for it.

`stop_server` and process exit drain briefly then close observation admission.
Pending envelopes are dropped; an in-flight consumer remains charged. A later
call can restart only after the previous thread and leases are gone, and routing
caches are cleared for that restart. Capture budgets belong to the initialized
process engine; changing them requires a fresh publisher process.

Remote delivery uses the shared negotiation cache and cooldowns, with a total
request deadline capped at two seconds. Failures pause new captures for that
target for 5 seconds (30 for auth/admission/protocol failures). There is no timer,
automatic resend or retained retry backlog: subsequent calls after cooldown try
again. Existing queued envelopes may be rejected by the shared transport cooldown.
The shared cooldown is per target, so a rejected catalogue ID can briefly pause
other observations to that target. Warnings contain fixed codes only and occur
at most once per 30 seconds, from the consumer. Shared transport diagnostics
have their own existing per-target rate limit. Routing/setup failures also have
a fixed cooldown, without hot-path logging or repeated config reads.

Warm routing caches are bounded to 16 connection configurations and at most
`max_view_ids` routing entries. They hold only bounded metadata/targets, never
sources. Routes stay fixed until restart or credential invalidation. Credential
rotation fails closed; a fresh inline/configured destination can resolve again.
An explicitly constructed `PublishTarget` must be reconstructed after rotation.

Native calls, DNS, runtime scheduling or arbitrary installed logging handlers
cannot be forcibly cancelled by Python time budgets. A stuck consumer cannot
create replacement threads or release its in-flight reservation early. Shutdown
returns after its finite wait; it cannot promise that native work has terminated.

## Reproducing the checks

```bash
python -m pytest -q tests/test_observation_capture.py tests/test_observation_admission.py \
  tests/test_observation_safety_regressions.py tests/test_observation_presentation.py \
  tests/test_observation_browser.py
python -m pytest -q -s tests/benchmarks/test_bench_observation_capture.py \
  tests/benchmarks/test_bench_observation_presentation.py \
  --benchmark-columns=min,median,max
```

The benchmark initializes sources and the engine before timing, measures accepted
`submit` calls with cadence reset between trials, and separately measures rejected
calls. Memory trials report Python traced peak, retained bytes and post-drain bytes,
excluding input allocation. Separate maximum-budget cases disable the deadline
only in the test to exercise structural limits under tracing. A separate Linux
subprocess measures RSS for the disabled Polars scalar-column adapter. Repeated
rejection and cold sparse-dictionary/wide-pandas cases cover failure costs.
Tracing itself changes execution time and can cause earlier soft-deadline exits
in the normal default-budget cases.
See [Testing & Benchmarks](testing-and-benchmarks.md) for a recorded run.
