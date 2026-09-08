# Standalone servers and direct remote publishers

Run `plotsrv serve` beside the dashboard and its storage. Run your Python
application beside its own code and data. The server does not discover, import
or watch the application, and starts normally with zero views. The empty page
says “Waiting for a publisher”. No publisher agent or extra CLI process is needed.

## Start the server

For a local, anonymous example:

```sh
plotsrv serve --host 127.0.0.1 --port 8000
```

For keyed ingestion, put this in the server's `server.yml`:

```yaml
server-settings:
  bind:
    host: 127.0.0.1
    port: 8000
  ingestion:
    bearer_token_env: PLOTSRV_INGEST_KEY
  admission:
    mode: dynamic
```

Set `PLOTSRV_INGEST_KEY` in the server environment, then run:

```sh
plotsrv serve --config server.yml
```

`--host` and `--port` override server configuration individually; omitted values
use configuration, then loopback:8000. `--name` selects an existing configuration
instance. `--quiet` reduces server logs. Ctrl+C or SIGTERM uses the foreground
server's normal shutdown and bounded storage drain. There is no target argument,
AST scan, callable execution or configured publisher/watch startup in `serve`.
Existing `plotsrv run`, its discovery defaults and explicit execution modes stay
available for combined local use.

The publisher key authenticates trusted producers. It **does not protect human
dashboard reads** or provide tenant isolation. Protect private reads at your
proxy, use HTTPS for remote publication, and exclude management endpoints such
as `/shutdown` from public proxy routing. TLS may terminate at the proxy.
Anonymous remote ingestion requires the explicit server opt-in described in
[Publisher ingestion](publisher-ingestion.md). A bearer destination using plain
HTTP outside loopback is rejected; certificate verification is never disabled.

## Publish from another process

The application directory can have its own `plotsrv.yml`:

```yaml
publisher-settings:
  destination:
    url: https://dashboard.example/team/
    bearer_token_env: PLOTSRV_PUBLISH_KEY
    request_timeout_s: 2
    stream_request_timeout_s: 1
```

Set the publisher's named environment variable to the same key. Its name need
not match the server variable. For the local example use
`http://127.0.0.1:8000/`; omit `bearer_token_env` on both sides for anonymous
loopback use. Config files and source files need not be shared between machines.
Config selection still uses the existing cwd file, `PLOTSRV_CONFIG`, and instance
rules. Base paths and IPv6 addresses use the shared destination resolver.

A directly publishing script can send ordinary data and follow a local JSONL
source:

```python
import json
import time
from pathlib import Path

import pandas as pd
from plotsrv import publish_view, stream_view, view

@view(view_id="etl:summary", label="Summary", section="ETL")
def summary():
    return {"state": "running"}

summary()  # configured remote destination activates publication
publish_view(pd.DataFrame({"orders": [12, 18]}), view_id="etl:orders")
publish_view("Import started", view_id="etl:message")

source = Path("events.jsonl")
source.touch(exist_ok=True)
stream = stream_view(source=source, view_id="etl:events", label="Events")
try:
    with source.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"event": "import_started"}) + "\n")
    time.sleep(1)  # the real application normally continues doing its own work
finally:
    stream.stop(timeout=1)
```

The file is opened only by the publisher. Existing stream sources start at EOF;
new records are followed in the existing bounded daemon worker. `stream.health`
reports source and delivery counters, errors and retry delay. A final drain is
best effort: inspect health when delivery matters, and retain the original log.

`publish_view(..., destination="https://…/prefix/")` and
`stream_view(..., destination="https://…/prefix/")` override configured routing.
An explicit URL replaces the configured credential too; for an authenticated
API override, pass a `PublishTarget` containing `base_url` and
`bearer_token_env`. Explicit legacy `host`/`port` also replaces configured routing
and its credential; it cannot be combined with `destination`.
No-config `publish_view` retains its existing attached-local-server behaviour.
No-config `stream_view` retains its existing loopback receiver behaviour.
A metadata-only `@view` stays passive unless it has explicit publishing options
or a configured remote destination when the decorator is evaluated.

## Negotiation, failures and restart

All ordinary HTTP publications (including traceback and shared runtime helpers)
and all four stream mutation routes use the shared authenticated transport.
It negotiates `/capabilities` before publication, without serialising user data
to test connectivity. Only advertised, implemented features are used. Redirects
are refused, including same-host redirects; correct the configured base URL
instead of sending credentials to a redirect destination.

The cache holds at most 64 target/security contexts and expires capabilities
after 30 seconds. Credential values are never cache keys. A rotated credential
requires re-resolution; already queued work fails closed. Failed exchanges
invalidate capability metadata. Stream retries retain pending batch IDs and use
the existing protocol 4 receiver/session fencing: after a receiver restart the
client re-registers with a new session, preserving explicit continuity semantics.
Replayed/deduplicated records do not create new server receipt observations.

There is no transport retry queue. Ordinary synchronous calls keep their
rendering/network cost; `async_=True` uses the existing bounded, coalescing view
worker and `flush_views(timeout=...)` remains bounded. The stream follower keeps
one pending ordered batch, with its existing exponential retry cadence. Permanent
stream auth/admission/protocol failures pause attempts for at least 30 seconds.
Ordinary target failures use a 5-second cooldown, or 30 seconds for credentials,
authentication, protocol or redirect failures. Other destinations can continue.
There is no anonymous downgrade or local-server fallback after remote failure.
Application results and exceptions retain their normal best-effort behaviour;
explicit debug mode can still raise publication errors for diagnosis.

Warnings are rate-limited per cached context and contain fixed categories and
allowlisted reasons, never raw response bodies, credentials or target URLs.
Capability responses and acknowledgements are capped at 64 KiB. Outgoing wire
caps match the server's ordinary/catalogue/stream caps. Each exchange closes its
response and socket; the transport creates no background thread or retained
connection pool per publication. Small capability metadata is cached, not data.

Connect/read socket operations use the configured bounded timeout. Handshake
lock waiting and the request following negotiation share their request budget.
A cold synchronous ordinary publication also performs its pre-capture handshake;
its total cost includes that handshake, preparation and the data request.
These are socket-operation bounds, not hard cancellation of arbitrary Python
rendering, DNS resolution or a peer trickling response bytes. Final drains do
not promise durable delivery or interrupt arbitrary user code.

## Catalogue locking and stored views

A dynamic server learns logical view IDs from accepted publications. A locked
server requires a configured complete allowlist or an explicit complete
bootstrap manifest. Direct publishers never guess that union, bootstrap a
partial project automatically, or unlock a server after restart. Until bootstrap
is available, ingestion reports `catalogue_awaiting_bootstrap`; unknown IDs after
sealing report `view_not_admitted`. See the
[bootstrap transaction and security matrix](publisher-ingestion.md).

Standalone latest-state restoration treats the existing `discovered` scope as
`all`: stored logical ID, label and section provide the catalogue without AST
files. Explicit `none`, disabled startup restoration, and existing `all` retain
their meanings. Local `run` keeps its existing `discovered` policy. Latest views
retain the original update timestamp and restored marker, and restoration does
not record a fresh data arrival or write another snapshot. Existing snapshots
remain available through history; they are not replayed as new live data.

Admission still gates restoration. A locked server awaiting bootstrap skips
unadmitted stored live state; configured admitted IDs can restore. Historical
content cannot authorise writes. Bootstrap after startup creates waiting entries;
it does not automatically rerun startup restoration. Restart with an appropriate
allowlist when admitted stored live state should be loaded at startup.

Run one server process per instance. Shared-state clustering, the publisher-agent
CLI and remote file-watch orchestration are outside this feature.

Source defaults, static discovery and local `run` overrides are described in
[Configured sources](configured-sources.md). `serve` continues to ignore these
publisher source settings.
