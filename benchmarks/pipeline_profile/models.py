from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Scenario = Literal[
    "baseline",
    "attached",
    "remote",
    "watch-idle",
    "watch-clients",
]


@dataclass(frozen=True, slots=True)
class TableSpec:
    """The dimensions of one generated tabular pipeline output."""

    rows: int
    columns: int

    def __post_init__(self) -> None:
        if self.rows < 1:
            raise ValueError("table rows must be at least 1")
        if self.columns < 1:
            raise ValueError("table columns must be at least 1")

    @classmethod
    def parse(cls, value: str) -> TableSpec:
        raw = value.strip().lower().replace(" ", "")
        if "x" not in raw:
            raise ValueError(f"table dimensions must use ROWSxCOLUMNS, got {value!r}")

        rows_text, columns_text = raw.split("x", maxsplit=1)
        try:
            return cls(
                rows=int(rows_text.replace("_", "")),
                columns=int(columns_text.replace("_", "")),
            )
        except ValueError as exc:
            raise ValueError(
                f"table dimensions must use positive integers, got {value!r}"
            ) from exc

    def to_dict(self) -> dict[str, int]:
        return {"rows": self.rows, "columns": self.columns}


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    """A configurable approximation of a normal data/ETL pipeline."""

    tables: tuple[TableSpec, ...] = (TableSpec(25_000, 12),)
    json_items: tuple[int, ...] = (2_000,)
    plots: int = 1
    html_kb: int = 0
    text_kb: int = 64
    log_kb: int = 64
    cpu_s: float = 0.25
    temporary_memory_mb: int = 0
    iterations: int = 1
    publish_every: int = 1

    def __post_init__(self) -> None:
        if any(value < 1 for value in self.json_items):
            raise ValueError("json item counts must be at least 1")
        if self.plots < 0:
            raise ValueError("plots cannot be negative")
        if self.html_kb < 0 or self.text_kb < 0 or self.log_kb < 0:
            raise ValueError("artifact sizes cannot be negative")
        if self.cpu_s < 0:
            raise ValueError("cpu_s cannot be negative")
        if self.temporary_memory_mb < 0:
            raise ValueError("temporary_memory_mb cannot be negative")
        if self.iterations < 1:
            raise ValueError("iterations must be at least 1")
        if self.publish_every < 1:
            raise ValueError("publish_every must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": [table.to_dict() for table in self.tables],
            "json_items": list(self.json_items),
            "plots": self.plots,
            "html_kb": self.html_kb,
            "text_kb": self.text_kb,
            "log_kb": self.log_kb,
            "cpu_s": self.cpu_s,
            "temporary_memory_mb": self.temporary_memory_mb,
            "iterations": self.iterations,
            "publish_every": self.publish_every,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorkloadSpec:
        tables_raw = raw.get("tables", [])
        tables = tuple(
            TableSpec(rows=int(table["rows"]), columns=int(table["columns"]))
            for table in tables_raw
        )
        return cls(
            tables=tables,
            json_items=tuple(int(value) for value in raw.get("json_items", [])),
            plots=int(raw.get("plots", 0)),
            html_kb=int(raw.get("html_kb", 0)),
            text_kb=int(raw.get("text_kb", 0)),
            log_kb=int(raw.get("log_kb", 0)),
            cpu_s=float(raw.get("cpu_s", 0)),
            temporary_memory_mb=int(raw.get("temporary_memory_mb", 0)),
            iterations=int(raw.get("iterations", 1)),
            publish_every=int(raw.get("publish_every", 1)),
        )


@dataclass(frozen=True, slots=True)
class PlotsrvConfigSpec:
    """plotsrv runtime config values generated for one benchmark run."""

    publish_max_plot_bytes: int = 5_242_880
    publish_max_table_rows: int = 100_000
    publish_max_table_columns: int = 200
    publish_max_artifact_text_chars: int = 200_000
    publish_max_json_container_items: int = 20_000
    truncate_table_rows: int | None = 1_000
    truncate_table_columns: int | None = 200
    watch_active_max_concurrent: int = 2
    watch_active_wait_timeout_s: float = 1.0
    storage_enabled: bool = False
    storage_watch_enabled: bool = False

    def __post_init__(self) -> None:
        if self.publish_max_plot_bytes < 1:
            raise ValueError("publish_max_plot_bytes must be at least 1")
        if self.publish_max_table_rows < 1:
            raise ValueError("publish_max_table_rows must be at least 1")
        if self.publish_max_table_columns < 1:
            raise ValueError("publish_max_table_columns must be at least 1")
        if self.publish_max_artifact_text_chars < 1:
            raise ValueError("publish_max_artifact_text_chars must be at least 1")
        if self.publish_max_json_container_items < 1:
            raise ValueError("publish_max_json_container_items must be at least 1")
        if self.truncate_table_rows is not None and self.truncate_table_rows < 1:
            raise ValueError("truncate_table_rows must be at least 1 or omitted")
        if self.truncate_table_columns is not None and self.truncate_table_columns < 1:
            raise ValueError("truncate_table_columns must be at least 1 or omitted")
        if self.watch_active_max_concurrent < 1:
            raise ValueError("watch_active_max_concurrent must be at least 1")
        if self.watch_active_wait_timeout_s < 0:
            raise ValueError("watch_active_wait_timeout_s cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_max_plot_bytes": self.publish_max_plot_bytes,
            "publish_max_table_rows": self.publish_max_table_rows,
            "publish_max_table_columns": self.publish_max_table_columns,
            "publish_max_artifact_text_chars": self.publish_max_artifact_text_chars,
            "publish_max_json_container_items": self.publish_max_json_container_items,
            "truncate_table_rows": self.truncate_table_rows,
            "truncate_table_columns": self.truncate_table_columns,
            "watch_active_max_concurrent": self.watch_active_max_concurrent,
            "watch_active_wait_timeout_s": self.watch_active_wait_timeout_s,
            "storage_enabled": self.storage_enabled,
            "storage_watch_enabled": self.storage_watch_enabled,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PlotsrvConfigSpec:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            publish_max_plot_bytes=int(raw.get("publish_max_plot_bytes", 5_242_880)),
            publish_max_table_rows=int(raw.get("publish_max_table_rows", 100_000)),
            publish_max_table_columns=int(raw.get("publish_max_table_columns", 200)),
            publish_max_artifact_text_chars=int(
                raw.get("publish_max_artifact_text_chars", 200_000)
            ),
            publish_max_json_container_items=int(
                raw.get("publish_max_json_container_items", 20_000)
            ),
            truncate_table_rows=(
                None
                if raw.get("truncate_table_rows") is None
                else int(raw.get("truncate_table_rows"))
            ),
            truncate_table_columns=(
                None
                if raw.get("truncate_table_columns") is None
                else int(raw.get("truncate_table_columns"))
            ),
            watch_active_max_concurrent=int(raw.get("watch_active_max_concurrent", 2)),
            watch_active_wait_timeout_s=float(
                raw.get("watch_active_wait_timeout_s", 1.0)
            ),
            storage_enabled=bool(raw.get("storage_enabled", False)),
            storage_watch_enabled=bool(raw.get("storage_watch_enabled", False)),
        )


@dataclass(frozen=True, slots=True)
class RunSpec:
    """One independently reproducible operational benchmark run."""

    scenario: Scenario
    workload: WorkloadSpec
    output_dir: Path
    sample_interval_s: float = 0.2
    idle_s: float = 3.0
    max_rss_mb: int | None = None
    watch_csv: TableSpec | None = None
    watch_materialization: Literal["memory", "file"] = "file"
    watch_max_mb: float | None = 16.0
    clients: int = 1
    requests_per_client: int = 1
    client_interval_s: float = 0.0
    table_limit: int = 1_000
    config: PlotsrvConfigSpec = PlotsrvConfigSpec()

    def __post_init__(self) -> None:
        if self.sample_interval_s <= 0:
            raise ValueError("sample_interval_s must be greater than zero")
        if self.idle_s < 0:
            raise ValueError("idle_s cannot be negative")
        if self.max_rss_mb is not None and self.max_rss_mb < 1:
            raise ValueError("max_rss_mb must be at least 1 when set")
        if self.watch_max_mb is not None and self.watch_max_mb <= 0:
            raise ValueError("watch_max_mb must be greater than zero or omitted")
        if self.clients < 1:
            raise ValueError("clients must be at least 1")
        if self.requests_per_client < 1:
            raise ValueError("requests_per_client must be at least 1")
        if self.client_interval_s < 0:
            raise ValueError("client_interval_s cannot be negative")
        if self.table_limit < 1:
            raise ValueError("table_limit must be at least 1")
        if self.scenario.startswith("watch") and self.watch_csv is None:
            raise ValueError("watch scenarios require watch_csv")

    @property
    def watch_max_bytes(self) -> int | None:
        if self.watch_max_mb is None:
            return None
        return int(self.watch_max_mb * 1024 * 1024)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "workload": self.workload.to_dict(),
            "output_dir": str(self.output_dir),
            "sample_interval_s": self.sample_interval_s,
            "idle_s": self.idle_s,
            "max_rss_mb": self.max_rss_mb,
            "watch_csv": None if self.watch_csv is None else self.watch_csv.to_dict(),
            "watch_materialization": self.watch_materialization,
            "watch_max_mb": self.watch_max_mb,
            "clients": self.clients,
            "requests_per_client": self.requests_per_client,
            "client_interval_s": self.client_interval_s,
            "table_limit": self.table_limit,
            "config": self.config.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunSpec:
        watch_raw = raw.get("watch_csv")
        watch_csv = (
            None
            if watch_raw is None
            else TableSpec(
                rows=int(watch_raw["rows"]), columns=int(watch_raw["columns"])
            )
        )
        return cls(
            scenario=raw["scenario"],
            workload=WorkloadSpec.from_dict(raw["workload"]),
            output_dir=Path(raw["output_dir"]),
            sample_interval_s=float(raw.get("sample_interval_s", 0.2)),
            idle_s=float(raw.get("idle_s", 3.0)),
            max_rss_mb=(
                None if raw.get("max_rss_mb") is None else int(raw["max_rss_mb"])
            ),
            watch_csv=watch_csv,
            watch_materialization=raw.get("watch_materialization", "file"),
            watch_max_mb=(
                None if raw.get("watch_max_mb") is None else float(raw["watch_max_mb"])
            ),
            clients=int(raw.get("clients", 1)),
            requests_per_client=int(raw.get("requests_per_client", 1)),
            client_interval_s=float(raw.get("client_interval_s", 0.0)),
            table_limit=int(raw.get("table_limit", 1_000)),
            config=PlotsrvConfigSpec.from_dict(raw.get("config")),
        )
