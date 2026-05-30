---
icon: lucide/rocket
---

# UI customisation

plotsrv can be customised through `plotsrv.yaml`.

This is useful when running plotsrv as a small internal status surface, demo app, or project-specific viewer.

Common UI customisations include:

- page title
- header text
- logo
- favicon
- header colour
- optional UI controls

## Create a config file

Create a starter config:

```bash
plotsrv config create
```

Then start plotsrv with the config:

```bash
plotsrv run --config plotsrv.yaml
```

## Basic UI settings

A simple UI settings section might look like this:

```yaml title="plotsrv.yaml"
ui-settings:
  page_title: "plotsrv"
  header_text: "plotsrv"
```

The page title appears in the browser tab.

The header text appears in the plotsrv UI header.

## Logo and favicon

A logo and favicon can be configured with local file paths.

```yaml title="plotsrv.yaml"
ui-settings:
  logo: "assets/logo.png"
  favicon: "assets/favicon.png"
```

Paths are resolved relative to the config file.

For example:

```text
project/
  plotsrv.yaml
  assets/
    logo.png
    favicon.png
```

## Header colour

The header colour can be customised:

```yaml title="plotsrv.yaml"
ui-settings:
  header_fill_colour: "#ffffff"
```

Use this to make the plotsrv UI fit a project, internal tool, or demo environment.

## A small branded config

```yaml title="plotsrv.yaml"
ui-settings:
  page_title: "Operations monitor"
  header_text: "Operations monitor"
  logo: "assets/logo.png"
  favicon: "assets/favicon.png"
  header_fill_colour: "#ffffff"
```

Start plotsrv:

```bash
plotsrv run --config plotsrv.yaml
```

## When to customise the UI

UI customisation is useful once plotsrv is being used for something more durable than a quick local check.

For example:

- a small internal monitoring page
- a demo environment
- a team-specific viewer
- a project-specific status surface
- a long-running server workflow

For quick interactive use, the defaults are usually enough.

## Combine with storage and freshness

UI customisation works well with storage and freshness settings.

```yaml title="plotsrv.yaml"
ui-settings:
  page_title: "Pipeline monitor"
  header_text: "Pipeline monitor"

storage-settings:
  enabled: true
  default_keep_last: 5
  default_min_store_interval: 1h
  max_snapshot_size_mb: 20

freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h
```

This gives a small project-specific viewer with:

- a custom title
- latest restore after restart
- snapshot history
- freshness indicators

## Next steps

- [Storage and history](storage-and-history.md)
- [Freshness](freshness.md)
- [CLI reference](cli.md)
