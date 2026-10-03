
# CLI reference

plotsrv includes a small CLI for starting the server, watching files, creating config, populating config, and managing stored outputs.

!!! note

    Workflows can also be controlled through Python code. See [Python API](python-api.md).

## Command index

| Command | Behaviour |
|---|---|
| `serve` | Start a receiver without discovering or executing an application. |
| `run [target]` | Discover views and serve; `--mode callable` explicitly executes a target. |
| `watch path` | Follow a file or startup-selected directory contents. |
| `publish [target]` | Register declarations and follow configured files beside an existing receiver. |
| `config init [target]` | Review and save configuration through terminal prompts. |
| `config create` | Write a starter YAML file. |
| `config populate` | Populate per-view config from static discovery. |
| `config ui` | Open a temporary browser editor for shared appearance. |
| `store stats/list/clear` | Inspect or delete persisted content. |

Use `plotsrv --help` or `plotsrv COMMAND --help` for the parser's complete option
list. `plotsrv --version` reports the installed version.

## Standalone receiver

```bash
plotsrv serve --host 127.0.0.1 --port 8000 --config server.yml
```

`--host`, `--port`, `--config`, `--name`, `--quiet`, and `--verbose` are supported.
Omitted bind values use server config, then loopback and port 8000. There is no
application target. `--quiet` and `--verbose` are mutually exclusive. The default
logs HTTP failures without logging successful requests or query strings.

## Run the server

Start plotsrv on the default address:

```bash
plotsrv run
```

Open:

```text
http://127.0.0.1:8000
```

Run against a script:

```bash
plotsrv run demo_pipeline.py
```

Run against a package or directory:

```bash
plotsrv run ./src
```

```bash
plotsrv run .
```

Choose a host and port:

```bash
plotsrv run demo_pipeline.py --host 127.0.0.1 --port 8000
```

By default, `plotsrv run`, `plotsrv serve`, and local `plotsrv watch` omit successful HTTP access records. Every HTTP 4xx response is logged as a warning and every 5xx response as an error, with the method, path, status, and client address. Query strings are omitted. This keeps busy dashboards from filling logs with routine 200 responses.

Use `--verbose` to restore Uvicorn's full access log, including successful requests and query strings. Use `--quiet` to suppress startup and discovery messages while retaining HTTP failure logs. These options are mutually exclusive. `watch --verbose` requires a local server; it is not available with a remote `--destination`.

## What `plotsrv run` does

`plotsrv run` starts the browser UI and scans the target for plotsrv views.

It looks for:

- `@ps.view(...)` decorators
- simple `publish_view(...)` calls

This lets plotsrv pre-populate the UI with known views before data has been published.

For example:

```python title="demo_pipeline.py"
import plotsrv as ps

@ps.view(label="daily import", section="pipelines")
def daily_import_status():
    return {"status": "ok"}
```

Running:

```bash
plotsrv run demo_pipeline.py
```

allows plotsrv to discover the `daily import` view.

## Publish to a running server

After starting plotsrv:

```bash
plotsrv run demo_pipeline.py --host 127.0.0.1 --port 8000
```

publish to it from Python:

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="daily import",
    section="pipelines",
    host="127.0.0.1",
    port=8000,
)
```

When `host` or `port` is supplied without `launch_server=True`, `publish_view()` publishes to an existing plotsrv server.

It does not start a server.

## Callable mode

`plotsrv run` can call a function directly.

For example, given:

```python title="views.py"
def summary():
    return {"status": "ok"}
```

run:

```bash
plotsrv run views:summary --mode callable --keep-alive
```

To call repeatedly:

```bash
plotsrv run views:summary --mode callable --call-every 60
```

Callable mode is useful for simple demos or functions that can be called without required arguments.

## Watch files

!!! note

    Use `plotsrv run` rather than `plotsrv watch` if also publishing content from python scripts (see below). If in doubt, stick to `plotsrv run`.

Watch one file:

```bash
plotsrv watch ./logs/job.log
```

Watch a log from the tail:

```bash
plotsrv watch ./logs/job.log --tail
```

Watch a CSV file:

```bash
plotsrv watch ./outputs/results.csv
```

Attach watched files while running the server:

```bash
plotsrv run --host 127.0.0.1 --port 8000 \
  --watch ./logs/job.log \
  --watch-label "job log" \
  --watch-section "files" \
  --watch-tail
```

Watch multiple files:

```bash
plotsrv run --host 127.0.0.1 --port 8000 \
  --watch ./logs/job.log \
  --watch ./outputs/results.csv \
  --watch ./outputs/status.json \
  --watch-label "job log" \
  --watch-label "results" \
  --watch-label "status"
```

## Watch options

Common watch options:

| Option | Purpose |
|---|---|
| `--watch PATH` | add a file to watch when running the server |
| `--watch-label LABEL` | set the view label for a watched file |
| `--watch-section SECTION` | set the section for a watched file |
| `--watch-head` | read from the start of the file |
| `--watch-tail` | read from the end of the file |
| `--watch-max-mb N` | limit how much of the file is read, in MB |
| `--watch-max-bytes N` | legacy/advanced byte-level read limit |
| `--watch-kind auto/text/json` | control file interpretation |
| `--watch-materialization auto/memory/file` | override whether watched files are memory-backed or file-backed |

For standalone `plotsrv watch`, the equivalent options are:

```bash
plotsrv watch ./logs/job.log --label "job log" --section "files" --tail
```

Force a watched file to be file-backed:

```bash
plotsrv watch ./logs/job.log --materialization file
```

Force watched files attached to `plotsrv run` to be file-backed:

```bash
plotsrv run . \
  --watch ./logs/job.log \
  --watch-materialization file
```

`memory` publishes watched-file content into the plotsrv server as a normal view.

`file` keeps the watched file on disk and serves bounded previews on demand.

`auto` lets plotsrv choose based on the configured file-size threshold.

## Configuration wizard

Run the sequential CLI wizard with the standard plotsrv installation:

```bash
plotsrv config init
plotsrv config init --source ./src --config plotsrv.yml --name etl
```

It works in an ordinary terminal or SSH session; there is no terminal UI extra.
Choose whether this installation publishes, serves, or does both. When local
publisher source is available, plotsrv discovers `@view` declarations by
reading their AST without executing the project, then lets you hide selected
views. Server-only setups can also discover views when local source is available,
but do not need source code to configure a receiving server. Discovery remains
separate from watched files and direct API publication. The scan shows progress
and reports file/line diagnostics for declarations it cannot resolve. The hide
list includes every resolved view. In combined mode, hiding views also locks
server admission to the selected and watched IDs, so direct API publications
for hidden IDs are rejected.

The main path asks whether to enable storage and freshness, then uses their
built-in defaults. Answer **yes** to customisation only when you need global
settings or per-view exceptions. Limits and watched files are optional; each
watched file needs only a path and a label, which defaults to the filename.
In an interactive terminal, Tab completes watched-file paths. The server step
accepts an explicit bind host before the port; `0.0.0.0` listens on all IPv4
interfaces and requires a publisher key or explicit remote ingestion opt-in.
Settings for watched-file snapshots appear alongside watched files when storage
is enabled. Advanced settings are behind an explicit question. The same
storage, freshness, limit and source semantics are available through the
existing `config populate` commands.

Press Enter to accept the shown value. Enter `?` at any prompt for an explanation
of the current question; the wizard then repeats it. Durations accept `30m`,
`4h` or `2d` (and `s` for seconds). Size prompts accept `500 KB`, `10 MB` or
`1.5 GB`, with case and spacing variations. These use plotsrv's binary units:
1 MB means 1 MiB, or 1,048,576 bytes. Plain integer bytes are accepted for
byte-valued limits. Invalid values are explained and prompted again. No clock
time is requested by the current schema; freshness uses elapsed durations since
last receipt.

Run the same command again to edit an existing config. Enter keeps its current
values, and declining a section's **Change** question preserves the entire
section. The wizard holds proposed edits in memory, shows a concise review,
and writes only after explicit confirmation. No-change runs do not rewrite the
file. Ctrl+C or EOF before confirmation leaves it untouched. Existing comments,
ordering, unknown settings and other instances are preserved where the safe
YAML editor supports the layout; ambiguous layouts are refused rather than
rewritten destructively. Confirmed writes use atomic replacement and make a
backup of an existing file. The wizard never reads watched-file contents or
secret values and does not contact a destination.

For appearance settings, `plotsrv config ui` remains a separate browser editor.
For automation, use `config create` and `config populate`.

## Create config

Simply create a `plotsrv.yml` file in the project root, or create a starter config:

```bash
plotsrv config create
```

Overwrite an existing config:

```bash
plotsrv config create --force
```

The generated config is intended as a starting point. Edit it to enable storage, freshness, UI settings, and limits.

## Populate config

plotsrv can scan code and add per-view config entries. If needing view specific settings, this can save typing the view `section:label` ids within the config file.

!!! note

    The default config file created with `plotsrv config create` contains placeholders for global freshness, storage and limit parameters. If not needing view specific settings, use these. Otherwise use the `populate` commands below.

Populate freshness settings:

```bash
plotsrv config populate freshness .
```

Populate storage settings:

```bash
plotsrv config populate storage .
```

Populate limits:

```bash
plotsrv config populate limits .
```

Scan a specific file:

```bash
plotsrv config populate freshness demo_pipeline.py
```

Scan a source directory:

```bash
plotsrv config populate storage ./src
```

## Populate modes

Merge generated entries into an existing config:

```bash
plotsrv config populate freshness . --mode merge
```

Replace generated entries:

```bash
plotsrv config populate freshness . --mode replace
```

Skip confirmation prompts:

```bash
plotsrv config populate freshness . --yes
```

## Store commands

Storage commands inspect and clear persisted plotsrv output, including bounded
stream-session history when it is enabled.

Show storage statistics:

```bash
plotsrv store stats
```

List stored material:

```bash
plotsrv store list
```

List a specific view:

```bash
plotsrv store list --view "pipelines:daily import"
```

Clear a specific view:

```bash
plotsrv store clear --view "pipelines:daily import"
```

Clear all stored material:

```bash
plotsrv store clear --all
```

!!! warning

    `plotsrv store clear --all` removes stored material, including latest restored state, snapshot history, and stream-session history. `--view` clears only that logical view across all three storage kinds.

## Browser appearance editor

```bash
plotsrv config ui
plotsrv config ui --config plotsrv.yml --name etl
plotsrv config ui --config /srv/plotsrv/plotsrv.yml --no-open
```

Run this command on the machine holding the **server config and its images**.
It opens a temporary editor at `http://127.0.0.1:8766`. Paste the session key
printed in your terminal into the browser. The key grants access to this draft
and its final save; keep it private. It is separate from a publisher bearer key,
never included in the URL, and never saved in browser storage or HTTP access logs.
No source scan, live data subscription or production restart occurs.

The preview uses the dashboard's renderer and styling with three example rows.
Choose a highlighted logo/header/control region, or use the equivalent keyboard
settings list. Changes update the preview automatically after a short pause in
typing; **Update preview** is available to retry manually. Light/Dark previews help check image contrast;
they do not change browser theme preferences. There is one shared logo for both
appearances. Legacy refresh/termination/colour settings and view lists remain
editable in YAML and are preserved by this tool.

Uploads accept still PNG/JPEG files up to **2 MiB**, **2048 pixels per side** and
**2 megapixels**. They are re-encoded as PNG, with metadata removed before it can
be inflated. SVG, HTML, animation and malformed images are refused. At most two
images / 4 MiB are staged, with 16 successful uploads per session. Images stay in
memory until Save. Existing external URLs or images outside the approved image
directory remain configured, but are not fetched for preview. As an alternative
to uploading, enter a path to an existing image file on the server. Relative
paths are resolved from the config folder; paths outside the upload directory
are saved but are not shown in this preview.

New images go into `plotsrv-assets/` beside the config. Use `--assets-dir images`
to select another directory inside that config folder. Its parent must exist;
the selected directory is created only when saving an upload. Existing directories
are reused without replacing them. Images receive unique filenames, and collisions
fail safely. The editor checks that typed image paths point to existing files.
Relative references use the ordinary plotsrv `/assets/` serving mechanism.

**Review changes** shows the exact scoped YAML paths and an effective UI diff.
**Save and close editor** writes a unique backup and atomically replaces the config.
Only the listed UI fields change; other settings, comments and instances stay
untouched. Files changed by another editor must be reopened and reviewed in a
new session. Failed saves remove only newly created assets from that attempt;
existing files are never deleted. Unsupported YAML layouts are refused rather
than reformatted destructively. Files remain limited to 1 MiB, with the same
YAML structure restrictions as the terminal wizard.

Save or Cancel closes the temporary service. Ctrl+C also clears staged images.
Closing only the browser tab does not stop the command; stop it in the terminal,
or let its one-hour session expire. The editor has no background preview polling.
Saving is bounded synchronous work in this separate tool; decoder calls are not
hard-cancelled by a timer. No new optional/required package is introduced: image
decoding uses Pillow, already required by plotsrv's plotting dependencies.

Use `--host` and `--port` to choose where the editor listens, just as with
`plotsrv serve`. For example, to access it directly from another machine:

```bash
plotsrv config ui --config /srv/plotsrv/plotsrv.yml --host 0.0.0.0 --port 8766 --no-open
# Open http://my-server:8766 and paste the key printed in the terminal.
```

HTTP works directly; an HTTPS proxy or `--origin` is not required for a remote
bind. The default remains `127.0.0.1:8766`, and `--port 0` chooses a free port.
You can also use SSH port forwarding:

```bash
# On the host holding the server config:
plotsrv config ui --config /srv/plotsrv/plotsrv.yml --no-open

# On your workstation:
ssh -L 8766:127.0.0.1:8766 my-server
# Open http://127.0.0.1:8766 and paste the key from the remote terminal.
```

Different browser hostnames and forwarded ports work without extra flags.
`--origin` is optional: supply it only when you want to restrict the editor to
one exact browser origin. The session key and final save confirmation still
apply. Normal `plotsrv serve` never exposes these editor routes.

## Configured sources

### What the scanner can establish

The scanner recognises module-level imports and aliases for the actual plotsrv
`view`, `publish_view` and `stream_view` APIs. It preserves literal IDs, labels
and sections and extracts a cleaned first docstring paragraph, bounded to 2,048
characters. A declared ordinary kind is kept when valid; otherwise kind remains
`unknown`. Stream declarations use the existing stream identity defaults when
literal metadata provides enough evidence. The source filename is provenance,
not a server filesystem instruction.

Dynamic IDs/labels/sections, `**kwargs`, unresolved imports and shadowed API names
are reported as unresolved. They are not evaluated or turned into guessed
catalogue entries. The scan is deliberately conservative: function-local imports,
conditional imports, wildcard imports and rebound names may need manual review.
An unrelated function merely named `view` or `publish_view` is not sufficient
proof of a plotsrv declaration. Ordinary runtime publication still works for
these cases; static discovery is not execution or full Python data-flow analysis.

Module resolution walks filesystem module/package paths without calling
`find_spec`, import hooks or package `__init__` code. Regular modules/packages and
unambiguous namespace directories are supported, including conventional `src`
layouts. Ambiguous namespace roots, zip-only/custom-importer modules and unknown
targets require an explicit source path. A misspelled target now reports an error
rather than silently broadening the scan to the current directory.

### Progress, bounds and cancellation

Enumeration reports a file count with an unknown total. Once enumeration finishes,
progress reports processed/total files. The filesystem is enumerated once.
TTY output uses a small spinner/status line; redirected output contains occasional
plain lines with no terminal escape sequences. `--quiet` suppresses both. Large
or slow unscoped runs receive a one-time suggestion to pass a package/source path;
small ordinary runs do not receive that tip.

| Resource | Bound/policy |
| --- | --- |
| Enumerated directory entries | 100,000 |
| Python files per scan | 10,000 |
| Source bytes per file | 1 MiB |
| Source bytes per scan | 64 MiB, with at most one extra byte to detect exhaustion |
| AST nodes per file | 100,000, checked after parsing the bounded source |
| Discovered declarations/catalogue IDs | 1,024 |
| Retained issue records | 128; total issue count remains available |
| Manifest body | At most 1 MiB, with descriptor field/count bounds |

Known caches, virtual environments, build/vendor trees and `node_modules` are
pruned. Use `--scan-all` or `discovery.include_pruned: true` to deliberately include
them, or target the needed subtree directly. The same structural limits still
apply. Directory and file symlinks encountered while walking are skipped; an
explicit root may resolve through a symlink. Symlink loops cannot expand a scan.
Unreadable, oversized, changing or invalid Python files are reported and skipped.
Special files are not read as Python source.

Bounds limit work and allocation; they are not hard cancellation of a blocked
filesystem operation or the Python parser. Cancellation is checked during
walking, between file operations and in bounded AST traversal steps. Source
mutation detection is best effort, not a transactional filesystem snapshot.

## Publisher helper


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

### Explicit catalogue initialisation

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
[configured discovery](cli.md#configured-sources) and [ingestion](remote-publishing-and-security.md).

### One file, locally or remotely

```sh
plotsrv watch ./application.log                       # start a local server and watch
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
and failure cooldowns are shared with [direct remote publishers](remote-publishing-and-security.md).

`--every` is both polling and debounce cadence (minimum 0.1 seconds). A version
normally remains stable for two admitted polls. Under continuous changes, capture
is attempted every second admitted poll; the read itself must still pass the
before/after mutation checks. `--update-limit-s` also limits capture
cadence before reading. `--force` permits a changed source version with identical
content to count as an update; it does not continuously resend unchanged files.
For remote sources, materialisation always means bounded publisher capture;
`materialization: file` remains a local optimisation when using local `run/watch`.
The receiver never installs a publisher path as a local watched file.

### Coverage, formats and downloads

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
content. Complete HTML follows the publisher's trust and the server's rendering
settings; authenticated publishers can send active HTML. See
[HTML trust](remote-publishing-and-security.md#remote-content-and-compatibility).
Relative assets are not collected or fetched. Incomplete HTML/Markdown stays plain text.

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

### Resource and ordering limits

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
