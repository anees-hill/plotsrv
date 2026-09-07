"""Delayed content feedback, including failures and image loading."""
import pytest

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
