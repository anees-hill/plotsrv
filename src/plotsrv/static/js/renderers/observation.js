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
    caption.textContent = "Fields / structure, observed distributions and compatible scalar history share these controls. Save a customised presentation to My views on this browser.";
    save.closest(".ps-table-shell").prepend(caption);
  };
})();
