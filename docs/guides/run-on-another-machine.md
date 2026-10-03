# Run plotsrv on another machine

Your Python process and the plotsrv server don’t have to run on the same machine.

```text
Python process  --->  plotsrv server  --->  browser
```

Start the server independently:

```bash
plotsrv serve --host 127.0.0.1 --port 8000
```

`serve` starts with no application target. It does not scan your project, run your
code, or open the publisher’s files. Views appear when you publish them.

## Start with an SSH tunnel

For a private server on a VM, run the command above on the VM. From your laptop:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@your-vm
```

Open **<http://127.0.0.1:8000>** on your laptop. To publish through that tunnel:

```python
import plotsrv as ps

ps.publish_view({"rows": 123}, label="orders", destination="http://127.0.0.1:8000/")
```

Keep the tunnel running. If Python also runs on the VM, publish to its local
`127.0.0.1:8000` directly. This avoids exposing the dashboard on a public port.
See [EDA over SSH](../examples/eda-on-a-server.md) for a complete table/plot example.

## Publish over HTTPS

When publishers need a network-accessible endpoint, put the server behind an HTTPS
proxy and configure a publisher key on the server:

```yaml title="server.yml"
server-settings:
  bind:
    host: 127.0.0.1
    port: 8000
  ingestion:
    bearer_token_env: PLOTSRV_INGEST_KEY
```

Set `PLOTSRV_INGEST_KEY` in the server environment to a secret shared only with
trusted publishers, then start:

```bash
plotsrv serve --config server.yml
```

In your application’s directory, use a separate config:

```yaml title="plotsrv.yml"
publisher-settings:
  destination:
    url: https://plots.example.test/
    bearer_token_env: PLOTSRV_PUBLISH_KEY
```

Set `PLOTSRV_PUBLISH_KEY` to the same secret on the publisher machine. Replace the
example URL with your HTTPS proxy’s URL. Then ordinary calls use that destination:

```python
import plotsrv as ps

ps.publish_view({"rows": 123}, view_id="daily:orders")
```

A configured destination also activates ordinary metadata-only decorators when
they are evaluated. The publisher and server do not need shared config files or
a shared filesystem. A failed remote publish never starts a local fallback.

**The publisher key does not protect browser reads.** Protect private dashboards
at the proxy too. Keep management routes such as `/shutdown` off public routing,
use a dedicated origin, and publish only data and HTML you trust. See
[Remote publishing and security](publisher-ingestion.md) before exposing a server.

## Watch a file beside the application

```bash
plotsrv watch ./logs/job.log --tail --config plotsrv.yml
```

A configured destination sends watched previews to that server. Alternatively,
specify both routing and the credential variable explicitly:

```bash
plotsrv watch ./logs/job.log --tail \
  --destination https://plots.example.test/ \
  --bearer-token-env PLOTSRV_PUBLISH_KEY
```

The watch runs where the file lives. The receiver never opens that file path.
For configured sets of files and declarations, `plotsrv publish --config plotsrv.yml`
provides an optional foreground helper. It does not execute your application.
See [CLI reference](cli.md) for its options.

## Keep the server running

For a Linux service, install plotsrv in a dedicated virtual environment and adapt
this unit to your paths and service account:

```ini title="/etc/systemd/system/plotsrv.service"
[Unit]
Description=plotsrv
After=network.target

[Service]
User=plotsrv
WorkingDirectory=/srv/plotsrv
ExecStart=/srv/plotsrv/.venv/bin/plotsrv serve --config /srv/plotsrv/server.yml
EnvironmentFile=/etc/plotsrv/server.env
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Create the account, directories, environment file, and config before installing
the unit. Keep the environment file readable only by the users that need its
secrets. Then, on that host:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now plotsrv
```

Keep the storage directory on persistent disk if you [keep history](keep-history.md).
For Caddy route restrictions, public demo isolation, TLS, and deployment checks,
see the [security reference](public-demo-security.md).
