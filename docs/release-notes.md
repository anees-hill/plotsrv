# Release notes

## v0.6.0

v0.6.0 makes replaceable live publishing bounded and inspectable.

* added `async_=True` to `publish_view()` and `@view(...)` for attached and remote live publishing
* added a bounded latest-wins `PublishWorker`, with count and estimated-byte budgets
* added `flush_views()` and short publish-worker flushing during `stop_server()`
* exposed publish and storage queue counters through `/status`
* guarded the global in-memory view store against concurrent request/worker mutation
* bounded queued storage work by task count and estimated retained bytes

## v0.5.1

v0.5.1 makes on-demand file-backed watched-file serving bounded and measurable.

* file-backed CSV previews are parsed incrementally from disk instead of holding a raw byte window and then scanning the full file for a row count
* CSV responses report loaded rows separately and mark a full row total as unknown when it has not been calculated
* file-backed preview loads are concurrency-bounded with a clear temporary-busy response
* watched-file source downloads, images, and unsanitised HTML use streaming routes instead of loading source bytes into JSON responses
* added the operational benchmark harness for comparing pipeline and watched-file resource use

## v0.5.0

v0.5.0 improves watched-file resource safety.

* added memory-backed and file-backed watched-file materialisation
* large watched files can now be represented by metadata and previewed from disk on demand
* file-backed CSV files are served through bounded table previews

## v0.4.0

v0.4.0 configuration clarity and watched-file reliability.

* simplified and clarified configuration structure and generated starter config
* improved watched-file behaviour, limits, freshness, and storage handling
* improved error reporting and visibility for failed publishes and watched-file updates

## v0.3.1

v0.3.1 first plotsrv documentation release.

* added getting-started guides and configuration documentation
* added documentation for watched files, storage, freshness, and Python APIs
* improved examples and guidance for real-world usage


## v0.3.0

v0.3.0 ease of use in real scripts and longer-running workflows.

- improved `@ps.view(...)` and `ps.publish_view(...)` as the main public API
- added `launch_server=True` for quick interactive use
- improved publishing to an existing plotsrv server with `host` and `port`
- added file-backed storage for latest views and snapshot history
- improved view discovery from Python code
- added storage CLI commands for inspecting and clearing stored outputs

## v0.2.0

v0.2.0 API usability and project tidying.

- moved toward `@ps.view(...)` and `ps.publish_view(...)`
- improved CLI behaviour
- improved config creation and population
- simplified the public API surface
- tidied internal structure ahead of broader documentation work

## v0.1.0

- significant UI updates/rich features

## Pre v0.1.0

Please see [GitHub](https://github.com/anees-hill/plotsrv/tags)
