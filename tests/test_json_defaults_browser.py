from plotsrv.renderers.json_tree import JsonTreeRenderer
from tests.test_plot_controls_browser import page, STATIC


def test_json_initial_markup_level_two_and_saved_level_override(page):
    markup = JsonTreeRenderer().render({"a": {"b": {"c": 1}}}, view_id="test:layout").html
    page.evaluate("html => document.body.innerHTML = '<div id=artifact-root>' + html + '</div>'", markup)
    assert page.locator('details[data-json-depth="0"]').first.evaluate("e => e.open")
    assert not page.locator('details[data-json-depth="1"]').first.evaluate("e => e.open")
    page.add_script_tag(path=str(STATIC / "js/core/storage.js"))
    page.add_script_tag(path=str(STATIC / "js/renderers/json.js"))
    page.evaluate("PLOTSRV.renderers.initJsonToolbar(document.querySelector('#artifact-root'))")
    levels = page.locator('[data-json-level-limit="1"]')
    assert levels.input_value() == "2"
    levels.select_option("3")
    assert page.locator('details[data-json-depth="1"]').first.evaluate("e => e.open")
    page.evaluate("html => {document.querySelector('#artifact-root').innerHTML = html; PLOTSRV.renderers.initJsonToolbar(document.querySelector('#artifact-root'));}", markup)
    assert levels.input_value() == "3"
    assert page.locator('details[data-json-depth="1"]').first.evaluate("e => e.open")
