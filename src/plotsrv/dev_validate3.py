from plotnine import scale_x_datetime
from plotnine import scale_colour_manual
import psutil
import time
import inspect
import polars as pl
import argparse
from plotnine import *
from datetime import datetime
import plotsrv, plotsrv.publisher
from plotsrv.decorators import plot, table

print("plotsrv:", plotsrv.__file__)
print("publisher:", plotsrv.publisher.__file__)


parser = argparse.ArgumentParser()
parser.add_argument(
    "--fetch-interval",
    help="How often to fetch sytem resource usage",
    type=int,
    default=10,
)
args = parser.parse_args()


@table(label="Tabular view", section="Resource Usage", host="127.0.0.1", port=8000)
def system_snapshot(interval: float = 1) -> pl.DataFrame:
    mem = psutil.virtual_memory()
    now = datetime.now()

    cpu_percent = psutil.cpu_percent(interval=interval)
    memory_percent = mem.percent
    memory_used_gb = round(mem.used / 1024**3, 2)
    disk_percent = psutil.disk_usage("/").percent

    row = pl.DataFrame(
        {
            "datetime": [now],
            "cpu_percent": [cpu_percent],
            "memory_percent": [memory_percent],
            "memory_used_gb": [memory_used_gb],
            "disk_percent": [disk_percent],
        }
    ).cast({"datetime": pl.Datetime("ms")})

    row = row.unpivot(
        ["cpu_percent", "memory_percent", "memory_used_gb", "disk_percent"],
        index="datetime",
    )

    return row


print("plotsrv package:", plotsrv.__file__)
print("table imported from:", table.__module__, getattr(table, "__file__", None))

print("system_snapshot module:", system_snapshot.__module__)
print("system_snapshot has __plotsrv__:", hasattr(system_snapshot, "__plotsrv__"))
print("system_snapshot has __wrapped__:", hasattr(system_snapshot, "__wrapped__"))

if hasattr(system_snapshot, "__plotsrv__"):
    print("system_snapshot.__plotsrv__ =", getattr(system_snapshot, "__plotsrv__"))

print("system_snapshot source file:", inspect.getsourcefile(system_snapshot))
print("system_snapshot repr:", system_snapshot)


def x_scale_picker(observation_count: int) -> [str, str]:
    if observation_count < 360:
        date_breaks_selection = "1 minute"
        date_labels_selection = "%H:%M"
    elif observation_count >= 360 and observation_count < 1080:
        date_breaks_selection = "10 minutes"
        date_labels_selection = "%H:%M"
    else:
        date_breaks_selection = "1 hour"
        date_labels_selection = "%D-%M %H:%M"

    return date_breaks_selection, date_labels_selection


@plot(label="CPU%", section="Resource Usage", host="127.0.0.1", port=8000)
def plot_cpu_percent(data: pl.DataFrame):

    cpu_percent = data.filter(pl.col("variable") == "cpu_percent").with_columns(
        [pl.when(pl.col("value") > 90).then(True).otherwise(False).alias("high_usage")]
    )

    date_breaks_selection, date_labels_selection = x_scale_picker(cpu_percent.height)

    p = (
        ggplot(cpu_percent, aes("datetime", "value"))
        + geom_line()
        + geom_point(aes(colour="high_usage"), show_legend=False)
        + scale_y_continuous(limits=[0, 100])
        + theme_bw()
        + scale_colour_manual(values={True: "#b82525", False: "#000000"})
        + scale_x_datetime(
            date_breaks=date_breaks_selection, date_labels=date_labels_selection
        )
        + labs(title="CPU%", x="Date/Time", y="CPU usage % (1s average)")
    )

    return p


@plot(label="MEM%", section="Resource Usage", host="127.0.0.1", port=8000)
def plot_mem_percent(data: pl.DataFrame):

    mem_percent = data.filter(pl.col("variable") == "memory_percent").with_columns(
        [pl.when(pl.col("value") > 90).then(True).otherwise(False).alias("high_usage")]
    )

    date_breaks_selection, date_labels_selection = x_scale_picker(mem_percent.height)

    p = (
        ggplot(mem_percent, aes("datetime", "value"))
        + geom_line()
        + geom_point(aes(colour="high_usage"), show_legend=False)
        + scale_y_continuous(limits=[0, 100])
        + theme_bw()
        + scale_colour_manual(values={True: "#b82525", False: "#000000"})
        + scale_x_datetime(
            date_breaks=date_breaks_selection, date_labels=date_labels_selection
        )
        + labs(title="MEM%", x="Date/Time", y="Memory used %")
    )

    return p


@plot(label="DISK%", section="Resource Usage", host="127.0.0.1", port=8000)
def plot_disk_percent(data: pl.DataFrame):

    disk_percent = data.filter(pl.col("variable") == "disk_percent").with_columns(
        [pl.when(pl.col("value") > 90).then(True).otherwise(False).alias("high_usage")]
    )

    date_breaks_selection, date_labels_selection = x_scale_picker(disk_percent.height)

    p = (
        ggplot(disk_percent, aes("datetime", "value"))
        + geom_line()
        + geom_point(aes(colour="high_usage"), show_legend=False)
        + scale_y_continuous(limits=[0, 100])
        + theme_bw()
        + scale_colour_manual(values={True: "#b82525", False: "#000000"})
        + scale_x_datetime(
            date_breaks=date_breaks_selection, date_labels=date_labels_selection
        )
        + labs(title="DISK%", x="Date/Time", y="Disk usage %")
    )

    return p


@plot(label="MEM-USED", section="Resource Usage", host="127.0.0.1", port=8000)
def plot_mem_used(data: pl.DataFrame):

    mem_used = data.filter(pl.col("variable") == "memory_used_gb")

    date_breaks_selection, date_labels_selection = x_scale_picker(mem_used.height)

    p = (
        ggplot(mem_used, aes("datetime", "value"))
        + geom_line()
        + geom_point()
        + theme_bw()
        + scale_x_datetime(
            date_breaks=date_breaks_selection, date_labels=date_labels_selection
        )
        + labs(title="Memory in use (actual)", x="Date/Time", y="gb")
    )

    return p


if __name__ == "__main__":

    i = 0

    running_data = pl.DataFrame(
        schema={
            "datetime": pl.Datetime(time_unit="ms"),
            "variable": pl.String,
            "value": pl.Float64,
        }
    )

    while i >= 0:
        res = system_snapshot()
        running_data = running_data.vstack(res)

        # plot
        p_cpu = plot_cpu_percent(running_data)
        p_mem = plot_mem_percent(running_data)
        p_disk = plot_disk_percent(running_data)
        p_mem_use = plot_mem_used(running_data)

        i += 1

        time.sleep(args.fetch_interval)
