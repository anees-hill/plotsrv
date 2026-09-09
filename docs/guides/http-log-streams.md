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
