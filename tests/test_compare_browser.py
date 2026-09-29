"""Real bundle/renderer History interactions with deterministic bounded HTTP fixtures."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from tests.test_expanded_view_browser import page, mount as base_mount


def mount(page):
    reads = base_mount(page)
    rows = [
        {
            "snapshot_id": f"s{i:03}",
            "created_at": "2026-09-09T12:00:00+00:00",
            "kind": "table",
        }
        for i in reversed(range(125))
    ]

    def route(route):
        url = urlparse(route.request.url)
        query = parse_qs(url.query)
        reads.append(url.path)
        if url.path == "/history/month":
            payload = {
                "days": (
                    {"2026-09-09": 125} if query.get("month") == ["2026-09"] else {}
                ),
                "timezone": "UTC",
                "capability": {"enabled": True},
            }
        else:
            selected = query.get("selected", [None])[0]
            filtered = "start" in query
            eligible = (
                rows
                if not filtered or query["start"][0].startswith("2026-09-09")
                else []
            )
            offset = 100 if query.get("before") == ["page2"] else 0
            page_rows = eligible[offset : offset + (100 if filtered else 50)]
            index = next(
                (i for i, row in enumerate(rows) if row["snapshot_id"] == selected), -1
            )
            payload = {
                "snapshots": page_rows,
                "count": len(eligible),
                "next_cursor": (
                    "page2" if len(eligible) > offset + len(page_rows) else None
                ),
                "selected": rows[index] if index >= 0 else None,
                "older": rows[index + 1] if index < len(rows) - 1 else None,
                "newer": rows[index - 1] if index > 0 else None,
                "capability": {"enabled": True},
            }
        route.fulfill(body=json.dumps(payload), content_type="application/json")

    for path in ("history/month", "history/navigation"):
        page.route("**/" + path + "?**", route)
    page.evaluate("PLOTSRV.core.snapshotNavigation.loadMetadata()")
    return reads


def enter(page):
    page.click("#compare-enter")
    page.wait_for_function(
        "PLOTSRV.state.compareActive && !PLOTSRV.state.snapshotNavigation.pending && !PLOTSRV.state.compare.loading"
    )


def test_normal_timeline_collapse_restore_and_exit_preserve_controller(page):
    reads = mount(page)
    page.evaluate("window.table=PLOTSRV.state.tabulatorInstance")
    page.click("#bottom-collapse")
    assert page.locator(".ps-bottom-dock").is_hidden()
    assert page.locator("#bottom-restore").evaluate("e=>e===document.activeElement")
    page.wait_for_function(
        "getComputedStyle(document.body).getPropertyValue('--ps-bottom-dock-clearance')==='0px'"
    )
    page.click("#bottom-restore")
    enter(page)
    page.evaluate("PLOTSRV.core.compare.setDay('2026-09-09')")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.locator("#compare-points button").count() == 100
    assert page.locator("#snapshots-control").is_hidden()
    assert page.locator("#export-button").is_visible()
    assert page.locator("#export-control").evaluate(
        "e=>e.parentElement.id==='history-export-slot'"
    )
    assert page.locator("#compare-timeline").is_visible()
    assert page.locator("#compare-list-tab, #compare-timeline-tab, #compare-list").count() == 0
    assert page.locator("#bottom-collapse").is_hidden()
    assert page.locator("#bottom-pin").count() == 0
    assert page.evaluate("PLOTSRV.state.tabulatorInstance===table")
    assert "/compare/latest" not in reads
    page.screenshot(path="/tmp/plotsrv-17-timeline.png")
    page.click("#compare-exit")
    assert page.locator("#history-select").is_visible()
    assert page.locator("#export-control").evaluate(
        "e=>e.parentElement.classList.contains('ps-bottom-bar__controls')"
    )
    assert not page.evaluate("PLOTSRV.state.compareActive")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None
    assert page.evaluate("PLOTSRV.core.canApplyPendingUpdate({force:true})")


def test_latest_returns_from_snapshot_to_live_view_and_green_freshness(page):
    reads = mount(page)
    page.route(
        "**/table/data?**",
        lambda route: route.fulfill(
            body=json.dumps({"columns": ["group", "value"], "rows": [{"group": "A", "value": 999}],
                             "total_rows": 1, "returned_rows": 1}),
            content_type="application/json",
        ) if "snapshot=" in route.request.url else route.fallback(),
    )
    page.route(
        "**/status?**",
        lambda route: route.fulfill(
            body=json.dumps({"view_id": "tables:main", "kind": "table",
                             "last_updated": "2026-09-09T12:00:00Z",
                             "freshness": {"enabled": True, "state": "ok", "label": "Fresh", "age_s": 1}}),
            content_type="application/json",
        ),
    )
    enter(page)
    assert page.locator("#compare-selected").inner_text() == "Live view"
    page.click("#compare-older")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s124"
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 999
    assert page.locator("#header-status-label").inner_text() == "Snapshot"
    page.click("#compare-latest")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    page.wait_for_function("document.querySelector('#header-status-label').textContent === 'Live'")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None
    assert page.evaluate("PLOTSRV.state.tableRows.length") == 100
    assert page.locator("#compare-selected").inner_text() == "Live view"
    assert page.locator("#header-status").get_attribute("data-status-tone") == "live"
    assert "snapshot=" not in page.url
    assert "/compare/latest" not in reads


def test_timeline_point_click_target_extends_below_visible_dot(page):
    mount(page)
    enter(page)
    page.evaluate("PLOTSRV.core.compare.setDay('2026-09-09')")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    point = page.locator("#compare-points button").last
    box = point.bounding_box()
    assert box["width"] >= 28 and box["height"] >= 28
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] - 3
    assert page.evaluate(
        "([x,y]) => document.elementFromPoint(x,y)?.closest('#compare-points button')?.dataset.snapshot",
        [x, y],
    ) == "s025"
    page.mouse.click(x, y)
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s025"
    point.focus()
    assert point.evaluate("e => e === document.activeElement")


def test_bottom_bar_controls_stay_in_place_when_snapshot_selected(page):
    mount(page)
    controls = ["#export-control", "#history-select", "#compare-enter"]
    before = [page.locator(selector).bounding_box()["x"] for selector in controls]
    page.evaluate("PLOTSRV.core.snapshotNavigation.select('s124')")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    after = [page.locator(selector).bounding_box()["x"] for selector in controls]
    assert after == pytest.approx(before, abs=1)
    assert page.locator("#snapshots-return-latest").count() == 0


def test_live_updates_continue_while_history_is_open(page):
    reads = mount(page)
    enter(page)
    before = reads.count("/table/data")
    page.evaluate("""() => {
      PLOTSRV.core.receiveBrowserUpdate({view_id:'tables:main',revision:100,
        render_revision:2,server_instance_id:'testserver',change_type:'ordinary'});
    }""")
    page.wait_for_function("PLOTSRV.state.appliedUpdateRevision === 100")
    assert reads.count("/table/data") > before
    assert page.locator("#compare-selected").inner_text() == "Live view"
    assert page.evaluate("PLOTSRV.state.pendingBrowserUpdate") is None


def test_latest_applies_a_waiting_live_update_in_history(page):
    mount(page)
    enter(page)
    page.fill("#table-search-input", "A")
    page.evaluate("""() => {
      PLOTSRV.core.receiveBrowserUpdate({view_id:'tables:main',revision:101,
        render_revision:2,server_instance_id:'testserver',change_type:'ordinary'});
    }""")
    assert page.evaluate("PLOTSRV.state.pendingBrowserUpdate.revision") == 101
    assert page.locator("#header-status").get_attribute("data-status-tone") == "new-data"
    page.click("#compare-latest")
    page.wait_for_function("PLOTSRV.state.appliedUpdateRevision === 101")
    assert page.evaluate("PLOTSRV.state.pendingBrowserUpdate") is None
    assert page.locator("#compare-selected").inner_text() == "Live view"


def test_calendar_empty_dates_pagination_same_time_ids_and_outside_day(page):
    reads = mount(page)
    enter(page)
    page.evaluate("PLOTSRV.core.compare.setDay('2026-09-09')")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    stable_height = page.locator("#compare-dock").bounding_box()["height"]
    page.click("#compare-calendar-toggle")
    assert (
        page.locator('[data-day="2026-09-09"]').get_attribute("aria-label")
        == "2026-09-09 UTC, 125 stored snapshots"
    )
    page.locator('[data-day="2026-09-09"]').focus()
    page.keyboard.press("ArrowRight")
    assert page.locator('[data-day="2026-09-10"]').evaluate(
        "e=>e===document.activeElement"
    )
    page.keyboard.press("Escape")
    assert page.locator("#compare-calendar").is_hidden()
    page.click("#compare-older")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert (
        page.locator("#compare-selected").inner_text()
        == "9 Sep 2026, 12:00:00 UTC"
    )
    assert "s124" not in page.locator("#compare-selected").inner_text()
    page.click("#compare-older")
    page.wait_for_function(
        "!PLOTSRV.state.snapshotNavigation.pending && !PLOTSRV.state.snapshotNavigation.loading"
    )
    assert (
        page.locator("#compare-selected").inner_text()
        == "9 Sep 2026, 12:00:00 UTC"
    )
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s123"
    page.click("#compare-more")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.locator("#compare-points button").count() == 25
    page.click("#compare-day-next")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert "No stored snapshots" in page.locator("#compare-timeline-empty").inner_text()
    assert "outside" in page.locator("#compare-message").inner_text()
    assert page.locator("#compare-dock").bounding_box()["height"] == pytest.approx(
        stable_height, abs=1
    )
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s123"
    page.click("#compare-exit")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s123"


@pytest.mark.parametrize("width,height", [(1366, 480), (1366, 650), (1366, 900), (375, 600), (375, 900)])
def test_empty_history_day_keeps_timeline_message_and_footer_visible(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    mount(page)
    enter(page)
    page.click("#compare-older")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    page.evaluate("PLOTSRV.core.compare.setDay('2026-09-10')")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert "No stored snapshots" in page.locator("#compare-timeline-empty").inner_text()
    assert "outside this displayed day" in page.locator("#compare-message").inner_text()

    bounds = page.evaluate("""() => {
      const rect = selector => {
        const {top, bottom} = document.querySelector(selector).getBoundingClientRect();
        return {top, bottom};
      };
      const textRect = selector => {
        const range = document.createRange();
        range.selectNodeContents(document.querySelector(selector));
        const {top, bottom} = range.getBoundingClientRect();
        return {top, bottom};
      };
      return {empty: textRect('#compare-timeline-empty'),
        message: textRect('#compare-message'), results: rect('#compare-results'),
        footer: rect('.ps-history-panel__footer'), dock: rect('.ps-bottom-dock'),
        viewport: innerHeight};
    }""")
    assert bounds["empty"]["top"] >= bounds["results"]["top"]
    assert bounds["empty"]["bottom"] <= bounds["results"]["bottom"]
    assert bounds["empty"]["bottom"] <= bounds["footer"]["top"]
    assert bounds["message"]["top"] >= bounds["footer"]["top"]
    assert bounds["message"]["bottom"] <= bounds["footer"]["bottom"]
    assert bounds["dock"]["top"] >= 0
    assert bounds["dock"]["bottom"] <= bounds["viewport"]


@pytest.mark.parametrize("viewport", [375, 1366])
def test_keyboard_mobile_theme_layout_and_no_idle_metadata_work(page, viewport):
    reads = mount(page)
    page.set_viewport_size({"width": viewport, "height": 900})
    page.emulate_media(color_scheme="dark", reduced_motion="reduce")
    page.evaluate("PLOTSRV.core.applyTheme('dark')")
    page.locator("#compare-enter").focus()
    page.keyboard.press("Enter")
    page.wait_for_function(
        "!PLOTSRV.state.snapshotNavigation.pending && !PLOTSRV.state.compare.loading"
    )
    assert page.locator("#compare-latest").evaluate("e=>e===document.activeElement")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    dock = page.locator(".ps-bottom-dock").bounding_box()
    assert dock["height"] < (350 if viewport == 375 else 240)
    before = list(reads)
    page.wait_for_timeout(300)
    assert reads == before
    page.screenshot(path=f"/tmp/plotsrv-17-dark-{viewport}.png")
    header = page.locator(".ps-history-panel__header").bounding_box()
    close = page.locator("#compare-exit").bounding_box()
    assert close["x"] + close["width"] == pytest.approx(
        header["x"] + header["width"], abs=1
    )
    page.click("#compare-exit")
    assert page.locator("#compare-dock").is_hidden()
    assert page.locator("#compare-enter").evaluate("e=>e===document.activeElement")


def test_focus_handoff_and_source_change_exit_compare(page):
    mount(page)
    page.click("#expand-view")
    page.evaluate("PLOTSRV.core.compare.enter()")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert not page.evaluate("PLOTSRV.state.expandedView.active")
    assert not page.evaluate("PLOTSRV.core.expandedView.set(true)")
    page.click(".ps-viewselect__btn")
    page.click('[data-plotsrv-view="tables:other"]')
    page.wait_for_function("window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete")
    assert not page.evaluate("!!PLOTSRV.state.compareActive")


@pytest.mark.parametrize("day", ["2026-03-29", "2026-10-25"])
def test_explicit_utc_day_ignores_browser_dst_23_and_25_hour_days(page, day):
    mount(page)
    result = page.evaluate("day=>PLOTSRV.core.compare.bounds(day)", day)
    assert result[0] == day + "T00:00:00.000Z"
    assert result[1].endswith("T00:00:00.000Z")


def test_normal_collapse_survives_reload_and_expanded_handoff(page):
    mount(page)
    page.click("#bottom-collapse")
    page.click("#expand-view")
    page.reload()
    page.wait_for_function("window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete")
    assert page.evaluate("PLOTSRV.state.bottomBar.collapsed")
    assert page.locator("#bottom-restore").is_hidden()
    page.click("#expanded-exit")
    assert page.locator("#bottom-restore").is_visible()
    page.click("#bottom-restore")
    assert page.locator("#bottom-pin").count() == 0


def test_closing_history_keeps_live_view_and_denied_storage_is_tolerated(page):
    mount(page)
    enter(page)
    page.click("#compare-exit")
    assert page.locator("#snapshots-return-latest").count() == 0
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None
    page.evaluate("() => {Storage.prototype.setItem=()=>{throw Error('denied');};}")
    page.click("#bottom-collapse")
    page.click("#bottom-restore")
    assert page.locator(".ps-bottom-dock").is_visible()


def test_history_day_change_retains_plot_svg_and_release_space(page):
    mount(page)
    enter(page)
    page.click("#table-mode-plot-btn")
    page.wait_for_selector(".ps-table-plot__svg")
    page.evaluate(
        "window.svg=document.querySelector('.ps-table-plot__svg'); window.prefs=JSON.stringify(PLOTSRV.state.tablePlotPreferences)"
    )
    page.click("#compare-day-prev")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.evaluate(
        "document.querySelector('.ps-table-plot__svg')===svg && JSON.stringify(PLOTSRV.state.tablePlotPreferences)===prefs"
    )


def test_selected_body_eviction_keeps_render_and_never_jumps_to_live(page):
    mount(page)
    enter(page)
    page.route(
        "**/table/data?**",
        lambda r: r.fulfill(status=404, body="{}", content_type="application/json"),
    )
    page.click("#compare-older")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s124"
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 0
    assert "unavailable" in page.locator("#compare-message").inner_text()
    assert page.locator("#export-button").is_disabled()


def test_streams_and_disabled_capabilities_cannot_enter_compare(page):
    base_mount(page, "streams:events")
    assert page.locator("#compare-enter").is_hidden()
    page.evaluate("PLOTSRV.core.compare.enter()")
    assert not page.evaluate("!!PLOTSRV.state.compareActive")
    assert page.locator("#stream-history-session-select").is_visible()


def test_normal_clearance_and_compare_clearance_leave_last_table_rows_reachable(page):
    mount(page)
    enter(page)
    page.wait_for_timeout(100)
    table = page.locator("#table-grid").bounding_box()
    dock = page.locator(".ps-bottom-dock").bounding_box()
    assert table["y"] + table["height"] <= dock["y"], page.locator(
        "#table-grid"
    ).evaluate(
        "e=>({classes:e.className,style:e.style.cssText,height:getComputedStyle(e).height,variable:getComputedStyle(e).getPropertyValue('--ps-table-available'),body:document.body.className})"
    )
    page.set_viewport_size({"width": 375, "height": 900})
    page.wait_for_timeout(100)
    table = page.locator("#table-grid").bounding_box()
    dock = page.locator(".ps-bottom-dock").bounding_box()
    assert table["y"] + table["height"] <= dock["y"], page.locator(
        "#table-grid"
    ).evaluate(
        "e=>({classes:e.className,style:e.style.cssText,height:getComputedStyle(e).height,variable:getComputedStyle(e).getPropertyValue('--ps-table-available'),body:document.body.className})"
    )


def test_empty_month_and_calendar_open_close_are_bounded(page):
    reads = mount(page)
    enter(page)
    page.evaluate("PLOTSRV.core.compare.setDay('2026-09-09')")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    page.click("#compare-calendar-toggle")
    page.click("#compare-month-next")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.locator("#compare-calendar-days .has-snapshots").count() == 0
    assert page.locator("#compare-calendar-days button").count() == 31
    assert page.locator("#compare-day").inner_text() == "9 Sep 2026"
    page.screenshot(path="/tmp/plotsrv-17-calendar.png")
    before = list(reads)
    for _ in range(5):
        page.click("#compare-calendar-toggle")
    assert reads == before


def test_rapid_date_intents_keep_one_request_and_one_replacement(page):
    mount(page)
    enter(page)
    page.evaluate("""() => {
      const real=window.fetch; window.dayRequests=[];
      window.fetch=(url, options)=>{
        if (String(url).includes('/history/navigation?') && String(url).includes('start=')) {
          return new Promise(resolve=>dayRequests.push({url:String(url), resolve}));
        }
        return real(url, options);
      };
      PLOTSRV.core.compare.setDay('2026-09-01');
      for(let i=0;i<100;i++) PLOTSRV.core.compare.setDay('2026-09-09');
    }""")
    assert page.evaluate("dayRequests.length") == 1
    page.evaluate(
        "() => {dayRequests[0].resolve(new Response(JSON.stringify({snapshots:[],count:0}),{status:200}));}"
    )
    page.wait_for_function("dayRequests.length===2")
    assert "2026-09-09" in page.evaluate("dayRequests[1].url")
    page.evaluate(
        "() => {dayRequests[1].resolve(new Response(JSON.stringify({snapshots:[],count:0}),{status:200}));}"
    )
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.evaluate("dayRequests.length") == 2
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None
    assert page.locator("#compare-points button").count() == 0


def test_repeated_bar_presentations_have_no_dom_growth_requests_or_idle_redraws(page):
    reads = mount(page)
    enter(page)
    page.wait_for_timeout(100)
    before = list(reads)
    result = page.evaluate("""() => {
      const table=PLOTSRV.state.tabulatorInstance, rows=PLOTSRV.state.tableRows;
      const nodes=document.querySelectorAll('*').length;
      const start=performance.now();
      for(let i=0;i<100;i++) {PLOTSRV.core.bottomBar.setCollapsed(true);PLOTSRV.core.bottomBar.setCollapsed(false);}
      const elapsed=performance.now()-start;
      return {elapsed, nodeDelta:document.querySelectorAll('*').length-nodes,
        sameTable:table===PLOTSRV.state.tabulatorInstance, sameRows:rows===PLOTSRV.state.tableRows};
    }""")
    page.wait_for_timeout(100)
    page.evaluate(
        "() => {window.idleRedraws=0;const table=PLOTSRV.state.tabulatorInstance;const redraw=table.redraw.bind(table);table.redraw=(...a)=>{idleRedraws++;return redraw(...a);};}"
    )
    page.wait_for_timeout(300)
    assert result["nodeDelta"] == 0 and result["sameTable"] and result["sameRows"]
    assert page.evaluate("idleRedraws") == 0
    assert reads == before
    print("History bar measurements:", result)


@pytest.mark.parametrize("kind", ["text", "json", "html", "image", "plot"])
def test_open_history_preserves_live_renderer_content(page, kind):
    vid = "plots:figure" if kind == "plot" else "artifacts:" + kind
    reads = base_mount(page, vid)
    page.route(
        "**/history/month?**",
        lambda route: route.fulfill(body='{"days":{}}', content_type="application/json"),
    )
    before = list(reads)
    page.click("#compare-enter")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    selector = "#plot" if kind == "plot" else "#artifact-root"
    page.evaluate(
        "selector=>{window.liveNode=document.querySelector(selector);window.liveChild=liveNode.firstChild;}",
        selector,
    )
    page.click("#compare-day-prev")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.evaluate(
        "selector=>liveNode===document.querySelector(selector) && liveNode.firstChild===liveChild",
        selector,
    )
    assert "/compare/latest" not in reads
    path = "/plot" if kind == "plot" else "/artifact"
    assert reads.count(path) == before.count(path)


def test_revoked_capability_is_not_presented_as_an_empty_day(page):
    mount(page)
    enter(page)
    page.route(
        "**/history/navigation?**",
        lambda r: r.fulfill(
            body='{"capability":{"enabled":false,"message":"Storage is disabled for this view."},"snapshots":[]}',
            content_type="application/json",
        ),
    )
    page.click("#compare-day-next")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert "Storage is disabled" in page.locator("#compare-message").inner_text()
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 0
