# Publisher/server internals

For user-facing authentication and routing rules, see [Remote publishing and security](../reference/remote-publishing-and-security.md).

## Server setup contract

A server-only file can configure ingestion authentication and admission. See
[Publisher ingestion](../reference/remote-publishing-and-security.md) for the enforced endpoint
matrix, explicit bootstrap transaction and proxy requirements. `plotsrv serve`
uses the bind fields; explicit CLI host/port override them. See
[Direct remote publishers](../reference/remote-publishing-and-security.md) for working examples.

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
[Configured sources](../reference/cli.md#configured-sources). Optional foreground
catalogue registration and remote watch transport are covered by
[Publisher agent](../reference/cli.md#publisher-helper). Full description presentation
remains subsequent work. Server wire
admission and authentication are now enforced by the ingestion boundary. No
discovery, wizard imports or network activity occurs on ordinary package import or
parser startup.

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

Descriptors use the [bounded metadata contract](publisher-server-internals.md).
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

## Shared engine and reviewable manifests

Terminal presentation is separate from the source engine, so other callers can
supply their own progress and cancellation handling:

```python
from threading import Event
from plotsrv.discovery import scan_sources
from plotsrv.source_setup import resolve_source_setup, build_manifest

stop = Event()
setup = resolve_source_setup()
result = scan_sources(
    setup.scan_root(default_target="."),
    include_pruned=setup.include_pruned,
    on_progress=lambda event: print(event.phase, event.processed, event.total),
    cancelled=stop,
)

# Inspect result.views and result.issues before deciding the complete union.
manifest = build_manifest(
    result,
    selection=setup.selection,
    watches=setup.watches,
    added_ids=["runtime:explicitly-reviewed-id"],
)
```

`DiscoveryProgress` carries phase, processed count, optional total, files found,
skipped count and elapsed time. `scan_sources` returns bounded views/issues and
completion/cancellation/limit state. `on_issue` is an optional issue callback.
`discover_views` remains the compatible list-returning API; it raises on cancelled
or limited scans so partial results cannot silently become registrations.

`build_manifest` produces the protocol-1 `views` body accepted by the
[catalogue bootstrap endpoint](../reference/remote-publishing-and-security.md). It includes selected
known declarations, configured watches and caller-supplied reviewed dynamic IDs.
Duplicate/conflicting IDs fail before registration or config writes. Cancelled
or resource-limited scans cannot produce a manifest. Completed scans with
unresolved declarations or skipped files require explicit `reviewed=True` after
inspection; that flag does not resolve duplicate IDs or remove structural limits.

Building or reviewing a manifest does not send it, register it remotely or seal a
catalogue. The caller must deliberately submit the complete union when that is
appropriate. The [publisher agent](../reference/cli.md#publisher-helper) uses this engine for
explicit catalogue registration/sealing and configured remote watches.
