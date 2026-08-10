from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.pipeline_profile.models import (
    PlotsrvConfigSpec,
    RunSpec,
    TableSpec,
    WorkloadSpec,
)
from benchmarks.pipeline_profile.cases import apply_case_overrides, build_case
from benchmarks.pipeline_profile.runner import compare_runs
from benchmarks.pipeline_profile.workload import write_watched_csv


def _write_run(path: Path, *, wall_time: float, max_rss: int) -> None:
    path.mkdir()
    (path / "run.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "wall_time_s": wall_time,
                "summary": {
                    "max_rss_bytes": max_rss,
                    "max_uss_bytes": max_rss // 2,
                    "max_cpu_percent": 50.0,
                    "read_bytes_delta": 100,
                    "write_bytes_delta": 20,
                },
            }
        ),
        encoding="utf-8",
    )


def test_table_spec_parses_underscores() -> None:
    assert TableSpec.parse("100_000x12") == TableSpec(rows=100_000, columns=12)


@pytest.mark.parametrize("value", ["100", "0x2", "1x0", "axb"])
def test_table_spec_rejects_invalid_shapes(value: str) -> None:
    with pytest.raises(ValueError):
        TableSpec.parse(value)


def test_watch_run_requires_a_source_csv(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="require watch_csv"):
        RunSpec(
            scenario="watch-clients",
            workload=WorkloadSpec(),
            output_dir=tmp_path / "output",
        )


def test_write_watched_csv_is_row_streamed(tmp_path: Path) -> None:
    output = tmp_path / "watched.csv"
    write_watched_csv(output, TableSpec(rows=3, columns=2))
    assert output.read_text(encoding="utf-8").splitlines() == [
        "col_0,col_1",
        "0,1",
        "1,2",
        "2,3",
    ]


def test_compare_runs_reports_deltas(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, wall_time=10.0, max_rss=100)
    _write_run(candidate, wall_time=12.5, max_rss=125)

    result = compare_runs(baseline, candidate)

    wall = result["metrics"]["wall_time_s"]
    memory = result["metrics"]["summary.max_rss_bytes"]
    assert wall == {
        "baseline": 10.0,
        "candidate": 12.5,
        "delta": 2.5,
        "percent_change": 25.0,
    }
    assert memory == {
        "baseline": 100,
        "candidate": 125,
        "delta": 25,
        "percent_change": 25.0,
    }


def test_plotsrv_config_spec_serialises_round_trip() -> None:
    spec = PlotsrvConfigSpec(
        publish_max_plot_bytes=10,
        publish_max_table_rows=20,
        publish_max_table_columns=30,
        publish_max_artifact_text_chars=40,
        publish_max_json_container_items=50,
        truncate_table_rows=None,
        truncate_table_columns=60,
        watch_active_max_concurrent=3,
        watch_active_wait_timeout_s=0.25,
        storage_enabled=True,
        storage_watch_enabled=True,
    )

    assert PlotsrvConfigSpec.from_dict(spec.to_dict()) == spec


@pytest.mark.parametrize(
    "kwargs",
    [
        {"publish_max_table_rows": 0},
        {"publish_max_table_columns": 0},
        {"publish_max_artifact_text_chars": 0},
        {"publish_max_json_container_items": 0},
        {"truncate_table_rows": 0},
        {"truncate_table_columns": 0},
        {"watch_active_max_concurrent": 0},
        {"watch_active_wait_timeout_s": -1},
    ],
)
def test_plotsrv_config_spec_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PlotsrvConfigSpec(**kwargs)


def test_run_spec_preserves_config() -> None:
    config = PlotsrvConfigSpec(publish_max_table_rows=500_000)
    spec = RunSpec(
        scenario="baseline",
        workload=WorkloadSpec(),
        output_dir=Path("out"),
        config=config,
    )

    assert RunSpec.from_dict(spec.to_dict()).config.publish_max_table_rows == 500_000


def test_named_watch_case_has_cycles_and_post_idle_profile() -> None:
    spec = build_case(
        "watch.csv.file.large.repeated-clients",
        profile="quick",
    )

    assert spec.case_id == "watch.csv.file.large.repeated-clients"
    assert spec.cycles > 1
    assert 503 in spec.accept_statuses


def test_case_override_changes_only_supported_setting() -> None:
    spec = build_case("watch.csv.file.large.repeated-clients", profile="quick")

    changed = apply_case_overrides(spec, ["cycles=10", "clients=4"])

    assert changed.cycles == 10
    assert changed.clients == 4
    assert changed.case_id == spec.case_id
