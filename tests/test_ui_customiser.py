from __future__ import annotations

from io import BytesIO
from pathlib import Path
import os
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import yaml

from plotsrv import settings, ui_config
from plotsrv.config_wizard.saving import SaveError
from plotsrv.ui_customiser.model import Draft
from plotsrv.ui_customiser.server import create_app
from plotsrv.ui_customiser.uploads import MAX_IMAGE_BYTES, raster

ORIGIN = "http://testserver"
TOKEN = "test-session-capability"
HEADERS = {
    "X-Plotsrv-UI-Session": TOKEN,
    "Origin": ORIGIN,
    "X-Plotsrv-UI-Action": "edit",
}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)


def png(size=(40, 20), *, format="PNG"):
    output = BytesIO()
    Image.new("RGBA" if format == "PNG" else "RGB", size, "red").save(
        output, format=format
    )
    return output.getvalue()


def setup(tmp_path, raw=None, name=None):
    path = tmp_path / "plotsrv.yml"
    if raw:
        path.write_bytes(raw)
    draft = Draft(path, name=name)
    app = create_app(draft, origin=ORIGIN, token=TOKEN)
    return draft, TestClient(app)


def post(client, path, json=None, **kwargs):
    return client.post(
        path, json={} if json is None else json, headers=HEADERS, **kwargs
    )


def test_preview_is_actual_inert_dashboard_and_routes_are_isolated(tmp_path):
    draft, client = setup(tmp_path)
    response = client.get("/api/preview", headers=HEADERS)
    assert response.status_code == 200
    assert "header-logo ps-header__logo" in response.text
    assert "Example table" in response.text and "<td>118</td>" in response.text
    assert "<script" not in response.text and "PLOTSRV_CONFIG" not in response.text
    assert "terminateServer" not in response.text
    for path in (
        "/publish",
        "/events",
        "/shutdown",
        "/openapi.json",
        "/docs",
        "/api/config",
        "/assets/secret",
    ):
        assert client.get(path, headers=HEADERS).status_code == 404
    root = client.get("/")
    assert TOKEN not in root.text
    assert root.headers["referrer-policy"] == "no-referrer"
    from plotsrv.ui_assets import get_ui_assets

    assert client.get(get_ui_assets().js).status_code == 404
    assert not draft.path.exists()


def test_logo_link_can_be_edited_and_preview_remains_inert(tmp_path):
    draft, client = setup(tmp_path)
    state = client.get("/api/state", headers=HEADERS).json()
    assert state["values"]["icon_url"] == ""
    assert state["fields"]["icon_url"]["region"] == "branding"

    response = post(client, "/api/draft", {"icon_url": "https://example.com/operations"})
    assert response.status_code == 200, response.text
    assert 'href="https://example.com/operations"' not in client.get(
        "/api/preview", headers=HEADERS
    ).text
    assert post(client, "/api/review").status_code == 200
    result = post(client, "/api/save", {"review_id": draft.review_id})
    assert result.status_code == 200, result.text
    assert yaml.safe_load(draft.path.read_text())["ui-settings"]["icon_url"] == "https://example.com/operations"


@pytest.mark.parametrize("value", ["javascript:alert(1)", "//evil.example", "https:///missing-host"])
def test_logo_link_editor_rejects_unsafe_url(tmp_path, value):
    draft, client = setup(tmp_path)
    assert post(client, "/api/draft", {"icon_url": value}).status_code == 400
    assert draft.values["icon_url"] == ""


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer " + TOKEN},
        {**HEADERS, "X-Plotsrv-UI-Session": "wrong"},
        {**HEADERS, "Origin": "https://evil.example"},
        {**HEADERS, "Host": "evil.example"},
        {**HEADERS, "X-Plotsrv-UI-Action": ""},
        {k: v for k, v in HEADERS.items() if k != "Origin"},
    ],
)
def test_unauthorised_mutations_do_not_read_or_write(tmp_path, headers):
    draft, client = setup(tmp_path)
    response = client.post("/api/draft", json={"header_text": "bad"}, headers=headers)
    assert response.status_code == 403
    assert draft.values["header_text"] == "" and not draft.path.exists()


def test_no_session_in_url_and_bad_host_on_public_shell(tmp_path):
    _, client = setup(tmp_path)
    assert client.get("/?session=" + TOKEN).status_code == 400
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/state").status_code == 403


def test_review_confirm_reload_scoping_and_assets(tmp_path):
    raw = b'# top\nstorage-settings: {enabled: true} # keep\nui-settings:\n  default:\n    show_help_note: true\n    header_fill_colour: "#123456" # legacy retained\n  instances:\n    selected:\n      header_text: Old # retain inline\n      extra: untouched\n    other: {header_text: Other}\nprivate: secret-value\n'
    draft, client = setup(tmp_path, raw, name="selected")
    assert (
        post(
            client, "/api/draft", {"header_text": "New title", "show_help_note": False}
        ).status_code
        == 200
    )
    response = client.post(
        "/api/upload/logo",
        content=png(),
        headers={**HEADERS, "X-Image-Name": "logo.png"},
    )
    assert response.status_code == 200, response.text
    reference = draft.values["logo"]
    assert not (tmp_path / reference).exists()
    review = post(client, "/api/review").json()
    assert "ui-settings / instances / selected / header_text" in review["text"]
    assert "secret-value" not in review["text"] and "extra:" not in review["text"]
    assert draft.path.read_bytes() == raw
    assert post(client, "/api/save", {"review_id": "wrong"}).status_code == 400
    response = post(client, "/api/save", {"review_id": review["review_id"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert Path(result["backup"]).read_bytes() == raw
    saved = draft.path.read_bytes()
    for line in (
        b"storage-settings: {enabled: true} # keep",
        b"extra: untouched",
        b"other: {header_text: Other}",
        b"private: secret-value",
        b"# retain inline",
    ):
        assert line in saved
    assert (tmp_path / reference).is_file()
    settings.set_runtime_context(config_path=draft.path, name="selected")
    ui = ui_config.load_ui_settings()
    assert ui.header_text == "New title" and ui.show_help_note is False
    assert ui.logo_url == "/assets/" + Path(reference).name
    assert tmp_path / reference in ui.asset_files
    assert not draft.images.staged
    assert post(client, "/api/draft", {"header_text": "again"}).status_code == 403


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_upload_canonicalises_and_removes_metadata(format):
    result = raster(png(format=format))
    with Image.open(BytesIO(result)) as image:
        assert image.format == "PNG" and image.size == (40, 20)
        assert not image.info


@pytest.mark.parametrize(
    "raw",
    [
        b"<svg><script>alert(1)</script></svg>",
        b"<html>image</html>",
        b"GIF89a",
        b"\x89PNG\r\n",
        b"x" * (MAX_IMAGE_BYTES + 1),
    ],
)
def test_bad_images_rejected(raw):
    with pytest.raises(SaveError):
        raster(raw)


@pytest.mark.parametrize("size", [(2049, 1), (2000, 2000)])
def test_dimensions_checked_before_pixel_decode(size, monkeypatch):
    raw = png(size)
    from PIL import PngImagePlugin

    monkeypatch.setattr(
        PngImagePlugin.PngImageFile,
        "load",
        lambda *a: pytest.fail("Decoded before dimension check"),
    )
    with pytest.raises(SaveError):
        raster(raw)


def test_animation_rejected():
    out = BytesIO()
    Image.new("RGBA", (10, 10), "red").save(
        out,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGBA", (10, 10), "blue")],
        duration=100,
    )
    with pytest.raises(SaveError):
        raster(out.getvalue())


@pytest.mark.parametrize(
    "filename",
    [
        "../logo.png",
        "/logo.png",
        "a\\b.png",
        "image.svg",
        ".hidden.png",
        "logo.png.exe",
    ],
)
def test_filename_rejected(tmp_path, filename):
    draft, client = setup(tmp_path)
    response = client.post(
        "/api/upload/logo", content=png(), headers={**HEADERS, "X-Image-Name": filename}
    )
    assert response.status_code == 400
    assert not draft.images.staged and not draft.images.root.exists()


def test_existing_directory_collision_cancel_and_failed_save(tmp_path, monkeypatch):
    from plotsrv.ui_customiser import model

    draft, client = setup(tmp_path)
    draft.images.root.mkdir()
    existing = draft.images.root / "keep.png"
    existing.write_bytes(b"previous-file")
    draft.upload("logo", png(), "logo.png")
    draft.prepare()
    monkeypatch.setattr(
        model,
        "save",
        lambda *a: (_ for _ in ()).throw(SaveError("simulated save failure")),
    )
    with pytest.raises(SaveError):
        draft.finish(draft.review_id)
    assert list(draft.images.root.iterdir()) == [existing]
    assert existing.read_bytes() == b"previous-file"
    assert not draft.path.exists()
    assert post(client, "/api/cancel").status_code == 200
    assert not draft.images.staged
    assert list(draft.images.root.iterdir()) == [existing]


def test_collision_never_overwrites_file(tmp_path):
    draft, _ = setup(tmp_path)
    draft.upload("logo", png(), "logo.png")
    draft.images.root.mkdir()
    asset = tmp_path / draft.values["logo"]
    asset.write_bytes(b"keep")
    draft.prepare()
    with pytest.raises(FileExistsError):
        draft.finish(draft.review_id)
    assert asset.read_bytes() == b"keep" and not draft.path.exists()


def test_concurrent_config_edit_rolls_back_assets(tmp_path):
    draft, _ = setup(tmp_path, b"# original\n")
    draft.upload("logo", png(), "logo.png")
    review = draft.prepare()
    draft.path.write_bytes(b"# externally edited\n")
    with pytest.raises(SaveError):
        draft.finish(review["review_id"])
    assert draft.path.read_bytes() == b"# externally edited\n"
    assert not draft.images.root.exists()


def test_review_invalidated_by_edit(tmp_path):
    draft, _ = setup(tmp_path)
    review = draft.prepare()
    draft.change({"header_text": "new"})
    with pytest.raises(SaveError):
        draft.finish(review["review_id"])
    assert not draft.path.exists()


def test_symlink_and_root_escape_refused(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "link").symlink_to(other, target_is_directory=True)
    for directory in ("../escape", "link", str(tmp_path), "nested/missing"):
        with pytest.raises(SaveError):
            Draft(tmp_path / "plotsrv.yml", assets_dir=directory)
    draft, _ = setup(tmp_path)
    draft.upload("logo", png(), "logo.png")
    draft.prepare()
    draft.images.root.symlink_to(other, target_is_directory=True)
    with pytest.raises(SaveError):
        draft.finish(draft.review_id)
    assert not list(other.iterdir()) and not draft.path.exists()


def test_unknown_and_active_ui_keys_not_editable(tmp_path):
    _, client = setup(tmp_path)
    for key in (
        "terminate_process_option",
        "header_fill_colour",
        "auto_refresh_option",
        "featured_views",
        "assets_dir",
    ):
        assert post(client, "/api/draft", {key: True}).status_code == 400
    assert post(client, "/api/draft", {"logo": "/missing/logo.png"}).status_code == 400
    assert post(client, "/api/draft", {"show_view_selector": False}).status_code == 400


def test_existing_image_paths_are_reviewed_and_saved(tmp_path):
    draft, client = setup(tmp_path)
    logo = tmp_path / "brand.png"
    favicon = tmp_path / "tab.png"
    logo.write_bytes(png())
    favicon.write_bytes(png())
    response = post(client, "/api/draft", {"logo": "brand.png", "favicon": str(favicon)})
    assert response.status_code == 200, response.text
    assert response.json()["values"]["logo"] == "brand.png"
    assert client.get("/api/image/logo", headers=HEADERS).status_code == 204
    review = post(client, "/api/review").json()
    assert "brand.png" in review["text"] and str(favicon) in review["text"]
    assert post(client, "/api/save", {"review_id": review["review_id"]}).status_code == 200
    saved = yaml.safe_load(draft.path.read_text())["ui-settings"]
    assert saved["logo"] == "brand.png"
    assert saved["favicon"] == str(favicon)
    assert "show_view_selector" not in saved


def test_existing_view_selector_setting_is_preserved(tmp_path):
    raw = b"ui-settings:\n  show_view_selector: false\n  header_text: Old\n"
    draft, client = setup(tmp_path, raw)
    assert "show_view_selector" not in draft.state()["fields"]
    assert post(client, "/api/draft", {"header_text": "New"}).status_code == 200
    review = post(client, "/api/review").json()
    assert post(client, "/api/save", {"review_id": review["review_id"]}).status_code == 200
    assert yaml.safe_load(draft.path.read_text())["ui-settings"]["show_view_selector"] is False


def test_malformed_existing_config_is_not_replaced(tmp_path):
    path = tmp_path / "plotsrv.yml"
    path.write_bytes(b"ui-settings: [bad\n")
    with pytest.raises(ValueError):
        Draft(path)
    assert path.read_bytes() == b"ui-settings: [bad\n"


def test_png_compressed_metadata_removed_before_inflation(monkeypatch):
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("private", "x" * (2 * 1024 * 1024), zip=True)
    out = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(out, format="PNG", pnginfo=info)
    monkeypatch.setattr(
        PngImagePlugin.PngStream,
        "chunk_zTXt",
        lambda *a: pytest.fail("Inflated image metadata"),
    )
    result = raster(out.getvalue())
    assert b"private" not in result and len(result) < 1024


def test_oversized_http_body_and_upload_count(tmp_path):
    draft, client = setup(tmp_path)
    response = client.post(
        "/api/upload/logo",
        content=b"x" * (MAX_IMAGE_BYTES + 1),
        headers={**HEADERS, "X-Image-Name": "a.png"},
    )
    assert response.status_code == 400
    for _ in range(16):
        draft.upload("logo", png(), "logo.png")
    assert len(draft.images.staged) == 1
    with pytest.raises(SaveError, match="upload limit"):
        draft.upload("logo", png(), "logo.png")
    assert not draft.images.root.exists()


def test_existing_preview_confined_to_approved_root(tmp_path):
    draft, _ = setup(tmp_path)
    draft.images.root.mkdir()
    external = tmp_path / "private.png"
    external.write_bytes(png())
    (draft.images.root / "linked.png").symlink_to(external)
    assert draft.images.existing("private.png") is None
    assert draft.images.existing("plotsrv-assets/linked.png") is None
    normal = draft.images.root / "approved.png"
    normal.write_bytes(png())
    assert draft.images.existing("plotsrv-assets/approved.png") == png()
    assert draft.images.existing("https://example.com/private.png") is None


def test_session_expiry_and_lifespan_cleanup(tmp_path, monkeypatch):
    from plotsrv.ui_customiser import server

    draft, client = setup(tmp_path)
    draft.upload("logo", png(), "logo.png")
    with client:
        monkeypatch.setattr(server, "monotonic", lambda: 10**12)
        assert client.get("/api/state", headers=HEADERS).status_code == 403
    assert not draft.images.staged and not draft.images.root.exists()


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "localhost"])
def test_cli_bind_needs_only_host_and_port(tmp_path, capsys, monkeypatch, host):
    from plotsrv.cli_parser import build_parser
    from plotsrv.ui_customiser import launch
    import uvicorn

    def run(server, *, sockets):
        assert server.config.host == host
        assert server.config.port == sockets[0].getsockname()[1] > 0
        client = TestClient(server.config.app, base_url="http://my-server:9876")
        token = server.config.app.state.capability
        headers = {
            **HEADERS,
            "Origin": "http://my-server:9876",
            "X-Plotsrv-UI-Session": token,
        }
        assert client.get("/").status_code == 200
        assert client.get("/api/state", headers=headers).status_code == 200
        assert client.post("/api/cancel", json={}, headers=headers).status_code == 200
        assert server.should_exit

    monkeypatch.setattr(uvicorn.Server, "run", run)
    args = build_parser().parse_args(
        [
            "config",
            "ui",
            "--host",
            host,
            "--port",
            "0",
            "--config",
            str(tmp_path / "plotsrv.yml"),
            "--no-open",
        ]
    )
    assert launch(args) == 0
    output = capsys.readouterr()
    assert not output.err
    assert "Open http://" in output.out
    assert "Open http://0.0.0.0" not in output.out
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "url",
    [
        "http://192.0.2.10:8766",
        "http://my-server:9876",
        "http://localhost:9876",
        "http://[::1]:8766",
        "https://plots.example.org",
    ],
)
def test_default_origin_follows_browser_address(tmp_path, url):
    draft = Draft(tmp_path / "plotsrv.yml")
    from urllib.parse import urlsplit

    # This Starlette TestClient version cannot parse IPv6 base_url authorities;
    # send the actual browser Host explicitly while exercising the same ASGI path.
    client = TestClient(
        create_app(draft, token=TOKEN),
        base_url=urlsplit(url).scheme + "://testserver",
        headers={"Host": urlsplit(url).netloc},
    )
    headers = {**HEADERS, "Origin": url}
    assert client.get("/").status_code == 200
    assert client.get("/api/state").status_code == 403
    assert client.get("/api/state", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/cancel",
            json={},
            headers={**headers, "Origin": "https://unrelated.example"},
        ).status_code
        == 403
    )
    assert not draft.closed
    assert client.post("/api/cancel", json={}, headers=headers).status_code == 200
    assert draft.closed and not draft.path.exists()


def test_inert_mode_ignores_description_config(monkeypatch, tmp_path):
    draft, _ = setup(tmp_path)
    monkeypatch.setattr(
        settings,
        "get_section",
        lambda *a, **kw: pytest.fail("Preview read production configuration"),
    )
    assert "Example table" in draft.preview()


def test_normal_cli_does_not_import_customiser():
    import subprocess, sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import plotsrv; import plotsrv.cli_entry; import plotsrv.ui_config; assert not any(k.startswith('plotsrv.ui_customiser') for k in sys.modules)",
        ],
        check=True,
    )


def test_second_asset_collision_rolls_back_only_new_asset(tmp_path):
    draft, _ = setup(tmp_path)
    draft.upload("logo", png(), "logo.png")
    draft.upload("favicon", png(), "icon.png")
    draft.images.root.mkdir()
    collision = tmp_path / draft.values["favicon"]
    collision.write_bytes(b"previous")
    draft.prepare()
    with pytest.raises(FileExistsError):
        draft.finish(draft.review_id)
    assert list(draft.images.root.iterdir()) == [collision]
    assert collision.read_bytes() == b"previous"
    assert not draft.path.exists()


def test_new_defaults_and_text_use_production_model(tmp_path):
    draft, _ = setup(tmp_path)
    draft.change({"page_title": "", "header_text": '"A title"'})
    assert draft.values["page_title"] == ui_config.DEFAULT_PAGE_TITLE
    assert draft.values["header_text"] == "A title"
    draft.prepare()
    draft.finish(draft.review_id)
    document = yaml.safe_load(draft.path.read_bytes())
    assert "show_view_selector" not in document["ui-settings"]
    assert document["ui-settings"]["header_text"] == "A title"


def test_normal_server_has_no_writer_routes():
    from plotsrv.app import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert not {"/api/draft", "/api/review", "/api/save", "/api/upload/{key}"} & paths


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_real_cli_ephemeral_port_and_cancel(tmp_path, host):
    import subprocess, sys, selectors, json, urllib.request

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "plotsrv.cli_entry",
            "config",
            "ui",
            "--config",
            str(tmp_path / "plotsrv.yml"),
            "--host",
            host,
            "--port",
            "0",
            "--no-open",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        reader = selectors.DefaultSelector()
        reader.register(process.stdout, selectors.EVENT_READ)
        assert reader.select(10), "CLI did not print connection instructions"
        origin = process.stdout.readline().strip().removeprefix("Open ").rstrip("/")
        token = process.stdout.readline().strip().partition(": ")[2]
        reader.close()
        # No token is interpolated into a URL or diagnostic message.
        import time

        for attempt in range(100):
            try:
                req = urllib.request.Request(
                    origin + "/api/state", headers={"X-Plotsrv-UI-Session": token}
                )
                with urllib.request.urlopen(req, timeout=1) as response:
                    assert response.status == 200
                break
            except (OSError, ValueError):
                if attempt == 99:
                    raise AssertionError("Temporary server did not start") from None
                time.sleep(0.02)
        req = urllib.request.Request(
            origin + "/api/cancel",
            data=b"{}",
            headers={
                "X-Plotsrv-UI-Session": token,
                "X-Plotsrv-UI-Action": "edit",
                "Origin": origin,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            assert response.status == 200
        process.wait(timeout=5)
        assert process.returncode == 0
        assert not list(tmp_path.iterdir())
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_preview_does_not_import_live_store_or_pandas(tmp_path):
    import subprocess, sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; from plotsrv.ui_customiser.model import Draft; Draft(Path(sys.argv[1])).preview(); assert 'plotsrv.store' not in sys.modules; assert 'pandas' not in sys.modules",
            str(tmp_path / "plotsrv.yml"),
        ],
        check=True,
    )


def test_invalid_unicode_cannot_be_saved_as_runtime_header(tmp_path):
    draft, client = setup(tmp_path)
    response = client.post(
        "/api/draft",
        content=b'{"header_text":"\\ud800"}',
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert draft.values["header_text"] == ""
    draft.path.write_bytes(b'ui-settings:\n  header_text: "\\ud800"\n')
    with pytest.raises(SaveError):
        Draft(draft.path)
