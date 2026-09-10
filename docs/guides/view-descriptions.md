# View descriptions

Sources can carry a short plain-text explanation. Open **About this view** (the
small **i** beside the header controls) by mouse, touch or keyboard. Escape closes
it before leaving expanded presentation. Sources without an explanation have no
empty information panel. This is separate from About this dashboard/settings.

Descriptions also appear in the selector. A My view's non-empty caption describes
that saved presentation; a suggested recipe uses its own purpose and scope. An
empty presentation caption falls back to the source description. Featured entries
keep their configured caption, falling back to the source when absent. Source
metadata updates do not replace saved or suggested captions, table data, filters
or plot settings.

## Source precedence and privacy

On each machine, `description-settings.views` supplies explicit source metadata.
The receiving server's explicit description wins over publisher metadata. On the
publisher, its explicit config wins over `publish_view(description=...)` or the
first paragraph of an actual decorated function's docstring. An explicit empty
string suppresses the source explanation.

```yaml
# On the publisher, disable automatic extraction globally if docs are private.
description-settings:
  extract_docstrings: false
  views:
    "orders:regional":
      description: Fulfilled orders and net revenue grouped by region.
    "ops:latency":
      extract_docstrings: true
    "internal:debug":
      description: ""
```

`extract_docstrings` defaults to `true`; per-view values override it. This setting
controls automatic extraction on the publisher/discovery machine. A receiving
server cannot undo text a publisher has already transmitted: disable extraction
where the application runs if its docstrings must remain private.

Extraction occurs during decoration or AST discovery, not on every function call.
Only the bounded first paragraph is cleaned. It does not unwrap decorators, inherit
class documentation, read README/Markdown files or import application modules to
obtain documentation. Dynamic functions without a docstring simply have no fallback.
Changing extraction/config policy requires recreating the decorated producer or
restarting discovery; it is not a live configuration watcher.

Descriptions use at most 512 characters. Cleaning/extraction examines at most the
first 4,096 characters before splitting/normalising; the wire descriptor's existing
2,048-byte limit remains enforced. Plain text is escaped, never rendered as HTML.
Ordinary and observation publication carry the bounded text with existing work;
there is no extra description worker, queue, polling or HTTP request per result.
Configured stream/watch descriptions travel with registration. Watch registration
uses the advertised `view-descriptions-v1` capability, so older watch receivers
can continue receiving data without that optional metadata.

Descriptions are **current catalogue/presentation metadata**, not snapshot facts.
About this view labels that distinction while inspecting a stored snapshot, stream
run or captured Latest. Existing stored payloads are not rewritten. In particular,
a source's current explanation is not evidence of what an earlier snapshot meant.

## Explain your own business summary

Ordinary Python and the existing publication API are sufficient:

```python
import pandas as pd
import plotsrv as ps

@ps.view(view_id="orders:regional", label="Regional orders", async_=True)
def regional_orders(orders: pd.DataFrame):
    """Fulfilled orders and net revenue grouped by region.

    Internal implementation notes stay out of the automatic description.
    """
    fulfilled = orders.loc[orders["fulfilled"]]
    return fulfilled.groupby("region", as_index=False).agg(
        orders=("order_id", "count"), revenue=("net_revenue", "sum")
    )
```

Call `regional_orders(orders)` with your data. Use normal
`publisher-settings.destination` configuration to send its result to a remote
server, or the usual local publication setup. For a one-shot application,
`ps.flush_views(timeout=2)` provides the existing bounded flush.

The filtering and aggregation above run in **your function**, synchronously.
Asynchronous publishing does not move that computation into the background or make
it free. For an already-computed table, metrics dictionary or figure, supply text
explicitly instead:

```python
ps.publish_view(
    {"fulfilled_orders": 120, "net_revenue": 8400.0},
    view_id="orders:totals",
    description="Current fulfilled-order totals supplied by the business pipeline.",
    async_=True,
)
```

No observation DSL or `observe=True` is required for these custom results.
