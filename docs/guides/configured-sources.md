# Configured sources and discovery progress

`plotsrv run` can use repeatable discovery and watch sources from its selected
configuration file. The sources belong to the machine running `run` or `publish`;
`plotsrv serve` never scans or starts these watches.

```yaml
publisher-settings:
  discovery:
    target: ./src
    selection: ["etl:orders", "Status"]
    include_pruned: false
  watch:
    - path: ./logs/application.log
      view_id: logs:application
      label: Application log
      section: Logs
      read_mode: tail
      materialization: memory
```

Select that file using the existing cwd/environment rules or an explicit path:

```sh
plotsrv run --config /project/config/plotsrv.yml
```

Configured filesystem targets and watch paths resolve beside the selected
config, not beside the shell's current directory. In this example `./src` means
`/project/config/src`. Module/package names are also supported, including a
`module:callable` target whose module supplies the scan scope. Discovery never
executes the callable.

## Overrides and selection

| Invocation | Discovery source | Watches |
| --- | --- | --- |
| `plotsrv run` | Configured target, otherwise existing project-root default | Configured set |
| `plotsrv run ./other` | Explicit path relative to shell cwd | Configured set |
| `plotsrv run --watch ./status.log` | Configured target/default | Explicit CLI set replaces configured set |
| `plotsrv run --no-watch` | Configured target/default | Disabled for this invocation |

An override prints a concise information message; `--quiet` suppresses progress
and information. `--watch` and `--no-watch` cannot be combined. An empty configured
`watch: []` is valid. Default argparse values do not erase configured labels,
sections, head/tail mode or materialisation. An explicit
`--watch-materialization` still overrides materialisation for the chosen watches.
Existing watch read limits, encoding, cadence and head/tail controls retain their
existing behaviour. CLI watch paths remain relative to the CLI working directory.

Configured `discovery.selection` uses the existing exact label, section or view
ID matching. Explicit `--include` replaces that selection; `--exclude` applies
afterwards and wins. Discovery selection does not filter the watch set. Explicit
view IDs survive registration and `config populate`, even when labels differ.
Config population retains its existing merge/replace behaviour and respects the
configuration's discovery selection.

The sequential configuration wizard writes `discovery.exact_selection` when saving
its chosen IDs. When present, this list matches only logical IDs; an empty list
skips discovery entirely. It takes precedence over legacy `selection`, whose
empty list continues to mean all views. An explicit CLI `--include` replaces
either configured selection. Optional `discovery.additional_ids` supplies reviewed
manual/dynamic IDs for local registration, publishing and config population.
These are logical identities, not filesystem paths. For example:

```yaml
publisher-settings:
  discovery:
    target: ./src
    exact_selection: ["etl:orders"]
    additional_ids: ["etl:runtime-only"]
```

Saving or loading these settings never seals a remote catalogue. A publisher
still needs explicit `--seal-catalogue` after reviewing the complete union when
initialising a locked receiver.

Selection controls discovery, registration and config population. It does not
stop application functions from executing, or prevent an active producer from
publishing another ID to a dynamic server. Use explicit server catalogue
admission when write admission must be restricted.

Existing `run --mode callable` remains an explicit execution choice. Discovery
resolves its module scope statically first. When a configured module target comes
from a different directory, the explicitly requested child process uses the
config directory (and its conventional `src` layout) for module lookup. Discovery
itself does not change the process directory or import the application.

## What the scanner can establish

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

## Progress, bounds and cancellation

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

## Shared engine and reviewable manifests

Terminal presentation is separate from the source engine, so other callers can
supply their own progress and cancellation handling:

```python
from threading import Event
from plotsrv.discovery import scan_sources
from plotsrv.source_setup import resolve_source_setup, build_manifest

stop = Event()
setup = resolve_source_setup()
result = scan_sources(
    setup.scan_root(default_target="."),
    include_pruned=setup.include_pruned,
    on_progress=lambda event: print(event.phase, event.processed, event.total),
    cancelled=stop,
)

# Inspect result.views and result.issues before deciding the complete union.
manifest = build_manifest(
    result,
    selection=setup.selection,
    watches=setup.watches,
    added_ids=["runtime:explicitly-reviewed-id"],
)
```

`DiscoveryProgress` carries phase, processed count, optional total, files found,
skipped count and elapsed time. `scan_sources` returns bounded views/issues and
completion/cancellation/limit state. `on_issue` is an optional issue callback.
`discover_views` remains the compatible list-returning API; it raises on cancelled
or limited scans so partial results cannot silently become registrations.

`build_manifest` produces the protocol-1 `views` body accepted by the
[catalogue bootstrap endpoint](publisher-ingestion.md). It includes selected
known declarations, configured watches and caller-supplied reviewed dynamic IDs.
Duplicate/conflicting IDs fail before registration or config writes. Cancelled
or resource-limited scans cannot produce a manifest. Completed scans with
unresolved declarations or skipped files require explicit `reviewed=True` after
inspection; that flag does not resolve duplicate IDs or remove structural limits.

Building or reviewing a manifest does not send it, register it remotely or seal a
catalogue. The caller must deliberately submit the complete union when that is
appropriate. The [publisher agent](publisher-agent.md) uses this engine for
explicit catalogue registration/sealing and configured remote watches.
