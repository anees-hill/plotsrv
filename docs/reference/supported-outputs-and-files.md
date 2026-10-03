---
icon: lucide/panels-top-left
---

# Supported outputs and files

plotsrv chooses a renderer based on the object or file that is published.

Most of the time, there is no need to choose a renderer manually. Publish an object, and plotsrv will display it in a useful way.

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="status",
    launch_server=True,
)
```

This publishes a dictionary-like object, so plotsrv displays it with the JSON renderer.

## Renderer summary

| Input | Renderer | Useful for |
|---|---|---|
| pandas or Polars DataFrame | Table | data inspection, search, filters, export |
| matplotlib or plotnine plot | Plot | charts and visual checks |
| `dict`, `list`, `tuple` | JSON | structured objects, metadata, configs, API responses |
| `str`, `bytes`, logs | Text | logs, plain text, command output |
| generic Python objects | Python | `repr()` output and object inspection |
| markdown text/files | Markdown | reports, notes, generated documentation |
| HTML text/files | HTML | HTML reports and generated pages |
| image files/payloads | Image | PNG, JPEG, GIF, WebP, BMP, SVG |
| traceback payloads | Traceback | exception observability |
| path-like files | Inferred from file type | CSV, JSON, YAML, TOML, markdown, HTML, text, images |

## Table renderer

DataFrames are rendered as tables.

```python title="table_example.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "centre": ["A", "B", "C"],
    "returned": [120, 98, 143],
    "expected": [125, 100, 150],
})

ps.publish_view(
    df,
    label="returns",
    section="renderers",
    launch_server=True,
)
```

The table renderer includes:

- search
- filters
- column controls
- pagination
- export
- status information when only part of a table is shown

pandas DataFrames are also supported.

```python title="pandas_table_example.py"
import pandas as pd
import plotsrv as ps

df = pd.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.publish_view(
    df,
    label="pandas table",
    section="renderers",
    launch_server=True,
)
```

Table limits can be configured in `plotsrv.yaml`.

```yaml title="plotsrv.yaml"
limits:
  tables:
    max_rows: 10000
    max_columns: 200
```

## Plot renderer

matplotlib and plotnine plots are rendered as image views.

```python title="plot_example.py"
import matplotlib.pyplot as plt
import plotsrv as ps

fig, ax = plt.subplots()
ax.plot([1, 2, 3, 4], [10, 20, 15, 30])
ax.set_title("Example metric")
ax.set_xlabel("Run")
ax.set_ylabel("Value")

ps.publish_view(
    fig,
    label="metric plot",
    section="renderers",
    launch_server=True,
)
```

The plot renderer is useful for checking charts from scripts, jobs, notebooks, or server sessions.

plotsrv renders plots using a headless matplotlib backend, which is useful on servers where a desktop plotting window is not available.

## JSON renderer

Dictionaries, lists, and tuples are shown with the JSON renderer.

```python title="json_example.py"
import plotsrv as ps

metadata = {
    "experiment": "baseline-model",
    "status": "complete",
    "metrics": {
        "accuracy": 0.91,
        "precision": 0.88,
        "recall": 0.86,
    },
    "features": ["age", "score", "previous_attempts"],
}

ps.publish_view(
    metadata,
    label="model metadata",
    section="renderers",
    launch_server=True,
)
```

The JSON renderer includes:

- expandable tree view
- simple tree view
- text view
- search
- expand/collapse controls
- pinned values

For convenience, a clearly rectangular JSON payload can also offer **Table**
and **Plot** modes. JSON always remains the initial view. This opt-in applies
only to non-empty, bounded top-level arrays of objects with the exact same
string keys and finite scalar values. It does not flatten nested values,
inconsistent objects, scalar arrays, or arbitrary JSON; those remain in the
rich JSON viewer.

It is useful for:

- API responses
- model metadata
- configuration-like objects
- nested dictionaries
- validation summaries
- job status objects

## Text renderer

Strings and bytes are shown with the text renderer.

```python title="text_example.py"
import plotsrv as ps

log_text = """INFO job started
INFO extract complete
WARNING 15 rows skipped
ERROR one optional file was missing
INFO job finished
"""

ps.publish_view(
    log_text,
    label="job log",
    section="renderers",
    launch_server=True,
)
```

The text renderer includes:

- copy
- word wrap
- reverse line order
- lightweight log colouring
- jump to bottom

This is useful for:

- logs
- console output
- plain text reports
- watched text files
- simple status messages

## Python renderer

Generic Python objects that do not match a more specific renderer are shown using a Python/repr-style view.

```python title="python_object_example.py"
from dataclasses import dataclass
import plotsrv as ps

@dataclass
class RunConfig:
    model_name: str
    threshold: float
    max_rows: int

config = RunConfig(
    model_name="baseline",
    threshold=0.75,
    max_rows=10000,
)

ps.publish_view(
    config,
    label="run config",
    section="renderers",
    launch_server=True,
)
```

The Python renderer is useful when debugging object state or publishing a `repr()`-style artifact.

## Markdown renderer

Markdown strings and markdown files are rendered as markdown views.

```python title="markdown_example.py"
import plotsrv as ps

report = """
# Daily import report

## Summary

- Rows in: 10,000
- Rows loaded: 9,985
- Warnings: 15

| Check | Status |
|---|---|
| Schema | OK |
| Duplicates | Warning |
"""

ps.publish_view(
    report,
    label="markdown report",
    section="renderers",
    artifact_kind="markdown",
    launch_server=True,
)
```

Markdown is useful for:

- generated reports
- summaries
- notes
- lightweight documentation
- validation output

Markdown sanitisation is configurable.

Rendered code blocks have a small **Copy code** icon in their top-right corner.
It copies the displayed code, preserving indentation, blank lines and trailing
newlines, and briefly shows **Copied** (or **Copy failed** if the clipboard is
unavailable). The button supports keyboard and touch use in light/dark themes;
inline code has no extra controls. Copy controls are excluded from code exports.
Like the TOC, these controls apply to sanitized Markdown, leaving sandboxed HTML
isolated. Button discovery is bounded to 1,000 blocks / 10,000 document elements;
code text is read only when a copy button is clicked.

Use **TOC** above a rendered Markdown document to open its table of contents.
Click a heading to jump to that section. **Heading depth** defaults to H1–H3;
choose H1 only or include deeper headings through H6. The sidebar follows the
browser's light/dark theme and supports keyboard navigation; Escape closes it.
On small screens, the contents appear above the document and close after a jump.

The open state and depth survive live updates and snapshot changes for the same
view during the current page session. Heading jumps do not change the selected
snapshot or browser URL. The TOC covers the rendered preview, so truncated content
may have fewer headings than the full source. Its scan is limited to 1,000 headings
or 10,000 document elements and runs only when opened; there is no extra polling
or network request. Raw-HTML Markdown displayed in an isolated sandbox, and raw
fallback previews, show a disabled TOC button with an explanation.

## HTML renderer

HTML strings and HTML files are rendered with the HTML renderer.

```python title="html_example.py"
import plotsrv as ps

html = """
<h1>Daily import report</h1>
<p>Status: <strong>ok</strong></p>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Rows processed</td><td>9985</td></tr>
  <tr><td>Warnings</td><td>15</td></tr>
</table>
"""

ps.publish_view(
    html,
    label="html report",
    section="renderers",
    artifact_kind="html",
    launch_server=True,
)
```

HTML artifacts are useful for:

- generated reports
- existing HTML output
- simple rendered pages
- exported artifacts from other tools

!!! warning

    HTML can contain active content.

    Selecting or explicitly publishing an HTML report counts as trusting it;
    there is no per-file confirmation. By default, developer reports retain
    their CSS, JavaScript, forms, downloads and normal browser functionality.
    PlotSrv does not inject interaction blockers or sandbox these reports.

    This applies to locally selected files, direct local publishers and
    publishers authenticated with the server's publisher key. Possession of
    that key grants authority to publish active HTML. Anonymous remote
    ingestion, if explicitly enabled, cannot grant itself this authority;
    its HTML and all HTTP-published Markdown remain sanitized.

    Trusted reports execute with the dashboard's browser-origin privileges.
    Publish only reports and scripts you trust, including their dependencies.
    Use a dedicated origin for a public demo, with no unrelated applications
    or privileged cookies on that origin. Do not give anonymous visitors a
    report-upload path or a publisher key.

    `html_sanitize: true` and a nonempty `html_sandbox` remain optional
    restrictions; they can reduce report functionality. An explicitly
    configured sandbox also applies when opening a watched HTML URL directly.

## Image renderer

Image files can be published directly using a `Path`.

```python title="image_file_example.py"
from pathlib import Path
import plotsrv as ps

ps.publish_view(
    Path("example.png"),
    label="example image",
    section="renderers",
    launch_server=True,
)
```

A `Path` object tells plotsrv to read the file contents.

A plain string is treated as text:

```python
ps.publish_view(
    "example.png",
    label="literal text",
    section="renderers",
    launch_server=True,
)
```

The image renderer supports common image types such as:

- PNG
- JPEG
- GIF
- WebP
- BMP
- SVG

## Traceback renderer

Tracebacks can be published as structured artifacts.

Traceback rendering is disabled by default because tracebacks can expose file paths, source-code context, and other implementation details.

Enable it in config:

```yaml title="plotsrv.yaml"
security-settings:
  tracebacks_enabled: true
```

Then use `capture_exceptions()`:

```python title="traceback_example.py"
import plotsrv as ps

with ps.capture_exceptions(
    label="job error",
    section="renderers",
    launch_server=True,
):
    raise RuntimeError("Example failure")
```

The traceback renderer shows:

- exception type
- exception message
- stack frames
- file names
- line numbers
- source-code context where available

!!! warning

    Tracebacks are useful for development and internal observability, but they may expose sensitive implementation details.

    Enable traceback rendering only where that is acceptable.

## File rendering

plotsrv can infer renderers from file extensions.

```python title="publish_file.py"
from pathlib import Path
import plotsrv as ps

ps.publish_view(
    Path("results.csv"),
    label="results table",
    section="files",
    launch_server=True,
)
```

File inference is useful for existing outputs written by a process, such as CSVs, JSON files, markdown reports, HTML reports, logs, and images.

## File type summary

| Extension | Renderer |
|---|---|
| `.csv` | Table |
| `.json` | JSON |
| `.yaml`, `.yml` | JSON-like structured view |
| `.toml` | JSON-like structured view |
| `.ini`, `.cfg` | JSON-like structured view |
| `.md`, `.markdown` | Markdown |
| `.html`, `.htm` | HTML |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg` | Image |
| anything else | Text |

## Forcing a renderer

Most of the time, automatic renderer selection is enough.

When needed, provide an explicit artifact kind.

```python title="force_markdown.py"
import plotsrv as ps

text = """
# Report

This should be rendered as markdown.
"""

ps.publish_view(
    text,
    label="forced markdown",
    section="renderers",
    artifact_kind="markdown",
    launch_server=True,
)
```

For HTML:

```python title="force_html.py"
import plotsrv as ps

html = "<h1>Hello from HTML</h1>"

ps.publish_view(
    html,
    label="forced html",
    section="renderers",
    artifact_kind="html",
    launch_server=True,
)
```

## Publishing to an existing server

The examples above use `launch_server=True`, which starts an attached server inside the current Python process.

For the server workflow, start plotsrv separately:

```bash
plotsrv run script.py --host 127.0.0.1 --port 8000
```

Then publish with `host` and `port`:

```python
ps.publish_view(
    obj,
    label="result",
    section="renderers",
    host="127.0.0.1",
    port=8000,
)
```

Do not use `launch_server=True` in this case. With `host` and `port` only, `publish_view()` publishes to an existing plotsrv server.

## Renderer limits

Some renderers apply display limits to keep the browser responsive.

For example:

```yaml title="plotsrv.yaml"
limits:
  render:
    text: 1000000
    html: off
    markdown: off

  tables:
    max_rows: 10000
    max_columns: 200
```

Text-like renderer limits control how much content is displayed in the browser.

Table limits control how much table data plotsrv accepts and displays.

## Next steps

- [Quick start](../get-started/quick-start.md)
- [Watch files](../get-started/watch-files.md)
- [Configuration basics](../guides/configure-plotsrv.md)
- [Storage and history](history.md)

## Expand a view

Use **Expand view**, the corner icon beside Settings, to give the content nearly
the whole browser viewport. This changes plotsrv's layout; it does not request
browser fullscreen permission or reload the data.

Two small buttons remain at the top right: **Show view controls** and **Exit
expanded view**. Reveal the controls for the current view selector, freshness
and check status, snapshots, and any supported Table / Plot + data choices.
Streams keep their own Run selector and pause control. The controls stay open
until you explicitly hide them; there is no hover requirement or inactivity
timer. Open menus and dialogs prevent the header from being hidden.

Escape closes an open menu or dialog first; another Escape exits the expanded
layout. The exit button restores normal controls and keyboard focus. Embedded
HTML keeps its own frame and document state; keyboard events inside a sandboxed
report belong to that report, so use Tab to reach the persistent outer controls
when needed.

Filters, grouping, column settings, plot presentation, selected snapshots and
stream sessions survive entering/exiting. Normal editing utilities and Export
return on exit. Changing source or selecting a My view keeps the expanded
layout, while retaining the existing navigation rules: a different source
starts at its current data, and a saved My view applies its presentation to
Latest. Snapshot IDs and stream sessions are never transferred to another
source.

The layout preference is scoped to the dashboard and URL path in this tab's
`sessionStorage`. It survives source changes and reloads in that session; no
server setting or shared preference is written. If browser storage is denied,
expansion still works on the current page. Only the layout flag is stored, not
data, snapshot IDs or presentation settings.

Expansion uses the existing renderer and controls. It adds no polling, payload
requests or publisher work. Resize handling coalesces into one animation frame;
its size observer is active only while expanded. Expanded view and
[Compare](history.md#compare-stored-versions) remain mutually
exclusive: opening Compare exits expansion, and Expand view exits Compare
while preserving the inspected version.


## Watched source code and raw config text

With automatic routing, `.py` and `.pyi` files use the Python/code viewer. R
(`.R` or `.r`), SQL, shell, JavaScript/TypeScript, CSS, C/C++, Go and Rust stay in
Text, with **Styling → Auto** selecting syntax colour from the suffix. Known code
suffixes default to a head preview; an explicit head/tail choice takes precedence.
Unknown suffixes remain plain text unless an existing log style is recognised.
`--kind text` keeps the Text viewer even for Python; its Styling menu still lets
you choose Auto, Source code, None/Plain or the existing log styles.

JSON, YAML, TOML and INI retain their structured views. Their Text surface colours
raw source where the document carries it, or generated JSON for ordinary structured
objects. Markdown, images and HTML keep their dedicated renderers. Nothing is
imported or executed from the watched code. Remote receivers identify the suffix
from a bounded basename, never by opening a publisher path.

Server-side overrides use the normal config file and logical view IDs:

```yaml
code-settings:
  language: auto
  style: auto
  views:
    "watch:query":
      language: sql
    "watch:diagnostic":
      style: plain
```

An explicit language wins over transported language/format hints; `text` or an
unknown language selects plain syntax. Supported aliases include `python`, `r`,
`sql`, `bash`, `json`, `yaml`, `toml`, `ini`, `javascript`, `typescript`, `css`, `c`,
`cpp`, `go` and `rust`. No lexer plugins or source paths can be configured. For
Text, `style` also accepts `code`, `http`, `application`, `timestamp`, `syslog`,
`container`, `test`, `traceback` and `keyvalue`. Existing browser choices override
initial styling defaults. Restart the server after changing config.

Copy returns the displayed source text, without token markup or line numbers;
Text's Reverse lines also reverses the copied presentation. Code keeps Wrap,
Highlight and Lines controls. Browser preferences remain per source view when
switching snapshots; My views currently cover adjustable table/plot presentations.
Stored snapshots and restored Latest retain their own filename/format/language
hints, independently of today's source. Server language/style configuration and
browser preferences are current presentation choices.

Pygments is imported lazily while rendering a requested preview. Existing current
revision caching avoids repeat highlighting; there is no syntax worker or idle
polling. Highlighting admits at most 16,384 characters, 65,536 UTF-8 bytes and fewer
than 2,000 lines, then enforces 4,096 tokens and 256 KiB of token markup. At most two
highlight operations run concurrently. Unknown, busy, failed or over-budget
highlighting falls back to plain text. Python display itself is bounded to 65,536
characters and 2,000 source lines, including when ordinary display limits are off.
Other existing preview/download limits remain in effect.

The 25 ms lexer-loop deadline is **cooperative**, not cancellation of a lexer or
its first import. A slow token may overrun it; bounded input and the supported
built-in lexer set remain necessary. Incomplete tails are deliberately plain:
earlier multiline string/comment context may be missing. Local tails with unknown
completeness also take this conservative fallback. Head previews are coloured
from their available starting context. Copy/export still follows existing preview
and complete-source capabilities.

Implementation reference: [Pygments API](https://pygments.org/docs/api/) and
[security considerations](https://pygments.org/docs/security/).

For saved table and plot settings, see [My views](supported-outputs-and-files.md#saved-presentations).
For structured live logs, see [HTTP log streams](streams.md).

## Saved presentations

For normal use, see [Explore in the browser](../guides/explore-in-browser.md#save-a-useful-setup).

### Changing data and historical browsing

Saved settings apply to the source's **latest data**. Saving while browsing a
snapshot or stream session saves the presentation only; the dialog explains
this. Opening that saved entry starts at the latest source. Snapshot/session
selection remains a separate browsing choice, not part of the saved settings.

Extra columns are compatible. Missing grouping/sort/column settings can be
omitted with an explanation. Missing filters, changed filter types and invalid
plot fields pause the presentation rather than silently showing more rows or
a different plot under its saved name. **Repair presentation** asks you to
acknowledge the possible removal of filters. It applies compatible settings as
an ordinary working presentation; review the filters and plot before saving a
new view. The original saved configuration is preserved. Reset or reopen it
when the source is compatible again.

Compatibility checks use field names, lightweight inferred types and source
capabilities. They cannot detect changed units or meaning behind otherwise
identical fields; review presentations when the source semantics change.

A plot sourced from derived stream summaries retains that source requirement;
it cannot silently become a plot of retained raw rows. Existing plot limits and
coverage notices still apply. A saved presentation does not increase the source's
retention, query or plotting limits.

### Storage and compatibility

Settings are scoped to the browser origin, dashboard base path and configured
instance name, plus the exact logical source ID. Server restart generations are
not part of the storage key. Another browser profile, origin, base path or
instance name has a separate collection.

The collection is limited to 64 entries and 262,144 JSON characters; one ViewSpec
is limited to 16,384 characters, 128 fields/columns, 10 filters and 8 sort keys.
Names are at most 80 characters and captions 256. Storage is checked before JSON
parsing. Only supported presentation settings and lightweight field/type/source
requirements are accepted; datasets, paths, executable predicates, credentials,
DOM state and stream cursors are excluded.

Storage failures are visible in the dialog or selector. Disabled/full storage,
corrupt documents and unsupported versions do not silently replace existing
saves. This is the first ViewSpec format (version 1); unknown versions remain
untouched and need a compatible browser bundle. Other tabs receive change
notifications without replacing your working presentation. Updating a stale
copy is refused. Where Web Locks are available, saves across tabs are serialized
without waiting behind a busy tab; elsewhere the browser's normal last-write
behavior still applies to truly simultaneous writes.

These settings are browser preferences, not authenticated privacy or durable
backup. Filter values and captions may be sensitive; other users of this browser
profile can see them. Clearing site storage removes them. There is no cross-device
sync, server save/delete request, sharing or historical data binding.
