"""Functional browser-local check attention against real engine evidence and modal markup."""

import json

from plotsrv import html as html_mod
from plotsrv.checks import CheckEngine
from plotsrv.checks_config import parse_checks
from tests.test_plot_controls_browser import page, STATIC


def evidence():
    rules = parse_checks(
        {
            "rules": [
                dict(
                    id="rows",
                    name="Row count within expected range",
                    source="test:layout",
                    kind="state",
                    path=["rows"],
                    op="gt",
                    value=10000,
                    severity="critical",
                )
            ]
        }
    )
    engine = CheckEngine(rules, generation="generation-one")
    for revision, value in enumerate((9000, 12481)):
        engine.submit(
            "test:layout",
            "state",
            [
                (
                    {"rows": value},
                    {
                        "source_revision": revision,
                        "received_at": "2026-09-09T03:10:13+00:00",
                    },
                )
            ],
        )
        assert engine.flush(1)
    result = engine.snapshot("test:layout")
    engine.close()
    assert result["states"][0]["state"] == "triggered"
    return result


def mount(page, data=None):
    data = evidence() if data is None else data
    markup = html_mod.render_index(
        kind="table",
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )
    page.evaluate("PLOTSRV.core.disposeEmbeddedTableExplorer()")
    page.evaluate(
        """markup => {
      const doc = new DOMParser().parseFromString(markup, 'text/html');
      document.body.innerHTML = doc.getElementById('header-status').outerHTML + doc.getElementById('status-modal-backdrop').outerHTML;
    }""",
        markup,
    )
    for name in (
        "core/state",
        "core/storage",
        "core/status",
        "core/status_modal",
        "core/check_status",
    ):
        page.add_script_tag(path=str(STATIC / ("js/" + name + ".js")))
    page.evaluate(
        """data => {
      PLOTSRV.config.activeViewId = 'test:layout'; PLOTSRV.config.kind = 'table';
      PLOTSRV.config.showHeaderFreshness = true;
      PLOTSRV.core.bindHeaderStatus(); PLOTSRV.core.bindStatusModal();
      window.checkData = data; window.checkReads = 0;
      window.fetch = async () => {checkReads++; return {ok:true, json:async () => checkData};};
      PLOTSRV.core.setHeaderLatestStatus({checks:data, last_updated:'2026-09-09T03:10:13+00:00', last_data_arrival_at:'2026-09-09T03:10:13+00:00', data_activity:{events:[{received_at:'2026-09-09T03:10:13+00:00'}],limit:256}});
    }""",
        data,
    )
    return data


def opened(page):
    page.click("#header-status-button")
    page.wait_for_function(
        "document.getElementById('status-checks-load').getAttribute('aria-busy') !== 'true'"
    )


def test_read_keeps_failure_keyboard_focus_and_screenshots(page):
    mount(page)
    assert page.locator("#header-check-attention").is_visible()
    page.screenshot(path="/tmp/plotsrv-13-header.png")
    page.set_viewport_size({"width": 1100, "height": 1400})
    page.locator("#header-status-button").focus()
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.getElementById('status-checks-load').getAttribute('aria-busy') !== 'true'"
    )
    assert page.locator("#header-check-attention").is_hidden()
    assert "1 active failure" in page.locator("#status-checks-summary").inner_text()
    assert (
        "Critical · Active failure"
        in page.locator("#status-checks-current").inner_text()
    )
    assert "Observed: 12481" in page.locator("#status-checks-current").inner_text()
    assert page.locator("#status-modal-activity-dots").is_visible()
    assert page.locator(".ps-arrival-chart__dot").count() == 1
    page.screenshot(path="/tmp/plotsrv-13-modal.png", full_page=True)
    page.keyboard.press("Escape")
    assert page.locator("#header-status-button").evaluate(
        "e => e === document.activeElement"
    )
    assert page.evaluate("checkReads") == 1
    assert "12481" not in page.evaluate("JSON.stringify(localStorage)")


def test_event_during_read_is_not_seen_and_recovery_explicit(page):
    data = mount(page)
    page.evaluate("""() => {
      window.fetch = () => { checkReads++; return new Promise(resolve => window.finishRead = () => resolve({ok:true,json:async()=>checkData})); };
    }""")
    page.click("#header-status-button")
    newer = json.loads(json.dumps(data))
    newer["cursor"] = 2
    newer["states"][0].update(state="ok", last_event_cursor=2, observed_value=9000)
    newer["events"] = [
        dict(
            data["events"][0],
            cursor=2,
            event_id="generation-one:2",
            event_type="recovered",
            state="ok",
            observed_value=9000,
        )
    ]
    page.evaluate("data => PLOTSRV.core.receiveCheckStatus(data)", newer)
    page.evaluate("finishRead()")
    page.wait_for_function(
        "document.getElementById('status-checks-load').getAttribute('aria-busy') !== 'true'"
    )
    assert page.locator("#header-check-attention").is_visible()
    assert page.get_by_role(
        "button", name="Show updated checks and activity"
    ).is_visible()
    page.evaluate(
        """data => { checkData=data; window.fetch=async()=>({ok:true,json:async()=>checkData}); }""",
        newer,
    )
    page.click("#status-checks-load")
    assert page.locator("#header-check-attention").is_hidden()
    assert "Recovered" in page.locator("#status-checks-events").inner_text()
    assert "0 active failures" in page.locator("#status-checks-summary").inner_text()


def test_restart_profiles_private_storage_and_snapshot(page):
    data = mount(page)
    opened(page)
    page.keyboard.press("Escape")
    page.evaluate("""() => {
      PLOTSRV.state.currentSnapshot = 'old';
      checkData.generation='generation-two';
      checkData.events.forEach(e => {e.generation='generation-two';e.event_id='generation-two:1';});
      PLOTSRV.core.receiveCheckStatus(checkData);
      Storage.prototype.setItem = () => {throw Error('private');};
    }""")
    assert page.locator("#header-check-attention").is_visible()
    opened(page)
    assert (
        "not this historical snapshot"
        in page.locator("#status-checks-context").inner_text()
    )
    assert (
        "remembered only on this page"
        in page.locator("#status-checks-personal").inner_text()
    )
    assert page.locator("#header-check-attention").is_hidden()
    # A separate browser profile has no acknowledgement.
    second = page.context.browser.new_context()
    other = second.new_page()
    other.route("**/*", lambda route: route.fulfill(body="<html></html>"))
    other.goto("http://plotsrv.test/")
    assert other.evaluate("localStorage.length") == 0
    second.close()


def test_error_gap_no_checks_and_event_only_source(page):
    data = mount(page)
    page.evaluate("window.fetch=async()=>({ok:false})")
    opened(page)
    assert "could not be loaded" in page.locator("#status-checks-summary").inner_text()
    assert page.locator("#header-check-attention").is_visible()
    page.evaluate("""() => {
      checkData.history_gap=true;
      checkData.states[0].kind='event'; checkData.states[0].state='ok';
      checkData.events[0].kind='event'; checkData.events[0].event_type='match'; checkData.events[0].state='ok';
      window.fetch=async()=>({ok:true,json:async()=>checkData});
    }""")
    page.click("#status-checks-load")
    assert "Event match" in page.locator("#status-checks-events").inner_text()
    assert (
        "not a complete activity record"
        in page.locator("#status-checks-events").inner_text()
    )
    assert "0 active failures" in page.locator("#status-checks-summary").inner_text()
    page.evaluate("checkData.states=[];checkData.events=[]")
    page.click("#status-checks-load")
    assert "No checks configured" in page.locator("#status-checks-summary").inner_text()


def test_mobile_and_hostile_text_remain_safe(page):
    data = evidence()
    data["states"][0]["name"] = "<img src=x onerror=alert(1)>"
    mount(page, data)
    page.set_viewport_size({"width": 390, "height": 844})
    opened(page)
    assert page.locator("#status-modal-checks img").count() == 0
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    assert page.locator("#status-modal").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.get_by_text("Technical details", exact=True).first.click()
    assert "check_id" in page.locator("#status-checks-current pre").inner_text()


def test_closed_read_restart_race_and_request_coalescing(page):
    mount(page)
    page.evaluate("""() => {
      window.fetch=(_, options)=>{checkReads++;window.readSignal=options.signal;return new Promise(resolve=>window.finishRead=()=>resolve({ok:true,json:async()=>checkData}));};
    }""")
    page.click("#header-status-button")
    page.evaluate(
        """() => {for(let i=0;i<1000;i++) {PLOTSRV.core.receiveCheckStatus(checkData);document.getElementById('status-checks-load').onclick();}}"""
    )
    assert page.evaluate("checkReads") == 1
    page.keyboard.press("Escape")
    assert page.evaluate("readSignal.aborted")
    page.evaluate("finishRead()")
    assert page.locator("#header-check-attention").is_visible()
    page.click("#header-status-button")
    page.evaluate("""() => {
      PLOTSRV.core.receiveCheckStatus({...checkData,generation:'restarted'});
      finishRead();
    }""")
    page.wait_for_function(
        "document.getElementById('status-checks-load').getAttribute('aria-busy') !== 'true'"
    )
    assert "could not be loaded" in page.locator("#status-checks-summary").inner_text()
    assert (
        page.evaluate(
            "Object.keys(localStorage).filter(k=>k.startsWith('plotsrv:v1:check_seen:')).length"
        )
        == 0
    )


def test_unavailable_disabled_and_evicted_unread_activity(page):
    data = evidence()
    data.update(events=[], history_gap=True)
    data["states"][0].update(state="unknown", reason="awaiting_live_data")
    mount(page, data)
    opened(page)
    assert (
        "Waiting for eligible live data"
        in page.locator("#status-checks-current").inner_text()
    )
    # Never claim that lost events were actually presented/read.
    assert page.locator("#header-check-attention").is_visible()
    page.evaluate("checkData.states[0].state='disabled'")
    page.click("#status-checks-load")
    assert "Checks are disabled" in page.locator("#status-checks-summary").inner_text()
    assert page.locator("#header-check-attention").is_visible()


def test_seen_scope_and_new_severity_event(page):
    mount(page)
    opened(page)
    page.keyboard.press("Escape")
    page.evaluate("""() => {
      checkData.cursor=2;checkData.states[0].last_event_cursor=2;
      checkData.states[0].severity='warning';checkData.events[0].cursor=2;checkData.events[0].severity='warning';
      PLOTSRV.core.receiveCheckStatus(checkData);
    }""")
    assert page.locator("#header-check-attention").is_visible()
    opened(page)
    assert "Warning · Triggered" in page.locator("#status-checks-events").inner_text()
    page.keyboard.press("Escape")
    page.evaluate(
        "PLOTSRV.config.dashboardName='another dashboard';PLOTSRV.core.renderCheckAttention()"
    )
    assert page.locator("#header-check-attention").is_visible()
    page.evaluate(
        "PLOTSRV.config.dashboardName='default';PLOTSRV.core.renderCheckAttention()"
    )
    assert page.locator("#header-check-attention").is_hidden()


def test_sse_reconnect_refreshes_checks_in_history_without_fetching_history(page):
    mount(page)
    page.add_script_tag(path=str(STATIC / "js/core/auto_refresh.js"))
    page.evaluate("""() => {
      PLOTSRV.state.currentSnapshot='pinned';
      PLOTSRV.state.observedUpdateRevision=20;
      window.statusReads=0;
      PLOTSRV.core.refreshStatus=async()=>{statusReads++;PLOTSRV.core.receiveCheckStatus(checkData);};
      PLOTSRV.core.receiveBrowserUpdate({revision:20,view_id:'test:layout',change_type:'reconnect'});
    }""")
    page.wait_for_function("statusReads === 1")
    assert page.evaluate("checkReads") == 0
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "pinned"
    assert page.locator("#header-check-attention").is_visible()


def test_bounded_history_render_and_idle_cost(page):
    data = evidence()
    base = data["events"][0]
    data["events"] = [
        dict(base, cursor=i, event_id=f"generation-one:{i}") for i in range(1, 257)
    ]
    data["cursor"] = 256
    data["states"][0]["last_event_cursor"] = 256
    mount(page, data)
    opened(page)
    assert page.locator("#status-checks-events article").count() == 256
    assert page.evaluate("checkReads") == 1
    measurements = page.evaluate("""() => {
      const start=performance.now();
      for(let i=0;i<1000;i++) PLOTSRV.core.receiveCheckStatus(checkData);
      return {noticeMs:performance.now()-start, seenBytes:Object.keys(localStorage).filter(k=>k.startsWith('plotsrv:v1:check_seen:')).reduce((n,k)=>n+localStorage.getItem(k).length,0), cards:document.querySelectorAll('.ps-check-card').length};
    }""")
    print("check UI bounded history:", measurements)
    assert measurements["seenBytes"] < 1024
    assert measurements["cards"] == 257
    assert page.evaluate("checkReads") == 1
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.evaluate("checkReads") == 1
    assert page.locator(".ps-check-card").count() == 0


def test_saved_attention_survives_reload_and_denied_storage_reads(page):
    data = mount(page)
    opened(page)
    page.keyboard.press("Escape")
    page.add_script_tag(path=str(STATIC / "js/core/check_status.js"))
    page.evaluate("data => PLOTSRV.core.receiveCheckStatus(data)", data)
    assert page.locator("#header-check-attention").is_hidden()
    page.evaluate("() => {Storage.prototype.getItem = () => {throw Error('denied');};}")
    page.add_script_tag(path=str(STATIC / "js/core/check_status.js"))
    page.evaluate("data => PLOTSRV.core.receiveCheckStatus(data)", data)
    assert page.locator("#header-check-attention").is_visible()
    opened(page)
    assert (
        "remembered only on this page"
        in page.locator("#status-checks-personal").inner_text()
    )
    assert page.locator("#header-check-attention").is_hidden()


def test_dark_theme_marker_contrast_and_closed_details_keyboard(page):
    mount(page)
    page.evaluate("document.documentElement.dataset.theme='dark'")
    colours = page.locator("#header-check-attention").evaluate(
        "e => {const s=getComputedStyle(e);return [s.color,s.backgroundColor];}"
    )
    assert colours[0] != colours[1]
    opened(page)
    first = page.locator("#status-checks-current summary").first
    first.focus()
    page.keyboard.press("Enter")
    assert page.locator("#status-checks-current details").first.evaluate("e=>e.open")
    page.screenshot(path="/tmp/plotsrv-13-modal-dark.png", full_page=True)
    page.keyboard.press("Escape")
    assert page.locator("#header-status-button").evaluate(
        "e=>e===document.activeElement"
    )


def test_keyboard_refresh_retains_focus_and_escape_during_request(page):
    mount(page)
    opened(page)
    page.evaluate(
        "() => {window.fetch=(_,options)=>{window.readSignal=options.signal;return new Promise(()=>{});};}"
    )
    button = page.locator("#status-checks-load")
    button.focus()
    page.keyboard.press("Enter")
    assert button.get_attribute("aria-busy") == "true"
    assert button.evaluate("e=>e===document.activeElement")
    page.keyboard.press("Escape")
    assert page.evaluate("readSignal.aborted")
    assert page.locator("#header-status-button").evaluate(
        "e=>e===document.activeElement"
    )


def test_notification_diagnostics_do_not_create_unseen_check_activity(page):
    data = mount(page)
    opened(page)
    assert page.locator("#header-check-attention").is_hidden()
    updated = json.loads(json.dumps(data))
    updated["states"][0]["notifications"] = [
        dict(
            destination="ops",
            state="paused",
            last_status=401,
            last_failure="http_permanent",
            suppressed=3,
            dropped=1,
        )
    ]
    page.evaluate(
        "data => {checkData=data;PLOTSRV.core.receiveCheckStatus(data);}", updated
    )
    assert page.locator("#header-check-attention").is_hidden()
    page.click("#status-checks-load")
    page.locator("#status-checks-current summary").click()
    assert "http_permanent" in page.locator("#status-checks-current pre").inner_text()
    assert page.locator("#status-checks-events article").count() == 1
    assert page.locator("#header-check-attention").is_hidden()


def test_arrival_axis_adapts_to_range_and_screen_width(page):
    mount(page)
    opened(page)
    page.set_viewport_size({"width": 1200, "height": 1000})
    page.select_option("#status-modal-range", "86400")
    ticks = page.locator(".ps-arrival-chart__tick")
    assert 3 <= ticks.count() <= 12
    desktop_count = ticks.count()
    day_labels = ticks.all_text_contents()
    page.select_option("#status-modal-range", "900")
    assert ticks.count() >= 2
    assert ticks.all_text_contents() != day_labels
    page.select_option("#status-modal-range", "604800")
    assert ticks.count() >= 2
    page.select_option("#status-modal-range", "86400")
    reads = page.evaluate("checkReads")
    page.set_viewport_size({"width": 375, "height": 800})
    page.wait_for_function(
        "count => document.querySelectorAll('.ps-arrival-chart__tick').length < count",
        arg=desktop_count,
    )
    assert ticks.count() >= 1
    boxes = page.locator(".ps-arrival-chart__axis > span").evaluate_all(
        "els => els.map(el => {const r=el.getBoundingClientRect(); return {left:r.left,right:r.right};}).sort((a,b)=>a.left-b.left)"
    )
    assert all(a["right"] <= b["left"] for a, b in zip(boxes, boxes[1:]))
    assert page.evaluate("checkReads") == reads
    page.evaluate("PLOTSRV.core.closeStatusModal()")
    labels = ticks.all_text_contents()
    page.set_viewport_size({"width": 1200, "height": 1000})
    assert ticks.all_text_contents() == labels


def test_restored_status_moves_to_header_and_clears_on_live_update(page):
    mount(page)
    page.evaluate("""() => {
      const header = document.createElement("header"); header.id = "site-header"; document.body.prepend(header);
      PLOTSRV.core.setHeaderLatestStatus({restored_from_storage:true,
        restored_at:'2026-09-14T10:20:50Z', freshness:{enabled:false}});
    }""")
    assert page.locator("#header-status-label").inner_text() == "Restored"
    assert page.locator("#site-header").get_attribute("data-status-accent") == "history"
    assert page.locator("#header-status").get_attribute("data-status-tone") == "restored"
    opened(page)
    assert page.locator("#status-modal-viewing").inner_text() == "Restored data"
    assert "Restored at" in page.locator("#status-modal-viewing-detail").inner_text()
    page.evaluate("PLOTSRV.core.setHeaderViewState('snapshot', {createdAt:'2026-09-13T12:00:00Z'})")
    assert page.locator("#header-status").get_attribute("data-status-tone") == "history"
    page.evaluate("""() => {
      PLOTSRV.core.setHeaderViewState('latest');
      PLOTSRV.core.setHeaderLatestStatus({restored_from_storage:false, freshness:{enabled:false}});
    }""")
    assert page.locator("#header-status-label").inner_text() != "Restored"
    assert page.locator("#site-header").get_attribute("data-status-accent") is None
