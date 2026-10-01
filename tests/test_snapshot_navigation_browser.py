"""Real shared controller/renderers: selection, bounded pages and late responses."""

from plotsrv import html as html_mod
from tests.test_plot_controls_browser import page, STATIC


def mount(page, kind="artifact"):
    page.set_default_timeout(5000)
    markup = html_mod.render_index(
        kind="artifact",
        table_view_mode="rich",
        table_html_simple=None,
        max_table_rows_simple=200,
        max_table_rows_rich=1000,
    )
    page.evaluate("PLOTSRV.core.disposeEmbeddedTableExplorer()")
    page.evaluate(
        """markup => {
      const doc = new DOMParser().parseFromString(markup, 'text/html');
      document.body.innerHTML = '<main id="view-content"><div id="artifact-root">Coherent initial content</div></main>' +
        doc.querySelector('.ps-bottom-dock').outerHTML;
      PLOTSRV.state.currentSnapshot = null;
      PLOTSRV.config.kind = 'text';
      PLOTSRV.config.activeViewId = 'test:layout';
      window.bodyReads = []; window.metaReads = []; window.releases = {}; window.held = [];
      window.count = 81; window.marked = 0; window.failures = {}; window.ignoreAbort = false;
      window.makeMeta = url => {
        const selected = url.searchParams.get('selected');
        const rows = Array.from({length:count}, (_,i) => ({snapshot_id:String(count-i),
          created_at:'2026-09-09T12:00:00.000Z', kind:'text', is_latest:i===0}));
        const index = rows.findIndex(x=>x.snapshot_id===selected);
        const before = Number(url.searchParams.get('before') || 0);
        return {capability:{enabled:true}, snapshots:rows.slice(before,before+50),
          next_cursor:before+50<count ? String(before+50) : null,
          selected:rows[index] || null,
          older: selected ? rows[index+1] || null : rows[0] || null,
          newer: selected && index>0 ? rows[index-1] : null};
      };
      window.fetch = (value, options={}) => {
        const url = new URL(value, location.href);
        if (url.pathname === '/history/navigation') {
          metaReads.push(url.href);
          const data = makeMeta(url);
          if (window.holdMetadata) return new Promise(resolve => window.releaseMetadata = () => resolve({ok:true,json:async()=>data}));
          return Promise.resolve({ok:true, json:async()=>data});
        }
        const id = url.searchParams.get('snapshot') || 'latest';
        bodyReads.push(id);
        const response = () => ({ok:!failures[id], status:failures[id] || 200,
          json:async()=>({kind:'text', html:'<p>Version '+id+'</p>', columns:['value'], rows:[{value:id}]}),
          blob:async()=>{const blob = new Blob(['image']); blob.testId=id; return blob;}});
        if (held.includes(id)) return new Promise((resolve,reject)=>{
          releases[id]=()=>resolve(response());
          if (!ignoreAbort && options.signal) options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')), {once:true});
        });
        return Promise.resolve(response());
      };
      PLOTSRV.core.refreshStatus = () => Promise.resolve();
      PLOTSRV.core.markBrowserViewApplied = () => { marked++; };
      PLOTSRV.renderers.initArtifactEnhancements = () => {};
    }""",
        markup,
    )
    for name in (
        "core/history",
        "renderers/artifact",
        "renderers/plot",
        "core/bottom_bar",
        "core/app",
    ):
        page.add_script_tag(path=str(STATIC / ("js/" + name + ".js")))
    if kind == "plot":
        page.evaluate("""() => {
          document.getElementById('artifact-root').outerHTML='<img id="plot">';
          PLOTSRV.config.kind='plot';
          window.blobs=[];
          const create=URL.createObjectURL.bind(URL);
          URL.createObjectURL=blob=>{blobs.push(blob.testId);return create(blob);};
        }""")
    elif kind == "table":
        page.evaluate("""() => {
          document.getElementById('artifact-root').outerHTML='<div id="table-grid"></div>';
          PLOTSRV.config.kind='table';
        }""")
    page.evaluate(
        "async () => {PLOTSRV.core.bindHistoryControls(); await PLOTSRV.core.loadHistory();}"
    )


def settled(page):
    page.wait_for_function(
        "!PLOTSRV.state.snapshotNavigation.pending && !PLOTSRV.state.snapshotNavigation.loading"
    )


def test_keyboard_boundaries_exact_and_ambiguous_latest(page):
    mount(page)
    page.evaluate("async () => {count=1; await PLOTSRV.core.loadHistory();}")
    assert page.locator("#snapshot-newer").is_disabled()
    assert page.locator("#snapshot-older").is_enabled()
    page.locator("#snapshot-older").focus()
    page.keyboard.press("Enter")
    settled(page)
    assert page.locator("#artifact-root").inner_text() == "Version 1"
    assert page.locator("#snapshot-older").is_disabled()
    assert page.locator("#snapshot-newer").is_enabled()
    selected = page.locator("#history-select option:checked")
    assert "2026" in selected.inner_text()
    assert "T12:00" not in selected.inner_text()
    assert "UTC" in selected.get_attribute("title")
    assert "snapshot=1" in page.url
    assert page.evaluate("marked") == 0
    assert page.locator("#snapshots-return-latest").count() == 0
    page.locator("#snapshot-newer").focus()
    page.keyboard.press("Space")
    settled(page)
    assert page.locator("#artifact-root").inner_text() == "Version latest"
    assert "snapshot=" not in page.url
    assert page.evaluate("bodyReads") == ["1", "latest"]
    assert page.locator("#snapshots-return-latest").count() == 0
    # Hide the duplicate stored latest until it is explicitly selected.
    page.evaluate("""async () => {
      const original=makeMeta;
      makeMeta=url=>{const data=original(url); data.snapshots[0].is_live_equivalent=true; return data;};
      await PLOTSRV.core.loadHistory();
    }""")
    assert page.locator("#history-select option").count() == 1
    assert "Live (latest)" in page.locator("#history-select").inner_text()
    page.click("#snapshot-older")
    settled(page)
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "1"
    assert "Same revision as Live" in page.locator("#history-select option:checked").inner_text()
    assert page.locator("#snapshot-newer").is_enabled()


def test_bounded_pages_pin_selection_and_never_load_unselected_bodies(page):
    mount(page)
    assert page.evaluate("PLOTSRV.state.historyItems.length") == 50
    assert page.evaluate("bodyReads") == []
    page.select_option("#history-select", "__older_page__")
    page.wait_for_function("PLOTSRV.state.historyItems.length === 31")
    assert page.evaluate("bodyReads") == []
    page.select_option("#history-select", "2")
    settled(page)
    assert page.locator("#history-select").input_value() == "2"
    assert page.evaluate("PLOTSRV.state.historyItems.length") == 50
    assert page.evaluate("PLOTSRV.core.currentHistoryMeta().snapshot_id") == "2"
    assert page.evaluate("bodyReads") == ["2"]
    page.click("#snapshot-older")
    settled(page)
    assert page.evaluate("bodyReads") == ["2", "1"]
    assert page.locator("#snapshot-older").is_disabled()


def test_snapshot_reminder_attaches_to_dock_without_moving_content(page):
    mount(page)
    initial_top = page.locator("#view-content").bounding_box()["y"]
    page.select_option("#history-select", "__older_page__")
    page.wait_for_function("PLOTSRV.state.historyItems.length === 31")
    page.select_option("#history-select", "2")
    settled(page)
    banner = page.locator("#snapshot-mode-banner")
    assert banner.is_visible()
    assert "Historical snapshot" in banner.inner_text()
    assert "2026" in page.locator("#snapshot-mode-banner-time").inner_text()
    assert banner.evaluate("e => e.parentElement.classList.contains('ps-bottom-dock')")
    assert page.locator("#view-content").bounding_box()["y"] == initial_top
    banner_box = banner.bounding_box()
    bar_box = page.locator(".ps-bottom-bar").bounding_box()
    assert abs(banner_box["y"] + banner_box["height"] - bar_box["y"]) < 2
    assert abs(banner_box["x"] - bar_box["x"]) < 2
    assert abs(banner_box["width"] - bar_box["width"]) < 2
    page.click("#snapshot-mode-dismiss")
    assert banner.is_hidden()
    page.select_option("#history-select", "80")
    settled(page)
    assert banner.is_visible()
    page.set_viewport_size({"width": 375, "height": 800})
    banner_box = banner.bounding_box()
    assert banner_box["x"] >= 0
    assert banner_box["x"] + banner_box["width"] <= 375
    page.click("#snapshot-mode-return-latest")
    settled(page)
    assert banner.is_hidden()
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None


def test_latest_wins_coalesces_rapid_selection_and_ignores_late_body(page):
    mount(page)
    page.evaluate(
        "() => {held=['80']; ignoreAbort=true; PLOTSRV.core.snapshotNavigation.select('80');}"
    )
    page.wait_for_function("bodyReads.includes('80')")
    page.evaluate("""() => {
      for (let i=79; i>=2; i--) PLOTSRV.core.snapshotNavigation.select(String(i));
      releases['80']();
    }""")
    settled(page)
    assert page.evaluate("bodyReads") == ["80", "2"]
    assert page.locator("#artifact-root").inner_text() == "Version 2"
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "2"
    assert page.evaluate("PLOTSRV.state.snapshotNavigation.displayed") == "2"
    assert page.evaluate("marked") == 0


def test_failed_selection_preserves_content_and_explicit_recovery(page):
    mount(page)
    page.evaluate("PLOTSRV.core.snapshotNavigation.select('4')")
    settled(page)
    page.evaluate("failures['3']=404; PLOTSRV.core.snapshotNavigation.select('3')")
    settled(page)
    assert page.locator("#artifact-root").inner_text() == "Version 4"
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "3"
    assert "snapshot=3" in page.url
    assert page.locator("#export-button").is_disabled()
    assert (
        "not the selected version"
        in page.locator("#snapshot-navigation-notice").inner_text()
    )
    page.click("#snapshot-newer")
    settled(page)
    assert page.locator("#artifact-root").inner_text() == "Version 4"
    assert page.locator("#export-button").is_enabled()


def test_stale_metadata_and_source_switch_are_ignored(page):
    mount(page)
    page.evaluate("() => {holdMetadata=true; PLOTSRV.core.loadHistory();}")
    page.wait_for_function("typeof releaseMetadata === 'function'")
    page.evaluate("""async () => {
      const release=releaseMetadata; holdMetadata=false; count=1;
      PLOTSRV.config.activeViewId='other'; await PLOTSRV.core.loadHistory(); release();
    }""")
    assert page.evaluate("PLOTSRV.state.historyItems.length") == 1
    page.evaluate(
        "() => {held=['1']; ignoreAbort=true; PLOTSRV.core.snapshotNavigation.select('1');}"
    )
    page.wait_for_function("bodyReads.includes('1')")
    page.evaluate("PLOTSRV.config.activeViewId='third'; releases['1']()")
    settled(page)
    assert page.locator("#artifact-root").inner_text() == "Coherent initial content"


def test_empty_and_unavailable_keep_disabled_selector_and_streams_do_not_fetch(page):
    mount(page)
    page.evaluate("async () => {count=0; await PLOTSRV.core.loadHistory();}")
    assert page.locator("#snapshots-control").get_attribute("data-state") == "empty"
    assert page.locator("#snapshot-older").is_disabled()
    assert page.locator("#history-select").is_disabled()
    page.evaluate("""async () => {
      makeMeta=()=>({snapshots:[], capability:{enabled:false,message:'Storage not admitted'}});
      await PLOTSRV.core.loadHistory();
    }""")
    assert page.locator("#snapshot-older").is_hidden()
    assert page.locator("#snapshots-selector").is_visible()
    page.locator("#snapshots-selector").hover()
    assert page.locator("#history-select").is_disabled()
    assert "browse saved versions" in page.locator("#snapshots-selector").get_attribute(
        "title"
    )
    assert "Storage not admitted" in page.locator("#snapshots-selector").get_attribute(
        "title"
    )
    page.evaluate(
        "PLOTSRV.config.kind='stream'; window.readCount=metaReads.length; PLOTSRV.core.loadHistory()"
    )
    assert page.evaluate("metaReads.length === readCount")


def test_renderer_timeout_releases_selection_and_allows_recovery(page):
    mount(page)
    page.evaluate("""() => {
      const timeout=window.setTimeout.bind(window);
      window.setTimeout=(fn, ms, ...args)=>timeout(fn, ms===10000 ? 30 : ms, ...args);
      held=['3']; PLOTSRV.core.snapshotNavigation.select('3');
    }""")
    settled(page)
    assert page.locator("#export-button").is_disabled()
    assert page.locator("#artifact-root").inner_text() == "Coherent initial content"
    page.evaluate("PLOTSRV.core.snapshotNavigation.select('2')")
    settled(page)
    assert page.locator("#artifact-root").inner_text() == "Version 2"


def test_plot_stale_response_and_latest_share_the_same_fence(page):
    mount(page, "plot")
    page.evaluate(
        "() => {held=['3']; ignoreAbort=true; PLOTSRV.core.snapshotNavigation.select('3');}"
    )
    page.wait_for_function("bodyReads.includes('3')")
    page.evaluate("PLOTSRV.core.returnToLive(); releases['3']()")
    settled(page)
    assert page.evaluate("blobs") == ["latest"]
    assert page.evaluate("PLOTSRV.state.currentSnapshot") is None


def test_table_stale_response_does_not_replace_selected_rows(page):
    mount(page, "table")
    page.evaluate(
        "() => {held=['3']; ignoreAbort=true; PLOTSRV.core.snapshotNavigation.select('3');}"
    )
    page.wait_for_function("bodyReads.includes('3')")
    page.evaluate("PLOTSRV.core.snapshotNavigation.select('2'); releases['3']()")
    settled(page)
    page.wait_for_function("PLOTSRV.state.tabulatorInstance.initialized")
    assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData()") == [
        {"value": "2"}
    ]
    assert page.evaluate("bodyReads") == ["3", "2"]


def test_real_bar_fits_desktop_and_mobile_without_idle_requests(page):
    mount(page)
    select_box = page.locator("#history-select").bounding_box()
    older_box = page.locator("#snapshot-older").bounding_box()
    newer_box = page.locator("#snapshot-newer").bounding_box()
    assert select_box["x"] + select_box["width"] <= older_box["x"]
    assert older_box["x"] + older_box["width"] <= newer_box["x"]
    page.screenshot(path="/tmp/plotsrv-15-desktop.png")
    page.set_viewport_size({"width": 375, "height": 800})
    assert page.locator("#snapshot-older").is_visible()
    bounds = page.locator(".ps-bottom-bar").bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 375
    for selector in (
        "#export-button",
        "#snapshot-older",
        "#history-select",
        "#snapshot-newer",
    ):
        box = page.locator(selector).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    page.screenshot(path="/tmp/plotsrv-15-mobile.png")
    reads = page.evaluate("metaReads.length + bodyReads.length")
    page.wait_for_timeout(150)
    assert page.evaluate("metaReads.length + bodyReads.length") == reads


def test_controller_without_toolbar_and_simple_table_selection(page):
    mount(page)
    page.evaluate("""() => {
      document.querySelector('.ps-bottom-dock').remove();
      document.getElementById('artifact-root').outerHTML='<div id="simple-table-root">Previous table</div>';
      PLOTSRV.config.kind='table'; PLOTSRV.config.tableViewMode='simple';
    }""")
    page.evaluate("PLOTSRV.core.snapshotNavigation.select('2')")
    settled(page)
    assert page.locator("#simple-table-root td").inner_text() == "2"
    assert page.evaluate("bodyReads") == ["2"]
    page.evaluate("failures['1']=404; PLOTSRV.core.snapshotNavigation.select('1')")
    settled(page)
    assert page.locator("#simple-table-root td").inner_text() == "2"
    assert page.evaluate("PLOTSRV.state.currentSnapshot") == "1"


def test_failed_latest_can_be_retried_without_blocking_ordinary_live_updates(page):
    mount(page)
    page.evaluate("failures.latest=503; PLOTSRV.core.returnToLive()")
    settled(page)
    assert page.locator("#snapshots-return-latest").count() == 0
    assert page.locator("#export-button").is_disabled()
    page.evaluate("failures.latest=0")
    page.locator("#history-select").dispatch_event("change")
    settled(page)
    assert page.locator("#export-button").is_enabled()
    page.evaluate(
        "async () => {failures.latest=500; await PLOTSRV.core.loadArtifact();}"
    )
    assert not page.evaluate("PLOTSRV.state.snapshotNavigation.error")


def test_pending_selection_blocks_forced_live_updates_and_failure_has_no_hot_retry(
    page,
):
    mount(page)
    page.add_script_tag(path=str(STATIC / "js/core/auto_refresh.js"))
    page.evaluate("""async () => {
      const {core,state}=PLOTSRV;
      state.snapshotNavigation.pending=true;
      if (core.canApplyPendingUpdate({force:true})) throw Error('Pending selection was bypassed');
      state.snapshotNavigation.pending=false;
      state.initialViewLoadComplete=true;
      state.pendingBrowserUpdate={revision:10};
      state.browserUpdateApplying=false;
      window.reloads=0;
      core.reloadCurrentView=async()=>{reloads++;return false;};
      await core.applyPendingUpdate({force:true});
    }""")
    page.wait_for_timeout(100)
    assert page.evaluate("reloads") == 1
    assert page.evaluate("PLOTSRV.state.pendingBrowserUpdate.revision") == 10


def test_loading_notice_waits_for_slow_selection_and_cleans_up(page):
    mount(page)
    page.evaluate("""() => {
      window.notices = [];
      const notice = document.getElementById('snapshot-navigation-notice');
      new MutationObserver(() => notices.push(notice.textContent)).observe(notice, {childList:true});
      PLOTSRV.core.snapshotNavigation.select('80');
    }""")
    settled(page)
    page.wait_for_timeout(550)
    assert not any("Loading selected" in text for text in page.evaluate("notices"))
    page.evaluate("() => {held=['79']; PLOTSRV.core.snapshotNavigation.select('79');}")
    assert page.locator("#snapshot-navigation-notice").inner_text() == ""
    page.wait_for_function("PLOTSRV.state.snapshotNavigation.loadingVisible")
    assert "Loading selected" in page.locator("#snapshot-navigation-notice").inner_text()
    page.evaluate("releases['79']()")
    settled(page)
    assert page.locator("#snapshot-navigation-notice").inner_text() == ""
    assert not page.evaluate("PLOTSRV.state.snapshotNavigation.loadingVisible")
    page.evaluate("() => {failures['78']=500; PLOTSRV.core.snapshotNavigation.select('78');}")
    settled(page)
    error = page.locator("#snapshot-navigation-notice").inner_text()
    assert error and "Loading selected" not in error
    page.wait_for_timeout(550)
    assert page.locator("#snapshot-navigation-notice").inner_text() == error
