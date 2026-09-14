#!/usr/bin/env python3
"""Generate small UI copies without changing the original package artwork."""

from __future__ import annotations

import argparse
import io
import runpy
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/plotsrv/static"
SOURCES = runpy.run_path(str(ROOT / "src/plotsrv/ui_images.py"))["UI_IMAGE_SOURCES"]


def build(*, check: bool = False) -> int:
    stale = []
    for source, size in SOURCES.items():
        destination = STATIC / "ui-images" / Path(source).name
        with Image.open(STATIC / source) as original:
            image = original.convert("RGBA")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
        data = output.getvalue()
        if check:
            if not destination.is_file() or destination.read_bytes() != data:
                stale.append(str(destination.relative_to(ROOT)))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    if stale:
        print("UI images are stale: " + ", ".join(stale))
        return 1
    print("UI images are current" if check else "Built small UI image copies")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    raise SystemExit(build(check=parser.parse_args().check))
