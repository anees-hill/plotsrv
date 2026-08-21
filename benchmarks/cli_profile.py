"""Measure cold-process startup for the public plotsrv CLI boundary.

The command deliberately starts a fresh Python process for every sample.  This
captures the import path users experience at a shell, rather than the much
cheaper cost of calling a parser repeatedly in one already-warm process.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from statistics import median
from typing import Sequence

MODES = ("import", "root-help", "bare", "version")


def _has_lightweight_entrypoint() -> bool:
    """Detect the 0.5.1 entrypoint without importing ``plotsrv`` in this process."""
    try:
        package_version = metadata.version("plotsrv")
    except metadata.PackageNotFoundError:
        return False
    return package_version != "0.5.0"


def command_for_mode(mode: str) -> list[str]:
    """Return the fresh-process command used for one CLI measurement."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(MODES)}")

    if mode == "import":
        return [sys.executable, "-c", "import plotsrv"]

    modern = _has_lightweight_entrypoint()
    if mode == "version" and not modern:
        raise RuntimeError("the installed plotsrv does not provide --version")

    module = "plotsrv.cli_entry" if modern else "plotsrv.cli"
    arguments = {
        "root-help": ["--help"],
        # The old CLI had no successful bare invocation.  Its --help path is
        # the closest user-facing comparison for a pre-0.5.1 target.
        "bare": [] if modern else ["--help"],
        "version": ["--version"],
    }[mode]
    return [sys.executable, "-m", module, *arguments]


def _run_once(command: Sequence[str], *, project_root: Path) -> tuple[int, float]:
    environment = os.environ.copy()
    # A local user's config should not turn a CLI startup measurement into a
    # benchmark of unrelated project discovery or server startup.
    environment.pop("PLOTSRV_CONFIG", None)

    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=project_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode, time.perf_counter() - started


def run_profile(
    *, mode: str, repeats: int, output: Path | None = None
) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")

    project_root = Path(__file__).resolve().parents[1]
    command = command_for_mode(mode)
    samples: list[float] = []
    return_codes: list[int] = []
    for _ in range(repeats):
        return_code, duration = _run_once(command, project_root=project_root)
        return_codes.append(return_code)
        samples.append(duration)

    result: dict[str, object] = {
        "mode": mode,
        "command": command,
        "repeats": repeats,
        "return_codes": return_codes,
        "status": "completed" if all(code == 0 for code in return_codes) else "failed",
        "duration_s": {
            "median": float(median(samples)),
            "min": min(samples),
            "max": max(samples),
            "samples": samples,
        },
        "python": sys.version,
    }
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        (output / "cli-profile.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.cli_profile",
        description="Measure fresh-process plotsrv CLI startup.",
    )
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_profile(mode=args.mode, repeats=args.repeats, output=args.output)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
        return 2  # pragma: no cover - argparse exits before reaching this line

    print(
        f"CLI benchmark {result['status']}: {args.mode} "
        f"median={result['duration_s']['median'] * 1000:.2f} ms "
        f"repeats={args.repeats}"
    )
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
