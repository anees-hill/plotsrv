---
icon: lucide/terminal
---

# CLI reference

plotsrv includes a small CLI for starting the server, watching files, creating config, populating config, and managing stored outputs.

!!! note

    Workflows can also be controlled through Python code. See [Python API](python-api.md).

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
plotsrv config init ./src --config plotsrv.yml --name etl
```

It works in an ordinary terminal or SSH session; there is no terminal UI extra.
Choose whether this installation publishes, serves, or does both. When local
publisher source is available, plotsrv discovers `@view` declarations by
reading their AST without executing the project, then lets you hide selected
views. Server-only setups can also discover views when local source is available,
but do not need source code to configure a receiving server. Discovery remains
separate from watched files and direct API publication.

The main path asks whether to enable storage and freshness, then uses their
built-in defaults. Answer **yes** to customisation only when you need global
settings or per-view exceptions. Limits and watched files are optional; each
watched file needs only a path and a label, which defaults to the filename.
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

## Common command patterns

### Quick local check

```bash
python quickstart.py
```

where the script contains:

```python
ps.publish_view(obj, label="result", launch_server=True)
```

### Server workflow

Terminal 1:

```bash
plotsrv run demo_pipeline.py --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
python demo_pipeline.py
```

where the script publishes with:

```python
ps.publish_view(obj, label="result", host="127.0.0.1", port=8000)
```

### Server plus watched log

```bash
plotsrv run demo_pipeline.py --host 127.0.0.1 --port 8000 \
  --watch ./logs/job.log \
  --watch-label "job log" \
  --watch-tail
```

### Config-backed server

```bash
plotsrv run demo_pipeline.py --config plotsrv.yaml
```

## Next steps

- [Storage and history](storage-and-history.md)
- [Freshness](freshness.md)
- [Watch files](../get-started/watch-files.md)
- [Deployment Patterns](deployment-patterns.md)

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
