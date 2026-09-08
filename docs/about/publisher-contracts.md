# Publisher and server contracts

Ordinary `publish_view()` accepts a destination URL or the configured
`publisher-settings.destination`. HTTP(S), IPv6, and reverse-proxy prefixes
are supported. For example:

```python
from plotsrv import publish_view

publish_view({"rows": 12}, destination="https://dashboard.example/team/",
             view_id="imports:订单:daily", label="Daily orders")
```

This posts to `/team/publish`. Failed publication never starts a local fallback.
Normal publication remains best effort; `PLOTSRV_DEBUG=1` makes setup/delivery
errors raise. Setup tools can call `plotsrv.config.resolve_publish_target()`
to validate before running application code.

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

## Server setup contract

A server-only file can configure ingestion authentication and admission. See
[Publisher ingestion](../guides/publisher-ingestion.md) for the enforced endpoint
matrix, explicit bootstrap transaction and proxy requirements. `plotsrv serve`
uses the bind fields; explicit CLI host/port override them. See
[Direct remote publishers](../guides/remote-publishers.md) for working examples.

```yaml
server-settings:
  bind: {host: 127.0.0.1, port: 8000}
  ingestion:
    bearer_token_env: PLOTSRV_INGEST_KEY
  admission:
    mode: catalogue-locked
    allowed_ids: ["imports:订单:daily"]
storage-settings:
  enabled: true
```

`get_server_connection_config()` validates this as
`ServerConnectionConfig(bind_host, bind_port, bearer_token_env, admission_mode,
allowed_ids)`. Defaults are loopback:8000, no key and dynamic admission. In locked
mode, absent `allowed_ids` means awaiting a manifest; an explicit empty list is
an empty manifest. Duplicate IDs and lists over 1,024 entries are rejected.
Configured publisher and server keys are independent environment references;
a missing/invalid configured value raises at resolution. Combining both
namespaces in one file is supported. Server resolution never resolves publisher
sources or requires the publisher key; publisher resolution never requires the
server key. The ingestion layer enforces sealing and authentication at server
setup and on publisher mutations.

New namespaces and nested mappings validate their supported keys. Future feature
owners should add named, validated fields to their owning mapping with focused
tests, rather than installing speculative defaults or accepting arbitrary
metadata as configuration.

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

## Identity, bounds and guarantees

`ui_config.get_dashboard_scope(public_serving_url)` derives a stable preference
namespace from the configured instance name plus normalised serving origin and
base path. It is separate from the ephemeral stream/SSE generation, which still
fences reconnects and event cursors. Use the externally visible URL, not a bind
address. Browser storage migration/wiring comes with the browser feature; no
existing preferences are rewritten here.

The descriptor bound is exact for its canonical UTF-8 encoding. Catalogue count
and identity round-trips are exact. Source capture, delivery and persistence
remain best effort: ordinary queues coalesce latest state, memory estimates are
not exact object sizes, and successful HTTP transport is not durable storage.
Multiple ordinary publishers of one ID retain latest-accepted semantics; stream
sessions retain their existing ownership/fencing rules.

Publisher preparation limits and `publish-settings.live` queue limits apply in
the publishing process. Server render, ingestion and storage limits apply at
the receiver and cannot be raised by metadata. Existing stream limits remain
64 KiB/record, 100 records and 512 KiB/batch, and 640 KiB/request. Descriptor
validation does not replace an HTTP body limit: the receiving route must enforce
wire bounds before decoding, and catalogue receivers need an aggregate body
bound in addition to the count bound. Ordinary explicit-destination response
reads are capped at 64 KiB. Request timeouts are socket-operation bounds, not
hard wall-clock cancellation of arbitrary parsing, rendering or slow trickles.

Ordinary and stream publishers now share bounded transport and capability
negotiation. Configured source selection and static discovery are covered by
[Configured sources](../guides/configured-sources.md). Publisher-agent/watch
transport lifecycle and description presentation remain subsequent work. Server wire
admission and authentication are now enforced by the ingestion boundary. No
discovery, TUI imports or network activity occurs on ordinary package import or
parser startup.
