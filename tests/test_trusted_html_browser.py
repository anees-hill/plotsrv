"""Developer reports retain browser functionality inside the actual UI."""
import json

from plotsrv import config
from plotsrv.renderers.html import HtmlRenderer
from tests.test_expanded_view_browser import page, mount


def test_report_css_scripts_controls_storage_and_downloads(page, monkeypatch):
    monkeypatch.setattr(config, "get_html_sanitize", lambda: False)
    monkeypatch.setattr(config, "get_html_sandbox", lambda: "")
    report = """<!doctype html><html><head><style>
        body {background: rgb(12, 34, 56); color: white}
        </style></head><body>
        <button id="run" onclick="document.querySelector('#result').textContent='Working'">Run</button>
        <output id="result">Ready</output><form id="form"><input id="note"><button>Save</button></form>
        <a download="report.txt" href="data:text/plain,report">Download</a>
        <script>
        localStorage.setItem('report-check', 'ok');
        document.querySelector('#form').onsubmit = function(e) {
            e.preventDefault(); document.querySelector('#result').textContent=document.querySelector('#note').value;
        };
        </script></body></html>"""
    mount(page, "artifacts:html")
    rendered = HtmlRenderer().render(report, view_id="artifacts:html")
    page.route("http://plotsrv.test/artifact?**", lambda route: route.fulfill(
        body=json.dumps({"kind": "html", "html": rendered.html}), content_type="application/json"
    ))
    assert page.evaluate("PLOTSRV.core.loadArtifact()")
    frame = page.frame_locator("iframe.plotsrv-html-iframe")
    assert frame.locator("body").evaluate("el=>getComputedStyle(el).backgroundColor") == "rgb(12, 34, 56)"
    frame.get_by_role("button", name="Run", exact=True).click()
    assert frame.locator("#result").inner_text() == "Working"
    frame.locator("#note").fill("Saved input")
    frame.get_by_role("button", name="Save", exact=True).click()
    assert frame.locator("#result").inner_text() == "Saved input"
    assert frame.locator("body").evaluate("()=>localStorage.getItem('report-check')") == "ok"
    with page.expect_download() as download:
        frame.get_by_role("link", name="Download", exact=True).click()
    assert download.value.suggested_filename == "report.txt"
