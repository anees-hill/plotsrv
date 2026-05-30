---
icon: lucide/rocket
---

# Release notes

A short summary of notable plotsrv releases.

## v0.3.0

v0.3.0 focused on making plotsrv easier to use in real scripts and longer-running workflows.

Notable changes:

- improved `@ps.view(...)` and `ps.publish_view(...)` as the main public API
- added `launch_server=True` for quick interactive use
- improved publishing to an existing plotsrv server with `host` and `port`
- added file-backed storage for latest views and snapshot history
- improved view discovery from Python code
- added storage CLI commands for inspecting and clearing stored outputs

## v0.2.0

v0.2.0 focused on API usability and project tidying.

Notable changes:

- moved toward `@ps.view(...)` and `ps.publish_view(...)`
- improved CLI behaviour
- improved config creation and population
- simplified the public API surface
- tidied internal structure ahead of broader documentation work

## v0.1.0

v0.1.0 was the first usable version of plotsrv.

Notable features:

- browser UI
- renderer support for common output types
- initial Python publishing API
- initial CLI workflow
