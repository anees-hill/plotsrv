"""Real HTTP/1 connections: mocked routes cannot reproduce socket starvation."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request as URLRequest, urlopen

import pytest

playwright = pytest.importorskip("playwright.sync_api")

SERVER = r"""
import io, sys
import pandas as pd
from PIL import Image
import uvicorn
from plotsrv import config, server, settings, store
from plotsrv.app import app, publish as receive_publish
from fastapi import Request
from plotsrv.browser_updates import browser_update_hub

settings.set_runtime_context(config_path=sys.argv[1])
config.set_table_view_mode('rich')
server.enqueue_snapshot = lambda **kwargs: None
rows = pd.DataFrame({'value': range(336), 'station': ['Stafford'] * 336})
server.refresh_view(rows, label='Table', section='Test', launch_server=False)
server.refresh_view({'stations': [{'values': rows, 'meta': {'name': 'Stafford'}}]},
    label='JSON', section='Test', artifact_kind='json', launch_server=False)
png = io.BytesIO()
Image.new('RGB', (640, 320), 'teal').save(png, format='PNG')
view = store.register_view(label='Plot', section='Test', kind='plot')
store.set_plot(png.getvalue(), view_id=view)

@app.get('/_test/state')
def state():
    return {'subscribers': browser_update_hub.subscriber_count()}

@app.post('/_test/publish')
def publish(request: Request):
    if sys.argv[3] == 'http':
        receive_publish(request, {'view_id': 'Test:Table', 'kind': 'table', 'force': True,
            'table': {'columns': ['value', 'station'], 'rows': [{'value': 9999, 'station': 'Stafford'}]}})
    else:
        store.set_table(pd.DataFrame({'value': [9999], 'station': ['Stafford']}),
            None, view_id='Test:Table')
    return {'revision': browser_update_hub.current_revision('Test:Table')}

uvicorn.run(app, fd=int(sys.argv[2]), log_level='error')
"""


@pytest.fixture(scope="module", params=["local", "http"])
def live_server(tmp_path_factory, request):
    if os.name == "nt":
        pytest.skip("isolated server fixture passes a listening socket to its child")
    tmp = tmp_path_factory.mktemp("browser-connections")
    config = tmp / "plotsrv.yml"
    config.write_text("storage-settings:\n  enabled: false\n", encoding="utf-8")
    with socket.socket() as sock, (tmp / "server.log").open("w+") as log:
        sock.bind(("127.0.0.1", 0))
        sock.listen(32)
        origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", SERVER, str(config), str(sock.fileno()), request.param],
            pass_fds=(sock.fileno(),), stdout=log, stderr=log,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
            cwd=tmp,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and proc.poll() is None:
                try:
                    with urlopen(origin + "/_test/state", timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                log.seek(0)
                pytest.fail("Test server did not start: " + log.read())
            if request.param == "http":
                payload = {"view_id": "Test:Table", "kind": "table", "force": True,
                           "table": {"columns": ["value", "station"], "rows": [
                               {"value": i, "station": "Stafford"} for i in range(336)]}}
                with urlopen(URLRequest(origin + "/publish", data=json.dumps(payload).encode(),
                                        headers={"Content-Type": "application/json"}), timeout=5) as response:
                    assert response.status == 200
            yield origin
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@pytest.fixture
def browser_context():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        # Headless Chromium reports every tab as visible. Drive the real page
        # lifecycle explicitly; keep all network requests on real HTTP/1 sockets.
        context.add_init_script("""
          window.testHidden = false;
          Object.defineProperty(document, 'hidden', {get: () => testHidden});
          window.setTestHidden = hidden => {
            testHidden = hidden;
            document.dispatchEvent(new Event('visibilitychange'));
          };
        """)
        errors = []
        context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
        try:
            yield context
        finally:
            context.close()
            browser.close()
        assert not errors


def ready(page):
    page.wait_for_function("window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete", timeout=7000)
    page.wait_for_function("PLOTSRV.state.browserUpdateSource && PLOTSRV.state.browserUpdateSource.readyState === 1")


def wait_subscribers(origin, expected):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with urlopen(origin + "/_test/state", timeout=1) as response:
            count = json.load(response)["subscribers"]
        if count == expected:
            return
        time.sleep(0.02)
    assert count == expected


def test_background_tabs_release_connections_and_catch_up(browser_context, live_server):
    pages = []
    for index in range(8):
        if pages:
            pages[-1].evaluate("setTestHidden(true)")
        page = browser_context.new_page()
        pages.append(page)
        page.goto(live_server + "/?view=Test:" + ("Table", "Plot", "JSON")[index % 3],
                  wait_until="domcontentloaded", timeout=7000)
        ready(page)
    wait_subscribers(live_server, 1)
    pages[-1].evaluate("setTestHidden(true)")
    wait_subscribers(live_server, 0)
    for page in pages:
        assert page.evaluate("""() => {
          const s = PLOTSRV.state;
          return !s.browserUpdateSource && s.browserUpdateWatchdogTimer == null &&
            s.browserUpdateReconnectTimer == null && s.browserUpdateRetryTimer == null;
        }""")

    # No notice can be received while hidden. The reconnect handshake catches
    # up exactly once; further visibility changes without updates do not reload.
    assert browser_context.request.post(live_server + "/_test/publish").ok
    table = pages[0]
    reads = []
    table.on("request", lambda req: reads.append(req.url) if "/table/data?" in req.url else None)
    table.evaluate("setTestHidden(false)")
    ready(table)
    table.wait_for_function("PLOTSRV.state.tabulatorInstance.getData()[0].value === 9999")
    table.wait_for_function("!PLOTSRV.state.browserUpdateApplying")
    assert len(reads) == 1
    table.evaluate("setTestHidden(true); setTestHidden(false)")
    ready(table)
    table.wait_for_timeout(250)
    assert len(reads) == 1


@pytest.mark.parametrize("view,path,selector", [
    ("Table", "/table/data", "#table-grid .tabulator-row"),
    ("Plot", "/plot", "#plot"),
    ("JSON", "/artifact", ".ps-json-typeicon"),
])
def test_hidden_startup_loads_on_show_without_new_publication(
    browser_context, live_server, view, path, selector
):
    page = browser_context.new_page()
    page.add_init_script("window.testHidden = true;")
    reads = []
    page.on("request", lambda req: reads.append(req.url) if path + "?" in req.url else None)
    page.goto(live_server + "/?view=Test:" + view, wait_until="domcontentloaded")
    assert page.evaluate("!PLOTSRV.state.initialViewLoadComplete && !PLOTSRV.state.initialViewLoadAttempted")
    assert not reads
    assert page.evaluate("!PLOTSRV.state.browserUpdateSource")
    page.evaluate("setTestHidden(false)")
    ready(page)
    page.locator(selector).first.wait_for(state="visible")
    assert len(reads) == 1
    if view == "JSON":
        icons = page.locator(".ps-json-typeicon")
        assert icons.count() > 1
        page.wait_for_function("Array.from(document.querySelectorAll('.ps-json-typeicon')).every(i => i.complete)")
        assert icons.evaluate_all("icons => icons.every(i => i.src.includes('/static/ui-images/') && i.naturalWidth > 0 && i.naturalWidth <= 128)")


def test_navigation_and_page_cache_release_and_reopen_notifications(browser_context, live_server):
    page = browser_context.new_page()
    page.goto(live_server + "/?view=Test:Table")
    ready(page)
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}))")
    wait_subscribers(live_server, 0)
    assert page.evaluate("!PLOTSRV.state.browserUpdateSource")
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
    ready(page)
    wait_subscribers(live_server, 1)
    page.goto(live_server + "/?view=Test:JSON")
    ready(page)
    page.go_back()
    ready(page)
    assert page.evaluate("PLOTSRV.config.activeViewId") == "Test:Table"
    wait_subscribers(live_server, 1)
