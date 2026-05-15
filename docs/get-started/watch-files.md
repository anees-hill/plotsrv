---
icon: lucide/file-search
---

# Watch files

plotsrv can watch files on disk and publish them into the browser UI.

This is useful when your process already writes logs, CSV files, JSON files, markdown reports, HTML reports, images, or other output files.

The simplest command is:

```bash
plotsrv watch app.log
```

Then open:

```text
http://127.0.0.1:8000
```

plotsrv will watch the file and update the browser view when it changes.

## Watch a log file

```bash
plotsrv watch app.log
```

Text-like files are shown with the text renderer.

The text renderer includes:

- copy
- word wrap
- reverse line order
- lightweight log colouring
- jump to bottom

By default, log-like files are read from the tail of the file, so you see the newest output first.

## Watch a CSV file

```bash
plotsrv watch results.csv
```

CSV files are shown as tables.

The table renderer includes:

- search
- filters
- column visibility controls
- pagination
- export

When tailing CSV files, plotsrv keeps the header row so the table can still be parsed correctly.

## Watch a JSON file

```bash
plotsrv watch status.json
```

JSON files are shown with the JSON renderer.

For example, a file like this:

```json title="status.json"
{
  "job": "daily-import",
  "status": "ok",
  "rows_loaded": 9985,
  "warnings": 15
}
```

will be rendered as a structured JSON tree.

## Watch multiple files

You can attach watched files when starting a plotsrv server:

```bash
plotsrv run --watch app.log --watch results.csv --watch status.json
```

This gives you one browser UI with multiple views.

## Add labels

By default, watched files use the filename as the label.

You can provide labels explicitly:

```bash
plotsrv run \
  --watch app.log \
  --watch results.csv \
  --watch-label "Application log" \
  --watch-label "Results table"
```

The labels are matched to the watched files in order.

## Add sections

Watched files default to the `watch` section.

You can provide a section:

```bash
plotsrv run \
  --watch app.log \
  --watch results.csv \
  --watch-section "files"
```

A single `--watch-section` applies to all watched files.

You can also provide one section per watched file:

```bash
plotsrv run \
  --watch app.log \
  --watch results.csv \
  --watch-section "logs" \
  --watch-section "tables"
```

## Choose head or tail mode

plotsrv chooses a sensible default read mode based on the file type.

- logs and unknown text files default to `tail`
- CSV, JSON, YAML, TOML, INI, markdown, HTML, and image files default to `head`

You can override this.

For one watched file:

```bash
plotsrv watch app.log --head
```

```bash
plotsrv watch app.log --tail
```

When using `plotsrv run --watch`, use `--watch-head` or `--watch-tail`:

```bash
plotsrv run --watch app.log --watch-tail
```

```bash
plotsrv run --watch config.json --watch-head
```

## Limit how much of a file is read

Large files can be limited with `--max-bytes`:

```bash
plotsrv watch app.log --max-bytes 5000000
```

Use `off` to read the whole file:

```bash
plotsrv watch app.log --max-bytes off
```

When using `plotsrv run --watch`, use `--watch-max-bytes`:

```bash
plotsrv run --watch app.log --watch-max-bytes 5000000
```

The default value can also be set in config:

```yaml title="plotsrv.yml"
limits:
  watched_files:
    max_bytes: 5000000
```

!!! note

    The watched-file byte limit controls how much data plotsrv reads from disk.

    Renderer limits control how much text-like content is displayed in the browser.

## Choose file interpretation

By default, plotsrv infers the file type from the extension.

You can force text mode:

```bash
plotsrv watch output.data --kind text
```

Or force JSON mode:

```bash
plotsrv watch output.data --kind json
```

For `plotsrv run --watch`, use `--watch-kind`:

```bash
plotsrv run --watch output.data --watch-kind text
```

Supported watch kinds are:

- `auto`
- `text`
- `json`

## Use watches from Python

You can also start watches from the Python API.

```python title="watch_from_python.py"
import plotsrv as ps

ps.start_server(
    watches=[
        ps.WatchConfig(
            path="app.log",
            label="Application log",
            section="files",
            kind="text",
        ),
        ps.WatchConfig(
            path="results.csv",
            label="Results table",
            section="files",
        ),
    ],
)

input("Open http://127.0.0.1:8000, then press Enter to stop...")
ps.stop_server()
```

## What file types can plotsrv infer?

plotsrv can infer common file types from file extensions.

| Extension | Renderer |
|---|---|
| `.csv` | Table |
| `.json` | JSON |
| `.yaml`, `.yml` | JSON |
| `.toml` | JSON |
| `.ini`, `.cfg` | JSON |
| `.md`, `.markdown` | Markdown |
| `.html`, `.htm` | HTML |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg` | Image |
| anything else | Text |

## Watch mode vs publishing from Python

Watching files is best when your process already writes useful output to disk.

Publishing from Python is better when the useful object already exists in memory.

For example:

```python
ps.publish_view(df, label="Results", section="etl")
```

is better than writing a temporary CSV just so plotsrv can watch it.

But if your process already writes `results.csv`, then watching the file is a simple way to make it visible.

## Next steps

- [Configuration basics](configuration-basics.md)
- [Renderer overview](../renderers.md)
- [Run a plotsrv server](run-a-plotsrv-server.md)
