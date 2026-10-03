# EDA over SSH

Inspect a DataFrame and plot from a VM without opening a public dashboard port.
Run both Python and plotsrv on the VM; open the browser on your laptop.

## Start plotsrv on the VM

```bash
python -m pip install plotsrv
plotsrv serve --host 127.0.0.1 --port 8000
```

Keep that terminal running. In another VM terminal, save this as `eda.py`:

```python
import pandas as pd
import matplotlib.pyplot as plt
import plotsrv as ps

sales = pd.DataFrame({
    "region": ["North", "South", "West", "East"],
    "orders": [12, 18, 9, 15],
    "revenue": [240, 540, 180, 375],
})
ps.publish_view(sales, label="sales", section="eda", port=8000)
ps.publish_view(sales.describe().to_dict(), label="summary", section="eda", port=8000)

fig, ax = plt.subplots()
ax.bar(sales["region"], sales["revenue"])
ax.set_ylabel("Revenue")
ps.publish_view(fig, label="revenue", section="eda", port=8000)
plt.close(fig)
```

Run it:

```bash
python eda.py
```

## Forward the port from your laptop

```bash
ssh -N -L 8000:127.0.0.1:8000 user@your-vm
```

Open **<http://127.0.0.1:8000>** on your laptop. Choose **sales**, filter or group
the table, and try a browser plot. **revenue** is the image rendered by Matplotlib.
The script can finish without closing the separate server.

If port 8000 is already used on your laptop, forward another local port:

```bash
ssh -N -L 8001:127.0.0.1:8000 user@your-vm
```

Then open `http://127.0.0.1:8001`. This does not change the port Python uses on the VM.

## Return to a useful table setup

Choose columns, filters, and a plot, then **Save view**. That presentation stays in
this browser’s **My views**. Keep the same local URL when reconnecting: browser
preferences are scoped to the origin and dashboard path. They do not save the
underlying data.

See [Explore in the browser](../guides/explore-in-browser.md) and
[Run plotsrv on another machine](../guides/run-on-another-machine.md) for history,
persistent services, and HTTPS access without a tunnel.
