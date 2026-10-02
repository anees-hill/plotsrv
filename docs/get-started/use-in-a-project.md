# Use plotsrv in a project

Give a function’s output a place in the browser. Save this as `job.py`:

```python
import plotsrv as ps

@ps.view(label="orders", section="daily", port=8000)
def orders():
    """Counts from the daily orders import."""
    return {"rows": 123, "errors": 0}

if __name__ == "__main__":
    result = orders()
    print(result)
```

Start plotsrv in one terminal:

```bash
plotsrv run job.py
```

Run your job in another, from the same environment:

```bash
python job.py
```

Open **<http://127.0.0.1:8000>** and choose **orders**. Run the job again to update it.
The server stays up between runs.

## Declare a view, then publish it

`plotsrv run` reads the source to find declarations before your job publishes
anything. It does not import or run your application in its normal mode.
A declared view can therefore be listed before it has data.

Calling `orders()` still returns the dictionary. The decorator also publishes it
to the server on port 8000. Its docstring provides the view’s short description.

The `port=8000` matters. An ordinary `@ps.view(label="orders")` can attach metadata
without publishing anything. Use explicit publishing options, as above, or a
configured remote destination when you want function calls to publish.

Keep labels and sections stable. Here the resulting view ID is `daily:orders`.
Repeated publication to that ID replaces the current output; it does not create
another view. Use `view_id="daily:orders"` when you want to set the identity
independently of its display label.

## Scan your project

```bash
plotsrv run ./src
```

The scanner recognises supported literal `@ps.view(...)`, `publish_view(...)`,
and `stream_view(...)` declarations. It cannot determine every ID constructed at
runtime. Normal dynamic publishing still works unless you explicitly restrict
which view IDs the server accepts.

Keep imports and IDs straightforward. See [CLI reference](../guides/cli.md) and
[discovery details](../guides/configured-sources.md) for selection and scan rules.

## Let plotsrv call a function

For a zero-argument function, callable mode can execute it in a subprocess and
publish its return value:

```bash
plotsrv run job:orders --mode callable --keep-alive
```

Use `--call-every 60` instead of `--keep-alive` to call it every minute. The target
is imported in that subprocess, so normal import side effects apply. A function
that already publishes through its decorator may also publish during that call;
use a metadata-only decorator for a function you intend the runner to publish.

For an application with its own scheduler, keep calling it normally and use the
two-terminal pattern above.

## Add config when you need it

```bash
plotsrv config init
```

The wizard can discover your declared views and help configure the server and
publisher. See [configuration](configuration-basics.md) for file selection and
[remote publishing](../guides/remote-publishers.md) when the server lives elsewhere.

Next: [Publish from Python](../guides/publish-from-python.md), or try the complete
[ETL example](../examples/etl-pipeline.md).
