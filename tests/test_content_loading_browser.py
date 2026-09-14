"""Delayed content feedback, including failures and image loading."""
import pytest
from urllib.parse import parse_qs, urlparse
from tests.test_expanded_view_browser import mount

from plotsrv.html import render_index
from tests.test_plot_controls_browser import page, STATIC


def prepare(page, kind="table", disk=False):
    markup = render_index(kind=kind, table_view_mode="rich", table_html_simple=None,
                          max_table_rows_simple=200, max_table_rows_rich=1000, file_backed=disk)
    page.evaluate("""args => {
      const parsed = new DOMParser().parseFromString(args.markup, 'text/html');
      document.body.replaceChildren(parsed.querySelector('#view-content'));
      document.body.dataset.kind = args.kind;
      PLOTSRV.config.kind = args.kind;
      PLOTSRV.core.refreshStatus = () => Promise.resolve();
      window.pendingLoad = () => new Promise((resolve, reject) => { window.finishLoad=resolve; window.failLoad=reject; });
      PLOTSRV.core.loadTable = pendingLoad;
      PLOTSRV.core.loadStream = pendingLoad;
      PLOTSRV.core.loadArtifact = pendingLoad;
    }""", {"markup": markup, "kind": kind})
    page.add_script_tag(path=str(STATIC / "js/core/app.js"))


@pytest.mark.parametrize("kind,disk,theme", [("table", False, "light"), ("artifact", True, "dark"), ("stream", False, "dark")])
def test_loading_feedback_success_failure_and_live_quietness(page, kind, disk, theme):
    prepare(page, kind, disk)
    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
    page.evaluate("void (window.loadResult = PLOTSRV.core.reloadCurrentView().catch(() => 'failed'))")
    # Do not return/await the pending JS promise through Playwright.
    page.wait_for_selector("#content-loading")
    assert page.locator("#content-loading").inner_text() == ("Loading from disk…" if disk else "Loading content…")
    assert page.locator("#view-content").get_attribute("aria-busy") == "true"
    assert page.locator("#content-loading").evaluate("e => getComputedStyle(e).getPropertyValue('--ps-loading-colour').trim()") == ("#568f97" if disk else "#cf647b")
    page.evaluate("finishLoad(true)")
    page.wait_for_selector("#content-loading", state="hidden")
    assert page.locator("#view-content").get_attribute("aria-busy") == "false"
    page.evaluate("void (window.loadResult = PLOTSRV.core.reloadCurrentView().catch(() => 'failed'))")
    if kind != "stream":
        page.wait_for_selector("#content-loading")
    else:
        page.wait_for_timeout(220)
        assert not page.locator("#content-loading").is_visible()
    page.evaluate("failLoad(new Error('test failure'))")
    page.wait_for_selector("#content-loading", state="hidden")


def test_fast_load_does_not_flash_and_reduced_motion(page):
    prepare(page)
    page.evaluate("PLOTSRV.core.loadTable = () => Promise.resolve(); void PLOTSRV.core.reloadCurrentView()")
    page.wait_for_timeout(220)
    assert not page.locator("#content-loading").is_visible()
    page.emulate_media(reduced_motion="reduce")
    assert page.locator(".ps-content-loading__spinner").evaluate("e => getComputedStyle(e).animationName") == "none"


def test_initial_history_wait_and_content_load_share_indicator(page):
    prepare(page)
    page.evaluate("""() => {
      PLOTSRV.core.loadHistory = () => new Promise(resolve => { window.finishHistory = resolve; });
      PLOTSRV.core.bootstrap();
    }""")
    page.wait_for_selector("#content-loading")
    page.evaluate("finishHistory()")
    page.wait_for_function("typeof finishLoad === 'function'")
    assert page.locator("#content-loading").is_visible()
    assert page.evaluate("PLOTSRV.core.reloadCurrentView() === PLOTSRV.core.reloadCurrentView()")
    page.evaluate("finishLoad()")
    page.wait_for_selector("#content-loading", state="hidden")


def test_plot_indicator_waits_for_image_and_clears_on_error(page):
    prepare(page, "plot")
    held = []
    page.route("**/held-plot.png", lambda route: held.append(route))
    page.evaluate("""() => {
      PLOTSRV.core.refreshPlot = async () => { document.querySelector('#plot').src = '/held-plot.png'; };
      void PLOTSRV.core.reloadCurrentView();
    }""")
    page.wait_for_selector("#content-loading")
    assert held
    held[0].abort()
    page.wait_for_selector("#content-loading", state="hidden")


def test_slow_history_does_not_block_initial_table(page):
    mount(page)
    held = []
    page.route("**/history/navigation?**", lambda route: held.append(route))
    page.goto("http://plotsrv.test/?view=tables:main", wait_until="domcontentloaded")
    page.wait_for_function("PLOTSRV.state.initialViewLoadComplete")
    assert held
    assert page.locator("#table-grid .tabulator-row").count() > 0
    assert page.evaluate("PLOTSRV.state.snapshotNavigation.loading")
    for route in held:
        route.fulfill(json={"snapshots": [], "capability": {"enabled": False}})
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.loading")


def test_initial_plot_downloads_only_selected_content_once(page):
    mount(page, "plots:figure")
    requests = []
    page.on("request", lambda request: requests.append(request.url) if urlparse(request.url).path == "/plot" else None)
    for suffix in ("", "&snapshot=1"):
        requests.clear()
        page.goto("http://plotsrv.test/?view=plots:figure" + suffix)
        page.wait_for_function("PLOTSRV.state.initialViewLoadComplete")
        assert len(requests) == 1
        assert parse_qs(urlparse(requests[0]).query).get("snapshot") == (["1"] if suffix else None)
        assert page.locator("#plot").is_visible()
        assert page.locator("#plot").evaluate("img => img.complete && img.naturalWidth > 0")


def test_invalid_plot_preserves_displayed_image_and_releases_candidate(page):
    mount(page, "plots:figure")
    previous = page.locator("#plot").get_attribute("src")
    page.evaluate("""() => {
      window.revoked = [];
      const revoke = URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL = url => { revoked.push(url); revoke(url); };
    }""")
    page.route("**/plot?**", lambda route: route.fulfill(body="broken image", content_type="image/png"))
    assert page.evaluate("PLOTSRV.core.reloadCurrentView()") is False
    assert page.locator("#plot").get_attribute("src") == previous
    assert page.locator("#plot").evaluate("img => img.complete && img.naturalWidth > 0")
    revoked = page.evaluate("revoked")
    assert len(revoked) == 1 and previous not in revoked


def test_superseded_decode_cannot_replace_newer_plot(page):
    mount(page, "plots:figure")
    previous = page.locator("#plot").get_attribute("src")
    page.evaluate("""() => {
      const decode = HTMLImageElement.prototype.decode;
      let first = true;
      HTMLImageElement.prototype.decode = function () {
        if (!first) return decode.call(this);
        first = false;
        window.decodeHeld = true;
        return new Promise((resolve, reject) => {
          window.releaseDecode = () => decode.call(this).then(resolve, reject);
        });
      };
      window.oldPlotLoad = PLOTSRV.core.refreshPlot();
    }""")
    page.wait_for_function("window.decodeHeld")
    assert page.locator("#plot").get_attribute("src") == previous
    assert page.evaluate("PLOTSRV.core.refreshPlot()")
    current = page.locator("#plot").get_attribute("src")
    assert current != previous
    page.evaluate("releaseDecode()")
    assert page.evaluate("oldPlotLoad") is False
    assert page.locator("#plot").get_attribute("src") == current


@pytest.mark.parametrize("endpoint,promise_key", [
    ("status", "statusRefreshPromise"), ("views", "viewMenuRefreshPromise"),
])
def test_stalled_metadata_cannot_hold_content_and_times_out(page, endpoint, promise_key):
    mount(page, "plots:figure")
    page.clock.install()
    held = []
    pattern = "**/" + endpoint + "?**"
    page.route(pattern, lambda route: held.append(route))
    page.goto("http://plotsrv.test/?view=plots:figure", wait_until="domcontentloaded")
    page.wait_for_function("PLOTSRV.state.initialViewLoadComplete")
    page.wait_for_function("key => !!PLOTSRV.state[key]", arg=promise_key)
    assert held
    assert page.locator("#plot").is_visible()
    assert page.locator("#view-content").get_attribute("aria-busy") == "false"
    assert not page.evaluate("!!PLOTSRV.state.reloadCurrentViewPromise")

    # Reloading real content remains possible and metadata requests coalesce.
    assert page.evaluate("PLOTSRV.core.reloadCurrentView()")
    if endpoint == "views":
        page.wait_for_function("!PLOTSRV.state.statusRefreshPromise")
    assert len(held) == 1
    page.clock.fast_forward(10001)
    page.wait_for_function("key => !PLOTSRV.state[key]", arg=promise_key)
    for route in held:
        route.abort()
    page.unroute(pattern)
    page.evaluate("PLOTSRV.core.refreshStatus()")
    page.wait_for_function("!PLOTSRV.state.statusRefreshPromise && !PLOTSRV.state.viewMenuRefreshPromise")
    assert page.evaluate("!!PLOTSRV.state.latestStatusPayload")


@pytest.mark.parametrize("recovery", ["notice", "explicit"])
def test_failed_initial_load_can_recover_on_a_later_update(page, recovery):
    mount(page, "plots:figure")
    page.route("**/plot?**", lambda route: route.fulfill(status=503, body="Temporarily unavailable"))
    page.goto("http://plotsrv.test/?view=plots:figure", wait_until="domcontentloaded")
    page.wait_for_function("PLOTSRV.state.initialViewLoadAttempted")
    assert not page.evaluate("PLOTSRV.state.initialViewLoadComplete")
    page.unroute("**/plot?**")
    if recovery == "notice":
        page.evaluate("""PLOTSRV.core.receiveBrowserUpdate({
          revision:PLOTSRV.state.observedUpdateRevision + 1,
          view_id:'plots:figure', kind:'plot', change_type:'ordinary'
        })""")
    else:
        assert page.evaluate("PLOTSRV.core.reloadCurrentView()")
    page.wait_for_function("PLOTSRV.state.initialViewLoadComplete && !PLOTSRV.state.browserUpdateApplying")
    assert page.locator("#plot").is_visible()
    assert not page.evaluate("!!PLOTSRV.state.pendingBrowserUpdate")


@pytest.mark.parametrize("invalidate", ["pagehide", "receiver-restart"])
def test_late_status_cannot_overwrite_a_resumed_or_restarted_page(page, invalidate):
    mount(page)
    page.wait_for_function("!PLOTSRV.state.statusRefreshPromise && !PLOTSRV.state.viewMenuRefreshPromise")
    page.evaluate("""() => {
      const fetch = window.fetch;
      window.fetch = (url, options) => {
        if (!url.startsWith('/status?')) return fetch(url, options);
        window.fetch = fetch;
        window.oldStatusSignal = options.signal;
        return new Promise(resolve => { window.releaseOldStatus = () => resolve(new Response(
          JSON.stringify({view_id:'tables:main', last_updated:'2000-01-01T00:00:00Z'}),
          {headers:{'Content-Type':'application/json'}})); });
      };
      void (window.oldStatus = PLOTSRV.core.refreshStatus());
    }""")
    page.wait_for_function("typeof releaseOldStatus === 'function'")
    if invalidate == "pagehide":
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}))")
        assert page.evaluate("oldStatusSignal.aborted && !PLOTSRV.state.statusRefreshPromise")
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
    else:
        page.evaluate("PLOTSRV.state.browserUpdateGeneration += 1")
    page.evaluate("releaseOldStatus(); oldStatus")
    assert page.evaluate("PLOTSRV.state.latestStatusPayload.last_updated") == "2026-09-09T12:00:00Z"
    page.evaluate("PLOTSRV.core.refreshStatus()")
    assert page.evaluate("PLOTSRV.state.latestStatusPayload.last_updated") == "2026-09-09T12:00:00Z"
