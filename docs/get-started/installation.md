---
icon: lucide/package
---

# Installation

Install `plotsrv` into the Python environment where the code will run.

=== "pip"

    ```bash
    pip install plotsrv
    ```

=== "uv"

    ```bash
    uv add plotsrv

    # or add to a dependency group, i.e:
    uv add plotsrv --group monitoring
    ```

## Check the CLI

Run:

```bash
plotsrv --help
```

This should print the plotsrv command-line help.

## Try a first publish

To check the UI:

```python
import plotsrv as ps

ps.publish_view(
    {"status": "ok"},
    label="install check",
    launch_server=True,
)
```

Open:

```text
http://127.0.0.1:8000
```

The object should appear in the browser UI.

## Working on a remote server

For SSH-based work, port forwarding is usually the simplest starting point.

Run this on the local machine:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

Then run plotsrv on the server and open this locally:

```text
http://127.0.0.1:8000
```

Avoid exposing plotsrv directly to a public network unless access controls and network boundaries have been considered.

## Next step

Continue to [Quick start](quick-start.md).
