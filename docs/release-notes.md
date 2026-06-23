# Release notes

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
