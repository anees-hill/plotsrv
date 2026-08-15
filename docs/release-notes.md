# Release notes

## v0.5.1

v0.5.1 refines resource-safe watched-file serving and its defaults.

* file-backed CSV previews parse bounded rows and columns incrementally, avoiding unnecessary full-file scans and duplicate in-memory representations
* generated configuration now exposes watched-file materialization, uses a 10 MB automatic file-backing threshold, and enables latest-state persistence when storage is enabled
* generated configuration documents bounded async live-publish settings; synchronous publishing remains the compatibility default
* added repeatable release-gate benchmark coverage for watched-file settling, overload recovery, and publish-queue behaviour

## v0.5.0

v0.5.0 is a perf-based update introducing bounded async live publishing and file-backed watched-file serving.

* added `async_=True` to `publish_view()` and `@view(...)` for attached and remote live publishing
* added a bounded latest-wins `PublishWorker`, with count and estimated-byte budgets
* guarded the global in-memory view store against concurrent request/worker mutation
* added memory-backed and file-backed watched-file materialisation
* file-backed CSV previews are parsed incrementally from disk instead of holding a raw byte window and then scanning the full file for a row count
* large watched files can now be represented by metadata and previewed from disk on demand

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
