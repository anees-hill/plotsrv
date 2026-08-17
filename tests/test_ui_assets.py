from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from plotsrv import config, store
from plotsrv.app import app
from plotsrv.ui_assets import get_ui_assets

_ROOT = Path(__file__).parents[1]
_STATIC = _ROOT / "src" / "plotsrv" / "static"


def _static_requests(html: str) -> list[str]:
    return re.findall(r'(?:src|href)="(/static/[^"]+)"', html)


def test_manifest_only_exposes_existing_local_assets() -> None:
    raw = json.loads((_STATIC / "dist" / "manifest.json").read_text("utf-8"))
    assets = get_ui_assets()

    assert raw["tabulator_version"] == "5.5.0"
    assert assets.css.startswith("/static/dist/plotsrv-ui.")
    assert assets.js.startswith("/static/dist/plotsrv-ui.")
    assert assets.tabulator_js == "/static/vendor/tabulator/5.5.0/tabulator.min.js"
    for url in (assets.css, assets.js, assets.tabulator_js):
        assert (_STATIC / url.removeprefix("/static/")).is_file()


def test_committed_bundles_match_ui_sources() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_ui_assets.py", "--check"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_standard_page_uses_two_bundles_and_no_remote_assets() -> None:
    store.reset()
    config.set_table_view_mode("simple")
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "https://unpkg.com" not in response.text
    loaded = _static_requests(response.text)
    assert get_ui_assets().css in loaded
    assert get_ui_assets().js in loaded
    assert get_ui_assets().tabulator_js not in loaded


def test_rich_table_loads_local_tabulator_before_plotsrv_bundle() -> None:
    store.reset()
    config.set_table_view_mode("rich")
    store.set_table(pd.DataFrame({"value": [1]}), html_simple=None)
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assets = get_ui_assets()
    loaded = _static_requests(response.text)
    assert assets.tabulator_js in loaded
    assert response.text.index(assets.tabulator_js) < response.text.index(assets.js)
    assert "http://" not in response.text
    assert "https://" not in response.text


def test_built_assets_are_served_by_the_application() -> None:
    client = TestClient(app)
    assets = get_ui_assets()

    css = client.get(assets.css)
    js = client.get(assets.js)
    tabulator = client.get(assets.tabulator_js)

    assert css.status_code == 200
    assert js.status_code == 200
    assert tabulator.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert "javascript" in js.headers["content-type"]
    assert "window.PLOTSRV" in js.text
    assert "Tabulator" in tabulator.text


def test_public_module_compatibility_imports_remain_available() -> None:
    import plotsrv.app as app_module
    import plotsrv.cli as cli_module
    import plotsrv.runtime as runtime_module
    import plotsrv.server as server_module

    assert callable(cli_module.build_parser)
    assert callable(app_module.require_local_request)
    assert callable(runtime_module.file_backed_load_slot)
    assert callable(server_module.refresh_view)
