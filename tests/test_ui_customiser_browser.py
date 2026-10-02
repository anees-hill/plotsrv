"""Real browser interaction with the isolated temporary service."""

import socket
import threading
import time

import pytest
import uvicorn

expect = pytest.importorskip("playwright.sync_api").expect

from plotsrv.ui_customiser.model import Draft
from plotsrv.ui_customiser.server import create_app
from tests.test_ui_customiser import png


@pytest.fixture(params=[False, True], ids=["browser-address", "pinned-origin"])
def editor(tmp_path, request):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    draft = Draft(tmp_path / "plotsrv.yml")
    token = "browser-test-session"
    app = create_app(draft, origin=origin if request.param else None, token=token)
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield draft, origin, token
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        yield page
        browser.close()


def unlock(page, origin, token):
    page.goto(origin)
    page.locator("#session").fill(token)
    page.locator("#session").press("Enter")
    page.locator("#editor").wait_for(state="visible")
    page.frame_locator("#preview").locator("#preview-branding").wait_for()
    expect(page.locator("#notice")).to_contain_text("Draft opened")


def test_keyboard_preview_upload_theme_and_save(page, editor, tmp_path):
    draft, origin, token = editor
    requests = []
    errors = []
    page.on("request", lambda r: requests.append(r.url))
    page.on("pageerror", lambda e: errors.append(str(e)))
    unlock(page, origin, token)
    assert page.evaluate("Object.keys(localStorage).length") == 0
    page.locator("#field-header_text").fill("<Example> dashboard")
    page.frame_locator("#preview").locator(".header-title").get_by_text(
        "<Example> dashboard"
    ).wait_for()
    assert not draft.path.exists()
    page.locator("#theme").select_option("dark")
    assert (
        page.frame_locator("#preview").locator("html").get_attribute("data-theme")
        == "dark"
    )
    page.frame_locator("#preview").locator("#preview-controls").focus()
    page.keyboard.press("Enter")
    assert page.locator("#field-show_view_selector").count() == 0
    page.locator("#field-export_table").uncheck()
    expect(page.locator("#field-export_table")).to_have_attribute("data-dirty", "false")
    assert draft.values["export_table"] is False
    page.locator("[data-region=branding]").click()
    (tmp_path / "existing.png").write_bytes(png())
    page.locator("#field-logo-path").fill("existing.png")
    expect(page.locator("#field-logo-path")).to_have_attribute("data-dirty", "false")
    assert draft.values["logo"] == "existing.png"
    expect(page.locator("#field-logo-path")).to_have_value("existing.png")
    page.locator("#field-logo").set_input_files(
        {"name": "safe.png", "mimeType": "image/png", "buffer": png()}
    )
    expect(page.locator("#notice")).to_contain_text("Image staged")
    assert not draft.images.root.exists()
    page.frame_locator("#preview").locator(".header-logo").evaluate("el => el.decode()")
    page.screenshot(path=str(tmp_path / "customiser-dark.png"), full_page=True)
    page.locator("#review").focus()
    page.keyboard.press("Enter")
    page.locator("#review-dialog").wait_for(state="visible")
    assert page.locator("#back").evaluate("el => el === document.activeElement")
    assert not draft.path.exists()
    page.keyboard.press("Escape")
    assert not page.locator("#review-dialog").is_visible()
    page.locator("#review").click()
    expect(page.locator("#save")).to_be_enabled()
    page.locator("#save").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#finished-title")).to_have_text("Saved")
    assert draft.path.exists()
    assert all(
        url.startswith(origin + "/static/")
        or url.startswith(origin + "/api/")
        or url == origin + "/"
        or url.startswith("blob:")
        for url in requests
    )
    assert not errors


def test_small_screen_cancel_and_no_polling(page, editor, tmp_path):
    draft, origin, token = editor
    page.set_viewport_size({"width": 390, "height": 844})
    unlock(page, origin, token)
    page.locator("#field-header_text").fill("Discard this")
    expect(page.locator("#notice")).to_contain_text("Preview updated")
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    page.wait_for_timeout(400)
    assert not [url for url in requests if "/api/" in url]
    page.screenshot(path=str(tmp_path / "customiser-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#cancel").focus()
    page.keyboard.press("Enter")
    page.locator("#finished-title").get_by_text("Cancelled").wait_for()
    assert not draft.path.exists() and not draft.images.root.exists()


def test_failed_save_is_visible_in_review_and_preserves_config(page, editor):
    draft, origin, token = editor
    unlock(page, origin, token)
    page.locator("#field-header_text").fill("Reviewed draft")
    page.locator("#review").click()
    page.locator("#review-dialog").wait_for(state="visible")
    draft.path.write_text("# another editor changed this\n")
    page.locator("#save").click()
    expect(page.locator("#review-error")).to_contain_text("changed")
    assert draft.path.read_text() == "# another editor changed this\n"
    page.locator("#back").click()
    expect(page.locator("#field-header_text")).to_have_value("Reviewed draft")
    page.locator("#cancel").click()
    expect(page.locator("#finished-title")).to_have_text("Cancelled")
