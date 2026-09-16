/* Bounded observation evidence on the normal table/plot surface. */
(function () {
  "use strict";
  const { core, state, renderers } = window.PLOTSRV;
  renderers.initObservation = function (root) {
    const surface = root.querySelector('[data-plotsrv-observation="1"]');
    if (!surface) return;
    const payload = surface.querySelector('[data-observation-data="1"]');
    if (!payload || payload.textContent.length > 192 * 1024) return;
    let data;
    try { data = JSON.parse(payload.textContent); } catch (_) { return; }
    if (!Array.isArray(data.rows) || data.rows.length > 256 || !Array.isArray(data.columns) || data.columns.length > 32) return;
    state.observationProfile = data;
    const fieldTypes = {surface:"text", field:"text", evidence:"text", value:"text", bucket:"text", received_at:"datetime", missing_fraction:"number", missing:"number", count:"number", inspected:"number", not_inspected:"number"};
    data.columns.filter(field => field.startsWith("metric_") || field.startsWith("evidence_")).forEach(field => { fieldTypes[field] = "number"; });
    core.initializeEmbeddedTableExplorer({grid: surface.querySelector('[data-observation-grid="1"]'), data, fieldTypes, plotCapabilities:{sources:["table"]}});

    const tabs = Array.from(surface.querySelectorAll("[data-observation-tab]"));
    function activateTab(name, options) {
      const selected = tabs.find(tab => tab.dataset.observationTab === name) || tabs[0];
      if (!selected) return;
      tabs.forEach(function (tab) {
        const active = tab === selected;
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
        const panel = surface.querySelector("#" + tab.getAttribute("aria-controls"));
        if (panel) panel.hidden = !active;
      });
      if (name === "evidence" && state.tabulatorInstance && state.tabulatorInstance.redraw) {
        window.requestAnimationFrame(() => state.tabulatorInstance.redraw(true));
      }
      if (options && options.focus) selected.focus();
    }
    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", () => activateTab(tab.dataset.observationTab));
      tab.addEventListener("keydown", function (event) {
        let target = null;
        if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") target = 0;
        if (event.key === "End") target = tabs.length - 1;
        if (target === null) return;
        event.preventDefault();
        activateTab(tabs[target].dataset.observationTab, {focus:true});
      });
    });
    surface.querySelectorAll("[data-observation-tab-target]").forEach(button => {
      button.addEventListener("click", () => activateTab(button.dataset.observationTabTarget, {focus:true}));
    });
    surface.querySelectorAll("[data-observation-field]").forEach(button => {
      button.addEventListener("click", function () {
        activateTab("fields", {focus:true});
        const name = button.dataset.observationField;
        const row = Array.from(surface.querySelectorAll("[data-observation-field-row]"))
          .find(candidate => candidate.dataset.observationFieldRow === name && !candidate.closest("[hidden]"));
        if (!row) return;
        row.classList.add("is-highlighted");
        row.focus({preventScroll:true});
        row.scrollIntoView({block:"center", behavior:"smooth"});
        window.setTimeout(() => row.classList.remove("is-highlighted"), 1800);
      });
    });

    const historyAction = surface.querySelector("[data-observation-history]");
    const historyTarget = document.getElementById("compare-enter");
    if (state.observationHistoryObserver) state.observationHistoryObserver.disconnect();
    state.observationHistoryObserver = null;
    function syncHistoryAction() {
      if (!historyAction) return;
      historyAction.hidden = !historyTarget || historyTarget.hidden || historyTarget.disabled;
    }
    if (historyAction && historyTarget) {
      historyAction.addEventListener("click", () => historyTarget.click());
      state.observationHistoryObserver = new MutationObserver(syncHistoryAction);
      state.observationHistoryObserver.observe(historyTarget, {attributes:true, attributeFilter:["hidden", "disabled"]});
    }
    syncHistoryAction();
    if (new URL(window.location.href).searchParams.has("my_view")) activateTab("evidence");

    const save = document.getElementById("table-save-view-btn");
    if (!save) return;
    const area = document.createElement("span");
    area.className = "ps-observation-suggestions";
    const select = document.createElement("select");
    select.className = "ps-table-select";
    select.setAttribute("aria-label", "Suggested observation views");
    select.append(new Option("Suggested views", ""));
    data.recipes.forEach((recipe, index) => select.append(new Option(recipe.name, String(index))));
    select.addEventListener("change", async function () {
      if (select.value === "") return;
      const recipe = data.recipes[Number(select.value)];
      select.value = "";
      if (!recipe) return;
      select.disabled = true;
      try { await core.applyViewSpec(recipe); }
      catch (_) {
        if (typeof core.setStatusMessage === "function") core.setStatusMessage("This suggested view could not be opened.");
      }
      finally { select.disabled = false; }
    });
    area.append(select);
    save.parentElement.before(area);
    const caption = document.createElement("p");
    caption.className = "note ps-observation-scope";
    caption.textContent = "Explore the captured fields, observed distributions and recent compatible values. You can save a useful presentation to My views in this browser.";
    save.closest(".ps-table-shell").prepend(caption);
  };
})();
