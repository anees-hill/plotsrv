"""Expanded layout against real page markup, bundle, renderers and controls."""

import base64
import io
import json
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from plotsrv import html as html_mod
from plotsrv.renderers import register_default_renderers
from plotsrv.renderers.registry import render_any
from plotsrv.store import ViewMeta
from plotsrv.table_explorer_markup import render_table_explorer
from tests.test_plot_controls_browser import page, STATIC

VIEWS = [
    ViewMeta("plots:figure", "plot", "Figure", "Plots", "plot"),
    ViewMeta("tables:main", "table", "Main table", "Tables", "table"),
    ViewMeta("tables:other", "table", "Other table", "Tables", "table"),
    ViewMeta("streams:events", "stream", "Events", "Streams", "stream"),
]
for kind in ("text", "json", "html", "image"):
    VIEWS.append(ViewMeta("artifacts:" + kind, "artifact", kind.title(), "Artifacts"))


def mount(page, view="tables:main", plot_size=(640, 1200), stream_data=None):
    page.set_default_timeout(7000)
    register_default_renderers()
    png = io.BytesIO()
    Image.new("RGB", plot_size, "teal").save(png, format="PNG")
    artifacts = {
        "text": "\n".join("Line " + str(i) for i in range(300)),
        "json": {"rows": [{"group": "A", "value": i} for i in range(30)]},
        "html": '<h1>Report</h1><input aria-label="Report note" value="Keep this">',
        "image": {
            "mime": "image/png",
            "data_b64": base64.b64encode(png.getvalue()).decode("ascii"),
        },
    }
    rendered = {
        kind: render_any(obj, view_id="artifacts:" + kind, kind_hint=kind)
        for kind, obj in artifacts.items()
    }
    assert all(result.kind == kind for kind, result in rendered.items())
    reads = []
    data = {
        "columns": ["group", "value"],
        "rows": [{"group": "A" if i % 2 else "B", "value": i} for i in range(100)],
        "total_rows": 100,
        "returned_rows": 100,
    }

    def route_handler(route):
        parsed = urlparse(route.request.url)
        query = parse_qs(parsed.query)
        vid = query.get("view", ["tables:main"])[0]
        kind = next((v.kind for v in VIEWS if v.view_id == vid), "table")
        path = parsed.path
        if path.startswith("/static/"):
            path = STATIC / path.removeprefix("/static/")
            if path.is_file():
                route.fulfill(path=str(path))
            else:
                route.fulfill(status=404, body="")
            return
        reads.append(parsed.path)
        if path == "/":
            markup = html_mod.render_index(
                kind=kind,
                table_view_mode="rich",
                table_html_simple=None,
                max_table_rows_simple=200,
                max_table_rows_rich=1000,
                active_view_id=vid,
                views=VIEWS,
            )
            route.fulfill(body=markup, content_type="text/html")
            return
        if path == "/plot":
            route.fulfill(body=png.getvalue(), content_type="image/png")
            return
        payload = {}
        if path == "/history/navigation":
            selected = query.get("selected", [None])[0]
            rows = [
                {
                    "snapshot_id": str(i),
                    "created_at": "2026-09-09T12:00:00Z",
                    "kind": "table",
                }
                for i in (3, 2, 1)
            ]
            index = next(
                (i for i, r in enumerate(rows) if r["snapshot_id"] == selected), -1
            )
            payload = {
                "snapshots": rows,
                "capability": {"enabled": True},
                "selected": rows[index] if index >= 0 else None,
                "older": rows[index + 1] if index < 2 else None,
                "newer": rows[index - 1] if index > 0 else None,
            }
        elif path == "/table/data":
            payload = data
        elif path == "/artifact":
            result = rendered[vid.split(":")[1]]
            payload = {"kind": result.kind, "html": result.html, "meta": result.meta}
        elif path == "/status":
            payload = {
                "view_id": vid,
                "kind": kind,
                "last_updated": "2026-09-09T12:00:00Z",
            }
        elif path == "/stream/history":
            payload = {"sessions": [], "capability": {"enabled": True}}
        elif path == "/stream/data":
            payload = stream_data if stream_data is not None else {
                "columns": data["columns"],
                "records": [
                    {"browser_sequence": i + 1, "data": row}
                    for i, row in enumerate(data["rows"])
                ],
                "session_id": "session",
                "historical": False,
                "raw_window": {
                    "first_browser_sequence": 1,
                    "last_browser_sequence": 100,
                    "record_count": 100,
                    "max_record_count": 100,
                },
            }
        route.fulfill(body=json.dumps(payload), content_type="application/json")

    page.add_init_script("window.EventSource = undefined;")
    page.route("http://plotsrv.test/**", route_handler)
    page.goto("http://plotsrv.test/?view=" + view)
    page.wait_for_function("window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete")
    # Content readiness deliberately precedes the startup status/catalogue
    # requests. Finish both before recording a no-extra-requests baseline.
    page.wait_for_function("""() => {
      const state = PLOTSRV.state;
      return state.latestStatusPayload &&
        !state.statusRefreshPromise && !state.viewMenuRefreshPromise;
    }""")
    if view.startswith(("tables:", "streams:")):
        page.wait_for_function(
            "PLOTSRV.state.tabulatorInstance && PLOTSRV.state.tabulatorInstance.initialized"
        )
    return reads


def expand(page):
    page.click("#expand-view")
    page.wait_for_function("PLOTSRV.state.expandedView.active")


def reveal(page):
    page.click("#expanded-reveal")
    page.wait_for_function("PLOTSRV.state.expandedView.revealed")


def test_table_layout_preserves_controller_filters_plot_and_scroll_without_requests(
    page,
    tmp_path,
):
    reads = mount(page)
    page.fill("#table-search-input", "A")
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.getData('active').length===50"
    )
    page.evaluate(
        "window.originalTable=PLOTSRV.state.tabulatorInstance; window.originalRows=PLOTSRV.state.tableRows; window.originalMode=document.querySelector('.ps-table-mode-switch');"
    )
    before = list(reads)
    expand(page)
    assert page.locator("#expanded-reveal").evaluate(
        "e => e === document.activeElement"
    )
    assert page.locator("#site-header").is_hidden()
    assert page.locator("#table-search-input").is_hidden()
    assert page.locator("#history-select").is_hidden()
    assert page.locator(".ps-bottom-dock").is_hidden()
    assert page.locator("#table-grid").bounding_box()["height"] > 700
    reveal(page)
    assert page.locator("#history-select").is_visible()
    assert page.locator("#table-mode-plot-btn").is_visible()
    page.screenshot(path=str(tmp_path / "plotsrv-16-table-desktop.png"))
    assert page.evaluate(
        "document.querySelector('.ps-table-mode-switch') === originalMode"
    )
    page.click("#table-mode-plot-btn")
    page.wait_for_selector(".ps-table-plot__svg")
    page.evaluate(
        "window.originalSvg=document.querySelector('.ps-table-plot__svg'); window.plotPrefs=JSON.stringify(PLOTSRV.state.tablePlotPreferences)"
    )
    page.click("#expanded-reveal")
    page.set_viewport_size({"width": 1000, "height": 760})
    page.wait_for_timeout(100)
    assert page.evaluate(
        "document.querySelector('.ps-table-plot__svg') === originalSvg"
    )
    page.set_viewport_size({"width": 375, "height": 800})
    reveal(page)
    page.screenshot(path=str(tmp_path / "plotsrv-16-table-plot-mobile.png"))
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.click("#expanded-exit")
    assert page.locator("#expand-view").evaluate("e => e === document.activeElement")
    assert page.locator("#table-search-input").input_value() == "A"
    assert page.evaluate(
        "originalTable===PLOTSRV.state.tabulatorInstance && originalRows===PLOTSRV.state.tableRows"
    )
    assert page.evaluate(
        "plotPrefs===JSON.stringify(PLOTSRV.state.tablePlotPreferences)"
    )
    assert reads == before


def test_keyboard_reveal_selector_status_escape_layers_and_hidden_tab_order(page):
    mount(page)
    page.focus("#expand-view")
    page.keyboard.press("Enter")
    page.keyboard.press("Tab")
    assert page.locator("#expanded-exit").evaluate("e => e === document.activeElement")
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Enter")
    page.focus(".ps-viewselect__btn")
    page.keyboard.press("Enter")
    assert page.locator("#view-selector-menu").is_visible()
    page.keyboard.press("Escape")
    assert page.locator("#view-selector-menu").is_hidden()
    assert page.evaluate("PLOTSRV.state.expandedView.active")
    page.focus("#header-status-button")
    page.keyboard.press("Enter")
    assert page.locator("#status-modal-backdrop").is_visible()
    assert not page.evaluate("PLOTSRV.core.expandedView.reveal(false)")
    page.keyboard.press("Escape")
    assert page.locator("#status-modal-backdrop").is_hidden()
    assert page.locator("#header-status-button").evaluate(
        "e => e === document.activeElement"
    )
    assert page.evaluate("PLOTSRV.state.expandedView.active")
    page.keyboard.press("Escape")
    assert not page.evaluate("PLOTSRV.state.expandedView.active")
    assert page.locator("#expand-view").evaluate("e => e === document.activeElement")


@pytest.mark.parametrize("width", [1366, 900, 390])
def test_source_change_reload_session_scope_and_snapshot_intention(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    mount(page)
    page.evaluate("PLOTSRV.core.snapshotNavigation.select('2')")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.locator("#snapshot-mode-banner").is_visible()
    expand(page)
    assert page.locator("#snapshot-mode-banner").is_hidden()
    assert "Historical snapshot" in page.locator("#expanded-handle").evaluate(
        "e => getComputedStyle(e, '::before').content"
    )
    reveal(page)
    assert page.locator("#history-select").input_value() == "2"
    page.wait_for_function("""() => {
      const controls = document.getElementById('expanded-controls').getBoundingClientRect();
      const handle = document.getElementById('expanded-handle').getBoundingClientRect();
      return controls.right <= handle.left || controls.top >= handle.bottom;
    }""")
    page.click("#snapshot-older")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert "snapshot=1" in page.url
    page.reload()
    page.wait_for_function(
        "window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete && PLOTSRV.state.expandedView.active"
    )
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "1"
    reveal(page)
    page.click(".ps-viewselect__btn")
    page.click('[data-plotsrv-view="tables:other"]')
    page.wait_for_function(
        "window.PLOTSRV && PLOTSRV.config.activeViewId==='tables:other' && PLOTSRV.state.initialViewLoadComplete"
    )
    assert page.evaluate("PLOTSRV.state.expandedView.active")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None
    assert "Historical snapshot" not in page.locator("#expanded-handle").evaluate(
        "e => getComputedStyle(e, '::before').content"
    )
    page.click("#expanded-exit")
    page.reload()
    page.wait_for_function("window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete")
    assert not page.evaluate("PLOTSRV.state.expandedView.active")


@pytest.mark.parametrize(
    "kind,metadata_delay_ms",
    [
        ("text", 0),
        ("json", 0),
        ("html", 0),
        ("image", 0),
        pytest.param("json", 500, id="json-delayed-metadata"),
    ],
)
def test_artifacts_retain_dom_and_html_frame_across_layout_and_themes(
    page, kind, metadata_delay_ms, tmp_path
):
    if metadata_delay_ms:
        page.add_init_script("""(() => {
          const fetch = window.fetch.bind(window);
          window.fetch = async (...args) => {
            const response = await fetch(...args);
            const path = new URL(args[0], location.href).pathname;
            if (path === '/status' || path === '/views') {
              await new Promise(resolve => setTimeout(resolve, %d));
            }
            return response;
          };
        })();""" % metadata_delay_ms)
    reads = mount(page, "artifacts:" + kind)
    page.evaluate(
        "window.originalRoot=document.getElementById('artifact-root'); window.originalContent=originalRoot.firstElementChild; window.originalFrame=originalRoot.querySelector('iframe')"
    )
    if kind == "html":
        page.frame_locator("#artifact-root iframe").get_by_label("Report note").fill(
            "Preserved note"
        )
    before = list(reads)
    assert "/status" in before and "/views" in before
    expand(page)
    assert page.locator("#artifact-root").is_visible()
    if kind == "image":
        page.wait_for_function(
            "document.querySelector('#artifact-root img').naturalHeight===1200"
        )
        assert page.locator("#artifact-root img").bounding_box()["height"] < 850
    page.screenshot(path=str(tmp_path / ("plotsrv-16-" + kind + ".png")))
    reveal(page)
    assert (
        page.locator("#table-mode-plot-btn").count() == 0
        or page.locator("#table-mode-plot-btn").is_hidden()
    )
    page.emulate_media(color_scheme="dark", reduced_motion="reduce")
    page.evaluate("PLOTSRV.core.applyTheme('dark')")
    page.set_viewport_size({"width": 375, "height": 800})
    page.wait_for_timeout(100)
    assert page.locator("#expanded-exit").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path / ("plotsrv-16-" + kind + "-mobile.png")))
    page.click("#expanded-exit")
    assert page.evaluate(
        "document.getElementById('artifact-root')===originalRoot && originalRoot.firstElementChild===originalContent && originalRoot.querySelector('iframe')===originalFrame"
    )
    if kind == "html":
        assert (
            page.frame_locator("#artifact-root iframe")
            .get_by_label("Report note")
            .input_value()
            == "Preserved note"
        )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert reads == before


def test_stream_controls_stay_separate_and_controller_continues(page, tmp_path):
    reads = mount(page, "streams:events")
    page.evaluate(
        "window.streamTable=PLOTSRV.state.streamTabulatorInstance; window.session=PLOTSRV.state.streamSessionId"
    )
    before = list(reads)
    expand(page)
    reveal(page)
    assert page.locator("#snapshots-control").count() == 0
    assert page.locator("#stream-history-session-select").is_visible()
    page.screenshot(path=str(tmp_path / "plotsrv-16-stream-table-desktop.png"))
    page.click("#table-mode-plot-btn")
    page.wait_for_selector(".ps-table-plot__svg")
    page.set_viewport_size({"width": 375, "height": 800})
    page.screenshot(path=str(tmp_path / "plotsrv-16-stream-plot-mobile.png"))
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.click("#expanded-reveal")
    page.click("#expanded-exit")
    assert page.evaluate(
        "streamTable===PLOTSRV.state.streamTabulatorInstance && session===PLOTSRV.state.streamSessionId"
    )
    assert reads == before


def test_denied_storage_and_compare_boundary_do_not_change_data(page):
    mount(page)
    page.evaluate(
        "() => {Storage.prototype.setItem=function(){throw Error('denied');}; Storage.prototype.removeItem=function(){throw Error('denied');};}"
    )
    expand(page)
    page.evaluate(
        "PLOTSRV.core.expandedView.prepareForCompare(); PLOTSRV.state.compareActive=true"
    )
    assert not page.evaluate("PLOTSRV.core.expandedView.set(true)")
    page.evaluate("PLOTSRV.state.compareActive=false")
    expand(page)
    page.click("#expanded-exit")


@pytest.mark.parametrize("width", [1366, 900, 390])
def test_my_view_selection_keeps_expanded_and_saved_filters(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    mount(page)
    page.fill("#table-search-input", "A")
    page.click("#table-save-view-btn")
    page.get_by_label("Name", exact=True).fill("Only A")
    page.locator("dialog").get_by_role("button", name="Save view", exact=True).click()
    page.wait_for_selector("dialog", state="detached")
    expand(page)
    reveal(page)
    page.click(".ps-viewselect__btn")
    page.wait_for_function("""() => {
      const menu = document.getElementById('view-selector-menu').getBoundingClientRect();
      return menu.left >= 0 && menu.right <= innerWidth;
    }""")
    page.click('[data-view-mode="my"]')
    page.click("[data-personal-view]")
    page.wait_for_function(
        "window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete && PLOTSRV.state.expandedView.active"
    )
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance && PLOTSRV.state.tabulatorInstance.getData('active').length===50"
    )
    assert "my_view=" in page.url
    assert page.evaluate("PLOTSRV.state.tableUiState.searchQuery") == "A"


def test_live_stream_append_and_stored_session_are_not_reset_by_layout(page):
    mount(page, "streams:events")
    expand(page)
    page.evaluate("""async () => {
      const state=PLOTSRV.state;
      window.existingTable=state.streamTabulatorInstance;
      await PLOTSRV.core.loadStream();
      if (existingTable!==state.streamTabulatorInstance) throw Error('Stream remounted');
      state.streamHistoricalSessionId='older-run';
      state.streamPaused=true;
    }""")
    reveal(page)
    page.click("#expanded-exit")
    assert page.evaluate("PLOTSRV.state.streamHistoricalSessionId") == "older-run"
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None
    assert page.evaluate("PLOTSRV.state.streamPaused")


def test_repeated_layout_changes_and_idle_work_stay_bounded(page):
    reads = mount(page)
    before = list(reads)
    result = page.evaluate("""async () => {
      const {core,state}=PLOTSRV;
      const table=state.tabulatorInstance;
      const rows=state.tableRows;
      const nodes=document.querySelectorAll('*').length;
      const start=performance.now();
      for (let i=0;i<100;i++) {core.expandedView.set(true);core.expandedView.set(false);}
      const togglesMs=performance.now()-start;
      core.expandedView.set(true);
      const syncStart=performance.now();
      for (let i=0;i<1000;i++) core.syncExpandedView();
      const syncMs=performance.now()-syncStart;
      core.expandedView.set(false);
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      return {togglesMs,syncMs,sameTable:table===state.tabulatorInstance,sameRows:rows===state.tableRows,
        nodeDelta:document.querySelectorAll('*').length-nodes, storage:sessionStorage.length};
    }""")
    assert result["sameTable"] and result["sameRows"]
    assert result["nodeDelta"] == 0
    assert page.evaluate(
        "!Array.from({length:sessionStorage.length},(_,i)=>sessionStorage.key(i)).some(k=>k.startsWith('plotsrv:expanded:'))"
    )
    page.evaluate("""() => {
      window.redraws=0;
      const table=PLOTSRV.state.tabulatorInstance;
      const redraw=table.redraw.bind(table);
      table.redraw=(...args)=>{redraws++;return redraw(...args);};
    }""")
    page.wait_for_timeout(250)
    assert page.evaluate("redraws") == 0
    assert reads == before
    expand(page)
    page.wait_for_timeout(100)
    settled_redraws = page.evaluate("redraws")
    page.wait_for_timeout(250)
    assert page.evaluate("redraws") == settled_redraws
    assert reads == before
    print("Expanded layout measurements:", result)


def test_renderer_replacement_reuses_new_controls_and_restores_focus(page):
    mount(page, "artifacts:text")
    expand(page)
    reveal(page)
    content = render_table_explorer(
        grid_html='<div id="table-grid"></div>', search_placeholder="Search"
    )
    page.route(
        "**/artifact?**",
        lambda route: route.fulfill(
            body=json.dumps({"kind": "table", "html": content}),
            content_type="application/json",
        ),
    )
    page.evaluate("PLOTSRV.core.reloadCurrentView()")
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.initialized")
    assert page.locator("#expanded-controls #table-mode-plot-btn").is_visible()
    assert page.locator(".ps-table-mode-switch").count() == 1
    page.focus("#table-mode-plot-btn")
    page.route(
        "**/artifact?**",
        lambda route: route.fulfill(
            body=json.dumps({"kind": "text", "html": "<p>Replacement text</p>"}),
            content_type="application/json",
        ),
    )
    page.evaluate("PLOTSRV.core.reloadCurrentView()")
    assert page.locator(".ps-table-mode-switch").count() == 0
    assert page.locator("#expanded-reveal").evaluate("e=>e===document.activeElement")
    page.click("#expanded-exit")
    assert page.locator(".ps-table-mode-switch").count() == 0
    assert page.locator("#artifact-root").inner_text() == "Replacement text"


def test_plot_image_and_scroll_do_not_reload_or_request_native_fullscreen(page):
    reads = mount(page, "plots:figure")
    page.evaluate("""() => {
      window.oldPlot=document.getElementById('plot'); window.oldSrc=oldPlot.src;
      HTMLElement.prototype.requestFullscreen=()=>{throw Error('Native fullscreen called');};
    }""")
    before = list(reads)
    expand(page)
    page.set_viewport_size({"width": 600, "height": 500})
    assert page.evaluate(
        "document.getElementById('plot')===oldPlot && oldPlot.src===oldSrc"
    )
    page.click("#expanded-exit")
    assert reads.count("/plot") == before.count("/plot")


def test_table_scroll_position_and_checks_attention_survive_layout(page):
    from tests.test_check_status_browser import evidence

    mount(page)
    checks = evidence()
    for rule in checks["states"]:
        rule["source"] = "tables:main"
    page.evaluate(
        """data => {
      PLOTSRV.core.setHeaderLatestStatus({checks:data,last_updated:'2026-09-09T12:00:00Z'});
      window.holder=document.querySelector('.tabulator-tableholder'); holder.scrollTop=400;
      window.scrollPosition=holder.scrollTop;
    }""",
        checks,
    )
    assert page.locator("#header-check-attention").is_visible()
    expand(page)
    reveal(page)
    assert page.locator("#header-check-attention").is_visible()
    page.wait_for_timeout(100)
    assert page.evaluate("holder.scrollTop===scrollPosition")
    page.click("#expanded-exit")
    page.wait_for_timeout(100)
    assert page.evaluate("holder.scrollTop===scrollPosition")
    assert page.locator("#header-check-attention").is_visible()


@pytest.mark.parametrize("width,height", [(375, 667), (600, 400), (1366, 600)])
def test_revealed_controls_leave_table_footer_inside_viewport(page, width, height):
    mount(page)
    page.set_viewport_size({"width": width, "height": height})
    expand(page)
    reveal(page)
    page.wait_for_function("""() => {
      const table=document.querySelector('.tabulator'), footer=table.querySelector('.tabulator-footer');
      return footer && table.getBoundingClientRect().bottom <= innerHeight &&
        footer.getBoundingClientRect().bottom <= innerHeight;
    }""")
    assert (
        page.evaluate(
            "getComputedStyle(document.querySelector('.tabulator')).minHeight"
        )
        == "0px"
    )
