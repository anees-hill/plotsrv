"""Markdown navigation against the actual renderer and generated browser bundle."""

import json

import pytest

from plotsrv.renderers.markdown import MarkdownRenderer
from tests.test_expanded_view_browser import page, mount


def install(page, text, *, unsafe=False):
    rendered = MarkdownRenderer().render(
        {"text": text, "unsafe_html": unsafe}, view_id="artifacts:text"
    )
    page.route(
        "http://plotsrv.test/artifact?**",
        lambda route: route.fulfill(
            body=json.dumps({"kind": "markdown", "html": rendered.html}),
            content_type="application/json",
        ),
    )
    assert page.evaluate("PLOTSRV.core.loadArtifact()")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_depth_click_duplicate_headings_keyboard_and_theme(page, theme):
    mount(page, "artifacts:text")
    page.evaluate("theme => document.documentElement.dataset.theme=theme", theme)
    install(
        page,
        "# Report\n\n## **Setup**\n\n"
        + "Paragraph.\n\n" * 60
        + "## Setup\n\n### Details\n\n#### Deep\n\n###### Deepest\n\n```\n# Not a heading\n```\n\n"
        + "More content.\n\n" * 30,
    )
    toggle = page.get_by_role("button", name="TOC", exact=True)
    assert toggle.get_attribute("aria-expanded") == "false"
    assert page.locator(".plotsrv-markdown h1[id]").count() == 0  # Lazy discovery.
    toggle.focus()
    page.keyboard.press("Enter")
    select = page.get_by_label("Heading depth", exact=True)
    assert select.evaluate("el => el===document.activeElement")
    links = page.locator(".ps-markdown-toc nav a")
    assert links.all_text_contents() == ["Report", "Setup", "Setup", "Details"]
    select.select_option("6")
    assert links.all_text_contents()[-2:] == ["Deep", "Deepest"]
    assert len(set(links.evaluate_all("nodes=>nodes.map(n=>n.hash)"))) == 6
    page.screenshot(path=f"/tmp/plotsrv-markdown-toc-{theme}.png")
    original_url = page.url
    history_length = page.evaluate("history.length")
    links.nth(2).click()
    heading = page.locator(".plotsrv-markdown h2").nth(1)
    assert heading.evaluate("el=>el===document.activeElement")
    assert 0 <= heading.bounding_box()["y"] < 300
    assert page.url == original_url
    assert page.evaluate("history.length") == history_length
    sidebar = page.locator(".ps-markdown-toc")
    assert sidebar.bounding_box()["y"] >= 0  # Sticky while reading a long document.
    colors = sidebar.evaluate(
        "el=>[getComputedStyle(el).backgroundColor,getComputedStyle(el).color]"
    )
    assert colors == (
        ["rgb(255, 255, 255)", "rgb(34, 39, 43)"]
        if theme == "light"
        else ["rgb(24, 32, 39)", "rgb(232, 237, 241)"]
    )
    page.keyboard.press("Escape")
    assert sidebar.is_hidden()
    assert toggle.evaluate("el=>el===document.activeElement")


def test_refresh_and_view_switch_rebuild_without_duplicate_controls(page):
    mount(page, "artifacts:text")
    install(page, "# First\n\n#### Nested")
    page.get_by_role("button", name="TOC", exact=True).click()
    page.get_by_label("Heading depth", exact=True).select_option("4")
    install(page, "# Replacement\n\n#### New nested")
    assert page.locator(".ps-markdown-toc nav a").all_text_contents() == [
        "Replacement",
        "New nested",
    ]
    assert page.get_by_label("Heading depth", exact=True).input_value() == "4"
    page.evaluate(
        "PLOTSRV.renderers.initArtifactEnhancements(document.getElementById('artifact-root'))"
    )
    assert page.locator(".ps-markdown-shell").count() == 1
    assert page.locator(".ps-markdown-toc nav a").count() == 2
    page.evaluate("PLOTSRV.config.activeViewId='artifacts:other'")
    install(page, "# Other")
    assert page.locator(".ps-markdown-toc").is_hidden()
    page.get_by_role("button", name="TOC", exact=True).click()
    assert page.get_by_label("Heading depth", exact=True).input_value() == "3"


def test_mobile_empty_deep_only_and_sandbox(page):
    mount(page, "artifacts:text")
    page.set_viewport_size({"width": 390, "height": 844})
    install(page, "Text without headings")
    page.get_by_role("button", name="TOC", exact=True).click()
    assert "No headings" in page.locator(".ps-markdown-toc__note").inner_text()
    install(page, "##### Deep heading\n\n" + "Content\n\n" * 30)
    assert (
        "Choose a deeper level" in page.locator(".ps-markdown-toc__note").inner_text()
    )
    page.get_by_label("Heading depth", exact=True).select_option("5")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path="/tmp/plotsrv-markdown-toc-mobile.png")
    page.locator(".ps-markdown-toc nav a").click()
    assert page.locator(".ps-markdown-toc").is_hidden()
    assert page.locator("h5").evaluate("el=>el===document.activeElement")
    install(
        page, "# Isolated\n<script>parent.window.compromised=true</script>", unsafe=True
    )
    assert page.get_by_role("button", name="TOC", exact=True).is_disabled()
    assert page.locator("iframe.plotsrv-markdown-iframe").get_attribute("sandbox") == ""
    assert page.evaluate("window.compromised") is None


def test_heading_scan_and_labels_are_bounded_and_safe(page):
    mount(page, "artifacts:text")
    install(page, "# " + "long" * 100 + "\n\n" + "## Heading\n\n" * 1100)
    page.get_by_role("button", name="TOC", exact=True).click()
    assert page.locator(".ps-markdown-toc nav a").count() == 1000
    assert len(page.locator(".ps-markdown-toc nav a").first.inner_text()) == 200
    assert "limited" in page.locator(".ps-markdown-toc__note").inner_text()
    install(page, "# &lt;img src=x onerror=alert(1)&gt;")
    assert page.locator(".ps-markdown-toc nav img").count() == 0
    assert "<img" in page.locator(".ps-markdown-toc nav a").inner_text()
    page.evaluate("""() => {
      const root=document.querySelector('.plotsrv-markdown');
      PLOTSRV.core.disposeMarkdownToc();
      root.innerHTML='<p>skip</p>'.repeat(10001)+'<h1>Beyond budget</h1>';
      PLOTSRV.renderers.initMarkdownToc(document.getElementById('artifact-root'));
    }""")
    assert page.locator(".ps-markdown-toc nav a").count() == 0
    assert "limited" in page.locator(".ps-markdown-toc__note").inner_text()
