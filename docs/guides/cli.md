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

Install the optional terminal interface explicitly, then open it:

```bash
pip install 'plotsrv[config]'
plotsrv config init
plotsrv config init ./src --config plotsrv.yml --name etl
```

Choose **Everything on this machine**, **Send data to another plotsrv server**,
or **Host a plotsrv server**. Local setup proceeds through sources, storage and
freshness, then offers Review and save or Advanced. Local setup starts with your
source target; Remote destination is optional, and existing remote settings stay
visible. Publisher setup offers a
destination, key environment reference, watches, manual logical IDs and bounded
publication/observation settings. Server setup covers bind, ingestion/admission,
storage and freshness without requiring application source code.

Storage and freshness start with on/off choices. Turning either off retains
values you may re-enable. Storage exposes snapshot size/retention, watched-file
storage; latest restore and queue settings are under Advanced / Storage advanced.
Freshness uses server receipt time:
an unset warning threshold uses the expected interval; an unset overdue
threshold uses twice the warning. Disabling disk storage does not disable
in-memory stream summaries. Per-view editors use the same logical IDs, including
configured/manual IDs when there is no local catalogue. Reset removes the local
override and reveals inherited policy. Watched-file freshness starts disabled
unless explicitly configured for that view; choose Yes to opt in.

Advanced covers Watch, Publish, Limits and server Security/Admission. Checks and
webhooks offer modest controls and existing-schema guidance; they do not have a
second rule language. Existing rules and destinations are validated and retained.
For appearance, run `plotsrv config ui` after saving, with the same `--config`
and `--name`. It opens a separate temporary browser editor.

| Keys | Action |
| --- | --- |
| Tab / Shift+Tab | Move through fields and actions |
| Arrows / j / k | Move within lists and open dropdowns |
| Space | Toggle a discovered view |
| a / c | Select all / clear all in the view list |
| r, then e | Set a range anchor, move, select through its end |
| Enter | Choose, continue, or activate the focused button |
| Esc | Dismiss or go back |
| Left / Backspace | Go back outside text editors |
| Ctrl+C / Ctrl+Q | Confirm abandonment |
| ? / F1 | Help; use F1 while editing text |

Contextual help includes meaning, units, defaults and inheritance; an asterisk
marks a departure from the displayed default. Input editing retains its normal
keys, and small terminals use scrolling panels. No mouse is required.

Discovery reads bounded AST source without importing the project. An optional
package/path focuses it; otherwise the configured target or normal project root
is used. New setups select all discovered views; existing setups start with the
effective selection. Explicit IDs are preserved, and duplicate/unresolved or
incomplete discovery is disclosed. The wizard saves `discovery.exact_selection`
so clearing every view means no discovery and never accidentally means all.
`discovery.additional_ids` records reviewed dynamic/manual publisher IDs.
Legacy `selection` keeps its existing label/section/ID matching and empty-means-all
behaviour when exact selection is absent. An explicit CLI `--include` overrides
the configured selection. Watches and direct API publication are independent of
AST selection. Choose Configure watches to add files; the editor opens
automatically for existing watches. Select an existing watch to edit its path, logical ID, label,
section, read mode or materialization (inherited or explicit), or remove that specific watch. Changes
apply with Add / update watch; New watch starts a new entry.

The wizard never reads watched-file contents, tests a destination, reads secret
values, registers views, seals a catalogue or changes a running service. Key and
webhook-header settings use environment-variable names. Those values must exist
on the machine starting the corresponding service; startup still validates them
and fails closed when required values are absent. Locked servers may use a
complete configured ID list, or await an explicit publisher bootstrap. An empty
configured list seals a catalogue admitting no IDs. Review the complete union
before using the generated `--seal-catalogue --reviewed` guidance. Publisher
additional IDs and server admission IDs are separate lists, including in local
setup. Advanced / Publish shows the applicable local or remote stream timeout;
the maximum retry delay must be at least the initial delay.

Config selection follows the existing resolver: explicit `--config`, environment
selection, then `plotsrv.yml` before `plotsrv.yaml`. New drafts default to
`./plotsrv.yml`. Choose an unused custom filename or edit an existing one with
`--config`. The final screen supplies the applicable run/serve/publish command,
including `--config` and the selected instance. CLI bind flags override saved
server bind values for combined `run` as well as standalone `serve`.

Before saving, inspect managed YAML excerpts in their actual default/instance
placement and the effective-value diff; unrelated content,
comments and webhook endpoints are hidden from the review display. They are
retained in the actual file. Confirmation writes a unique restrictive backup
when replacing a file, then atomically replaces the target. New files use
no-clobber creation. Nothing writes until confirmation. File identity, timestamps
and content are checked against the review. If another editor changes the file,
reload it for review with your draft edits retained; do not confirm until you have
reviewed the new diff. Permission/write errors retain the previous target and
your draft. Closing before saving or cancelling the confirmation leaves files unchanged.

Edits preserve unrelated YAML bytes, comments, quoting and other instances.
Appending a watch preserves existing list rows/comments. Ambiguous layouts,
commented structures requiring destructive replacement, aliases, duplicate or
non-string keys, unsupported tags, nesting beyond 32 levels, more than 20,000
parser events, and files exceeding 1 MiB are refused with repair/new-file guidance.
An existing config must remain in its original directory when saving under a new
name, so unrelated relative paths cannot silently change meaning. New configs
may use another existing directory; explicitly entered source/storage paths keep
their original base. Module/package expressions retain their import names,
including `package.module:callable`; run those commands from the project
environment where the module is importable. Use `module:callable` for callable
execution, rather than `file.py:callable`. Directories are not created automatically. The draft allows
at most 2,048 field edits in one session.

Discovery has one cooperative worker and one replaceable progress slot; there is
no idle scan polling after completion. A filesystem/parser call cannot be
interrupted mid-call. Saving is synchronous, bounded local work in this optional
configuration process. The optional interface is never loaded by publishers or
servers and never installs dependencies on invocation. Noninteractive invocation
exits with guidance to the unchanged `config create/populate` commands.

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
settings list. Change the title, logo, tab icon or supported visibility options,
then choose **Update preview**. Light/Dark previews help check image contrast;
they do not change browser theme preferences. There is one shared logo for both
appearances. Legacy refresh/termination/colour settings and view lists remain
editable in YAML and are preserved by this tool.

Uploads accept still PNG/JPEG files up to **2 MiB**, **2048 pixels per side** and
**2 megapixels**. They are re-encoded as PNG, with metadata removed before it can
be inflated. SVG, HTML, animation and malformed images are refused. At most two
images / 4 MiB are staged, with 16 successful uploads per session. Images stay in
memory until Save. Existing external URLs or images outside the approved image
directory remain configured, but are not fetched for preview.

New images go into `plotsrv-assets/` beside the config. Use `--assets-dir images`
to select another directory inside that config folder. Its parent must exist;
the selected directory is created only when saving an upload. Existing directories
are reused without replacing them. Images receive unique filenames, and collisions
fail safely. The editor cannot accept arbitrary asset paths from the browser.
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
