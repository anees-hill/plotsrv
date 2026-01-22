# * [dev] dependencies are needed to run this script

from plotsrv import plot
import numpy as np
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


@plot(label="titanic", host="127.0.0.1", port=8000)
def test_titanic_plot(randomness=True):

    dat = sns.load_dataset("titanic")
    dat = pl.from_pandas(dat)

    if randomness:
        cols = ["red", "black", "yellow", "green", "orange", "purple"]
        col_x = str(np.random.choice(cols))
        print(f"plot should show {col_x} points")
    else:
        col_x = "black"

    p = ggplot(dat, aes("age", "fare")) + geom_point(colour=col_x)
    return p

test_titanic_plot()
