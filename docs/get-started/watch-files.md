---
icon: lucide/file-search
---

# Watch files

plotsrv can expose files on disk in the same browser UI as Python objects.

This is useful when a process already writes useful files, such as:

- logs
- CSV files
- JSON, YAML, INI, TOML files
- markdown reports
- HTML reports
- generated images

## Watch a log file

To simply "watch" a log file, you can use the `plotsrv watch` command:

```bash
plotsrv watch ./logs/job.log
```

Open:

```text
http://127.0.0.1:8000
```

The file appears in the plotsrv UI and updates when the file changes.

For log-like files, plotsrv is usually most useful in tail mode, showing the newest content from the end of the file.

```bash
plotsrv watch ./logs/job.log --tail
```

## Watch files while running plotsrv as a server

For scripts, jobs, and pipelines, watched files can be declared when starting the server. In this example, the plotsrv UI will include 2 on-disk files in the plotsrv UI dropdown menu:

```bash
plotsrv run . --host 127.0.0.1 --port 8000 \
  --watch logs/uvicorn.log --watch-label "job log" --watch-section "files" --watch-tail \
  --watch reports/daily_report.html --watch-label "daily" --watch-section "reports"
```

This starts the plotsrv UI and adds the watched file as a view.

## Watch a CSV file

CSV files are rendered as tables.

```bash
plotsrv watch ./outputs/results.csv
```

The table renderer provides search, filters, pagination, and column controls.

CSV watching is useful when a process writes result tables to disk, but changing the Python code to call `publish_view()` is not convenient.

## Watch a JSON file

JSON files are rendered with the JSON renderer.

```bash
plotsrv watch ./outputs/status.json
```

For example:

```json title="status.json"
{
  "job": "daily-import",
  "status": "ok",
  "rows_processed": 123,
  "warnings": 2
}
```

This appears as an expandable JSON view in the browser.

## Choose head or tail mode

Head mode reads from the start of the file.

```bash
plotsrv watch ./outputs/results.csv --head
```

Tail mode reads from the end of the file.

```bash
plotsrv watch ./logs/job.log --tail
```

plotsrv also chooses sensible defaults based on the file type.

## Limit large files

Large watched files can be limited in megabytes with `--max-mb`.

```bash
plotsrv watch ./logs/job.log --max-mb 25
```

To read the full file:

```bash
plotsrv watch ./logs/job.log --max-mb off
```

`--max-bytes` is still available as a legacy/advanced option when byte-level precision is needed:

```bash
plotsrv watch ./logs/job.log --max-bytes 5000000
```

For large logs, keeping a read limit is usually better. It keeps the UI responsive and avoids reading too much from disk.

The equivalent config key is:

```yaml title="plotsrv.yaml"
limits:
  watched_files:
    max_mb: 500
```

Watched CSV files also use table preparation limits:

```yaml title="plotsrv.yaml"
limits:
  truncate_after:
    table_rows: 100000
    table_columns: 200
```

## Memory-backed and file-backed watched files

Watched files can be represented in two ways.

| Mode | Meaning | Best for |
|---|---|---|
| `memory` | plotsrv reads the watched file content and publishes a normal in-memory view | small files, simple local workflows |
| `file` | plotsrv keeps file metadata in memory and reads bounded previews from disk only when the browser asks for them | large logs, large CSV files, long-running servers |
| `auto` | plotsrv chooses based on file size and config | most workflows |

The default is `auto`.

In `auto` mode, small watched files behave like normal published objects. Larger files become file-backed views, so plotsrv does not keep the full file content in server memory.

Force file-backed mode:

```bash
plotsrv watch ./logs/job.log --materialization file
```

Force memory-backed mode:

```bash
plotsrv watch ./logs/job.log --materialization memory
```

For files attached to `plotsrv run`:

```bash
plotsrv run . \
  --watch ./logs/job.log \
  --watch-materialization file
```

The equivalent config is:

```yaml title="plotsrv.yaml"
limits:
  watched_files:
    materialization: auto
    file_threshold_mb: 50
```

Use `file` for large watched files when you want predictable memory use.

## File-backed behaviour

File-backed watched files are designed to protect the plotsrv server from large in-memory payloads.

For file-backed text, markdown, HTML, JSON-like, and log files:

- the view is registered immediately
- plotsrv stores metadata such as path, file type, size, and read mode
- `/artifact` reads a bounded preview from disk when the browser requests it
- preview errors are shown in the UI as `watch_error` messages

For file-backed CSV files:

- the view appears as a table
- `/table/data` reads a bounded CSV preview from disk when the browser requests it
- the full CSV is not loaded into server memory
- export is intentionally blocked for now, because exporting a file-backed CSV safely has different semantics from exporting an in-memory table

If a file-backed watched file cannot be read, plotsrv shows a visible error view instead of hiding the failure behind a server error.

## File types

plotsrv infers common file types from the extension.

| File type | Rendered as |
|---|---|
| `.log`, `.txt`, unknown text | Text |
| `.csv` | Table |
| `.json` | JSON |
| `.yaml`, `.yml` | JSON-like structured view |
| `.toml` | JSON-like structured view |
| `.ini`, `.cfg` | JSON-like structured view |
| `.md`, `.markdown` | Markdown |
| `.html`, `.htm` | HTML |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg` | Image |

## Watch files or publish from Python?

Watching files is best when the useful output already exists on disk.

Publishing from Python is better when the useful object already exists in memory.

For example, this is usually better than writing a temporary CSV just for plotsrv:

```python
ps.publish_view(
    df,
    label="results",
    section="demo",
    host="127.0.0.1",
    port=8000,
)
```

But if a process already writes `results.csv`, watching that file is a simple way to expose it.

## Freshness and storage defaults for watched files

Watched files are source-aware.

Global freshness settings do not mark watched-file views stale by default. A watched file might be static for a long time and still be valid.

To apply freshness to a watched file, opt that specific view in:

```yaml title="plotsrv.yaml"
freshness-settings:
  enabled: true
  views:
    "files:job log":
      enabled: true
      expected_every: 5m
      warn_after: 10m
      overdue_after: 30m
```

Storage is source-aware too.

Memory-backed watched-file publishes can be snapshotted only if watched storage is enabled with `storage-settings.watch_enabled` or a per-view `watch_enabled` override.

File-backed watched files are not stored as latest-state payloads or historical snapshots. Their data already lives on disk and is previewed from the source file.

```yaml title="plotsrv.yaml"
storage-settings:
  enabled: true
  watch_enabled: false
```

## Next step

Continue to [Configuration basics](configuration-basics.md).
