"""Default recent-first ordering uses event time without changing server cursors."""
import pytest

from tests.test_plot_controls_browser import page
from tests.test_stream_schema_browser import mount_stream


def load(page, rows, fields, *, reset=False, first=1):
    page.evaluate("""async ({rows,fields,reset,first}) => {
      window.fetch = async url => {
        if (url.includes('/stream/history?')) return {ok:true,json:async()=>({sessions:[]})};
        return {ok:true,json:async()=>({columns:fields, session_id:'session',
          reset_required:reset, records:rows.map(([sequence,data])=>({browser_sequence:sequence,data})),
          raw_window:{first_browser_sequence:first,last_browser_sequence:Math.max(...rows.map(r=>r[0]),0)}})};
      };
      await PLOTSRV.core.loadStream();
    }""", dict(rows=rows, fields=fields, reset=reset, first=first))


def ids(page):
    return page.evaluate("PLOTSRV.state.streamTabulatorInstance.getData('active').map(r=>r.id)")


def test_event_time_ties_invalid_values_and_manual_sort_survive_updates(page):
    mount_stream(page)
    load(page, [[1, dict(id='a', timestamp='2026-09-25T12:00:00Z')],
                [2, dict(id='b', timestamp='2026-09-25T11:00:00Z')],
                [3, dict(id='bad', timestamp='unknown')],
                [4, dict(id='tie', timestamp='2026-09-25T13:00:00+01:00')]],
         ['id', 'timestamp'], reset=True)
    assert ids(page) == ['tie', 'a', 'b', 'bad']
    load(page, [[5, dict(id='late', timestamp='2026-09-25T10:00:00Z')]], ['id', 'timestamp'])
    assert ids(page) == ['tie', 'a', 'b', 'late', 'bad']
    load(page, [[6, dict(id='new', timestamp='2026-09-25T14:00:00Z')],
                [7, dict(id='newer', timestamp='2026-09-25T15:00:00Z')]], ['id', 'timestamp'])
    assert ids(page) == ['newer', 'new', 'tie', 'a', 'b', 'late', 'bad']
    assert page.evaluate('PLOTSRV.state.streamCursor') == 7
    page.evaluate("PLOTSRV.state.streamTabulatorInstance.setSort('id','asc')")
    load(page, [[8, dict(id='c', timestamp='2026-09-25T16:00:00Z', extra=1)]], ['id','timestamp','extra'])
    assert ids(page) == sorted(['a','b','bad','tie','late','new','newer','c'])
    assert page.evaluate("PLOTSRV.state.streamTabulatorInstance.getSorters().map(s=>[s.field,s.dir])") == [['id','asc']]


@pytest.mark.parametrize('first_values,expected', [
    (['2026-09-25T15:00:00Z', '2026-09-25T13:00:00Z'], ['a', 'b']),
    ([2026, 2025], ['b', 'a']),
    (['10/05/2026', '09/05/2026'], ['b', 'a']),
    (['001', '002'], ['b', 'a']),
])
def test_unambiguous_first_column_or_arrival_fallback(page, first_values, expected):
    mount_stream(page)
    load(page, [[1,dict(when=first_values[0],id='a')], [2,dict(when=first_values[1],id='b')]],
         ['when','id'], reset=True)
    assert ids(page) == expected


def test_default_arrival_order_and_scroll_survive_incremental_update(page):
    mount_stream(page)
    load(page, [[i,dict(id=str(i),message='record '+str(i))] for i in range(1,100)], ['id','message'], reset=True)
    assert ids(page)[0] == '99'
    page.evaluate("document.querySelector('#stream-grid .tabulator-tableholder').scrollTop = 500")
    before = page.locator('#stream-grid .tabulator-tableholder').evaluate('e=>e.scrollTop')
    load(page, [[100,dict(id='100',message='record 100')]], ['id','message'])
    assert ids(page)[0] == '100'
    assert page.locator('#stream-grid .tabulator-tableholder').evaluate('e=>e.scrollTop') == pytest.approx(before, abs=2)
