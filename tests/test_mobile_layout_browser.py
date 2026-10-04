"""Mobile layout regressions against the shipped page and browser bundle."""

import pytest

from plotsrv.streams.log_profile import LogProfile
from tests.test_expanded_view_browser import mount, expand, reveal
from tests.test_log_profile import NOW, structured
from tests.test_plot_controls_browser import page


def assert_in_viewport(locator):
    assert locator.evaluate("""node => {
      const r = node.getBoundingClientRect();
      const v = window.visualViewport;
      return r.width > 0 && r.height > 0 && r.left >= v.offsetLeft - 1 &&
        r.right <= v.offsetLeft + v.width + 1 && r.top >= v.offsetTop - 1 &&
        r.bottom <= v.offsetTop + v.height + 1;
    }""")


def assert_page_width(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


@pytest.mark.parametrize("width", [320, 390, 640])
def test_mobile_header_keeps_actions_with_branding_and_optional_controls(page, width):
    page.set_viewport_size({"width": width, "height": 850})
    mount(page)
    page.locator('#site-header .header-logo').evaluate("node => node.src = '/static/plotsrv_icon_title_colour_swash_logo.png'")
    page.locator('#site-header .header-title').evaluate("node => node.textContent = 'Northstar Outdoors ' + 'with a very long project name '.repeat(5)")
    page.locator('.ps-viewselect__label').evaluate("node => node.textContent = 'Orders with a very long descriptive view name'")
    assert_page_width(page)
    actions = page.locator('.ps-header-actions').bounding_box()
    logo = page.locator('#site-header .header-logo').bounding_box()
    status = page.locator('#header-status').bounding_box()
    assert abs(actions['y'] - logo['y']) < 3
    assert actions['y'] + actions['height'] <= status['y']
    assert logo['x'] + logo['width'] <= actions['x']
    for selector in ('#expand-view', '#settings-button', '#header-status', '.ps-viewselect__btn'):
        assert_in_viewport(page.locator(selector))
    assert page.locator('#site-header .header-title').evaluate('node => node.scrollWidth > node.clientWidth')
    for selector, class_name in (('#header-status', 'ps-header__right--no-status'), ('.ps-viewselect', 'ps-header__right--no-view')):
        page.locator(selector).evaluate('node => node.hidden = true')
        page.locator('#site-header .header-right').evaluate('(node, name) => node.classList.add(name)', class_name)
        assert_in_viewport(page.locator('#settings-button'))
        assert_page_width(page)


def log_payload():
    records = structured()
    profile = LogProfile()
    for sequence, record in enumerate(records, 1):
        profile.add(sequence, record, NOW)
    columns = list(dict.fromkeys(key for record in records for key in record))
    return {
        'columns': columns,
        'http_profile': {'version': 1, 'recipes': []},
        'log_profile': profile.describe('streams:events', columns),
        'session_id': 'session',
        'schema_revision': 1,
        'records': [
            {'browser_sequence': sequence, 'data': record, 'log_projection': profile.projection(sequence)}
            for sequence, record in enumerate(records, 1)
        ],
        'raw_window': {'first_browser_sequence': 1, 'last_browser_sequence': len(records),
                       'record_count': len(records), 'max_record_count': 512},
    }


@pytest.mark.parametrize('width', [320, 390, 640])
def test_mobile_stream_controls_stack_and_only_table_scrolls_horizontally(page, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    mount(page, 'streams:events', stream_data=log_payload())
    page.wait_for_function("document.querySelector('.ps-stream-interpretation')?.textContent.includes('Python application log')")
    assert_page_width(page)
    left = page.locator('.ps-table-topbar__left').bounding_box()
    right = page.locator('.ps-table-topbar__right').bounding_box()
    secondary = page.locator('.ps-stream-secondary-controls').bounding_box()
    assert left['height'] < 130
    assert right['y'] >= left['y'] + left['height']
    assert secondary['y'] >= right['y'] + right['height']
    for selector in ('#stream-pause-button', '#table-search-input', '#table-group-by-select',
                     '#http-suggestions-select', '#table-filters-toggle-btn', '#table-columns-toggle-btn'):
        node = page.locator(selector)
        node.scroll_into_view_if_needed()
        assert_in_viewport(node)
    page.locator('#stream-grid .tabulator-row').first.wait_for(state='attached')
    # Force a wide table through the public column API, retaining its local scroll.
    page.evaluate("PLOTSRV.state.tabulatorInstance.getColumns().forEach(c => c.setWidth(900))")
    holder = page.locator('#stream-grid .tabulator-tableholder')
    page.wait_for_function("document.querySelector('#stream-grid .tabulator-tableholder').scrollWidth > document.querySelector('#stream-grid .tabulator-tableholder').clientWidth")
    holder.evaluate('node => node.scrollLeft = 150')
    assert holder.evaluate('node => node.scrollLeft > 0')
    assert_page_width(page)
    page.locator('.ps-stream-interpretation summary').click()
    assert_in_viewport(page.locator('.ps-stream-interpretation__options'))
    page.get_by_role('menuitemradio', name='Default stream').click()
    assert page.evaluate("PLOTSRV.state.streamInterpretationOverride === 'default'")
    page.locator('#stream-pause-button').click()
    assert page.locator('#stream-pause-button').get_attribute('aria-pressed') == 'true'
    page.locator('#stream-pause-button').click()


@pytest.mark.parametrize('width', [320, 390, 640])
def test_mobile_overlays_keep_close_visible_and_restore_focus(page, width):
    page.set_viewport_size({'width': width, 'height': 600})
    mount(page)
    trigger = page.locator('.ps-viewselect__btn')
    trigger.click()
    close = page.get_by_role('button', name='Close view picker')
    assert_in_viewport(close)
    assert close.evaluate('node => document.activeElement === node')
    assert not page.locator('.ps-viewselect__search').evaluate('node => document.activeElement === node')
    page.locator('.ps-viewselect__results').evaluate('node => node.scrollTop = node.scrollHeight')
    assert_in_viewport(close)
    page.locator('.ps-viewselect__search').fill('Main')
    page.wait_for_function("document.querySelectorAll('.ps-viewselect__results [data-plotsrv-view]').length === 1")
    page.set_viewport_size({'width': width, 'height': 350})
    assert_in_viewport(close)
    assert_in_viewport(page.locator('.ps-viewselect__search'))
    close.click()
    assert trigger.evaluate('node => document.activeElement === node')
    trigger.click()
    page.keyboard.press('Escape')
    assert page.locator('.ps-viewselect__menu').is_hidden()
    status = page.locator('#header-status-button')
    status.click()
    modal_close = page.locator('#status-modal-close-icon')
    assert_in_viewport(modal_close)
    page.locator('.ps-status-modal__body').evaluate('node => node.scrollTop = node.scrollHeight')
    assert_in_viewport(modal_close)
    page.keyboard.press('Shift+Tab')
    assert page.locator('#status-modal').evaluate('node => node.contains(document.activeElement)')
    modal_close.click()
    assert status.evaluate('node => document.activeElement === node')
    assert 'ps-status-modal-open' not in page.locator('body').get_attribute('class')


def test_mobile_overlays_follow_visual_viewport_and_cleanup(page):
    page.set_viewport_size({'width': 390, 'height': 850})
    mount(page)
    page.evaluate("""() => {
      window.testViewport = new EventTarget();
      Object.assign(testViewport, {offsetTop: 100, offsetLeft: 0, width: 390, height: 350});
      Object.defineProperty(window, 'visualViewport', {value: testViewport, configurable: true});
    }""")
    for trigger, panel, close in (
        ('.ps-viewselect__btn', '.ps-viewselect__menu', '.ps-viewselect__close'),
        ('#header-status-button', '#status-modal-backdrop', '#status-modal-close-icon'),
    ):
        page.locator(trigger).click()
        assert_in_viewport(page.locator(close))
        page.evaluate("testViewport.offsetTop = 150; testViewport.height = 300; testViewport.dispatchEvent(new Event('resize'))")
        assert_in_viewport(page.locator(close))
        page.evaluate("testViewport.offsetTop = 175; testViewport.dispatchEvent(new Event('scroll'))")
        assert_in_viewport(page.locator(close))
        page.locator(close).click()
        assert page.locator(panel).evaluate("node => !node.style.getPropertyValue('--ps-mobile-viewport-height')")


def test_mobile_expanded_controls_and_picker_still_work(page):
    page.set_viewport_size({'width': 390, 'height': 700})
    mount(page)
    expand(page)
    reveal(page)
    page.locator('.ps-viewselect__btn').click()
    assert_in_viewport(page.locator('.ps-viewselect__menu'))
    page.get_by_role('button', name='Close view picker').click()
    page.locator('#expanded-exit').click()
    assert page.locator('#site-header').is_visible()
    assert_in_viewport(page.locator('#settings-button'))
    assert_page_width(page)


@pytest.mark.parametrize('width', [641, 1280, 1440])
def test_above_mobile_breakpoint_keeps_picker_autofocus_and_hides_close(page, width):
    page.set_viewport_size({'width': width, 'height': 850})
    mount(page)
    page.locator('.ps-viewselect__btn').click()
    page.wait_for_function("document.activeElement.matches('.ps-viewselect__search')")
    assert page.get_by_role('button', name='Close view picker').is_hidden()
    assert page.locator('.ps-viewselect__menu').evaluate("node => !node.style.getPropertyValue('--ps-mobile-viewport-height')")
