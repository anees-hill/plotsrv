from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_MANIFEST_PATH = _STATIC_DIR / "dist" / "manifest.json"


@dataclass(frozen=True, slots=True)
class UIAssets:
    css: str
    js: str
    tabulator_js: str


def _static_asset_url(value: object, *, key: str) -> str:
    url = str(value or "")
    if not url.startswith("/static/") or ".." in url:
        raise RuntimeError(f"Invalid {key!r} URL in {_MANIFEST_PATH.name}")
    local_path = _STATIC_DIR / url.removeprefix("/static/")
    if not local_path.is_file():
        raise RuntimeError(f"Missing built UI asset: {local_path}")
    return url


def get_ui_assets() -> UIAssets:
    """Return verified, package-local URLs from the current UI manifest.

    The manifest is intentionally read for each rendered page. Development
    builds rotate fingerprinted bundle names while a smoke server may still be
    running, so process-lifetime caching can leave new pages pointing at files
    that the build has removed.
    """
    try:
        raw = cast(dict[str, object], json.loads(_MANIFEST_PATH.read_text("utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            "plotsrv UI assets are missing or invalid; run scripts/build_ui_assets.py"
        ) from exc

    return UIAssets(
        css=_static_asset_url(raw.get("css"), key="css"),
        js=_static_asset_url(raw.get("js"), key="js"),
        tabulator_js=_static_asset_url(raw.get("tabulator_js"), key="tabulator_js"),
    )
