"""Freeze an unmodified Git baseline and the current Python dependency versions."""
from __future__ import annotations

import argparse
from importlib.metadata import distributions
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True, help="Git revision preceding the receiver change")
    parser.add_argument("--campaign", choices=("table-cache", "artifact-cache"), default="table-cache")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", args.baseline_ref], cwd=root, text=True).strip()
    destination = root / ".ptop" / f"{args.campaign}-baseline"
    if destination.exists():
        saved = json.loads((destination / "provenance.json").read_text())
        if saved["revision"] != revision:
            raise SystemExit("existing baseline differs; preserve it and choose a separate campaign checkout")
    else:
        destination.mkdir(parents=True)
        archive = subprocess.check_output(["git", "archive", revision], cwd=root)
        (destination / "source.tar").write_bytes(archive)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(destination / "source", filter="data")
        (destination / "provenance.json").write_text(json.dumps({
            "revision": revision, "python": sys.version,
        }, indent=2) + "\n")
    constraints = "\n".join(sorted(
        f'{d.metadata["Name"]}=={d.version}' for d in distributions()
        if d.metadata["Name"].lower() != "plotsrv"
    )) + "\n"
    path = root / ".ptop" / f"{args.campaign}-constraints.txt"
    if path.exists() and path.read_text() != constraints:
        raise SystemExit("saved dependency constraints differ; do not overwrite an existing campaign")
    path.write_text(constraints)
    print(f"Baseline: {revision}\nConstraints: {path}\nPython: {sys.version.split()[0]}")
    print("Set both manifest targets to this Python version; run ptop from the checkout root.")


if __name__ == "__main__":
    main()
