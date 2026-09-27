# A continuously running public demo

Run a dedicated PlotSrv receiver showing only synthetic data, on its own
origin, behind HTTPS and a proxy that exposes selected read routes. Keep the
publisher separate from the receiver and keep its key out of the browser.
The controls below are a deployment baseline, not a claim that an internet
service cannot be overloaded.

## Preserve developer reports

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

## Receiver configuration

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

## Reverse proxy and edge

The [Caddy routing example](deployment-patterns.md#use-a-strict-read-only-caddyfile)
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

## Process, filesystem and network

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

## Verification and maintenance

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
