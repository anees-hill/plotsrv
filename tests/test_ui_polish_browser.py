"""Rendered alignment checks for the stream toolbar and Settings header."""
import re

import pytest

from plotsrv.html import render_index
from tests.test_browser_settings_assets import _ui
from tests.test_plot_controls_browser import page, STATIC


@pytest.mark.parametrize("width", [1366, 600, 390])
def test_stream_toolbar_and_settings_header(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    page.route("http://plotsrv.test/static/**", lambda route: route.fulfill(path=str(STATIC / route.request.url.split('/static/', 1)[1])) if (STATIC / route.request.url.split('/static/', 1)[1]).is_file() else route.abort())
    markup = render_index(kind="stream", table_view_mode="rich", table_html_simple=None,
                          max_table_rows_simple=200, max_table_rows_rich=1000,
                          ui_settings=_ui(logo_url="/static/plotsrv_icon_title_colour_swash_logo.png"),
                          views=[], active_view_id="demo:stream")
    markup = re.sub(r"<script\b[^>]*>.*?</script>", "", markup, flags=re.S)
    page.set_content(markup)
    page.add_script_tag(path=str(STATIC / "js/core/settings.js"))
    page.evaluate("PLOTSRV.core.bindSettings()")
    page.wait_for_function("Array.from(document.querySelectorAll('.header-logo')).every(e => e.complete)")
    label = page.locator("#stream-session-label").bounding_box()
    control = page.locator(".ps-stream-session__control").bounding_box()
    title = page.locator(".ps-stream-controls__identity").bounding_box()
    assert label["x"] == pytest.approx(title["x"], abs=1)
    assert control["x"] > label["x"]
    assert abs(label["y"] + label["height"]/2 - control["y"] - control["height"]/2) < 2
    icon = page.locator("#stream-insights-button svg").bounding_box()
    button = page.locator("#stream-insights-button").bounding_box()
    assert abs(icon["y"] + icon["height"]/2 - button["y"] - button["height"]/2) < 1
    pause_icon = page.locator(".ps-stream-pause-button__icon").bounding_box()
    assert pause_icon["y"] + pause_icon["height"]/2 == pytest.approx(icon["y"] + icon["height"]/2, abs=0.5)
    page.add_script_tag(path=str(STATIC / "js/renderers/stream.js"))
    page.evaluate("PLOTSRV.state.streamPauseAvailable = true; PLOTSRV.core.setStreamPaused(true)")
    assert page.locator(".ps-stream-resume-glyph").is_visible()
    assert not page.locator(".ps-stream-pause-glyph").is_visible()
    page.evaluate("PLOTSRV.core.setStreamPaused(false)")
    assert page.locator(".ps-stream-pause-glyph").is_visible()
    assert not page.locator(".ps-stream-resume-glyph").is_visible()
    page.evaluate("document.querySelector('.ps-header-status').dataset.statusTone = 'live'")
    for elapsed in (0, 2000, 3000):
        offsets = page.evaluate("""elapsed => {
          document.getAnimations().filter(a => a.animationName === 'ps-stream-active-pulse').forEach(a => { a.pause(); a.currentTime = elapsed; });
          const dot = document.querySelector('.ps-header-status__dot');
          const ring = getComputedStyle(dot, '::after');
          const transform = new DOMMatrix(ring.transform);
          return [parseFloat(ring.left) + parseFloat(ring.width)/2 + transform.e - dot.offsetWidth/2,
                  parseFloat(ring.top) + parseFloat(ring.height)/2 + transform.f - dot.offsetHeight/2];
        }""", elapsed)
        assert offsets == pytest.approx([0, 0], abs=0.1)
    page.emulate_media(reduced_motion="reduce")
    assert page.locator(".ps-header-status__dot").evaluate("e => getComputedStyle(e, '::after').display") == "none"
    page.emulate_media(reduced_motion="no-preference")
    page.click("#settings-button")
    original = page.locator("#site-header").bounding_box()
    settings = page.locator(".ps-settings-page__header").bounding_box()
    assert settings["height"] == pytest.approx(original["height"], abs=1)
    logo = page.locator("#site-header .header-logo").bounding_box()
    settings_logo = page.locator(".ps-settings-page__header .header-logo").bounding_box()
    assert settings_logo["x"] == pytest.approx(logo["x"], abs=1)
    assert settings_logo["y"] == pytest.approx(logo["y"], abs=1)
    assert page.locator(".ps-settings-page__header .header-logo").get_attribute("src") == page.locator("#site-header .header-logo").get_attribute("src")
    assert page.locator(".ps-settings-page__header .ps-viewselect").count() == 0
    assert page.locator(".ps-settings-about__identity").count() == 0
    assert page.locator(".ps-settings-about__powered").inner_text() == "plotsrv"
    assert page.locator(".ps-settings-about code").is_visible()
    page.keyboard.press("Escape")
    assert not page.locator("#settings-page").is_visible()
