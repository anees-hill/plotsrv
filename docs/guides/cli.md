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

## Configuration draft wizard

Install the optional terminal interface explicitly, then open it:

```bash
pip install 'plotsrv[config]'
plotsrv config init
plotsrv config init ./src --config plotsrv.yml --name etl
```

This first stage offers **Everything on this machine**, **Send data to another
plotsrv server**, or **Host a plotsrv server**. It currently ends at an **unsaved
draft preview**. Settings pages and saving are not available yet; closing the
wizard changes no configuration or assets. Use `config create/populate` below
when you need to write configuration now.

The host-only route skips source discovery. The other routes accept an optional
package/path, otherwise use configured discovery or normal project detection.
The source page accepts an HTTP(S) destination, a bearer-key **environment
variable name**, and local watched files with stable logical IDs. It never tests
the remote endpoint, reads the key value, registers views or seals a catalogue.
Paths belong to the machine running this tool; config-relative paths resolve
beside the selected config. An explicit command target starts relative to the
working directory. Watched file contents are not read by the wizard.

| Keys | Action |
| --- | --- |
| Tab / Shift+Tab | Move through fields and actions |
| Arrows / j / k | Move within lists |
| Space | Toggle a discovered view |
| a / c | Select all / clear all in the view list |
| r, then e | Set a range anchor, move, select through its end |
| Enter | Choose a role, continue from the view list, or activate a button |
| Esc | Dismiss or go back; the first page asks before abandoning |
| Left / Backspace | Go back outside text editors |
| Ctrl+C / Ctrl+Q | Confirm abandonment |
| ? / F1 | Help; use F1 while editing text |

The help region explains the focused field, units, defaults and inheritance.
An asterisk marks a departure from the built-in default. Text-entry keys retain
their usual meaning; `q` is not a navigation shortcut. Panels scroll in small
terminals. Discovery uses the existing bounded AST scanner without executing
the application. One worker and a replaceable progress slot keep updates
bounded; cancellation is cooperative, not a guarantee of interrupting a
filesystem or parser operation mid-call. No scan timer remains after completion.

New setups select all discovered views, grouped by section. Existing configs
start from their effective selection and retain the original bytes, unrelated
settings and instance inheritance. Duplicates and unresolved declarations are
shown for review; partial discovery is not presented as a complete catalogue.
Clearing every view is an in-memory choice: the preview explicitly distinguishes
it from runtime `selection: []`, which means all views. Skipping discovery skips
this preview scan; it does not disable discovery in existing configuration.

Config selection follows the existing resolver (`--config`, the configured
environment selector, then `plotsrv.yml` before `plotsrv.yaml`); with no existing
file the draft path is `./plotsrv.yml`. Use `--config` with custom filenames.
The draft reader refuses malformed YAML, duplicate/non-string keys, aliases,
nesting beyond 32 levels, more than 20,000 parser events, or files over 1 MiB.
It does not silently reset unsupported files. Noninteractive invocations exit
with guidance to `config create/populate`. The optional interface is lazy-loaded
and never installs dependencies or accesses the network on invocation.

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
