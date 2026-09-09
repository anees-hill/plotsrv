# Follow HTTP logs as a stream

`stream_view` can follow mixed Uvicorn access/application output beside the
logfile and send structured events to a local or remote plotsrv server. It does
not change the application's logger, intercept stdout, import application code,
or let the server open the publisher's files.

```python
from plotsrv import stream_view

handle = stream_view(
    source="/var/log/my-service/access.log",
    format="uvicorn",
    view_id="web:access",
    label="HTTP log",
    destination="https://plots.example.test/dashboard/",
)
# Keep this publisher process alive while observation is wanted.
# When stopping:
handle.stop()
```

Destination configuration, bearer-key environment references, TLS verification,
server admission and retries are the same as for other
[remote publishers](remote-publishers.md). Saving an event requires admission of
its source view ID. Authentication/admission failures retain one bounded pending
batch and follow the existing retry policy; they do not start a local fallback
server. No text-specific server endpoint or protocol is needed.

Mixed-text adaptation does more work and sends more metadata per event than
structured JSONL. For busy logs, use the separate publisher process illustrated
below so parsing does not share the observed application’s Python process.

## Formats and supported input

- **`jsonl` (default):** the existing strict JSON-object-per-line mode, requiring
  `.jsonl` or `.ndjson`. This remains preferred for structured events and supplied
  HTTP metadata. It does not automatically redact or wrap the original objects.
- **`uvicorn`:** bounded mixed-text framing with conservative access recognition.
- **`text`:** the same framing, with HTTP recognition disabled.
- **`auto`:** `.jsonl`/`.ndjson` remain strict JSONL; other suffixes use Uvicorn
  recognition, preserving anything else as text. This is not universal format
  inference or a JSON parser for arbitrary application output.

Access recognition supports the default shape, including ANSI-coloured INFO:

```text
INFO:     127.0.0.1:54321 - "GET /health HTTP/1.1" 200
INFO:     [::1]:54321 - "POST /work HTTP/1.1" 503
```

An optional ISO date/time prefix is supported, with `T` or space between date
and time, optional fractional seconds, and optional `Z`/numeric timezone offset.
The prefix may be bracketed. Python logging-style comma fractional seconds are
also supported. Invalid/custom prefixes remain text.

An optional trailing duration must explicitly supply a unit: `12.5ms`,
`duration=12.5ms`, `0.25s`, or the corresponding `us`, `µs`, `ns` forms. Only a
validated supplied duration becomes `http.duration_ms`. Default Uvicorn output
provides neither duration nor source timestamp; neither is inferred.

Malformed/quoted paths containing whitespace or embedded quotes, unsupported
suffixes, startup/shutdown messages, application output, blank lines and incomplete
JSON survive as explicit text events. There is no nginx/Gunicorn parser or
framework dashboard in this adapter.

## Event contract and privacy

Each adapted record uses version 1 and separate namespaces:

```json
{
  "log_schema_version": 1,
  "event": {
    "kind": "http_request",
    "adapter": "uvicorn",
    "publisher_observed_at": "2026-09-09T12:00:00+00:00"
  },
  "http": {"method": "GET", "path": "/health", "status": 200},
  "raw": {
    "text": "INFO: 127.0.0.1:54321 - \"GET /health HTTP/1.1\" 200\n",
    "partial": false,
    "truncated": false,
    "ambiguous": false,
    "transformations": []
  }
}
```

`event.kind` is `http_request`, `traceback` or `text`; `http` is absent for non-request
events. `event.source_timestamp` exists only for a valid supplied prefix, and
`source_timezone_known` distinguishes a timezone-less local clock from an
absolute timestamp. `publisher_observed_at` marks framing/observation time; the
existing outer stream record's server-assigned `observed_at` is receipt time.
Neither is substituted for missing source event time. Retries preserve the
already-framed record and its observation timestamp.

`raw.text` is a **sanitised bounded excerpt**, not byte-for-byte archival evidence.
Transformations are listed explicitly. Terminal CSI/OSC escapes, control and bidi
control characters are removed; invalid UTF-8 is replaced. Query/fragment tails
are redacted in text, and removed from normalised request paths. Conventional
credential fields/headers are redacted. Traceback `File` paths become basenames;
recognised local path prefixes are shortened. Source provenance uses a basename,
not an instruction for the server to read any file.

This is not a general secret detector. Arbitrary messages, URL path segments,
client addresses and exception/code text can still be sensitive. Encoded secrets
and private values without recognised syntax may survive. Review which logfile
you publish and redact sensitive content at its producer when necessary.
Structured JSONL retains its existing caller-controlled data contract.

## Framing, continuity and bounds

Recognisable Python traceback continuations and conventional exception chains
can form one frame. Every traceback remains explicitly ambiguous/unattributed:
interleaved writers can produce plausible but unrelated lines. Another traceback
header or unrelated message splits the block. No nearby 500 response is correlated
with an exception, and no request ID or route template is invented.

| Limit | Value |
| --- | --- |
| Physical line prefix retained | 4 KiB |
| Frame text | 8 KiB / 32 lines |
| Source read work per text delivery turn | 64 KiB / 128 bounded line reads, including lookahead |
| Incomplete frame grace | 1 second, then finalisation at the next scheduled poll |
| Pending delivery | Existing 100-record / 512 KiB stream batch, plus at most one bounded lookahead record |
| Per-record wire ceiling | Existing 64 KiB |

A physical line over its cap emits one truncated prefix/notice. Its remaining
bytes are discarded through the next newline over bounded turns; the suffix is
not uploaded or retained. A traceback at its cap splits, with a truncation notice.
Incomplete fragments are reread only within their bounded grace period and then
emitted with `partial=true`; later fragments are marked ambiguous. Pending framing
state retains offsets/times, not an ever-growing source buffer.

The JSONL mode also bounds valid, malformed and oversized-suffix read work per
turn; completed invalid JSONL records retain their existing rejection accounting.
Text truncation is instead visible on the delivered event's `raw` metadata.

Existing files start at registration EOF; missing files start at byte zero when
they appear. There is no automatic historical import. Rotation drains the retained
predecessor descriptor before switching; finalising an unfinished predecessor
marks continuity uncertain. Truncation discards pending parser state and uses the
existing continuity warning. The protocol's legacy source warnings may still say
“JSONL source”; their continuity meaning also applies to adapted text. Repeated
replacement, server restart and unknown delivery outcomes follow existing stream
session fencing and batch deduplication, not latest-wins replacement.

While a batch awaits acknowledgement, later events stay in the source file.
Nothing buffers the whole outage in publisher memory. If the producer removes or
rewrites unread content, observation cannot reconstruct it. A close has a finite
drain budget and reports incomplete delivery when necessary. No audit/completeness
guarantee or globally atomic view of concurrently written files is implied.

## Minimal independent-file example

From a checkout, run the receiver and example in separate terminals:

```sh
plotsrv serve --host 127.0.0.1 --port 8765
python examples/follow_http_log.py /tmp/service.log --destination http://127.0.0.1:8765
```

Use a logfile already written by an independent process. For a disposable check,
a third terminal can append a synthetic line **after** the follower starts:

```sh
printf 'INFO: 127.0.0.1:54321 - "GET /health HTTP/1.1" 200\n' >> /tmp/service.log
```

Open the stream and inspect its records. Append unknown text or a traceback to
inspect fallback/framing. Stop the example with Ctrl+C. No production logger or
server-side project installation is required.

## HTTP suggestions and saved presentations

The server interprets accepted JSON independently of log syntax. For a recognised
stream, **Suggested views** appears beside **Save view | Reset view**. Open Recent
requests, Errors, Busiest endpoints, Traffic by status over time, or Endpoint event
activity. Actual validated duration adds Latency distribution, Latency over time
and Slowest retained requests. Change filters, columns or plot settings and save
in **My views** on this browser. These are settings for the same admitted source
ID, including on a catalogue-locked server. **Raw stream** restores access to every
loaded record, including unknown text and tracebacks. No generated source IDs or
extra global selector tabs are created.

Automatic recognition accepts the version-1 Uvicorn adapter envelope above, or
JSON objects containing a complete `method`, `path`, integer `status` combination,
either at the top level or together inside `http`. A record containing both
complete structured shapes is ambiguous and gets no automatic interpretation.
Methods are GET, HEAD, POST, PUT, DELETE, CONNECT, OPTIONS, TRACE or PATCH; statuses
must be integers 100–599, not strings or booleans. An explicit `route` at the same
level is treated as a supplied template. Otherwise endpoints are labelled request
paths, without inferring templates from numeric segments. Query and fragment
parts are removed from derived columns. The original structured JSON remains
unchanged and can still contain secrets: choose what you publish accordingly.

A numeric, finite, non-negative `duration_ms` has explicit units. Fields such as
`time`, `elapsed` and `latency` are not guessed to be durations. A timezone-aware
ISO `timestamp` (top level for structured input), adapter `source_timestamp`, or
adapter `publisher_observed_at` can establish the time axis. The first recognised
request fixes the mapping for that session: prefer event time, then publisher
observation time, otherwise server receipt time. Labels state this origin. Missing
or invalid later timestamps are excluded from time plots; they are never silently
replaced with a different clock. A provided route on the first request similarly
fixes template grouping; later missing routes stay missing. No nearest-request
traceback correlation is performed.

For other JSON keys, configure a small **server-side** mapping by logical source
ID. Lists are paths through JSON keys, including literal keys containing dots;
they are not filesystem paths. The server reads this setting on registration of a
new session. Restart the publisher session after changing it.

```yaml
stream-settings:
  http_profiles:
    "web:access":
      method: [request, verb]
      path: [request, target]
      status: [response, code]
      route: [request, template]     # optional, genuinely supplied template
      timestamp: [event_time]       # optional, timezone-aware ISO string
      duration: [elapsed]           # optional; unit is required with this field
      duration_unit: s              # ns, us, ms or s
    "worker:ordinary": false        # disable interpretation, retain raw stream
```

Mappings require method/path/status and allow only the optional roles shown.
Invalid mappings disable suggestions with a browser explanation; raw publication
continues. Each JSON key path has at most four components of at most 128 characters.
There are at most 256 configured overrides. Mapping/clock/template identity is
part of derived field identity, so a saved presentation pauses if its required
fields become unavailable or change meaning. A newly available recipe never
replaces an open or paused presentation automatically. Older browsers reject the
new `time-count` plot setting rather than silently changing its meaning; the
stream transport remains protocol 4 and older servers simply offer no suggestions.

### Evidence window and cost

Interpretation inspects fixed candidate paths, never searches every field or
rescans retention on append. Objects traversed must have at most 32 keys. A top-level object exceeding that
bound stops interpretation for its session, preventing uninspected keys from
impersonating derived fields. Raw data stays usable. Paths
must start with `/`, have no whitespace/control characters, and be at most 1,024
characters before query removal. Invalid requests remain raw; they are excluded
from request denominators. Optional invalid duration remains missing.

At most the newest **512 accepted records** still in raw retention are eligible;
the default raw window is 200. Older raw rows can still be inspected when the
operator increases raw retention, but do not contribute to HTTP recipes. The
browser also respects its loaded window and current filters. Endpoint bars select
the top ten categories and preserve remaining counts as **Other**. Endpoint event
activity uses one shared plot with a grouped supporting table, not a separate
facet dashboard; filter an endpoint to focus. Status classes have explicit legend
labels as well as colours. The default HTTP palette keeps success green, client
errors orange and server errors red even when a class is absent. Scatter marks
can overlap.

Counts over time use UTC-aligned half-open `[start, end)` intervals, starting at
one second and doubling the width until the evidence fits at most 40 buckets.
At most eight series and 320 count marks are drawn; HTTP uses five status classes.
A lower configured point limit refuses the plot with an explanation, without
dropping counts.
These are counts of retained evidence, **not exact service rates or availability**.
Missing buckets, rejected/malformed records, source gaps and disconnected periods
do not establish absence of actual traffic. Existing stream continuity, source
health and retention notices remain applicable. Latency summaries are calculated
from actual retained durations, never by averaging stored percentiles.

Stored sessions and existing generic compact summaries do not preserve the joint
HTTP fields required by these recipes. HTTP historical presentations are explicitly
unavailable there; existing raw-history and generic-summary controls remain usable.
There is no new history store, queue, worker, timer, polling request or publisher
payload. Projections add bounded server memory and browser-response bytes. Server
recipe construction examines at most 512 projections on a browser read. Sources
with over 100 raw columns, names over 256 characters, or more than 3,000 total name
characters do not get recipes, keeping ViewSpecs within their existing size cap.
A source key starting with the reserved `__plotsrv_http_` presentation namespace
disables interpretation for that session instead of overwriting source data.

### Reproducible mixed-traffic demo

In separate terminals from this checkout:

```bash
plotsrv serve --port 8000
```

```bash
# Create the file before starting the existing start-at-end follower.
touch /tmp/plotsrv-demo-http.log
python examples/follow_http_log.py /tmp/plotsrv-demo-http.log --destination http://127.0.0.1:8000
```

```bash
python examples/write_http_demo.py /tmp/plotsrv-demo-http.log
```

Open `web:access`, select Errors or a plot, customise and Save view, then return
to Raw stream to inspect the traceback. The synthetic writer exits after a small
fixed batch; nothing hooks or changes a real application's logging.
