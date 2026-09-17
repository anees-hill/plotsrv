"""Real stream -> shared ViewSpec/table/plot interactions with server projections."""

import pytest
from tests.test_plot_controls_browser import page, STATIC
from tests.test_http_profile import describe, event


def payload(records):
    profile, descriptor = describe(records)
    columns = list(dict.fromkeys(k for r in records for k in r))
    descriptor = profile.describe("test:layout", columns)
    return {
        "columns": columns,
        "http_profile": descriptor,
        "session_id": "session",
        "schema_revision": 1,
        "records": [
            {"browser_sequence": i, "data": r, "http_projection": profile.projection(i)}
            for i, r in enumerate(records, 1)
        ],
        "raw_window": {
            "first_browser_sequence": 1,
            "last_browser_sequence": len(records),
            "record_count": len(records),
            "max_record_count": 512,
        },
    }


def mount(page, records):
    page.click("#table-mode-table-btn")
    for name in (
        "core/storage",
        "core/view_spec",
        "core/my_views",
        "core/http_suggestions",
        "renderers/stream",
    ):
        page.add_script_tag(path=str(STATIC / ("js/" + name + ".js")))
    page.evaluate(
        """data => {
      PLOTSRV.state.tabulatorInstance.destroy();
      document.querySelector('#table-grid').id = 'stream-grid';
      PLOTSRV.state.tableFields = [];
      PLOTSRV.config.kind = 'stream';
      PLOTSRV.state.streamHistoryCatalogViewId = PLOTSRV.config.activeViewId;
      window.responseData = data;
      window.fetch = async url => ({ok:true,json:async () => JSON.parse(JSON.stringify(responseData))});
      return PLOTSRV.core.loadStream();
    }""",
        payload(records),
    )
    page.wait_for_function("PLOTSRV.state.streamTabulatorInstance.initialized")


def test_recipes_keyboard_errors_save_and_customise(page):
    records = [
        event(status=200, duration_ms=5),
        event(status=404, duration_ms=10),
        event(status=503, duration_ms=50),
        {"message": "Traceback: synthetic error"},
    ]
    mount(page, records)
    visible = page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getColumns().filter(c => c.isVisible()).map(c => c.getField())"
    )
    profile_fields = page.evaluate("PLOTSRV.state.httpProfile.fields")
    assert visible == [
        profile_fields["time"], profile_fields["method"],
        profile_fields["path"], profile_fields["status"],
    ]
    interpretation = page.locator(".ps-stream-interpretation")
    assert interpretation.is_visible()
    assert "Detected as" in interpretation.inner_text()
    assert "HTTP access log" in interpretation.inner_text()
    assert page.locator("#http-suggestions-select").input_value() == ""
    assert "✦ Suggested views 8" in page.locator("#http-suggestions-select").inner_text()
    assert (
        page.locator("#http-suggestions-select optgroup").get_attribute("label")
        == "Based on HTTP access log"
    )
    assert page.locator("#http-suggestions-select").get_attribute("title") is None
    assert "is-available" in page.locator("#http-suggestions").get_attribute("class")
    assert page.locator("#http-raw-view").count() == 0
    assert page.locator("#http-suggestions-scope").count() == 0
    assert page.evaluate(
        "Array.from(document.querySelector('#stream-secondary-controls').children).map(x => x.id || x.className)"
    ) == [
        "stream-interpretation-host", "http-suggestions",
        "table-filters-toggle-btn", "table-columns-toggle-btn", "ps-my-view-actions",
    ]
    heights = page.evaluate("""() => [
      '#stream-interpretation-host summary', '#http-suggestions-select',
      '#table-filters-toggle-btn', '#table-columns-toggle-btn',
      '#table-save-view-btn', '#table-reset-btn'
    ].map(selector => document.querySelector(selector).getBoundingClientRect().height)""")
    assert all(31.5 <= height <= 32.5 for height in heights)
    assert page.locator("#table-filter-panel").is_hidden()
    assert page.locator("#table-columns-panel").is_hidden()
    page.locator("#stream-grid .tabulator-row").first.click()
    detail = page.locator(".ps-stream-record-detail")
    assert detail.is_visible()
    assert "method" in detail.inner_text() and "/item/123" in detail.inner_text()
    page.locator("#http-suggestions-select").focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.select_option("#http-suggestions-select", "1")
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.getData('active').length === 2"
    )
    assert page.locator("#table-mode-table-btn").get_attribute("aria-pressed") == "true"
    assert page.locator("#table-filters-toggle-btn").inner_text() == "Filters · 2"
    assert page.locator("#table-filter-panel").is_visible()
    assert "2 matching current filters" in page.locator(".ps-stream-feed-status").inner_text()
    page.click("#table-save-view-btn")
    assert (
        page.get_by_label("Caption", exact=True)
        .input_value()
        .startswith("Newest up to 512")
    )
    page.get_by_label("Name", exact=True).fill("My errors")
    page.get_by_role("dialog").get_by_role(
        "button", name="Save view", exact=True
    ).click()
    page.wait_for_function("PLOTSRV.core.viewSpec.read().items.length === 1")
    saved = page.evaluate("PLOTSRV.core.viewSpec.read().items[0]")
    assert saved["spec"]["sourceId"] == "test:layout"
    assert "secret" not in str(saved)


def test_stream_interpretation_can_be_overridden_and_returned_to_auto(page):
    mount(page, [event(timestamp="2026-09-17T09:38:52Z"), event(status=503)])
    profile_fields = page.evaluate("PLOTSRV.state.httpProfile.fields")
    assert page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getColumns().filter(c => c.isVisible()).map(c => c.getField())"
    ) == [
        profile_fields["time"], profile_fields["method"],
        profile_fields["path"], profile_fields["status"],
    ]

    page.locator(".ps-stream-interpretation summary").click()
    page.evaluate(
        "document.querySelector('.ps-stream-interpretation').dataset.liveProbe = 'stable'"
    )
    update = payload([
        event(timestamp="2026-09-17T09:38:52Z"),
        event(status=503),
        event(path="/new-live-record"),
    ])
    page.evaluate("data => {responseData=data; return PLOTSRV.core.loadStream();}", update)
    assert page.locator(".ps-stream-interpretation__menu").get_attribute("open") == ""
    assert (
        page.locator(".ps-stream-interpretation").get_attribute("data-live-probe")
        == "stable"
    )
    page.get_by_role("menuitemradio", name="Default stream").click()
    page.wait_for_function("PLOTSRV.state.streamInterpretationOverride === 'default'")
    assert "Chosen as" in page.locator(".ps-stream-interpretation").inner_text()
    assert page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getColumns().filter(c => c.isVisible()).map(c => c.getField())"
    ) == ["timestamp", "method"]
    assert page.evaluate("responseData.records[0].data.path") == "/item/123?token=secret"

    page.locator(".ps-stream-interpretation summary").click()
    page.get_by_role("menuitemradio", name="Return to auto", exact=False).click()
    page.wait_for_function("PLOTSRV.state.streamInterpretationOverride == null")
    assert "Detected as" in page.locator(".ps-stream-interpretation").inner_text()
    assert page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getColumns().filter(c => c.isVisible()).map(c => c.getField())"
    ) == [
        profile_fields["time"], profile_fields["method"],
        profile_fields["path"], profile_fields["status"],
    ]


@pytest.mark.parametrize("recipe", [2, 3, 4, 5, 6, 7])
def test_every_plot_recipe_uses_real_shared_renderer(page, recipe):
    mount(
        page,
        [
            event(
                path=f"/item/{i}?private=yes",
                status=[200, 404, 503][i % 3],
                duration_ms=i + 0.5,
            )
            for i in range(40)
        ],
    )
    page.select_option("#http-suggestions-select", str(recipe))
    if recipe != 7:
        page.wait_for_function(
            "PLOTSRV.state.tablePlotLastResult && PLOTSRV.state.tablePlotLastResult.ok"
        )
        assert page.locator(".ps-table-plot__svg").count() == 1
    if recipe == 2:
        assert "Other" in page.locator("#table-plot-output").inner_text()
        assert "4xx client error" in page.locator("#table-plot-output").inner_text()
    if recipe == 3:
        assert page.evaluate("PLOTSRV.state.tablePlotLastResult.plottedCount") == 40
        assert (
            "UTC buckets [start, end)"
            in page.locator("#table-plot-output").inner_text()
        )
    assert "private" not in page.locator("#stream-grid").inner_text()


def test_no_suggestion_mobile_and_schema_loss_pauses_without_switching(page):
    page.set_viewport_size({"width": 390, "height": 844})
    mount(page, [{"message": "unknown"}])
    assert page.locator(".ps-stream-interpretation").count() == 0
    assert page.locator("#http-suggestions-select").is_disabled()
    assert "is-available" not in page.locator("#http-suggestions").get_attribute("class")
    assert page.locator("#http-suggestions-scope").count() == 0
    first = payload([event(duration_ms=5)])
    first["reset_required"] = True
    page.evaluate(
        "data => {responseData=data; return PLOTSRV.core.loadStream();}", first
    )
    page.select_option("#http-suggestions-select", "5")
    page.wait_for_function(
        "PLOTSRV.state.tablePlotLastResult && PLOTSRV.state.tablePlotLastResult.ok"
    )
    changed = payload([{"message": "no request schema"}])
    changed["reset_required"] = True
    page.evaluate(
        "data => {responseData=data; return PLOTSRV.core.loadStream();}", changed
    )
    assert page.evaluate("PLOTSRV.state.myViewBlocked")
    assert page.locator(".ps-table-plot__svg").count() == 0
    page.click("#table-reset-btn")
    assert not page.evaluate("PLOTSRV.state.myViewBlocked")
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 1
    )


def test_incremental_projection_expiry_removes_old_eligibility(page):
    mount(page, [event(), event(status=500)])
    page.select_option("#http-suggestions-select", "0")
    update = payload([event(), event(status=500), event(status=404)])
    update["http_profile"]["first_sequence"] = 2
    update["records"] = update["records"][-1:]
    page.evaluate(
        "data => {responseData=data; return PLOTSRV.core.loadStream();}", update
    )
    page.wait_for_function(
        "PLOTSRV.state.tabulatorInstance.getData('active').length === 2"
    )
    page.click("#table-reset-btn")
    assert (
        page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == 3
    )


def test_initial_stream_mount_collapses_remembered_filter_and_column_panels(page):
    page.evaluate("""() => {
      PLOTSRV.state.tableUiState.filtersOpen = true;
      PLOTSRV.state.tableUiState.columnsOpen = true;
      document.querySelector('#table-filter-panel').hidden = false;
      document.querySelector('#table-columns-panel').hidden = false;
    }""")
    mount(page, [{"message": "fresh stream"}])

    assert page.locator("#table-filter-panel").is_hidden()
    assert page.locator("#table-columns-panel").is_hidden()
    assert page.locator("#table-filters-toggle-btn").get_attribute("aria-expanded") == "false"
    assert page.locator("#table-columns-toggle-btn").get_attribute("aria-expanded") == "false"


@pytest.mark.parametrize(
    "records,expected_fields,expected_text",
    [
        ([{"timestamp": "2026-09-17T09:38:52Z", "level": "INFO", "message": "Worker started"}],
         ["timestamp", "level", "message"], "Worker started"),
        ([{"time": "2026-09-17T09:38:52Z", "component": "billing", "msg": "Invoice queued", "context": {"id": 7}}],
         ["time", "component", "msg"], "Invoice queued"),
        ([{"event": {"publisher_observed_at": "2026-09-17T09:38:52Z"},
           "raw": {"text": "WARN Retry 2/5 for upstream request"}}],
         ["event", "raw"], "Retry 2/5 for upstream request"),
        ([{"opaque": {"phase": "unknown", "value": 7}, "log_schema_version": 9}],
         ["opaque"], '"phase":"unknown"'),
    ],
)
def test_neutral_feed_selects_readable_fields_and_falls_back_conservatively(
    page, records, expected_fields, expected_text
):
    mount(page, records)

    visible = page.evaluate(
        "PLOTSRV.state.tabulatorInstance.getColumns().filter(c => c.isVisible()).map(c => c.getField())"
    )
    assert visible == expected_fields
    assert expected_text in page.locator("#stream-grid").inner_text()
    assert page.locator("#http-suggestions-select").input_value() == ""
    assert page.evaluate("PLOTSRV.state.tabulatorInstance.getData('active').length") == len(records)


def test_buckets_boundaries_negative_time_large_span_and_invalid_values(page):
    result = page.evaluate("""() => {
      const rows = [-1,0,999,1000,39999].map(t=>({t:new Date(t).toISOString(),s:'2xx success'}));
      rows.push({t:'bad',s:'2xx success'}, {t:null,s:'2xx success'});
      return PLOTSRV.core.bucketTimeCounts(rows,{xField:'t',seriesField:'s'});
    }""")
    assert result["width"] == 2000
    assert sum(p["y"] for p in result["points"]) == 5
    assert sorted((p["x"], p["y"]) for p in result["points"]) == [
        (-2000, 1),
        (0, 3),
        (38000, 1),
    ]
    assert result["missing"] == result["invalid"] == 1
    result = page.evaluate(
        """() => PLOTSRV.core.bucketTimeCounts([{t:'0001-01-01T00:00:00Z'},{t:'9999-12-31T00:00:00Z'}],{xField:'t'})"""
    )
    assert len(result["points"]) <= 40
    assert sum(p["y"] for p in result["points"]) == 2


def test_low_mark_limit_and_series_overflow_refuse_without_sampling(page):
    result = page.evaluate("""() => {
      const c=PLOTSRV.core;
      c.TABLE_PLOT_LIMITS.maxPoints=1;
      const rows=[{t:'2026-01-01T00:00:00Z'},{t:'2026-01-01T00:00:01Z'}];
      const result=c.renderTablePlot({container:document.getElementById('table-plot-output'), type:'time-count', rows, xField:'t', xKind:'datetime'});
      const overflow=c.bucketTimeCounts(Array.from({length:9},(_,i)=>({t:'2026-01-01T00:00:00Z',s:'series'+i})),{xField:'t',seriesField:'s'});
      return {result,overflow};
    }""")
    assert result["result"]["reason"] == "point_limit"
    assert result["overflow"]["overflow"]
    assert "no counts were dropped" in page.locator("#table-plot-output").inner_text()


def test_default_status_colours_labels_and_desktop_controls_fit(page):
    mount(page, [event(status=200), event(status=503)])
    page.select_option("#http-suggestions-select", "3")
    page.wait_for_function(
        "PLOTSRV.state.tablePlotLastResult && PLOTSRV.state.tablePlotLastResult.ok"
    )
    assert page.locator(".ps-table-plot__point").evaluate_all(
        "els => els.map(e => e.getAttribute('fill'))"
    ) == ["#15803d", "#b91c1c"]
    assert (
        "__plotsrv_http_"
        not in page.locator("#stream-grid .tabulator-header").inner_text()
    )
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    assert page.evaluate("PLOTSRV.core.tableFieldLabel('constructor')") == "constructor"
    assert page.evaluate("PLOTSRV.core.tableFieldLabel('__proto__')") == "__proto__"
