# Watch files

```bash
plotsrv watch ./logs/job.log
```

Open **<http://127.0.0.1:8000>**. The view updates as the existing file changes.
Leave the command running; Ctrl+C stops the local server and watch.

## Watch a log file

For logs, use the end of the file:

```bash
plotsrv watch ./logs/job.log --tail
```

Log and text files use tail mode by default; `--tail` makes the choice explicit.
Use `--head` to inspect the beginning instead.

This is a changing text preview. To follow structured records, pause live updates,
or inspect stream sessions, see [Follow logs and streams](../guides/follow-logs-and-streams.md).

## Watch a directory

```bash
plotsrv watch ./reports
```

Each supported file found at startup becomes a view. Subfolders become sections.
CSV opens as a table; JSON, YAML, and TOML can be explored as structured data;
Markdown and HTML open as reports. Code files are displayed, never executed.
Only open HTML reports you trust: scripts are allowed by default.

The scan runs once. Changes to selected files keep appearing, but restart the
command to pick up newly added files. By default, the scan includes two subfolder
levels and allows 32 views. Hidden files, symlinks, and unknown formats are skipped.

To narrow the selection:

```bash
plotsrv watch ./reports --include '*.csv'
plotsrv watch ./reports --max-depth 0
```

Quote patterns so your shell does not expand them. If the directory is too large,
plotsrv asks you to narrow the selection rather than choosing an arbitrary subset.

## Watch a table or report

```bash
plotsrv watch ./reports/orders.csv
plotsrv watch ./reports/summary.json
plotsrv watch ./reports/notes.md
```

These formats normally read from the beginning. Large-file previews have limits;
the view does not promise to show every row or byte.

## Add a file beside your Python views

```bash
plotsrv run ./src --watch ./logs/job.log --watch-tail
```

Or send a local file to an existing server:

```bash
plotsrv watch ./logs/job.log --tail --destination http://127.0.0.1:8000/
```

The watch process reads the file; the receiving server does not open that path.
See [remote publishing](../guides/run-on-another-machine.md) for another machine.

Need matching rules, scan depth, byte limits, or large-file behaviour? See
[Files and watching reference](../reference/files-and-watching.md).
