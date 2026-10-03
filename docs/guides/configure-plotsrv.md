# Configure plotsrv

You don’t need a config file to try plotsrv. When you want one:

```bash
plotsrv config init
```

The terminal wizard asks about the parts you use, can scan your project’s declared
views, and shows the proposed changes before saving. It can edit an existing file
and makes a backup when replacing one. Cancelling leaves the config unchanged.

## Choose the file

```bash
plotsrv config init --config plotsrv.yml
plotsrv run ./src --config plotsrv.yml
```

Without an explicit path, commands use `PLOTSRV_CONFIG`, then the usual
`plotsrv.yml` / `plotsrv.yaml` lookup. A directly publishing Python process uses
its own selected config, not the server’s copy.

For a separate publisher process:

```bash
PLOTSRV_CONFIG=publisher.yml python job.py
```

Keep server policy on the server: storage, checks, webhook destinations, and
which publishers it accepts. Keep publisher destinations and local source paths
beside the application. See [remote publishing](run-on-another-machine.md).

## Write a small config by hand

Start with the settings you need:

```yaml title="plotsrv.yml"
storage-settings:
  enabled: true
  default_keep_last: 5

freshness-settings:
  enabled: true
  expected_every: 1h
  warn_after: 90m
  overdue_after: 2h

ui-settings:
  page_title: Daily jobs
  header_text: Daily jobs
```

Restart the server after changing its config. See [Keep history](keep-history.md)
and [Keep an eye on a job](keep-an-eye-on-a-job.md) for what these settings do.
Global history/freshness settings do not automatically opt watched files in.

## Change the title, colours, or logo

```bash
plotsrv config ui --config plotsrv.yml
```

This opens a temporary browser editor for the shared dashboard appearance. Use
the session key printed in the terminal, review the preview, and save or cancel.
It is separate from the running dashboard; restart that dashboard to load saved
settings. Keep the editor private, or reach it through an SSH tunnel.

The ordinary browser theme and My views preferences are local to that browser.
They do not edit the server config.

## Generate rather than answer questions

```bash
plotsrv config create
plotsrv config populate storage ./src
```

`create` writes the compact starter template. `create --expanded` includes more
settings. `populate` discovers view IDs and proposes per-view entries; review them
before saving. Use the CLI reference for replacement and noninteractive options.

## Look up an exact setting

The [Configuration reference](configuration-reference.md) covers defaults,
per-view overrides, named instances, limits, and source-specific behaviour.
[CLI reference](cli.md) lists all configuration commands.
