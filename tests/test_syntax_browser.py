"""Real generated assets: server tokens, raw copy and renderer preferences."""

import pytest

from plotsrv.renderers.registry import render_any
from plotsrv.renderers import register_default_renderers
from plotsrv.source_info import for_file
from tests.test_expanded_view_browser import page, mount as base_mount


def install(page, source, kind="python", name="source.py"):
    register_default_renderers()
    result = render_any(
        source, view_id="artifacts:text", kind_hint=kind, source_info=for_file(name)
    )
    page.evaluate(
        """markup => {
      const root=document.getElementById('artifact-root');
      root.innerHTML=markup;
      PLOTSRV.renderers.initArtifactEnhancements(root);
      PLOTSRV.core.copyTextToClipboard=async text=>{window.copied=text;return true;};
    }""",
        result.html,
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_python_multiline_copy_controls_and_snapshot_remount(page, theme):
    base_mount(page, "artifacts:text")
    page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
    raw = 'value = """first\n<script>still a string</script>\nlast"""\r\nprint(value)\n'
    install(page, raw)
    assert page.locator(".ps-code-line").count() == 4
    assert (
        page.locator(".ps-code-line").nth(1).locator(".ps-code-token--string").count()
    )
    assert page.locator("#artifact-root script").count() == 0
    page.click('[data-plotsrv-code-action="copy"]')
    assert page.evaluate("window.copied") == raw
    page.evaluate("window.originalLine=document.querySelector('.ps-code-line')")
    page.click('[data-plotsrv-code-action="wrap"]')
    page.click('[data-plotsrv-code-action="lines"]')
    assert page.evaluate(
        "window.originalLine===document.querySelector('.ps-code-line')"
    )
    assert page.locator(".ps-code-pre--wrap.ps-code-pre--no-lines").count() == 1
    page.click('[data-plotsrv-code-action="highlight"]')
    assert page.locator(".ps-code-token").count() == 0
    install(page, raw)  # Same view, different rendered revision/snapshot.
    assert page.locator(".ps-code-token").count() == 0
    assert page.locator(".ps-code-pre--wrap.ps-code-pre--no-lines").count() == 1
    page.click('[data-plotsrv-code-action="highlight"]')
    assert page.locator(".ps-code-token--string").count()


def choose_style(page, style):
    page.click('[data-plotsrv-action="style-menu"]')
    page.click('[data-plotsrv-text-style="' + style + '"]')


def test_text_auto_code_plain_log_styles_reverse_and_copy(page):
    base_mount(page, "artifacts:text")
    raw = "SELECT count(*)\nFROM orders;\n"
    install(page, raw, "text", "query.sql")
    assert page.locator(".ps-code-token--keyword").count() >= 2
    choose_style(page, "plain")
    assert page.locator(".ps-code-token").count() == 0
    install(page, raw, "text", "query.sql")
    assert page.locator(".ps-code-token").count() == 0
    choose_style(page, "code")
    page.click('[data-plotsrv-action="reverse"]')
    assert (
        page.locator("[data-plotsrv-pre]").inner_text()
        == "FROM orders;\nSELECT count(*)\n"
    )
    page.click('[data-plotsrv-action="copy"]')
    assert page.evaluate("window.copied") == "FROM orders;\nSELECT count(*)\n"
    page.click('[data-plotsrv-action="wrap"]')
    assert page.locator(".plotsrv-pre--wrap").count() == 1
    choose_style(page, "http")
    install(page, "GET /path 503\n", "text", "access.log")
    assert page.locator(".ps-log-token--method").count() == 1
    assert page.locator("[data-plotsrv-text-style-choice]").inner_text() == "HTTP"


def test_json_raw_switch_preserves_server_tokens_and_tree(page):
    from plotsrv.json_model import build_json_document

    base_mount(page, "artifacts:text")
    raw = 'message: "<script>"\ncount: 42\n'
    doc = build_json_document(
        {"message": "<script>", "count": 42},
        source_format="yaml_file",
        raw_text=raw,
        source_filename="config.yml",
    )
    install(page, doc, "json", "config.yml")
    page.click('[data-json-mode="text"]')
    pre = page.locator("[data-json-text-view]")
    assert pre.inner_text() == raw
    assert pre.locator(".ps-code-token").count()
    page.click('[data-json-mode="json"]')
    assert page.locator('[data-json-panel="json"]').is_visible()
    page.click('[data-json-mode="text"]')
    assert pre.locator(".ps-code-token").count()
    assert page.locator("#artifact-root script").count() == 0
