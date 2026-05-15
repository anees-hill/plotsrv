---
icon: lucide/package
---

# Installation

Install plotsrv into the Python environment where your code runs.

=== "pip"

    ```bash
    pip install plotsrv
    ```

=== "uv"

    ```bash
    uv add plotsrv
    ```

## Check the CLI is available

After installation, check that the `plotsrv` command is available:

```bash
plotsrv --help
```

You should see the plotsrv command-line help.

## Check the Python API is available

You can also check the Python import:

```python
import plotsrv as ps

print(ps)
```

If that runs without an import error, plotsrv is available in your Python environment.

## Recommended first check

The fastest way to confirm everything is working is to publish a small table.

```python title="check_install.py"
import polars as pl
import plotsrv as ps

df = pl.DataFrame({
    "name": ["alpha", "beta", "gamma"],
    "value": [10, 20, 30],
})

ps.refresh_view(df)
```

Then open:

```text
http://127.0.0.1:8000
```

You should see the table in the plotsrv browser UI.

!!! note

    `ps.refresh_view()` starts a local plotsrv server automatically if one is not already running.

## Installing on a server

plotsrv is often useful on a remote or headless server.

Install it in the environment used by your script or project:

=== "pip"

    ```bash
    pip install plotsrv
    ```

=== "uv"

    ```bash
    uv add plotsrv
    ```

Then run Python or the plotsrv CLI from that same environment.

For example:

```bash
plotsrv run --host 127.0.0.1 --port 8000
```

If you are working over SSH, you can access the UI using port forwarding.

```bash
ssh -L 8000:127.0.0.1:8000 user@your-server
```

Then open this on your local machine:

```text
http://127.0.0.1:8000
```

!!! warning

    Be careful before binding plotsrv to a public network interface.

    For many server workflows, an SSH tunnel is a safer first option than exposing the plotsrv server directly.

## Next step

Continue to the [Quick start](quick-start.md).
