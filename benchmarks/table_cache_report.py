"""Compare browser-profile run.json files from a table-cache ptop manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median


def metrics(run):
    result = {"receiver.peak_rss_bytes": run["receiver"]["peak_rss_bytes"]}
    result.update({f"cpu.{phase}": value for phase, value in run.get("cpu_per_table_s", {}).items()})
    for name, row in run["summary"].items():
        if not name.startswith(("setup.", "soak-setup.", "settling.")):
            result[f"p95.{name}"] = row["latency_s"]["p95"]
            if row.get("latency_s", {}).get("count") and "response_bytes" in row:
                result[f"bytes.{name}"] = row["response_bytes"] / row["latency_s"]["count"]
    for name in ("settling", "soak"):
        values = run.get("phase_metrics", {}).get(name, [])
        if values:
            result[f"{name}.last_rss_bytes"] = values[-1]["rss_bytes"]
            result[f"{name}.last_uss_bytes"] = values[-1]["uss_bytes"]
        if name == "soak" and 3 <= len(values) < 6:
            # Focused two-minute soak: compare post-warmup to final checkpoint.
            # This is a short observation, not an endurance trend estimate.
            result["soak.rss_growth_bytes"] = values[-1]["rss_bytes"] - values[1]["rss_bytes"]
            result["soak.uss_growth_bytes"] = values[-1]["uss_bytes"] - values[1]["uss_bytes"]
        if name == "soak" and len(values) >= 6:
            # Compare early and late settled windows, excluding initial warmup.
            result["soak.rss_growth_bytes"] = median(v["rss_bytes"] for v in values[-3:]) - median(v["rss_bytes"] for v in values[1:4])
            result["soak.uss_growth_bytes"] = median(v["uss_bytes"] for v in values[-3:]) - median(v["uss_bytes"] for v in values[1:4])
    return result


def report(root, *, focused=False, expected_recipes=None):
    groups = {}
    failures = []
    for path in sorted(root.glob("*/*/run-*/run.json")):
        target, recipe = path.relative_to(root).parts[:2]
        run = json.loads(path.read_text())
        groups.setdefault(recipe, {}).setdefault(target, []).append((path, run))
        if run["status"] != "completed":
            failures.append(f"{path}: {run.get('failure')}")
    if not groups:
        raise ValueError(f"no benchmark results in {root}")
    if expected_recipes is None:
        names = {"six", "mixed", "twenty", "large", "soak"}
        if not focused:
            names.update({"single", "republish"})
        expected_recipes = {f"table-cache-{name}" for name in names}
    for missing in sorted(expected_recipes - groups.keys()):
        failures.append(f"{missing}: missing workload")
    rows, checks = [], []
    for recipe, targets in sorted(groups.items()):
        if set(targets) != {"baseline", "candidate"}:
            failures.append(f"{recipe}: missing baseline or candidate")
            continue
        all_runs = [r for values in targets.values() for _, r in values]
        fingerprints = {r["case_fingerprint"] for r in all_runs}
        environments = {json.dumps({k: v for k, v in r["dependencies"].items() if k.lower() != "plotsrv"}, sort_keys=True) for r in all_runs}
        pythons = {json.dumps(r["system"], sort_keys=True) for r in all_runs}
        harnesses = {r.get("harness_sha256") for r in all_runs}
        if len(fingerprints) != 1 or len(environments) != 1 or len(pythons) != 1 or len(harnesses) != 1:
            failures.append(f"{recipe}: incomparable workload, dependencies, machine/Python or harness")
        minimum = (3 if recipe in {"table-cache-six", "table-cache-mixed"} else 1) if focused else 5
        if any(len(values) < minimum for values in targets.values()):
            failures.append(f"{recipe}: fewer than {minimum} attempts per target")
        samples = {target: [metrics(run) for _, run in values] for target, values in targets.items()}
        keys = sorted(set.intersection(*(set(s) for values in samples.values() for s in values)))
        comparisons = {}
        for key in keys:
            before_values = [s[key] for s in samples["baseline"]]
            after_values = [s[key] for s in samples["candidate"]]
            before, after = median(before_values), median(after_values)
            comparisons[key] = {"baseline": before, "candidate": after,
                                "change_percent": 100 * (after / before - 1) if before else None,
                                "baseline_attempts": before_values, "candidate_attempts": after_values}
            if key.startswith("p95.") and key.rsplit(".", 1)[-1] in {"page", "status", "plot", "publish"}:
                if after > before * 1.1 and after - before > .005:
                    checks.append(f"{recipe}: repeat comparison for {key} ({before:.4f}s -> {after:.4f}s)")
        if recipe == "table-cache-six":
            for key, ratio in (("cpu.warm", .5), ("p95.warm.table", .7)):
                if key not in comparisons:
                    failures.append(f"{recipe}: missing {key}")
                    continue
                value = comparisons[key]
                if value["candidate"] > value["baseline"] * ratio:
                    failures.append(f"{recipe}: did not meet improvement target for {key}")
        wire = comparisons.get("bytes.warm.table")
        if wire and wire["candidate"] != wire["baseline"]:
            failures.append(f"{recipe}: warm table response bytes changed")
        peak = comparisons["receiver.peak_rss_bytes"]
        if peak["candidate"] > peak["baseline"] + 16 * 1024**2:
            checks.append(f"{recipe}: peak RSS increased beyond the 16 MiB cache allowance")
        for _, run in targets["candidate"]:
            for sample in run.get("cache_samples", []):
                if (sample.get("bytes", 0) > 16 * 1024**2 or sample.get("entries", 0) > 32
                        or sample.get("builds", 0) > 32 or sample.get("waiters", 0) > 128):
                    failures.append(f"{recipe}: cache accounting exceeded bounds")
            m = metrics(run)
            if m.get("soak.uss_growth_bytes", 0) > 2 * 1024**2:
                checks.append(f"{recipe}: inspect continuing USS growth above 2 MiB")
        rows.append({"recipe": recipe, "comparisons": comparisons,
                     "runs": {target: [str(p) for p, _ in values] for target, values in targets.items()}})
    return {"rows": rows, "failures": failures, "investigate": sorted(set(checks)),
            "status": "failed" if failures else "investigate" if checks else "passed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--focused", action="store_true", help="Three primary comparisons; one stress/soak attempt")
    args = parser.parse_args()
    result = report(args.root, focused=args.focused)
    (args.root / "table-cache-comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Table cache comparison", "", f"Status: **{result['status']}**", "",
             "| Workload | Warm CPU/read before → after | Warm table p95 before → after | Peak RSS before → after |",
             "| --- | --- | --- | --- |"]
    for row in result["rows"]:
        c = row["comparisons"]
        def pair(key, scale=1, suffix=""):
            if key not in c:
                return "missing"
            v = c[key]
            return f"{v['baseline'] * scale:.2f} → {v['candidate'] * scale:.2f}{suffix}"
        lines.append(f"| {row['recipe']} | {pair('cpu.warm', 1000, ' ms')} | {pair('p95.warm.table', 1000, ' ms')} | {pair('receiver.peak_rss_bytes', 1 / 1024**2, ' MiB')} |")
    for title, items in (("Failures", result["failures"]), ("Investigate", result["investigate"])):
        if items:
            lines.extend(["", f"## {title}", "", *[f"- {item}" for item in items]])
    text = "\n".join(lines) + "\n"
    (args.root / "table-cache-comparison.md").write_text(text)
    print(text)
    return 1 if result["status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
