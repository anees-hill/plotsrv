import json

from benchmarks.table_cache_report import report


def fixture_run(cpu, latency, rss=100):
    return {"status": "completed", "failure": None, "case_fingerprint": "same",
            "harness_sha256": "same", "dependencies": {"fastapi": "same"},
            "system": {"python": "same"}, "receiver": {"peak_rss_bytes": rss},
            "cpu_per_table_s": {"warm": cpu}, "phase_metrics": {},
            "summary": {"warm.table": {"latency_s": {"p95": latency}},
                        "publishing.status": {"latency_s": {"p95": .020}}}}


def write_runs(root, baseline, candidate):
    for name, value in (("baseline", baseline), ("candidate", candidate)):
        for repeat in range(5):
            path = root / name / "table-cache-six" / f"run-{repeat + 1}" / "run.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))


def test_objective_gates_and_repeatable_cheap_route_threshold(tmp_path):
    before, after = fixture_run(.020, .2), fixture_run(.005, .040)
    write_runs(tmp_path, before, after)
    assert report(tmp_path, expected_recipes={"table-cache-six"})["status"] == "passed"
    after["summary"]["publishing.status"]["latency_s"]["p95"] = .03
    write_runs(tmp_path, before, after)
    result = report(tmp_path, expected_recipes={"table-cache-six"})
    assert result["status"] == "investigate"
    assert "publishing.status" in result["investigate"][0]


def test_failed_attempt_and_environment_mismatch_cannot_pass(tmp_path):
    before, after = fixture_run(.020, .2), fixture_run(.005, .040)
    after["dependencies"]["fastapi"] = "different"
    after["status"], after["failure"] = "failed", "stream closed"
    after["summary"] = {}
    after["cpu_per_table_s"] = {}
    write_runs(tmp_path, before, after)
    result = report(tmp_path, expected_recipes={"table-cache-six"})
    assert result["status"] == "failed"
    assert any("incomparable" in reason for reason in result["failures"])
    assert any("stream closed" in reason for reason in result["failures"])


def test_focused_primary_comparison_still_requires_three_attempts(tmp_path):
    write_runs(tmp_path, fixture_run(.020, .2), fixture_run(.005, .040))
    for path in tmp_path.glob("*/*/run-[45]/run.json"):
        path.unlink()
    assert report(tmp_path, focused=True, expected_recipes={"table-cache-six"})["status"] == "passed"
    assert report(tmp_path, expected_recipes={"table-cache-six"})["status"] == "failed"
    for path in tmp_path.glob("*/*/run-3/run.json"):
        path.unlink()
    assert report(tmp_path, focused=True, expected_recipes={"table-cache-six"})["status"] == "failed"


def test_partial_campaign_cannot_pass(tmp_path):
    write_runs(tmp_path, fixture_run(.020, .2), fixture_run(.005, .040))
    result = report(tmp_path, focused=True)
    assert result["status"] == "failed"
    assert any("missing workload" in reason for reason in result["failures"])
