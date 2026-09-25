"""Real Tabulator regression for bounded evolving stream schemas."""
import pytest

from tests.test_plot_controls_browser import page, STATIC


def mount_stream(page):
    page.click("#table-mode-table-btn")
    page.add_script_tag(path=str(STATIC / "js/renderers/stream.js"))
    page.evaluate("""() => {
      PLOTSRV.state.tabulatorInstance.destroy();
      document.querySelector('#table-grid').id = 'stream-grid';
      PLOTSRV.state.tableFields = [];
      PLOTSRV.config.kind = 'stream';
      PLOTSRV.state.streamHistoryCatalogViewId = PLOTSRV.config.activeViewId;
      window.revision = 0;
      window.fetch = async url => {
        if(url.includes('/stream/history?')) return {ok:true,json:async () => ({sessions:[],capability:{enabled:true}})};
        if(!url.includes('/stream/data?')) throw Error('Unexpected route: '+url);
        return {ok:true, json:async () => {
        const n = ++revision;
        return {columns:['stable','hidden','key'+n],
          records:[{browser_sequence:n,data:{stable:42,hidden:7,['key'+n]:n}}],
          session_id:window.fixtureSession || 'session', historical:!!window.fixtureHistorical,
          raw_window:{first_browser_sequence:n,
            last_browser_sequence:n,record_count:1,max_record_count:1}};
        }};
      };
      return PLOTSRV.core.loadStream();
    }""")
    page.wait_for_function("PLOTSRV.state.streamTabulatorInstance.initialized")


def test_stream_schema_discards_expired_columns_and_preserves_survivors(page):
    mount_stream(page)
    page.evaluate("""() => {
      const table = PLOTSRV.state.streamTabulatorInstance;
      table.getColumn('stable').setWidth(180);
      table.moveColumn('hidden', 'stable', false);
      table.hideColumn('hidden');
      PLOTSRV.state.tableUiState.hiddenColumns = ['hidden'];
      window.stableColumn = table.getColumn('stable');
      PLOTSRV.core.setTableGrouping('key1');
    }""")
    result = page.evaluate("""async () => {
      for(let n=0;n<250;n++) {
        await PLOTSRV.core.loadStream();
        if(PLOTSRV.state.streamTabulatorInstance.getColumns().length !== 3)
          throw Error('unbounded column accumulation');
      }
      const table = PLOTSRV.state.streamTabulatorInstance;
      return {fields:PLOTSRV.state.tableFields,
        columns:table.getColumns().map(c => c.getField()), rows:table.getData(),
        width:table.getColumn('stable').getWidth(), hidden:!table.getColumn('hidden').isVisible(),
        sameColumn:table.getColumn('stable') === stableColumn};
    }""")
    assert result["fields"] == ["stable", "hidden", "key251"]
    assert set(result["columns"]) == set(result["fields"])
    assert result["columns"][:2] == ["hidden", "stable"]
    assert len(result["rows"]) == 1
    assert result["sameColumn"] and result["hidden"]
    assert result["width"] == 180
    assert page.locator("#table-group-by-select").input_value() == ""
    assert page.locator("#table-group-by-select option").count() == 4


def test_receiver_restart_does_not_pin_current_view_to_restored_fallback(page):
    mount_stream(page)
    page.add_script_tag(path=str(STATIC / "js/core/auto_refresh.js"))
    page.evaluate("""() => {
      Object.assign(PLOTSRV.state, {browserUpdateInstanceId:'old',browserUpdateGeneration:0,
        observedUpdateRevision:10000,appliedUpdateRevision:10000,initialViewLoadComplete:true});
      PLOTSRV.core.reloadCurrentView = PLOTSRV.core.loadStream;
      window.fixtureHistorical = true;
      PLOTSRV.core.receiveBrowserUpdate({server_instance_id:'new',revision:0,
        view_id:PLOTSRV.config.activeViewId,change_type:'reconnect'});
    }""")
    page.wait_for_function("PLOTSRV.state.appliedUpdateRevision === 0 && !PLOTSRV.state.browserUpdateApplying")
    assert page.evaluate("PLOTSRV.state.streamHistoricalSessionId == null")
    page.evaluate("""() => {
      window.fixtureHistorical = false;
      window.fixtureSession = 'new-session';
      PLOTSRV.core.receiveBrowserUpdate({server_instance_id:'new',revision:1,
        view_id:PLOTSRV.config.activeViewId,change_type:'stream'});
    }""")
    page.wait_for_function("PLOTSRV.state.streamSessionId === 'new-session'")
    assert page.evaluate("PLOTSRV.state.streamPauseAvailable")
    assert page.evaluate("PLOTSRV.state.streamHistoricalSessionId == null")
    assert page.evaluate("PLOTSRV.state.streamTabulatorInstance.getData()[0].key3") == 3


@pytest.mark.parametrize("stored_run_fails", [False, True])
def test_returning_from_sparse_or_unavailable_run_restores_column_widths(page, stored_run_fails):
    mount_stream(page)
    page.evaluate("""async fails => {
      document.body.insertAdjacentHTML('beforeend',
        '<div id="stream-history-picker"><select id="stream-history-session-select"></select>' +
        '<span id="stream-history-picker-status"></span></div>');
      window.fetch = async url => {
        if (url.includes('/stream/history?') && !url.includes('session_id='))
          return {ok:true,json:async () => ({sessions:[{session_id:'old',available:true}],
            capability:{enabled:true}})};
        if (url.includes('session_id=old')) {
          if (fails) return {ok:false,status:404};
          return {ok:true,json:async () => ({data:{columns:['level'],records:[],
            session_id:'old',historical:true}})};
        }
        if (!url.includes('/stream/data?')) throw Error('Unexpected route: ' + url);
        return {ok:true,json:async () => ({columns:['timestamp','level','message'],
          records:[{browser_sequence:1,data:{timestamp:'2026-09-25T12:00:00Z',
            level:'INFO',message:'A stream record'}}],
          session_id:'current',historical:false})};
      };
      await PLOTSRV.core.loadStream();
      await PLOTSRV.core.loadStreamHistoryCatalogue({historical:false});
      if (fails) PLOTSRV.state.streamTabulatorInstance.getColumn('level').setWidth(1200);
    }""", stored_run_fails)
    page.select_option("#stream-history-session-select", "old")
    page.wait_for_function(
        "PLOTSRV.state.streamHistoricalSessionId === null && "
        "!document.querySelector('#stream-history-session-select').disabled && "
        "PLOTSRV.state.streamSessionId === 'current'"
        if stored_run_fails else "PLOTSRV.state.streamSessionId === 'old'"
    )
    if not stored_run_fails:
        assert page.evaluate(
            "PLOTSRV.state.streamTabulatorInstance.getColumn('level').getWidth()"
        ) > 1000
        page.select_option("#stream-history-session-select", "")
        page.wait_for_function("PLOTSRV.state.streamSessionId === 'current'")
    result = page.evaluate("""() => {
      const table = PLOTSRV.state.streamTabulatorInstance;
      return {width:table.getColumn('level').getWidth(),
        fields:table.getColumns().map(column => column.getField()),
        visible:table.getColumns().filter(column => column.isVisible()).length,
        rows:table.getData()};
    }""")
    assert result["width"] < 400, result
    assert set(result["fields"]) == {"timestamp", "level", "message"}
    assert result["visible"] == 3
    assert len(result["rows"]) == 1
