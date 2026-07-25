from __future__ import annotations

import csv
import gc
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from .models import TableSpec, WorkloadSpec


EventCallback = Callable[[str, dict[str, Any] | None, float | None], None]
PublishMode = Literal["none", "attached", "remote"]


@dataclass(slots=True)
class PublishItem:
    obj: Any
    kind: str
    view_id: str
    label: str
    artifact_kind: str | None = None


def write_watched_csv(path: Path, spec: TableSpec) -> None:
    """Write a deterministic CSV without first retaining it as a large object."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([f"col_{index}" for index in range(spec.columns)])
        for row in range(spec.rows):
            writer.writerow([row + column for column in range(spec.columns)])


def _make_table(spec: TableSpec, *, iteration: int, index: int) -> Any:
    import numpy as np
    import pandas as pd

    start = iteration * 1_000_000 + index * 10_000
    data: dict[str, Any] = {}
    for column in range(spec.columns):
        values = np.arange(start + column, start + column + spec.rows, dtype=np.int64)
        data[f"col_{column}"] = values
    return pd.DataFrame(data)


def _make_json(item_count: int, *, iteration: int, index: int) -> dict[str, Any]:
    return {
        "iteration": iteration,
        "items": [
            {
                "id": row,
                "category": f"group-{row % 10}",
                "amount": row * 1.25,
                "valid": row % 2 == 0,
                "source": index,
            }
            for row in range(item_count)
        ],
    }


def _make_plot(*, iteration: int, index: int) -> Any:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    x = list(range(200))
    y = [math.sin((item + iteration + index) / 12.0) for item in x]
    figure, axis = plt.subplots(figsize=(7, 3))
    axis.plot(x, y)
    axis.set_title(f"Benchmark plot {iteration + 1}.{index + 1}")
    axis.set_xlabel("sample")
    axis.set_ylabel("value")
    return figure


def _repeated_text(size_kb: int, *, prefix: str) -> str:
    if size_kb <= 0:
        return ""
    unit = f"{prefix} benchmark payload\n"
    repeats = max(1, (size_kb * 1024) // len(unit) + 1)
    return (unit * repeats)[: size_kb * 1024]


def _burn_cpu(seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    value = 0.0
    counter = 1
    while time.perf_counter() < deadline:
        value += math.sin(counter) * math.cos(counter / 3.0)
        counter += 1
    if value == float("inf"):  # pragma: no cover - keeps the loop observable
        raise RuntimeError("unreachable")


def _temporary_memory(size_mb: int) -> bytearray | None:
    if size_mb <= 0:
        return None
    value = bytearray(size_mb * 1024 * 1024)
    for index in range(0, len(value), 4096):
        value[index] = 1
    return value


def _publish(item: PublishItem, *, mode: PublishMode, host: str, port: int) -> None:
    if mode == "none":
        return

    from plotsrv import publish_view

    publish_view(
        item.obj,
        launch_server=(mode == "attached"),
        host=(None if mode == "attached" else host),
        port=(None if mode == "attached" else port),
        label=item.label,
        section="benchmark",
        view_id=item.view_id,
        kind=item.kind,
        artifact_kind=item.artifact_kind,
        force=True,
    )


def run_workload(
    spec: WorkloadSpec,
    *,
    mode: PublishMode,
    host: str,
    port: int,
    event: EventCallback,
) -> None:
    """Build a configurable workload and optionally surface its outputs in plotsrv."""
    for iteration in range(spec.iterations):
        event("iteration_started", {"iteration": iteration + 1}, None)
        pressure = _temporary_memory(spec.temporary_memory_mb)
        try:
            _burn_cpu(spec.cpu_s)
            items: list[PublishItem] = []

            for index, table_spec in enumerate(spec.tables):
                items.append(
                    PublishItem(
                        obj=_make_table(table_spec, iteration=iteration, index=index),
                        kind="table",
                        view_id=f"benchmark:table-{index + 1}",
                        label=f"table {index + 1}",
                    )
                )

            for index, item_count in enumerate(spec.json_items):
                items.append(
                    PublishItem(
                        obj=_make_json(item_count, iteration=iteration, index=index),
                        kind="artifact",
                        view_id=f"benchmark:json-{index + 1}",
                        label=f"json {index + 1}",
                        artifact_kind="json",
                    )
                )

            for index in range(spec.plots):
                items.append(
                    PublishItem(
                        obj=_make_plot(iteration=iteration, index=index),
                        kind="plot",
                        view_id=f"benchmark:plot-{index + 1}",
                        label=f"plot {index + 1}",
                    )
                )

            if spec.html_kb:
                items.append(
                    PublishItem(
                        obj=_repeated_text(spec.html_kb, prefix="<p>html</p>"),
                        kind="artifact",
                        view_id="benchmark:html",
                        label="html",
                        artifact_kind="html",
                    )
                )

            if spec.text_kb:
                items.append(
                    PublishItem(
                        obj=_repeated_text(spec.text_kb, prefix="text"),
                        kind="artifact",
                        view_id="benchmark:text",
                        label="text",
                        artifact_kind="text",
                    )
                )

            if spec.log_kb:
                items.append(
                    PublishItem(
                        obj=_repeated_text(spec.log_kb, prefix="INFO pipeline"),
                        kind="artifact",
                        view_id="benchmark:log",
                        label="log",
                        artifact_kind="text",
                    )
                )

            should_publish = (iteration + 1) % spec.publish_every == 0
            for item in items:
                started = time.perf_counter()
                event(
                    "publish_started",
                    {"view_id": item.view_id, "kind": item.kind, "published": should_publish},
                    None,
                )
                if should_publish:
                    _publish(item, mode=mode, host=host, port=port)
                event(
                    "publish_finished",
                    {"view_id": item.view_id, "kind": item.kind, "published": should_publish},
                    time.perf_counter() - started,
                )

            for item in items:
                if item.kind == "plot":
                    try:
                        import matplotlib.pyplot as plt

                        plt.close(item.obj)
                    except Exception:
                        pass
        finally:
            pressure = None
            gc.collect()
        event("iteration_finished", {"iteration": iteration + 1}, None)
