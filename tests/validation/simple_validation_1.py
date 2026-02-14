# In-session launcher tests =====================================
# * [dev] dependencies are needed to run this script

import time
import matplotlib.pyplot as plt
import seaborn as sns
from plotnine import *
import polars as pl
from plotsrv import (
    start_server,
    stop_server,
    refresh_view,
)
from plotsrv.config import set_table_view_mode

# PLOTS ----------------------
### PART 1
# matplotib/seaborn


start_server(port=8000, host="127.0.0.1", auto_on_show=True)
dat = sns.load_dataset("titanic")
sns.scatterplot(data=dat, x="age", y="fare")
plt.show()
print("plot 1 (matplotlib) up")
time.sleep(10)
stop_server()

### PART 2
# plotnine
start_server(port=8000, host="127.0.0.1", auto_on_show=True)
p = ggplot(dat, aes("age", "fare")) + geom_point()
refresh_view(p)
print("plot 2 (plotnine) up")
time.sleep(10)

stop_server()
print("script finished")

# TABLES ----------------------

# * Simple-view ---------
set_table_view_mode("simple")

# pandas
start_server(port=8000, host="127.0.0.1", auto_on_show=True)
df = sns.load_dataset("titanic")
refresh_view(df)
print("df 1 (pandas) up - simple view")
time.sleep(10)
stop_server()

# polars
start_server(port=8000, host="127.0.0.1", auto_on_show=True)
df = sns.load_dataset("titanic")
df = pl.from_pandas(df)
refresh_view(df)
print("df 2 (polars) up - simple view")
time.sleep(10)
stop_server()

# * Rich-view ---------
set_table_view_mode("rich")

# pandas
start_server(port=8000, host="127.0.0.1", auto_on_show=True)
df = sns.load_dataset("titanic")
refresh_view(df)
print("df 1 (pandas) up - rich view")
time.sleep(10)
stop_server()

# polars
start_server(port=8000, host="127.0.0.1", auto_on_show=True)
df = sns.load_dataset("titanic")
df = pl.from_pandas(df)
refresh_view(df)
print("df 2 (polars) up - rich view")
time.sleep(10)
stop_server()


# CLI tests =====================================

# plotsrv run src --host 127.0.0.1 --port 8000
# plotsrv run plotsrv --host 127.0.0.1 --port 8000
# plotsrv run plotsrv.dev_validate3 --host 127.0.0.1 --port 8000
# plotsrv run plotsrv.dev_validate3:plot_mem_percent --host 127.0.0.1 --port 8000 # << expect fail due to argparse clash !

# Demo module
# python -m plotsrv.dev_validate3

# Renderer detection checks
from plotsrv import store
from plotsrv.renderers.registry import render_any

print(render_any({"a": {"b": [1, 2, 3]}}, view_id="default").kind)  # expect 'json'
print(render_any("hello", view_id="default").kind)  # expect 'text'
