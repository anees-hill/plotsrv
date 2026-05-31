---
icon: lucide/server-cog
---

# Deployment patterns

`plotsrv` can be used in several modes:

- attached to a local Python process
- as a separate server alongside scripts or jobs
- on a VM or internal server
- inside a container
- behind a reverse proxy
- as part of a managed platform

Not every deployment pattern is mature yet - this is an ongoing piece of work! (sections marked TODO are not yet mature)

!!! note

    The examples below use `ps.publish_view()` but can be substituted with the decorator approach using `@view`.

## Simple development

From an interactive Python session, notebook, or short local script.

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="summary",
    section="demo",
    launch_server=True,
)
```

This starts an attached plotsrv server inside the current Python process.

Open:

```text
http://127.0.0.1:8000
```

Useful for:

- quick local exploration
- testing whether plotsrv is installed correctly
- publishing one or two objects during development
- demos and small experiments

It is not the best pattern for long-running scripts, scheduled jobs, or shared access.

For those, use the server workflow.

## Server workflow

For scripts, pipelines, batch jobs, and scheduled processes, start plotsrv separately and publish to it from Python.

Example:

```bash
plotsrv run ./src --host 127.0.0.1 --port 8000
```

In a seperate terminal using Python:

```python
import plotsrv as ps

ps.publish_view(
    {"status": "complete"},
    label="status",
    section="daily pipeline",
    host="127.0.0.1",
    port=8000,
)
```

This pattern keeps the plotsrv UI running independently of the script that publishes output.

It is useful for:

- ETL jobs
- batch scripts
- model training runs
- scheduled reporting jobs
- headless or remote development
- lightweight internal monitoring

## VM or internal server

A common deployment pattern is to run plotsrv on a VM or internal Linux server.

The server might run:

- as a foreground process during development
- inside `tmux` or `screen`
- as a `systemd` service
- behind a reverse proxy such as Caddy or Nginx

For private/internal access, SSH port forwarding is often the safest first option.

For public internet access, avoid binding plotsrv directly to a public interface. Prefer keeping plotsrv bound to `127.0.0.1` and exposing only selected routes through a reverse proxy. The Caddy section below shows this pattern.

!!! warning

    plotsrv is designed primarily for trusted development, internal, and controlled environments.

    Public internet exposure should be treated carefully. Only expose non-sensitive demo data, avoid enabling traceback views publicly, and block write/control endpoints such as `/publish` and `/shutdown`.

## Running manually

For a simple internal setup:

```bash
plotsrv run ./src --host 127.0.0.1 --port 8000 --config plotsrv.yaml
```

Then publish to it from scripts running on the same server:

```python
ps.publish_view(
    result,
    label="result",
    section="pipeline",
    host="127.0.0.1",
    port=8000,
)
```

If accessing the UI remotely, SSH port forwarding is usually the safest first option:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

Then open locally:

```text
http://127.0.0.1:8000
```

## Running with systemd

For a persistent internal server, plotsrv can be run with `systemd`.

Example service file:

```ini title="/etc/systemd/system/plotsrv.service"
[Unit]
Description=plotsrv server
After=network.target

[Service]
Type=simple
User=plotsrv
WorkingDirectory=/opt/plotsrv-project
ExecStart=/opt/plotsrv-project/.venv/bin/plotsrv run ./src --host 127.0.0.1 --port 8000 --config plotsrv.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable plotsrv
sudo systemctl start plotsrv
sudo systemctl status plotsrv
```

This pattern works well when plotsrv is used as an internal observability surface for jobs running on the same machine.

## Reverse proxy with Caddy

Caddy can expose plotsrv through a public or internal hostname while keeping the plotsrv server itself bound to localhost.

With this setup:

```text
browser -> Caddy -> plotsrv on 127.0.0.1:8000
```

This is safer than binding plotsrv directly to a public network interface because Caddy controls which routes are exposed.

### When to use this pattern

Use this pattern when:

- plotsrv is running on a VM or server
- the UI needs a friendly URL
- HTTPS should be handled automatically
- only selected read-only routes should be exposed publicly

For private workflows, SSH tunnelling or an authenticated internal reverse proxy is usually preferable.

For public demos, expose only non-sensitive content and block write/control routes.

### Start plotsrv on localhost

Run plotsrv bound to `127.0.0.1`:

```bash
plotsrv run ./src --host 127.0.0.1 --port 8000 --config plotsrv.yaml
```

This means plotsrv is only reachable locally on the server.

Caddy will handle external access.

### Use a strict read-only Caddyfile

Edit the Caddyfile:

```bash
sudo nano /etc/caddy/Caddyfile
```

Use an allow-list so only the routes needed for viewing the UI are public:

```caddy title="/etc/caddy/Caddyfile"
demo.plotsrv.com {
    @public {
        path / /plot /table/data /artifact /status /history /table/export /static/* /assets/*
    }

    handle @public {
        reverse_proxy 127.0.0.1:8000
    }

    respond 404
}
```

This configuration means:

- selected UI routes are proxied to plotsrv
- all other routes return `404`
- write/control routes such as `/publish` and `/shutdown` are not publicly reachable
- new or unexpected routes are blocked by default

This pattern is suitable for a public read-only demo where trusted code running on the server publishes the displayed content.

### Validate and reload Caddy

Validate the configuration:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

Reload Caddy:

```bash
sudo systemctl reload caddy
```

Check the service:

```bash
sudo systemctl status caddy
```

### Test the deployment

First test plotsrv locally on the server:

```bash
curl http://127.0.0.1:8000
```

Then test the public hostname:

```bash
curl -I https://demo.plotsrv.com
```

Blocked routes should return `404`:

```bash
curl -I https://demo.plotsrv.com/publish
curl -I https://demo.plotsrv.com/shutdown
curl -I https://demo.plotsrv.com/openapi.json
```

### Security considerations

Before exposing plotsrv beyond localhost, consider:

- who can access the UI
- whether the data is safe to publish
- whether tracebacks are enabled
- whether watched files may contain sensitive data
- whether published tables or objects contain sensitive data
- whether write/control endpoints are blocked
- whether the reverse proxy provides authentication
- whether the service is reachable from the public internet

For public demos, prefer:

- binding plotsrv to `127.0.0.1`
- exposing it through a reverse proxy
- using HTTPS
- allowing only read-only UI routes
- blocking everything else by default
- publishing only non-sensitive demo data

## Docker

TODO
## Kubernetes

TODO
## Cloud-based deployment

TODO

## Posit Connect

TODO

## Next steps

- [Configuration basics](../get-started/configuration-basics.md)
- [Storage and history](storage-and-history.md)
- [CLI reference](cli.md)
