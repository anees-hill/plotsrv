#!/usr/bin/env python3
"""Build plotsrv's browser assets without requiring a JavaScript toolchain.

The browser modules and stylesheets remain readable source files.  This script
concatenates them in dependency order, fingerprints the outputs, and writes the
small manifest consumed by :mod:`plotsrv.ui_assets`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "plotsrv" / "static"
DIST = STATIC / "dist"

CSS_SOURCES = (
    "vendor/tabulator/5.5.0/tabulator.min.css",
    "css/base.css",
    "css/layout.css",
    "css/controls.css",
    "css/status.css",
    "css/renderers/plot.css",
    "css/renderers/table.css",
    "css/renderers/table_plot.css",
    "css/renderers/table_plot_controls.css",
    "css/renderers/stream.css",
    "css/renderers/json.css",
    "css/renderers/text.css",
    "css/renderers/code.css",
    "css/renderers/html.css",
    "css/renderers/markdown.css",
    "css/renderers/traceback.css",
    "css/themes.css",
)

JS_SOURCES = (
    "js/core/dom.js",
    "js/core/state.js",
    "js/core/storage.js",
    "js/core/settings.js",
    "js/core/history.js",
    "js/core/status.js",
    "js/core/status_modal.js",
    "js/core/bottom_bar.js",
    "js/core/auto_refresh.js",
    "js/core/view_selector.js",
    "js/renderers/artifact.js",
    "js/renderers/plot.js",
    "js/renderers/table.js",
    "js/renderers/table_plot.js",
    "js/renderers/table_plot_controls.js",
    "js/renderers/stream.js",
    "js/renderers/json.js",
    "js/renderers/text.js",
    "js/renderers/code.js",
    "js/core/app.js",
)


def _bundle(paths: tuple[str, ...]) -> bytes:
    chunks: list[bytes] = []
    for relative in paths:
        source = STATIC / relative
        chunks.extend(
            (
                f"/* plotsrv source: {relative} */\n".encode(),
                source.read_text(encoding="utf-8").rstrip().encode(),
                b"\n\n",
            )
        )
    return b"".join(chunks)


def _fingerprint(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:12]


def _outputs() -> dict[Path, bytes]:
    css = _bundle(CSS_SOURCES)
    js = _bundle(JS_SOURCES)
    css_name = f"plotsrv-ui.{_fingerprint(css)}.css"
    js_name = f"plotsrv-ui.{_fingerprint(js)}.js"
    manifest = {
        "css": f"/static/dist/{css_name}",
        "js": f"/static/dist/{js_name}",
        "tabulator_js": "/static/vendor/tabulator/5.5.0/tabulator.min.js",
        "tabulator_version": "5.5.0",
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return {
        DIST / css_name: css,
        DIST / js_name: js,
        DIST / "manifest.json": manifest_bytes,
    }


def build(*, check: bool) -> int:
    outputs = _outputs()
    if check:
        stale = [
            str(path.relative_to(ROOT))
            for path, data in outputs.items()
            if not path.exists() or path.read_bytes() != data
        ]
        if stale:
            print("UI assets are stale: " + ", ".join(stale))
            return 1
        print("UI assets are current")
        return 0

    DIST.mkdir(parents=True, exist_ok=True)
    expected = set(outputs)
    manifest_path = DIST / "manifest.json"

    # Publish new fingerprinted files before switching the manifest. A running
    # development server can therefore resolve either side of the rollover.
    for path, data in outputs.items():
        if path != manifest_path:
            path.write_bytes(data)

    manifest_temp = DIST / ".manifest.json.tmp"
    manifest_temp.write_bytes(outputs[manifest_path])
    manifest_temp.replace(manifest_path)

    for old in DIST.glob("plotsrv-ui.*"):
        if old not in expected and old.is_file():
            old.unlink()
    print("Built " + ", ".join(path.name for path in outputs))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed assets do not match their source files.",
    )
    args = parser.parse_args()
    return build(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
