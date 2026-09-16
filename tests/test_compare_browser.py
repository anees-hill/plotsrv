"""Real bundle/renderer Compare interactions with deterministic bounded HTTP fixtures."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from tests.test_expanded_view_browser import page, mount as base_mount


def mount(page):
    reads = base_mount(page)
    captures = []
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
        if url.path == "/compare/latest":
            revision = len(captures) + 1
            captures.append(revision)
            payload = {
                "version": 1,
                "server_instance_id": "testserver",
                "view_id": "tables:main",
                "revision": revision,
                "kind": "table",
                "created_at": f"2026-09-09T12:00:0{revision}+00:00",
                "status": {"last_updated": f"2026-09-09T12:00:0{revision}+00:00"},
                "scope": "Published table preview: 1 of 1 hosted rows",
                "table": {
                    "columns": ["group", "value"],
                    "rows": [{"group": "A", "value": revision}],
                    "total_rows": 1,
                    "returned_rows": 1,
                },
            }
        elif url.path == "/history/month":
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

    for path in ("compare/latest", "history/month", "history/navigation"):
        page.route("**/" + path + "?**", route)
    page.evaluate("PLOTSRV.core.snapshotNavigation.loadMetadata()")
    return reads, captures


def enter(page):
    page.click("#compare-enter")
    page.wait_for_function(
        "PLOTSRV.state.compareActive && !PLOTSRV.state.snapshotNavigation.pending && !PLOTSRV.state.compare.loading"
    )


def test_normal_timeline_list_collapse_restore_and_exit_preserve_controller(page):
    reads, captures = mount(page)
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
    page.click("#compare-list-tab")
    page.click("#bottom-collapse")
    assert page.locator("#compare-list").is_hidden()
    page.click("#bottom-restore")
    assert page.locator("#compare-list").is_visible()
    assert page.locator("#bottom-pin").count() == 0
    assert page.evaluate("PLOTSRV.state.tabulatorInstance===table")
    assert captures == [1]
    page.screenshot(path="/tmp/plotsrv-17-list.png")
    page.click("#compare-timeline-tab")
    page.screenshot(path="/tmp/plotsrv-17-timeline.png")
    page.click("#compare-exit")
    assert page.locator("#history-select").is_visible()
    assert not page.evaluate("PLOTSRV.state.compareActive")
    assert page.evaluate("PLOTSRV.state.compareCapture.revision") == 1
    assert not page.evaluate("PLOTSRV.core.canApplyPendingUpdate({force:true})")


def test_latest_freezes_payload_exact_timestamp_export_and_explicit_recapture(page):
    reads, captures = mount(page)
    enter(page)
    assert "r1" in page.locator("#compare-selected").inner_text()
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 1
    page.evaluate("""() => {
      PLOTSRV.state.pendingBrowserUpdate={revision:99};
      PLOTSRV.core.applyPendingUpdate({force:true});
    }""")
    before = list(reads)
    page.wait_for_timeout(200)
    assert reads == before
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 1
    page.click("#compare-latest")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert captures == [1, 2]
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 2
    assert "12:00:02" in page.locator("#compare-selected").inner_text()
    page.click("#export-button")
    with page.expect_download() as download:
        page.click('[data-export-scope="complete"]')
    assert download.value.suggested_filename == "plotsrv-captured-preview.csv"
    assert reads.count("/table/export") == 0


def test_calendar_empty_dates_pagination_same_time_ids_and_outside_day(page):
    reads, _ = mount(page)
    enter(page)
    page.evaluate("PLOTSRV.core.compare.setDay('2026-09-09')")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
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
    page.click("#compare-list-tab")
    page.locator('#compare-list [data-snapshot="s124"]').click()
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert "s124" in page.locator("#compare-selected").inner_text()
    page.click("#compare-older")
    page.wait_for_function(
        "!PLOTSRV.state.snapshotNavigation.pending && !PLOTSRV.state.snapshotNavigation.loading"
    )
    assert "s123" in page.locator("#compare-selected").inner_text()
    page.click("#compare-more")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.locator("#compare-list button").count() == 25
    page.click("#compare-day-next")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert "No stored snapshots" in page.locator("#compare-list").inner_text()
    assert "outside" in page.locator("#compare-message").inner_text()
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s123"
    page.click("#compare-exit")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s123"


def test_failed_latest_keeps_coherent_body_and_explicit_retry(page):
    mount(page)
    enter(page)
    page.route(
        "**/compare/latest?**",
        lambda r: r.fulfill(
            status=409,
            body=json.dumps(
                {"detail": "Latest changed during capture. Choose Latest again."}
            ),
            content_type="application/json",
        ),
    )
    page.click("#compare-latest")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert "changed" in page.locator("#compare-message").inner_text()
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 1
    assert page.locator("#export-button").is_disabled()


@pytest.mark.parametrize("viewport", [375, 1366])
def test_keyboard_mobile_theme_layout_and_no_idle_metadata_work(page, viewport):
    reads, _ = mount(page)
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
    page.locator("#bottom-collapse").focus()
    page.keyboard.press("Enter")
    assert page.locator("#bottom-restore").evaluate("e=>e===document.activeElement")
    page.keyboard.press("Enter")
    assert page.locator("#compare-dock").is_visible()


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
    assert not page.evaluate("!!PLOTSRV.state.compareCapture")


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


def test_captured_latest_can_be_released_after_exit_and_denied_storage(page):
    mount(page)
    enter(page)
    page.click("#compare-exit")
    assert page.locator("#snapshots-return-latest").is_visible()
    page.click("#snapshots-return-latest")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.compareCapture") is None
    page.evaluate("() => {Storage.prototype.setItem=()=>{throw Error('denied');};}")
    page.click("#bottom-collapse")
    page.click("#bottom-restore")
    assert page.locator(".ps-bottom-dock").is_visible()


def test_compare_presentation_changes_retain_plot_svg_and_release_space(page):
    mount(page)
    enter(page)
    page.click("#table-mode-plot-btn")
    page.wait_for_selector(".ps-table-plot__svg")
    page.evaluate(
        "window.svg=document.querySelector('.ps-table-plot__svg'); window.prefs=JSON.stringify(PLOTSRV.state.tablePlotPreferences)"
    )
    page.click("#bottom-collapse")
    page.wait_for_function(
        "getComputedStyle(document.body).getPropertyValue('--ps-bottom-dock-clearance')==='0px'"
    )
    page.click("#bottom-restore")
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
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 1
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
    reads, _ = mount(page)
    enter(page)
    page.evaluate("PLOTSRV.core.compare.setDay('2026-09-09')")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    page.click("#compare-calendar-toggle")
    page.click("#compare-month-next")
    page.wait_for_function("!PLOTSRV.state.compare.loading")
    assert page.locator("#compare-calendar-days .has-snapshots").count() == 0
    assert page.locator("#compare-calendar-days button").count() == 31
    assert page.locator("#compare-day").input_value() == "2026-09-09"
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
    assert page.evaluate("PLOTSRV.state.compareCapture.revision") == 1
    assert page.locator("#compare-list button").count() == 0


def test_rapid_latest_intents_coalesce_and_late_capture_cannot_replace_selection(page):
    mount(page)
    enter(page)
    page.evaluate("""() => {
      const real=window.fetch; window.latestRequests=[];
      window.fetch=(url, options)=>String(url).includes('/compare/latest?')
        ? new Promise(resolve=>latestRequests.push(resolve)) : real(url, options);
      PLOTSRV.core.snapshotNavigation.select(null);
      for(let i=0;i<100;i++) PLOTSRV.core.snapshotNavigation.select(null);
    }""")
    assert page.evaluate("latestRequests.length") == 1
    page.evaluate(
        "() => {latestRequests[0](new Response(JSON.stringify(PLOTSRV.state.compareCapture),{status:200}));}"
    )
    page.wait_for_function("latestRequests.length===2")
    page.evaluate(
        "() => {const data={...PLOTSRV.state.compareCapture, revision:5}; data.table={...data.table,rows:[{group:'A',value:5}]}; latestRequests[1](new Response(JSON.stringify(data),{status:200}));}"
    )
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 5
    assert page.evaluate("latestRequests.length") == 2
    page.evaluate(
        "() => {PLOTSRV.core.snapshotNavigation.select(null); PLOTSRV.core.snapshotNavigation.select('s123'); latestRequests[2](new Response(JSON.stringify(PLOTSRV.state.compareCapture),{status:200}));}"
    )
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s123"
    assert page.evaluate("PLOTSRV.state.compareCapture") is None
    assert page.evaluate("PLOTSRV.state.tableRows.length") == 100


def test_repeated_bar_presentations_have_no_dom_growth_requests_or_idle_redraws(page):
    reads, _ = mount(page)
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
    print("Compare bar measurements:", result)


@pytest.mark.parametrize("kind", ["text", "json", "html", "image", "plot"])
def test_latest_capture_across_supported_renderers_keeps_selected_content(page, kind):
    import base64
    import io
    from PIL import Image
    from plotsrv.renderers.registry import render_any

    vid = "plots:figure" if kind == "plot" else "artifacts:" + kind
    reads = base_mount(page, vid)
    png = io.BytesIO()
    Image.new("RGB", (20, 20), "teal").save(png, format="PNG")
    objects = {
        "text": "Captured text",
        "json": {"frozen": 1},
        "html": "<h1>Captured report</h1><input aria-label='Note' value='Keep'>",
        "image": {
            "mime": "image/png",
            "data_b64": base64.b64encode(png.getvalue()).decode(),
        },
    }
    payload = {
        "version": 1,
        "view_id": vid,
        "revision": 7,
        "created_at": "2026-09-09T12:00:00Z",
        "scope": "Published representation",
        "status": {"last_updated": "2026-09-09T12:00:00Z"},
    }
    if kind == "plot":
        payload["plot"] = base64.b64encode(png.getvalue()).decode()
    else:
        result = render_any(objects[kind], view_id=vid, kind_hint=kind)
        payload["artifact"] = {
            "kind": result.kind,
            "html": result.html,
            "meta": result.meta,
        }
    page.route(
        "**/compare/latest?**",
        lambda r: r.fulfill(body=json.dumps(payload), content_type="application/json"),
    )
    page.route(
        "**/history/month?**",
        lambda r: r.fulfill(body='{"days":{}}', content_type="application/json"),
    )
    enter(page)
    assert page.evaluate("PLOTSRV.state.compareCapture.revision") == 7
    assert not page.evaluate("PLOTSRV.state.snapshotNavigation.error")
    selector = "#plot" if kind == "plot" else "#artifact-root"
    page.evaluate(
        "selector=>{window.capturedNode=document.querySelector(selector);window.capturedChild=capturedNode.firstChild;}",
        selector,
    )
    if kind == "html":
        page.frame_locator("#artifact-root iframe").get_by_label("Note").fill(
            "Unchanged on collapse"
        )
    before = list(reads)
    page.click("#bottom-collapse")
    page.click("#bottom-restore")
    assert page.evaluate(
        "selector=>capturedNode===document.querySelector(selector) && capturedNode.firstChild===capturedChild",
        selector,
    )
    assert reads == before
    if kind == "html":
        assert (
            page.frame_locator("#artifact-root iframe")
            .get_by_label("Note")
            .input_value()
            == "Unchanged on collapse"
        )


def test_failed_capture_releases_busy_state_for_historical_navigation(page):
    mount(page)
    enter(page)
    page.route(
        "**/compare/latest?**",
        lambda r: r.fulfill(
            status=413,
            body='{"detail":"Inspection too large"}',
            content_type="application/json",
        ),
    )
    page.click("#compare-latest")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert not page.evaluate("PLOTSRV.state.snapshotNavigation.loading")
    assert page.locator("#compare-older").is_enabled()
    page.click("#compare-older")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "s124"
    assert page.locator("#export-button").is_enabled()


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
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 1


def test_new_source_revision_is_announced_and_recapture_acknowledges_only_that_server(
    page,
):
    mount(page)
    enter(page)
    page.evaluate(
        "PLOTSRV.core.receiveBrowserUpdate({view_id:'tables:main',revision:100,render_revision:2,server_instance_id:'testserver',change_type:'ordinary'})"
    )
    assert "New data available" in page.locator("#header-status").inner_text()
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 1
    page.click("#compare-latest")
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 2
    assert page.evaluate("PLOTSRV.state.pendingBrowserUpdate") is None
    page.evaluate(
        "PLOTSRV.core.receiveBrowserUpdate({view_id:'tables:main',revision:1,render_revision:1,server_instance_id:'newserver',change_type:'ordinary'})"
    )
    assert "New data available" in page.locator("#header-status").inner_text()
    page.click("#expand-view")
    assert page.evaluate("PLOTSRV.state.expandedView.active")
    assert not page.evaluate("PLOTSRV.state.compareActive")
    assert page.evaluate("PLOTSRV.state.compareCapture.revision") == 2


@pytest.mark.parametrize("action", ["exit", "pagehide", "bfcache"])
def test_inflight_latest_exit_and_page_lifecycle_keep_coherent_body(page, action):
    mount(page)
    enter(page)
    page.evaluate("""() => {
      const real=window.fetch;
      window.delayedCapture={...PLOTSRV.state.compareCapture, revision:2,
        table:{...PLOTSRV.state.compareCapture.table,rows:[{group:'A',value:2}]}};
      window.fetch=(url,options)=>String(url).includes('/compare/latest?')
        ? new Promise(resolve=>{window.finishCapture=resolve; window.captureSignal=options.signal;}) : real(url,options);
      PLOTSRV.core.snapshotNavigation.select(null);
    }""")
    if action == "exit":
        page.click("#compare-exit")
    else:
        page.evaluate(
            "persisted=>window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted}))",
            action == "bfcache",
        )
        assert page.evaluate("captureSignal.aborted")
    page.evaluate(
        "() => {finishCapture(new Response(JSON.stringify(delayedCapture),{status:200}));}"
    )
    page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
    assert page.evaluate("PLOTSRV.state.compareCandidate") is None
    if action == "exit":
        assert not page.evaluate("PLOTSRV.state.compareActive")
        assert page.evaluate("PLOTSRV.state.compareCapture.revision") == 2
        assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 2
        assert not page.evaluate("PLOTSRV.core.canApplyPendingUpdate({force:true})")
    else:
        assert page.evaluate("PLOTSRV.state.tableRows[0].value") == 1
        if action == "bfcache":
            assert page.evaluate("PLOTSRV.state.compareCapture.revision") == 1
            page.evaluate(
                "window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))"
            )
        else:
            assert page.evaluate("PLOTSRV.state.compareCapture") is None
