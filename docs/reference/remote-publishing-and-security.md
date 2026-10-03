# Remote publishing and security

For a working local/SSH/HTTPS setup, start with [Run plotsrv on another machine](../guides/run-on-another-machine.md).

## Configuration and precedence

File selection is unchanged: runtime/API/CLI config path, an existing file named
by `PLOTSRV_CONFIG`, then `./plotsrv.yml`, then `./plotsrv.yaml`. Instance selection
uses the runtime name before `PLOTSRV_NAME`. Each new namespace supports the
existing `default` and recursively merged `instances` (or `instance`) layout.
Existing render, storage, freshness, limits and UI sections retain their owners
and defaults; they do not move into these namespaces.

A publisher-only file can contain:

```yaml
publisher-settings:
  destination:
    url: https://dashboard.example/team/
    bearer_token_env: PLOTSRV_PUBLISH_KEY
    request_timeout_s: 2.0
    stream_request_timeout_s: 1.0
  discovery:
    target: ./src
    selection: ["imports:订单:daily"]
  watch:
    - path: ./results/orders.csv
      view_id: "imports:订单:daily"
      label: Daily orders
      section: Imports
      read_mode: tail
      materialization: auto
```

Only `destination` is wired into ordinary publication in this implementation.
`get_publisher_sources()` validates discovery/watch settings and returns
`PublisherSources(discovery_target, selection, watch)` using the existing
`WatchSpec` extended with `view_id`. It does not scan, import application code,
start watchers or contact a server. Config watch paths and explicit filesystem
discovery expressions (`./src`, `./app.py`) resolve beside the config; module
expressions remain module expressions. The CLI's source selection/override
wiring comes separately. CLI paths still use the CLI working directory.

| Choice | Resolution |
| --- | --- |
| Explicit `destination` URL or resolved `PublishTarget` | Replaces configured destination, including its credential and timeouts |
| Explicit URL together with explicit `host`/`port` | Error, even if apparently equivalent |
| Explicit URL with local launch intent | Error; legacy explicit `launch_server=False` still overrides `mode="local"` |
| Explicit legacy `host`/`port` | Replaces configured destination and credential; auto means remote |
| Explicit `launch_server=True`, or `mode="local"` without a launch override | Local bind; ignores configured remote destination |
| No explicit target/local intent, configured URL | Remote, including `launch_server=False` and `mode="remote"` |
| No configured URL | Legacy launch override, then mode; auto launches locally only when host/port were omitted |

Built-in legacy address remains `127.0.0.1:8000`. Passing these exact values
explicitly still counts as a remote choice in auto mode. CLI parsers retain
those defaults and expose `host_supplied`/`port_supplied` for later resolution.
There is no new destination-URL environment variable: environment values supply
the existing file/instance selectors and the named credential only.

## Destination and metadata shapes

`PublishTarget` retains `kind`, `host`, and `port`, and adds `base_url`,
`bearer_token_env`, ordinary/stream request timeouts, optional negotiated
`ProtocolCapabilities`, and a derived `credential_context`. Timeouts are finite,
greater than zero and at most 300 seconds. `url_for('/publish')` preserves the
base prefix. URL userinfo, queries, fragments and dot segments are rejected.
Bearer HTTP is allowed only for loopback; use HTTPS elsewhere. Explicit URL
requests refuse redirects and retain default TLS verification.

Targets store an environment-variable name and a process-local salted HMAC
context, never the credential value. Credentials appear only in the request
Authorization header. Repr, dataclass export and queue keys contain no bearer
value. Different credential contexts cannot coalesce; rotating a key causes
already-resolved work to fail closed until resolved again. No credential cache
or persistent identity database is created. Remote error diagnostics omit
server response bodies and exception details that could echo a credential.

`ViewDescriptor` is a strict JSON-safe metadata object with:

- `metadata_version: 1`, exact `view_id`, `label`, optional `section`;
- `kind`: `unknown`, `plot`, `table`, `artifact`, or `stream`;
- optional plain-text `description`, and a bounded list of capability names;
- optional `SourceMetadata(basename, source_type, scope)`, where scope is
  `publisher`, `server`, or `unknown` provenance.

IDs/labels/sections are bounded to 512 Unicode code points, descriptions to
2,048, basename to 255, source type to 64, and capabilities to 32 names of 64
code points each. Text must be well-formed Unicode without control characters.
The complete descriptor is capped at 16 KiB of UTF-8 JSON; `from_json()` checks
that bound before decoding. A catalogue holds at most 1,024 validated descriptors
and rejects duplicate IDs (including conflicting declarations). Source metadata
has no path field, and basename rejects path separators. Provenance never grants
filesystem access, changes admission, or enables storage/checks.

```python
from plotsrv.contracts import SourceMetadata, ViewDescriptor

metadata = ViewDescriptor(
    view_id="imports:订单:daily", label="Daily orders", section="Imports",
    source=SourceMetadata(basename="orders.py", source_type="python"),
)
assert ViewDescriptor.from_json(metadata.to_json()) == metadata
```

Discovery's `DiscoveredView.descriptor()` produces this shape with exact IDs.
When kind is not statically declared it uses `unknown` with no capability
guarantees; an explicit supported publication kind is preserved. Passive registration preserves
those IDs while waiting for runtime data. `@view(view_id=...)` and
`WatchConfig(view_id=...)` also preserve explicit identities. Paths and displayed
labels are independent of explicit IDs. Existing legacy paths that do not use
the descriptor are not retroactively subjected to its new metadata bounds.

`ProtocolCapabilities` defines `protocol_version: 1`, `stream_protocol_version:
4`, a capability list, `server_generation`, and `dashboard_scope`. Capability
names default to empty; no future route is advertised. This is the response
shape returned by the authenticated `/capabilities` handshake.
Stream protocol 4 and its session/sequence/acknowledgement rules stay unchanged.
Stable error category strings are `incompatible_protocol`,
`unauthorised_publisher`, `inadmissible_view`, `oversize_data`, `invalid_request`,
and `ingestion_busy`.


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
override them. See [Standalone servers and direct remote publishers](remote-publishing-and-security.md)
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

## Catalogue bootstrap

Catalogue locking is optional. Initialise a reviewed complete catalogue with `plotsrv publish --seal-catalogue`; later publishers cannot silently extend it. See [Publisher/server internals](../development/publisher-server-internals.md#bootstrap-transaction) for transaction details.

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
[bootstrap transaction and security matrix](remote-publishing-and-security.md).

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

Run one server process per instance. Shared-state clustering remains outside this
feature. For optional catalogue registration and foreground remote file watches,
see [Publisher agent](cli.md#publisher-helper).

Source defaults, static discovery and local `run` overrides are described in
[Configured sources](cli.md#configured-sources). `serve` continues to ignore these
publisher source settings.

## Public deployments


Run a dedicated PlotSrv receiver showing only synthetic data, on its own
origin, behind HTTPS and a proxy that exposes selected read routes. Keep the
publisher separate from the receiver and keep its key out of the browser.
The controls below are a deployment baseline, not a claim that an internet
service cannot be overloaded.

### HTML trust

Selecting or explicitly publishing HTML is the developer's trust decision;
there is no per-file prompt. Trusted reports keep CSS, JavaScript, forms,
downloads and normal browser functionality. Leave `html_sanitize: false` and
`html_sandbox: ""` for that behaviour. Browser regression coverage exercises
these features inside the actual UI.

These reports have the dashboard origin's privileges, including access to
other public view data. Trust the report's scripts and external dependencies
as well as its author. Use a dedicated origin without unrelated applications,
shared privileged cookies or production authentication sessions. Do not offer
anonymous uploads or give visitors the publisher key. Sanitization of
anonymous remote content does not make open public ingestion a supported demo
design.

Existing payload and preview size limits still apply. A report using relative
sibling files needs those assets hosted at explicit URLs; selecting one report
does not expose its containing directory. File-backed reports use
`/watched-file/raw`, so that route must be allowed if the demo uses them.

### Public receiver configuration

Start with a fresh working directory and this example, adjusting the exact
catalogue to your producer. Supply a newly generated publisher token through
the service environment; never commit it or send it to frontend code.

```yaml
server-settings:
  bind: {host: 127.0.0.1, port: 8000}
  ingestion:
    bearer_token_env: PLOTSRV_PUBLISHER_TOKEN
    allow_remote_without_key: false
  admission:
    mode: catalogue-locked
    allowed_ids: ["demo:plot", "demo:table", "demo:log", "demo:report"]

security-settings:
  shutdown_enabled: false
  docs_enabled: false
  openapi_enabled: false
  tracebacks_enabled: false
  control_local_only: true
  views_local_only: true
  status_local_only: false  # This demo's status data is deliberately public.
  history_local_only: true
  internal_read_local_only: false  # Only synthetic selected files in this instance.

render-settings:
  html_sanitize: false
  html_sandbox: ""
  markdown_sanitize: true

storage-settings:
  enabled: false

limits:
  published_objects:
    max_plot_bytes: 1048576
    max_table_rows: 2000
    max_table_columns: 50
    max_artifact_text_chars: 200000
    max_json_container_items: 5000
  watched_files:
    max_mb: 1
```

Run `plotsrv serve --config demo.yml` under the isolated service account.
Configure the separate publisher's destination as the private receiver URL and
`bearer_token_env: PLOTSRV_PUBLISHER_TOKEN`. The publisher key grants permission
to publish active reports, not just passive data. Do not embed a privileged
production process inside the public receiver.

For public history, deliberately set `history_local_only: false`, enable the
necessary routes below, use finite snapshot retention and a dedicated storage
volume with a hard quota. Example persistence limits:

```yaml
storage-settings:
  enabled: true
  root_dir: /var/lib/plotsrv-demo
  default_keep_last: 10
  default_min_store_interval: 30s
  max_snapshot_size_mb: 4
  max_pending_tasks: 16
  max_pending_mb: 32
  latest:
    enabled: true
    max_size_mb: 4
    min_store_interval_s: 5
  streams:
    max_bytes_per_view_mb: 8
    max_total_mb: 64
    keep_last_sessions: 4
    raw_retention: null
```

Latest writes skipped by the interval do not receive a delayed flush; after
restart the display can therefore lag the last live update. Disabling writes
does not erase old files or revoke access to already restored live state.
Use a fresh store when changing the data published by a public instance.

### Reverse proxy and edge

The [Caddy routing example](#use-a-strict-read-only-caddyfile)
is a starting point. Match both method and exact route; reject everything
outside the allowlist. In Caddy, matchers in the same set must all match.
See [Caddy request matchers](https://caddyserver.com/docs/caddyfile/matchers).

| Feature | Allowed public read paths |
|---|---|
| Dashboard and content | `/`, `/plot`, `/artifact`, `/table/data` |
| UI assets | `/static/*`, `/assets/*` |
| Live refresh | `/updates` |
| Stream UI | `/stream/data`, `/stream/summary`, `/stream/status` |
| Public synthetic status | `/status`, `/checks` |
| Downloads and selected file reports | `/table/export`, `/watched-file/raw`, `/watch/source` |
| Capability discovery for the history UI | `/history/navigation` |
| Optional persistent history and comparison | `/history/month`, `/history`, `/stream/history`, `/compare/latest` |

Only GET and HEAD should reach these paths; some application routes support
only GET and legitimately return 405 to HEAD. No public `/publish`, ingestion,
catalogue, watch mutation, stream mutation, control, settings, shutdown or API
documentation routes. The publisher uses the private listener instead.

Use a fixed hostname and reject unknown hosts at the edge. The proxy must
overwrite forwarding headers and must never inject the publisher credential
into public requests. Keep proxy provenance visible: stripping all forwarding
headers can make a forwarded request appear to be a direct local request.
If another load balancer precedes the proxy, trust only its actual source
addresses. See [Caddy proxy header handling](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

Use these initial limits, then adjust against normal representative use:

| Control | Initial value |
|---|---|
| Dynamic requests per source IP | 20/second, burst 80; separate static-asset allowance |
| Active dynamic requests | 32/IP, 128/instance |
| Active SSE connections | 8/IP, 128/instance; multiple tabs consume separate slots |
| SSE reconnect requests | 2/second/IP, burst 10 |
| Request header deadline | 10 seconds |
| Ordinary upstream/read and stalled-client write deadlines | 30 seconds |
| SSE upstream idle deadline | 60 seconds, longer than PlotSrv's heartbeats |
| Request target/header size | 4 KiB target; 16 KiB headers |
| Request body | Reject bodies on public read routes; never forward public writes |

Rate limits alone do not bound long-lived streams. An SSE read timeout measures
idle time, not total lifetime: heartbeats keep healthy connections alive.
Bound connection counts and stalled-client writes separately. Disable proxy
response buffering for `/updates`; do not cache dynamic data or reports. If
using Nginx, its [request rate controls](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html),
[connection controls](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html)
and [proxy buffering/timeouts](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
are distinct settings. Stock Caddy's route allowlist alone does not implement
this resource policy; use edge-platform limits or an appropriate configured proxy.

Set `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` at the
proxy. Do not apply a blanket script-blocking CSP or sandbox directive to
trusted reports: it would disable the report features this design preserves.
If you opt into report sandboxing, test every report feature it affects.

### Process, filesystem and network

- Use an unprivileged dedicated UID in a container or VM. Start with a 512 MiB
  memory limit, one CPU, 64 processes/threads and a 1,024-file-descriptor limit;
  adjust only if representative normal use needs more.
- Mount the application and selected synthetic reports read-only. Keep the
  root filesystem read-only, with a bounded temporary directory. Mount no
  home directories, SSH/cloud credentials, source secrets, host sockets or
  container-engine socket. Drop capabilities and enable no-new-privileges.
- Keep writable storage private to this one receiver. With persistence,
  enforce an initial 256 MiB filesystem/volume quota; without persistence,
  provide only bounded temporary space. Rotate logs, for example four 10 MiB
  files. App retention is not a disk quota.
- On POSIX, watched-source reads refuse replacement symlinks at every path
  component and special files. On systems lacking descriptor-relative
  no-follow opens, the fallback cannot eliminate ancestor replacement races;
  keep selected directories unwritable by other principals. Regular file
  rotation is supported, but a file being rewritten can still produce an
  inconsistent preview.
- Expose only HTTPS (and HTTP if needed for redirect/certificate issuance).
  Bind PlotSrv to loopback or a private container network; firewall its port
  against public ingress. Keep SSH/admin access on an administrative network.
- Deny receiver egress to the internet, production networks and cloud
  metadata endpoints unless a specific server-side feature requires it.
  Disable webhooks unless intentionally demonstrated. Browser-loaded report
  resources are fetched by the visitor's browser, so receiver egress blocking
  does not inherently break a report's external CSS or JavaScript.
- Use restart backoff and monitor memory, CPU, volume use, open connections,
  rejected ingestion, storage skips/failures and restarts. Keep the receiver's
  resource allocation separate from the publisher/observed process.

### Verification and maintenance

Before opening the listener, validate the actual proxy configuration and make
harmless checks against your own local staging instance: normal UI/report
interactions work, blocked methods/routes stay blocked, direct upstream access
is impossible from the public network, and disconnected clients release their
slots. Check public-history policy both through the selector and direct
payload URLs. Validate IPv4, IPv6 and any container port mappings.

Use `uv sync --locked` for reproducible installs. CI audits the locked Python
runtime dependencies; repeat the audit and rebuild the deployment regularly.
Also scan the deployed OS/container and review bundled browser libraries.
As of this change, Bleach 6.4 is its final release; plan a separately tested
replacement for the paths that still sanitize untrusted content.
See [Bleach's maintenance notice](https://bleach.readthedocs.io/en/latest/changes.html).

This baseline has not been applied to any deployed demo by this change. The
connection values are initial operational limits, not measured capacity or a
load-test result.

### Bound browser update subscriptions

`/updates` uses SSE (ordinary HTTP streaming, not WebSockets). Configure finite
admission separately from proxy request rates:

```yaml
browser-update-settings:
  max_connections: 96
  max_connections_per_client: 64
  max_connection_seconds: 600
```

The example above is a conference profile for a shared IP; the smaller per-IP
values in the general baseline table need adjustment for that situation.
These limits apply per receiver process, across all views. Defaults are 1024,
1024 and 600 respectively; counts must be integers between 1 and 1024 and the
lifetime between 1 and 86400 seconds. Invalid values fall back to defaults.
The client key is the ASGI client address, not an arbitrary forwarding header.
Configure trusted proxy forwarding correctly; otherwise a proxy's clients may
all count as one client. A shared conference IP can legitimately contain dozens
of browsers, so the per-client allowance must account for that.

The application closes SSE responses at the lifetime, including blocked writes
(with at most a one-second closing grace period); browsers reconnect using their
existing backoff and revision handling. Rejected subscriptions return 503 with
Retry-After. Subscription cleanup covers disconnection and expiry. Set the proxy
upstream allowance above the SSE total (for example 128 versus 96) to leave
capacity for ordinary reads. Caddy's `stream_timeout` is not an SSE lifetime
control. Limits protect capacity, not fair service under a distributed attack;
retain proxy request limits and monitor saturation. No HTML sandbox or report
sanitization change is involved.

## Read-only Caddy example

For a read-only dashboard origin, use an allowlist rather than forwarding all routes. Publisher requests need a separate private or authenticated path. Adapt the domain and storage settings to your deployment.

### Use a strict read-only Caddyfile

Edit the Caddyfile:

```bash
sudo nano /etc/caddy/Caddyfile
```

Use an allow-list so only the routes needed for viewing the UI are public:

```caddy title="/etc/caddy/Caddyfile"
demo.plotsrv.com {
    @public {
        method GET HEAD
        path / /plot /table/data /artifact /status /checks /table/export /updates /stream/data /stream/status /stream/summary /history/navigation /static/* /assets/*
    }

    handle @public {
        reverse_proxy 127.0.0.1:8000
    }

    respond 404
}
```

This configuration means:

- selected UI routes are proxied to plotsrv
- all other routes return `404`
- write/control routes such as `/publish` and `/shutdown` are not publicly reachable
- new or unexpected routes are blocked by default

This is the routing portion of a public read-only demo where trusted code
publishes the content. It does not supply connection limits or process
isolation. Add `/watched-file/raw` and `/watch/source` when demonstrating
downloads or file-backed reports, and enable history routes only with finite
retention and a disk quota; see the [full baseline](#public-deployments).

### Validate and reload Caddy

Validate the configuration:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

Reload Caddy:

```bash
sudo systemctl reload caddy
```

Check the service:

```bash
sudo systemctl status caddy
```

### Test the deployment

First test plotsrv locally on the server:

```bash
curl http://127.0.0.1:8000
```

Then test the public hostname:

```bash
curl -I https://demo.plotsrv.com
```

Blocked routes should return `404`:

```bash
curl -I https://demo.plotsrv.com/publish
curl -I https://demo.plotsrv.com/shutdown
curl -I https://demo.plotsrv.com/openapi.json
```

### Security considerations

Before exposing plotsrv beyond localhost, consider:

- who can access the UI
- whether the data is safe to publish
- whether tracebacks are enabled
- whether watched files may contain sensitive data
- whether published tables or objects contain sensitive data
- whether write/control endpoints are blocked
- whether the reverse proxy provides authentication
- whether the service is reachable from the public internet

For public demos, prefer:

- binding plotsrv to `127.0.0.1`
- exposing it through a reverse proxy
- using HTTPS
- allowing only read-only UI routes
- blocking everything else by default
- publishing only non-sensitive demo data

