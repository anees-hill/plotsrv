# Publisher ingestion and catalogue admission

Publisher mutations have a dedicated authentication and admission boundary.
They do not require disabling `security-settings.control_local_only`. A single
shared bearer key authenticates trusted publishers; it is not dashboard login,
tenant isolation, or per-view authorisation. Dashboard reads retain their
existing read-security settings and require proxy authentication if private.

## Server configuration

```yaml
server-settings:
  ingestion:
    bearer_token_env: PLOTSRV_INGEST_KEY
    allow_remote_without_key: false
  admission:
    mode: catalogue-locked
    # Omit allowed_ids to await an explicit complete bootstrap transaction.
    # Alternatively provide the complete ID union here:
    # allowed_ids: ["etl:orders", "logs:requests"]
```

Set the named environment variable before starting the server. A missing,
empty or malformed configured key fails setup closed. The server retains a key
digest, and changes require a process restart. Publisher configuration refers
to its own environment variable containing the same key; variable names need
not match. Keys belong only in the Authorization header, never URLs, browser
storage or catalogue manifests.

No key remains the default for ordinary loopback use. Anonymous remote ingestion
requires `allow_remote_without_key: true` and emits a warning. Explicitly binding
on a non-loopback address does **not** enable anonymous remote ingestion: it
warns about dashboard exposure while the ingestion boundary still rejects
remote anonymous clients. Forwarded anonymous local requests are rejected.

Use HTTPS through a reverse proxy for remote bearer publication. Exclude
administration endpoints from proxy routing. A proxy may conceal the original
peer, so loopback checks are not human authentication. In particular, do not
proxy anonymous ingestion through a loopback connection while stripping its
forwarding headers. Use a publisher key when crossing a proxy/trust boundary.
Browser-originated mutation requests are rejected, even on loopback.

Start a server without discovering project code:

```sh
plotsrv serve --config server.yml
```

`server-settings.bind` supplies the bind defaults; explicit `--host` and `--port`
override them. See [Standalone servers and direct remote publishers](remote-publishers.md)
for independent server/publisher configurations, direct Python examples and
standalone restoration policy.

## Endpoint and security matrix

All publisher endpoints below use the same key/no-key policy. A bearer key
never grants filesystem or administrative access.

| Endpoint | Method | Rights and behaviour |
| --- | --- | --- |
| `/capabilities` | GET | Authenticated publisher read; protocol versions, supported routes, admission state, generation, dashboard scope and limits; no source paths, keys, payload data or admin settings |
| `/catalogue/register` | POST | Register/update bounded source descriptions for admitted IDs; dynamic mode admits new IDs; no implicit sealing |
| `/catalogue/bootstrap` | POST | Explicit complete-manifest transaction for catalogue-locked mode |
| `/publish` | POST | Ordinary bounded data, including current HTTP watch updates; admitted-ID gate before creating views or freshness/storage effects |
| `/stream/register` | POST | Stream protocol 4 registration, admitted-ID gate and existing session ownership checks |
| `/stream/append` | POST | Stream protocol 4 ordered/deduplicated batches, same authentication and ID gate |
| `/stream/heartbeat` | POST | Same authentication and gate; does not claim new source data |
| `/stream/close` | POST | Same authentication and gate; existing session fencing remains |
| `/shutdown` | POST | Disabled by default; when enabled, direct local administration only, independently of the legacy control-locality switch; bearer and forwarded requests rejected |
| `/views`, `/status`, `/history`, data/snapshot/stream reads | GET | Existing browser/read-security policies; publishers need only `/capabilities`, so no read permissions are relaxed |
| Config editing, local-file registration, remote file access | — | No publisher HTTP rights or new routes |

The shutdown route now correctly receives a FastAPI `Request` (its earlier
untyped argument could be interpreted as a query parameter). Cross-origin local
administrative mutations are rejected; keep shutdown disabled and exclude it
from public reverse proxies. The publisher key is not an admin credential.

## Bootstrap transaction

A locked server without `allowed_ids` starts awaiting bootstrap. Publication,
individual registration, heartbeats, and elapsed time cannot seal it. Send one
complete manifest to `/catalogue/bootstrap`, using `Authorization: Bearer …`:

```json
{
  "protocol_version": 1,
  "views": [
    {"view_id": "etl:orders", "label": "Orders", "section": "ETL"},
    {"view_id": "logs:requests", "label": "Requests", "section": "Logs"}
  ]
}
```

Descriptors use the [bounded metadata contract](../about/publisher-contracts.md).
The same body shape applies to `/catalogue/register`. Registration creates empty
placeholders without fabricating data arrivals. Source basename/type/scope and
optional descriptions remain metadata; they cannot enable storage, alter
checks, select a server path, or disable authentication.

Bootstrap validates the entire manifest before any writes. Under the shared
store lock it registers all entries and seals the exact ID set for this process
generation. Competing different bootstraps yield one winner and a conflict.
An identical canonical manifest is idempotent regardless of descriptor order;
conflicting retries return 409 without mutation. Identical retries do not
rewrite metadata or emit new catalogue updates. Missing default descriptor
fields and their explicit default values are equivalent.

A configured allowlist starts sealed. It may receive one matching complete
metadata bootstrap; a different ID set is refused. `allowed_ids: []` is an
explicit empty sealed set, distinct from omitting `allowed_ids`.

Include the complete union of expected AST, watch, and explicitly named dynamic
IDs. All key holders are trusted to perform bootstrap. For multiple projects,
coordinate that union or configure the allowlist; the first project's partial
manifest is not expanded automatically by later publishers. There is no unlock
endpoint. Restart the process to change the sealed set.

After sealing, admitted IDs continue accepting new data, schema and ordinary
view-kind changes. A stream and an ordinary view cannot concurrently own the
same ID. Descriptors are placeholders until actual data establishes the store
kind; catalogue locking freezes source IDs, not data schemas or rendering.
Direct in-process publication, watch metadata registration, error artifacts,
stream methods and storage restoration obey the same ID policy. Restored
unadmitted views are skipped; they cannot authorise fresh writes or seed an
unexpected stream history entry.

The handshake's server generation is process state, separate from stable
browser preference scope. Stream responses retain the existing protocol 4
receiver/session generation and acknowledgement semantics. This change does
not alter stream v4 semantics or add a browser poller. Direct publisher
negotiation and restart handling are described in the remote-publisher guide.

## Limits and errors

Authentication runs before body consumption/decoding. Actual streamed bytes
are counted regardless of missing or misleading Content-Length. Compressed
request bodies are rejected. Limits are server-owned hard bounds:

| Resource | Bound |
| --- | --- |
| Ordinary `/publish` wire body | 8 MiB |
| Each catalogue body | 1 MiB |
| Stream wire body | Existing 640 KiB; existing 64 KiB record / 100 records and 512 KiB batch bounds also apply |
| JSON nesting | 100 |
| JSON structural tokens outside strings (`{`, `[`, `,`, `:`) | 500,000; rejected before JSON object expansion |
| Catalogue/state IDs | 1,024, including admitted state created through error/status mutation paths |
| Descriptor | Existing 16 KiB UTF-8 plus individual field bounds |
| Concurrent ingestion requests | 4 across read, preparation and mutation; no waiting queue |
| Ingestion token bucket | 100 requests/second with a 100-request burst, including rejected authentication attempts |
| Body receive deadline | 10 seconds |

Catalogue count and byte bounds apply together; 1,024 maximum-size descriptors
will not fit in one HTTP manifest. Keep manifest metadata concise. UTF-8 JSON
structural checks and decoding run off the event loop; excessive complexity
and non-finite JSON constants are rejected. The body deadline does not cancel
arbitrary renderer work. Existing object/render/storage limits remain additional
constraints, and these wire/concurrency bounds are not a total process-RSS cap.

New rejection details have `category` and `reason` fields, for example:

```json
{"detail": {"category": "inadmissible_view", "reason": "catalogue_awaiting_bootstrap"}}
```

Categories include `unauthorised_publisher` (401/403), `inadmissible_view`
(403/409/422), `incompatible_protocol` (422), `oversize_data` (413),
`invalid_request` (408/415/422), and `ingestion_busy` (429). Existing data/stream
validation retains its compatible status/detail messages. Errors do not echo
keys, manifests or arbitrary remote request bodies. No per-rejected-ID cache or
unbounded error history is created. Authentication and ID-policy failures do not
create views, advance freshness, or queue storage. Existing admitted-payload
validation errors may still produce the established error artifact.

## Remote content and compatibility

HTTP content is untrusted even when a request originates on loopback or carries
a valid publisher key. HTML/Markdown safety applies to the actual selected
renderer, including fallback selection. Publisher `unsafe`, `unsafe_html`,
`sandbox`, and `interactive` flags cannot opt out. Server-supplied provenance
markers persist with the payload, so history uses the same safe rendering.
Remote SVG image artifacts are rejected. Table HTML is regenerated from bounded
data with escaping; client-supplied inline HTML is ignored. Trusted in-process
HTML/Markdown retains its existing explicit rendering options.

HTTP `publish_source="watch"` no longer bypasses ordinary artifact hard limits;
HTML/Markdown dictionary text is checked too. Local file-backed reads keep their
existing source limits. The upcoming remote-watch representation will define its
own validated source-specific bounds, rather than trusting a publisher flag.

Ordinary publication and persistence remain best effort. These changes do not
promise durable or exactly-once delivery. Authentication and admission failures
stay failures; publishers must not fall back to an unprotected route or start a
local server. Run one serving process per instance: catalogue state, locks,
budgets and event notifications are process-local.
