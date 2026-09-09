# Generic webhook notifications

Configured checks can POST compact JSON to an operator-owned HTTP(S) endpoint.
Configure this on the **plotsrv server**, independently of publisher connection
settings. Published data cannot choose a destination, supply HTTP headers or turn
notifications on. No receiver service or vendor integration is required to use
checks without notifications.

```yaml
webhook-settings:
  event_cooldown_s: 60
  dashboard_url: https://plots.example.test/dashboard/
  destinations:
    ops:
      url: https://receiver.example.test/hooks/plotsrv
      headers_env:
        Authorization: PLOTSRV_WEBHOOK_AUTH

checks-settings:
  rules:
    - id: duration-high
      name: Pipeline duration above limit
      source: etl:metrics
      kind: state
      path: [duration_s]
      op: gt
      value: 120
      severity: warning
      notify: [ops]
```

Set `PLOTSRV_WEBHOOK_AUTH` in the server's environment to the receiver's complete
header value, such as its required `Bearer …` value. The environment variable's
name is a reference, not a literal header value. Missing, empty, oversized or
invalid configured secrets fail server setup. Values are resolved at setup;
restart to rotate them. Do not put actual secrets in a shared YAML example.
`headers_env` is optional; webhook and publisher credentials are never inherited
from one another. These sections also support the existing defaults/instance
configuration convention.

At most eight named destinations and two references per rule are allowed.
Destination names contain letters, digits, underscores or hyphens, up to 64
characters. A destination accepts only `url` and `headers_env`; at most eight
headers, 4 KiB per secret and 8 KiB aggregate header names/values. Routing/framing
headers such as Host, Content-Length, Connection, Content-Type and proxy headers,
and the event identity headers, are reserved. Arbitrary literal headers, scripts,
templates and vendor payload builders are not supported.

URLs must be bounded ASCII HTTP(S) URLs, without user information or fragments.
Use percent-encoded paths when needed. Private endpoints are permitted. Secret
headers require HTTPS, except for numeric loopback addresses for local receivers;
HTTP without secret headers remains available for trusted private endpoints. Use
HTTPS for sensitive data or secret URL paths/query parameters too. TLS verifies the
configured hostname and certificate. All redirects are refused, including same-host
redirects. Webhooks ignore environment proxy settings and do not use `.netrc` or
publisher credentials. DNS chooses network addresses, but never changes the TLS
hostname or forwards credentials through a redirect. Configure the intended final
endpoint; telemetry cannot override it.

The optional dashboard URL must have no query, user information or fragment. It
is intended as a public dashboard link; the server appends the encoded logical
view ID. It does not grant access or carry a publisher credential.

## Events and receiver contract

A successful request is any HTTP 2xx response. Bodies are not parsed or retained.
The sender uses `Content-Type: application/json`, `Idempotency-Key` and
`X-Plotsrv-Event-Id`. Both identity headers contain the same stable event ID as the
version 1 JSON payload. For the example above, a trigger resembles:

```json
{
  "version": 1,
  "event_id": "server-generation:1",
  "generation": "server-generation",
  "cursor": 1,
  "view_id": "etl:metrics",
  "check_id": "duration-high",
  "check_name": "Pipeline duration above limit",
  "kind": "state",
  "event_type": "triggered",
  "severity": "warning",
  "previous_state": "ok",
  "current_state": "triggered",
  "received_at": "2026-09-09T12:00:00+00:00",
  "source_time": null,
  "source_time_origin": null,
  "captured_at_unix_s": null,
  "observed_value": 135,
  "condition": {"op": "gt", "threshold": 120},
  "evidence_scope": "supplied_value",
  "unit": null,
  "coverage": {"inspected": null, "not_inspected": null, "lost": 0},
  "suppressed_since_previous": 0,
  "dashboard_url": "https://plots.example.test/dashboard/?view=etl%3Ametrics"
}
```

`received_at` is the server receipt time of the evidence, not an invented delivery
or evaluation timestamp. Source time is optional and labelled publisher-supplied;
its original units/format are preserved. Observation capture time, when available,
is Unix seconds. Large integers and rational values use the checks API's typed
JSON representation instead of lossy/non-finite numeric conversion. Sample metrics
retain their evidence scope and counts; they do not validate a whole source.
Payloads omit raw records, arbitrary source context and tracebacks, and are capped
at 8 KiB encoded. An oversized payload is dropped and disclosed, not truncated into
a misleading claim. A scalar value or check name may itself be sensitive; select
appropriate evidence and a trusted endpoint.

State notifications follow the existing `triggered`, `recovered`, `unavailable`
and `available` transitions. Unchanged evaluations produce no notification. The
first accepted value establishes a baseline without notifying, even if failing.
Unknown or missing evidence cannot manufacture a recovery. A restart starts a new
generation with this same baseline policy; browsing/restoring snapshots does not
replay incidents. Separate severity rules notify independently under their own
check IDs; there is no automatic escalation chain.

Event checks notify on `match` occurrences, with no invented persistent failure or
recovery. Each check/destination pair sends at most one newly admitted match during
`event_cooldown_s` (1–86,400 seconds; default 60). Further matches increment the
suppression counter. The next eligible match includes `suppressed_since_previous`;
there is no scheduled trailing summary if no later match arrives. Duplicated event
cursors are ignored separately. Queue/pause drops are counted separately from
cooldown suppression. Counters are bounded diagnostics, not an exact audit ledger.

## Delivery limits, ordering and recovery

Only referenced enabled rules create a delivery worker. There is one daemon
worker, no executor or per-destination threads, and no idle polling. Socket work
runs outside the checks and delivery queue locks, independently of ingestion,
SSE and browser activity. The global queue holds at most 64 items and 256 KiB of
encoded payloads, **including the in-flight item**. Queue-full or lock-contention
admission drops work immediately. Notification payload encoding happens on the
checks worker after releasing its ingestion admission lock.

One HTTP request runs at a time. Requests start no more often than once per 200 ms
across all destinations, with a two-second exchange deadline for socket operations.
Response socket reads, including headers and buffering, stop at 16 KiB; response
bodies are discarded. Each event gets at most three attempts. HTTP 408, 425, 429,
5xx and network/timeouts can retry after one then two seconds. Retry-After seconds
or HTTP dates may extend a delay to at most 30 seconds. A destination's failed
attempts also pace other queued work for that endpoint. Queued items expire after 60
seconds, and every retry consumes the same queue item and payload bytes.

Other HTTP errors, refused redirects, TLS verification errors and response limits
are permanent for that attempt: the destination pauses for five minutes, its
queued backlog is dropped, and new events during the pause are counted as drops.
No timer probes the endpoint to test recovery. After the pause, a newly generated
eligible event can try again. Runtime failures expose short categories and status
codes, never exception text, URL queries, headers or response bodies.

Attempts for a check/destination pair retain FIFO order. Other pairs can proceed
while an older retry waits. **Timeout does not prove non-delivery:** a receiver may
have accepted a POST before the sender times out. Retries preserve the exact body
and event ID, and a receiver may finish processing an old attempt after a newer
recovery. Receivers should deduplicate event IDs, retain generation, and use cursor
order within a check/generation when updating their current state. Delivery is
best effort, process-local and neither durable nor exactly once.

Shutdown shares a finite drain budget with checks (normally 0.5 seconds), then
drops pending work. A small part of that budget is reserved for worker exit.
Native system DNS resolution cannot be preempted by socket timeouts. If it stalls,
it occupies only the fixed worker; shutdown returns after its budget and refuses
a replacement worker until the old one exits. No extra resolver threads accumulate.
An in-flight POST can finish after shutdown begins. These are bounded-resource
and best-effort deadline policies, not hard cancellation guarantees.

## Diagnostics

Open **Checks → Technical details** in the existing status modal, or read
`/checks?view=etl:metrics`. Each configured check's `notifications` lists named
destination status, queued count, attempt count/time, last event ID, HTTP status,
failure category, delivered/suppressed/dropped/duplicate/failure counters and
remaining pause time. Completion notices reuse the existing coalesced status SSE.
Reading this information does not resend notifications or acknowledge incidents.
Delivery failures never create another check event or notification chain, and do
not affect freshness colours or browser-local unseen-event watermarks.
