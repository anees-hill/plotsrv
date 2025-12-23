# * [dev] dependencies are needed to run this script

from plotsrv import plot
import datetime as dt
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


# dat = sns.load_dataset("titanic")
# sns.scatterplot(data=dat, x="age", y="fare")
# plt.show()


@plot(label="titanic")
def get_plotnine_plot(randomness=True):

    dat = sns.load_dataset("titanic")

    if randomness:
        now = dt.datetime.now()
        val = now.second
        dat = pl.from_pandas(dat)
        dat[1, "fare"] = val

    p = ggplot(dat, aes("age", "fare")) + geom_point()
    return p
