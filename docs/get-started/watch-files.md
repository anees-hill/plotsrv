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

Large files can be limited with `--max-bytes`.

```bash
plotsrv watch ./logs/job.log --max-bytes 5000000
```

To read the full file:

```bash
plotsrv watch ./logs/job.log --max-bytes off
```

For large logs, keeping a byte limit is usually better. It keeps the UI responsive and avoids reading too much from disk.

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

## Next step

Continue to [Configuration basics](configuration-basics.md).
