# * [dev] dependencies are needed to run this script

import time
import matplotlib.pyplot as plt
import seaborn as sns
from plotnine import *
import polars as pl
from plotsrv.server import (
    start_plot_server,
    stop_plot_server,
    refresh_plot_server,
    set_table_view_mode,
)

# PLOTS ----------------------
### PART 1
# matplotib/seaborn


start_plot_server()
dat = sns.load_dataset("titanic")
sns.scatterplot(data=dat, x="age", y="fare")
plt.show()
print("plot 1 (matplotlib) up")
time.sleep(10)
stop_plot_server()

### PART 2
# plotnine
start_plot_server()
p = ggplot(dat, aes("age", "fare")) + geom_point()
refresh_plot_server(p)
print("plot 2 (plotnine) up")
time.sleep(10)

stop_plot_server()
print("script finished")

# TABLES ----------------------

# * Simple-view ---------
set_table_view_mode("simple")

# pandas
start_plot_server()
df = sns.load_dataset("titanic")
refresh_plot_server(df)
print("df 1 (pandas) up - simple view")
time.sleep(10)
stop_plot_server()

# pandas
start_plot_server()
df = sns.load_dataset("titanic")
df = pl.from_pandas(df)
refresh_plot_server(df)
print("df 2 (polars) up - simple view")
time.sleep(10)
stop_plot_server()

# * Rich-view ---------
set_table_view_mode("rich")

# pandas
start_plot_server()
df = sns.load_dataset("titanic")
refresh_plot_server(df)
print("df 1 (pandas) up - rich view")
time.sleep(10)
stop_plot_server()

# polars
start_plot_server()
df = sns.load_dataset("titanic")
df = pl.from_pandas(df)
refresh_plot_server(df)
print("df 2 (polars) up - rich view")
time.sleep(10)
stop_plot_server()
