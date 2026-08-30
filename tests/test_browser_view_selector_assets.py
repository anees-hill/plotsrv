from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


_SOURCE = (
    Path(__file__).parents[1]
    / "src"
    / "plotsrv"
    / "static"
    / "js"
    / "core"
    / "view_selector.js"
)


def test_view_selector_source_keeps_navigation_explicit_and_local_lists_safe() -> None:
    source = _SOURCE.read_text(encoding="utf-8")
    storage = (
        _SOURCE.parent / "storage.js"
    ).read_text(encoding="utf-8")
    controls = (
        Path(__file__).parents[1] / "src" / "plotsrv" / "static" / "css" / "controls.css"
    ).read_text(encoding="utf-8")

    assert "const MAX_RECENT_VIEWS = 4" in source
    assert (
        'window.location.href = "/?view=" + encodeURIComponent(viewId)' in source
    )
    assert "requestAnimationFrame(render)" in source
    assert 'event.key === "Escape"' in source
    assert 'event.key === "ArrowDown"' in source
    assert "event.composedPath()" in source
    assert "event.stopPropagation()" in source
    assert 'const modes = [["grouped", "Grouped"], ["az", "A–Z"]]' in source
    assert '"ps-viewselect__group ps-viewselect__group--featured"' in source
    assert 'appendGroup(fragment, "Pinned views"' in source
    assert 'event.target.closest("[data-pin-view]")' in source
    assert "core.togglePinnedView" in source
    assert 'viewSelectorPinned: "plotsrv:v1:view_selector_pinned"' in storage
    assert 'viewSelectorRecentVisible: "plotsrv:v1:view_selector_recent_visible"' in storage
    assert "document.cookie" not in source
    assert ".ps-viewselect__pin--active" in controls
    assert ".ps-viewselect__group-action" in controls
    assert ".ps-viewselect__item--compact" in controls
    assert 'event.target.closest("[data-view-recent-toggle]")' in source
    assert "core.resolveCompactViews" in source
    assert "core.updateViewSelectorCatalogue" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_view_selector_catalogue_search_order_features_and_mode_persistence() -> None:
    script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const values = new Map();
const localStorage = {
  getItem: (key) => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
};
const context = {
  localStorage,
  window: {
    PLOTSRV: {core: {}, renderers: {}, state: {}, config: {activeViewId: "ops:zulu"}},
  },
};
vm.runInNewContext(source, context, {filename: "view_selector.js"});
const core = context.window.PLOTSRV.core;
const views = [
  {view_id: "ops:zulu", label: "Zulu 10", section: "Operations", kind: "table", icon_key: "table"},
  {view_id: "reports:alpha", label: "alpha", section: "Reports", kind: "artifact", icon_key: "json"},
  {view_id: "ops:zulu-2", label: "Zulu 2", section: "Operations", kind: "plot", icon_key: "plot"},
];
const sorted = core.sortViewsAlphabetically(views).map((view) => view.view_id).join(",");
if (sorted !== "reports:alpha,ops:zulu-2,ops:zulu") {
  throw new Error("unexpected A-Z order: " + sorted);
}
const byMetadata = core.filterViewCatalogue(views, "reports json");
if (byMetadata.length !== 1 || byMetadata[0].view_id !== "reports:alpha") {
  throw new Error("search did not include section and renderer metadata");
}
const features = core.resolveFeaturedViews(views, [
  {view_id: "missing", title: "Missing"},
  {view_id: "ops:zulu", title: "Featured Zulu", caption: "Safe <caption>"},
  {view_id: "ops:zulu", title: "Duplicate"},
]);
if (features.length !== 1 || features[0].title !== "Featured Zulu") {
  throw new Error("featured references were not reconciled with the catalogue");
}
const compact = core.resolveCompactViews(views, [
  "reports:alpha",
  {view: "ops:zulu-2", title: "Small plot"},
  {view: "ops:zulu-2", title: "Duplicate"},
  {view: "missing"},
]);
if (compact.length !== 2 || compact[0].title !== "alpha" || compact[1].title !== "Small plot") {
  throw new Error("compact references were not reconciled with the catalogue");
}
if (!core.loadRecentVisibility()) {
  throw new Error("Recent should be visible by default");
}
core.saveRecentVisibility(false);
if (core.loadRecentVisibility()) {
  throw new Error("hidden Recent preference did not persist");
}
core.saveRecentVisibility(true);
if (!core.loadRecentVisibility()) {
  throw new Error("shown Recent preference did not persist");
}
if (core.initialViewSelectorMode(true) !== "grouped") {
  throw new Error("Grouped was not the default when featured views exist");
}
let pinned = core.togglePinnedView("reports:alpha", views);
if (pinned.join(",") !== "reports:alpha" || core.loadPinnedViews(views).join(",") !== "reports:alpha") {
  throw new Error("pin preference was not persisted");
}
pinned = core.togglePinnedView("ops:zulu", views);
if (pinned.join(",") !== "ops:zulu,reports:alpha") {
  throw new Error("most recently pinned view was not placed first");
}
pinned = core.togglePinnedView("reports:alpha", views);
if (pinned.join(",") !== "ops:zulu") {
  throw new Error("unpin did not remove the view");
}
localStorage.setItem("plotsrv:v1:view_selector_pinned", JSON.stringify(["missing", "ops:zulu"]));
if (core.loadPinnedViews(views).join(",") !== "ops:zulu") {
  throw new Error("stale pinned view IDs were not removed");
}
core.saveViewSelectorMode("az");
if (core.initialViewSelectorMode(true) !== "az" || core.initialViewSelectorMode(false) !== "az") {
  throw new Error("browse mode preference did not persist");
}
const large = Array.from({length: 750}, (_, index) => ({
  view_id: "bulk:" + index,
  label: "View " + index,
  section: "Batch-" + (index % 10),
  kind: index % 2 ? "plot" : "table",
  icon_key: index % 2 ? "plot" : "table",
}));
if (core.filterViewCatalogue(large, "batch-7 table").length !== 0) {
  throw new Error("multi-token filtering did not require every token");
}
if (core.filterViewCatalogue(large, "batch-7 plot").length !== 75) {
  throw new Error("large-catalogue metadata filtering returned the wrong count");
}
'''

    subprocess.run(
        ["node", "-e", script, str(_SOURCE)],
        check=True,
        capture_output=True,
        text=True,
    )
