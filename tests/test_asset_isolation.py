from types import SimpleNamespace

from fastapi.testclient import TestClient

import plotsrv.app as app_module


def test_current_selection_only_no_parent_or_stale_cache_exposure(tmp_path, monkeypatch):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    private = tmp_path / "private.txt"
    first.write_bytes(b"first image")
    second.write_bytes(b"second image")
    private.write_text("private fixture")
    ui = SimpleNamespace(assets_dir=None, asset_files=(first,))
    monkeypatch.setattr(app_module, "get_ui_settings", lambda: ui)
    http = TestClient(app_module.app)
    assert http.get("/assets/first.png").content == b"first image"
    assert http.get("/assets/private.txt").status_code == 404
    ui.asset_files = (second,)
    assert http.get("/assets/first.png").status_code == 404
    assert http.get("/assets/second.png").content == b"second image"
    ui.asset_files = ()
    assert http.get("/assets/second.png").status_code == 404


def test_legacy_package_cache_is_not_public(tmp_path):
    from fastapi import FastAPI

    cache = tmp_path / "_runtime_assets"
    cache.mkdir()
    (cache / "old.txt").write_text("old private fixture")
    app = FastAPI()
    app.mount("/static", app_module.PackageStaticFiles(directory=tmp_path))
    assert TestClient(app).get("/static/_runtime_assets/old.txt").status_code == 404
