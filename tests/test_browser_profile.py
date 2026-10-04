"""Check that the rehearsal exercises real HTTP/SSE and reports failures."""
import json
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from benchmarks.browser_profile import distribution

ROOT = Path(__file__).resolve().parents[1]


def test_percentiles_include_sample_count_and_empty_is_not_zero():
    assert distribution([]) == {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}
    assert distribution(list(range(1, 101))) == {
        "count": 100, "p50": 50, "p95": 95, "p99": 99, "max": 100,
    }


def invoke(output, *extra):
    pytest.importorskip("psutil")
    result = subprocess.run([
        sys.executable, "-m", "benchmarks.browser_profile", "--output", str(output),
        "--clients", "2", "--rows", "16", "--artifact-items", "4", "--rounds", "1",
        "--settle", "0.1", *extra,
    ], cwd=ROOT, capture_output=True, text=True, timeout=45)
    return result, json.loads((output / "run.json").read_text())


def test_real_receiver_concurrent_reads_republish_and_sse(tmp_path):
    process, result = invoke(tmp_path / "run")
    assert process.returncode == 0, process.stdout + process.stderr
    assert result["status"] == "completed"
    assert result["summary"]["cold.table"]["latency_s"]["count"] == 2
    assert result["summary"]["republished.artifact"]["errors"] == 0
    assert all(s["publication_notice_s"] is not None for s in result["streams"])
    assert result["receiver"]["peak_rss_bytes"] > 0
    assert result["receiver"]["exit_code_after_cleanup"] is not None


def test_timeout_writes_failed_result_and_reaps_receiver(tmp_path):
    process, result = invoke(tmp_path / "run", "--settle", "0", "--max-seconds", "0.001")
    assert process.returncode == 1
    assert result["status"] == "failed"
    assert "TimeoutError" in result["failure"]
    assert result["receiver"]["exit_code_after_cleanup"] is not None


def test_manifest_load_levels_have_distinct_recipes():
    # ptop 0.5 groups report medians by recipe, not by settings.
    manifest = tomllib.loads((ROOT / "plotsrv-conference.toml").read_text())
    recipes = tomllib.loads((ROOT / "ptop.toml").read_text())["recipes"]
    names = [run["recipe"] for run in manifest["runs"]]
    assert len(set(names)) == len(names)
    for run in manifest["runs"]:
        recipe = recipes[run["recipe"]]
        assert recipe["defaults"]["clients"] == run["set"]["clients"]
        assert recipe["defaults"]["rows"] == run["set"]["rows"]


def test_expected_sse_expiry_reconnects_without_losing_receiver_epoch(tmp_path):
    process, result = invoke(tmp_path / "run", "--sse-lifetime", "1", "--settle", "3.5")
    assert process.returncode == 0, process.stdout + process.stderr
    assert all(s["reconnects"] >= 1 and s["error"] is None for s in result["streams"])
    assert len({s["server_instance_id"] for s in result["streams"]}) == 1
