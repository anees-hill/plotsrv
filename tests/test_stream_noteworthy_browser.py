"""Compact noteworthy rendering with real DOM, including untrusted log values."""
import pytest

from tests.test_plot_controls_browser import page, STATIC  # shared real-browser fixture
from plotsrv.html import _stream_insights_help


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_compact_noteworthy_values_times_and_classification(page, theme):
    page.add_script_tag(path=str(STATIC / "js/renderers/stream.js"))
    page.evaluate("""theme => {
      document.documentElement.dataset.theme = theme;
      document.body.innerHTML = '<div style="width:360px;max-width:100%"><p id="stream-noteworthy-status"></p><div id="stream-noteworthy-items" class="ps-stream-noteworthy__items"></div></div>';
      window.noteworthyFixture = {object_type:'stream_noteworthy_collection', max_retained_items:64,
        retained_item_count:64, items:Array.from({length:64}, (_, i) => ({
          object_type:'stream_noteworthy_source_record', kind:'source_record',
          noteworthy_reason:'structured_severity', severity:'warning',
          observed_at:new Date(Date.now()-120000-i*1000).toISOString(), source_browser_sequence:String(i+1),
          data:{severity:'warning', value:i === 0 ? 0 : i/10, message:'<img src=x onerror=alert(1)>'}
        }))};
      PLOTSRV.core.renderStreamNoteworthy(noteworthyFixture, {noteworthy_items:'64'});
    }""", theme)
    assert page.locator(".ps-stream-noteworthy__item").count() == 64
    assert "64 source-reported warnings" in page.locator("#stream-noteworthy-status").inner_text()
    first = page.locator(".ps-stream-noteworthy__item").first
    assert first.locator(".ps-stream-noteworthy__value").inner_text() == "Value: 0"
    assert first.locator("time").get_attribute("datetime")
    assert first.locator(".ps-stream-noteworthy__age").inner_text() == "2m ago"
    assert first.locator("img").count() == 0
    assert first.bounding_box()["height"] < 135
    first.locator("summary").click()
    assert "Why retained" in first.inner_text()
    assert "recognised structured severity" in first.inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_noteworthy_missing_time_and_field_values(page):
    page.add_script_tag(path=str(STATIC / "js/renderers/stream.js"))
    page.evaluate("""() => {
      document.body.innerHTML = '<p id="stream-noteworthy-status"></p><div id="stream-noteworthy-items"></div>';
      PLOTSRV.core.renderStreamNoteworthy({object_type:'stream_noteworthy_collection', items:[{
        object_type:'stream_noteworthy_source_record', kind:'source_record', noteworthy_reason:'numeric_maximum',
        field_name:'temperature', field_value:42, observed_at:'bad time', data:{temperature:42}
      }]}, null);
    }""")
    assert page.locator(".ps-stream-noteworthy__value").inner_text() == "temperature: 42"
    assert page.locator("time").inner_text() == "Time unavailable"
    assert page.locator(".ps-stream-noteworthy__age").count() == 0


@pytest.mark.parametrize("width,theme", [(1366, "light"), (390, "dark")])
def test_insights_help_hover_focus_escape_and_scroll(page, width, theme):
    page.set_viewport_size({"width": width, "height": 800})
    markup = '<button id="stream-insights-button">Insights</button><aside id="stream-insights-drawer" style="width:360px;max-width:100%">'
    for panel in ("since", "noteworthy", "history"):
        markup += f'<div class="ps-stream-insights-heading"><h3>{panel}</h3>{_stream_insights_help(panel)}</div>'
    markup += '</aside>'
    page.evaluate("args => { document.body.innerHTML = args.markup; document.documentElement.dataset.theme = args.theme; }", {"markup": markup, "theme": theme})
    page.add_script_tag(path=str(STATIC / "js/renderers/stream.js"))
    page.evaluate("PLOTSRV.core.bindStreamInsights()")
    for index in range(3):
        help_box = page.locator(".ps-stream-insights-help").nth(index)
        summary = help_box.locator("summary")
        summary.hover()
        assert help_box.get_attribute("open") is not None
        help_box.locator('[role="region"]').hover()
        assert help_box.locator('[role="region"]').is_visible()
        summary.focus()
        page.keyboard.press("Escape")
        assert help_box.get_attribute("open") is None
        assert page.locator("#stream-insights-drawer").is_visible()
        page.locator("#stream-insights-button").focus()
        summary.focus()
        assert help_box.get_attribute("open") is not None
        if index == 1:
            body = help_box.locator('[role="region"]')
            assert body.evaluate("e => e.scrollHeight > e.clientHeight")
            body.evaluate("e => e.scrollTop = e.scrollHeight")
            assert body.evaluate("e => e.scrollTop > 0")
        page.keyboard.press("Escape")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_noteworthy_help_matches_classifier_allowlists():
    from plotsrv.streams.models import RECOGNIZED_SEVERITIES, STRUCTURED_SEVERITY_FIELDS
    from plotsrv.streams.server_state import NOTEWORTHY_LOW_CARDINALITY_FIELDS, NOTEWORTHY_NUMERIC_EXTREMUM_FIELDS

    help_html = _stream_insights_help("noteworthy")
    for value in (*RECOGNIZED_SEVERITIES, *STRUCTURED_SEVERITY_FIELDS,
                  *NOTEWORTHY_LOW_CARDINALITY_FIELDS, *NOTEWORTHY_NUMERIC_EXTREMUM_FIELDS):
        assert value in help_html
    assert "do not reset server classification" in help_html
    assert "frequent warnings can displace older errors" in help_html
