# Publisher agent and remote watched files

Use `plotsrv publish` to register a catalogue and watch configured files beside
an existing server. This optional helper never starts a server or executes your
application. Direct `publish_view`, decorators and streams continue to work
without it.

Start the receiver separately:

```sh
plotsrv serve --config server.yml
```

On the publisher machine, use a separate configuration:

```yaml
publisher-settings:
  destination:
    url: https://dashboard.example.org/plotsrv/
    bearer_token_env: PLOTSRV_PUBLISHER_KEY
  discovery:
    target: ./src
    selection: [Orders]
  watch:
    - path: ./logs/orders.log
      view_id: orders:log
      label: Orders log
      section: Orders
      read_mode: tail
    - path: ./reports/orders.csv
      view_id: orders:table
      read_mode: head
```

The key environment variable must contain the same publisher key configured on
the server. Neither config contains the key itself. Config paths resolve beside
that config on the publisher machine.

```sh
plotsrv publish --config publisher.yml
plotsrv publish ./src --no-watch   # catalogue only; exits after registration
plotsrv publish --no-discovery    # configured watches only
```

A supplied or configured target enables the shared static scan. With neither,
`publish` registers configured watches and explicit IDs without scanning cwd.
Use `publish .` to deliberately scan the current project. Watchers keep the
process in the foreground; Ctrl+C or SIGTERM requests shutdown. Catalogue-only
registration failures exit with a diagnostic. A running watcher retries transient
failures using the shared bounded transport cooldown.

## Explicit catalogue initialisation

For a server configured with `admission.mode: catalogue-locked`, initialise its
**complete union** deliberately:

```sh
plotsrv publish ./src --seal-catalogue --add-id orders:runtime
```

Normal registration never seals a catalogue. Repeating the same complete
manifest is safe. A later partial/different manifest cannot extend a sealed
catalogue. For several projects, include their complete reviewed union or use
the server's configured allowed IDs. `--add-id` is repeatable. Dynamic AST IDs
and skipped sources require inspection and `--reviewed`; cancelled or resource
limited scans cannot be used, even with that flag. See
[configured discovery](configured-sources.md) and [ingestion](publisher-ingestion.md).

## One file, locally or remotely

```sh
plotsrv watch ./application.log                       # existing local server/watch
plotsrv watch ./application.log --materialization file
plotsrv watch ./application.log --destination http://127.0.0.1:8000 --tail
plotsrv watch ./report.csv --destination https://dashboard.example.org/plotsrv/ \
  --bearer-token-env PLOTSRV_PUBLISHER_KEY --view-id reports:orders --head
plotsrv watch ./report.csv --config publisher.yml --head
```

An explicit destination or configured publisher destination selects remote
transport. It never falls back to launching a local server. Legacy local
`--host`/`--port` use overrides a configured destination, including its credential. An explicit destination conflicts with
explicit host/port. An explicit URL uses `--bearer-token-env` for its credential;
otherwise use the full destination config. HTTPS verification, redirect refusal
and failure cooldowns are shared with [direct remote publishers](remote-publishers.md).

`--every` is both polling and debounce cadence (minimum 0.1 seconds). A version
normally remains stable for two admitted polls. Under continuous changes, capture
is attempted every second admitted poll; the read itself must still pass the
before/after mutation checks. `--update-limit-s` also limits capture
cadence before reading. `--force` permits a changed source version with identical
content to count as an update; it does not continuously resend unchanged files.
For remote sources, materialisation always means bounded publisher capture;
`materialization: file` remains a local optimisation when using local `run/watch`.
The receiver never installs a publisher path as a local watched file.

## Coverage, formats and downloads

Small supported files can be hosted completely. Larger text/code and CSV files
provide a head/tail preview. CSV parsing retains at most 200 rows and 64 columns;
there is no scan just to count all rows. Quoted multiline records are supported
when their boundaries are known. A quoted tail window with unknown quote context,
large fields/headers, or incomplete records produces a bounded raw-text preview
with a parse limitation.

JSON/INI/TOML/YAML parsing is limited to complete inputs up to 64 KiB with
structural limits. Larger, partial or unsafe structured inputs remain text with
a parse limitation. INI interpolation is displayed literally, and repeated
INI defaults are bounded before building the presentation. YAML aliases/anchors
are not expanded. A temporarily invalid
complete structured source preserves an existing good presentation until the
source changes again. Continuous log/event semantics belong in `stream_view`;
file watch represents latest state and can coalesce intermediate versions.

Complete PNG/JPEG/GIF/WebP/BMP files are accepted only after format checks, with
at most four million pixels and one frame. Truncated images, SVG and unsupported
binary data are rejected; the watcher reports a status and retains last good
content. Complete HTML uses the existing isolated remote renderer. Relative
assets are not collected or fetched. Incomplete HTML/Markdown stays plain text.

Full-source download is advertised only for an entire bounded object held by
the receiver. Otherwise the UI says “Preview available; original file is not
hosted here.” Table exports of received rows are labelled previews. Source
exports are attachments with opaque content type and a sandbox policy. There
are no callbacks or URLs for retrieving arbitrary files from the publisher.

Basename, publisher-reported size/mtime, read scope, presentation read mode, source generation and
revision accompany uploads. These are provenance facts, not server paths or
server-authoritative times. Freshness uses server receipt time. Missing,
unreadable, changing or stopped sources retain their last good content and an
honest status. Opening the status modal fetches the latest remote source status without treating it as new data. Status notices and transport retries do not create arrivals or
snapshots. Only receiver storage policy can enable snapshots for watch IDs.
Hosted original bytes are process-local; historical snapshots retain the bounded
presentation, without claiming a full original-file download.

## Resource and ordering limits

| Resource | Bound |
| --- | --- |
| Watched IDs per foreground agent / receiver | 64 |
| Bytes read per capture, including CSV header work | 256 KiB |
| Watch HTTP update body | 384 KiB |
| Prepared presentation encoding | 1 MiB |
| Text presentation | 65,536 characters, reduced by configured display limits |
| Receiver hosted bytes plus encoded presentation accounting | 16 MiB aggregate |
| CSV rows / columns / individual field characters | 200 / 64 / 8,192 |
| Structured parse input / visited values / depth | 64 KiB / 10,000 / 32 |
| Active capture/transport jobs per agent | 1; no retained payload queue |

Existing watch read limits can reduce capture bytes. Disabling display/read
truncation does not remove these remote limits. Receiver ingestion and published
object limits can reject smaller values independently. A single worker checks
transport admission before capture; slow network work delays other watched
sources rather than creating workers per change. Unchanged accepted signatures
cause no additional file reads. Files are opened read-only, regular-file checks
reject special files, final symlinks are refused, and size/mtime/inode checks
around capture reject detected replacements or concurrent changes.

One active watch owner holds a 60-second renewable receiver session per ID. Competing owners get a
conflict; delayed requests from closed/old sessions cannot overwrite it. Within
a session, only increasing revisions are eligible, and identical captured
content is deduplicated. A retry of one captured source version keeps its revision,
including with `--force`. Idle agents renew every 20 seconds independently of
capture cadence. Clean close releases ownership; after a crash or failed close,
a new owner can take over after the lease expires. Old sessions remain fenced
after takeover. Expired sources show disconnected status. Closed/expired hosted
sources are retained until their slot or hosted-byte budget is needed for another ID. Use distinct IDs for independent
producers. Ordinary direct publishing retains its existing latest-accepted
behaviour; replacing a watch presentation clears its hosted-source capabilities.

Server restart changes the session generation. A watcher re-registers and sends
its current source, subject to catalogue admission. Detection uses the shared
capability cache (up to 30 seconds when otherwise idle); failed exchanges
invalidate it. This is modest fencing and latest-state delivery, not durable
synchronisation or an audit trail.

The updated agent requires the `watch-v2` capability (renewable ownership and
separate presentation read mode). Older receivers fail negotiation before any
file capture. The receiver still accepts legacy `watch-v1` uploads; their older
agents lack idle renewal and can lose ownership after an expired lease. The
base ingestion protocol remains version 1 and stream protocol remains version 4.

Transport uses a total deadline of at most two seconds per watch request,
including slow header/body/error responses, with a two-second shared best-effort
close budget. There are no transport timer threads. HTTP 403/413/422 rejections
also enter a 30-second cooldown before further capture or negotiation; transient
failures use five seconds. The first Ctrl+C/SIGTERM requests cooperative stop; a
second interrupts cleanup. OS filesystem and DNS calls are still not guaranteed
to honour the HTTP deadline; bounded parsing and source-mutation detection are
cooperative. Queue-byte accounting
is not total Python/Pandas/Pillow process memory. No incoming publisher listener,
background deployment service or source-file mutation is introduced.
