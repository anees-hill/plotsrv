/* Optional server-generated presentations of the existing stream source. */
(function () {
  "use strict";
  const { core, state, config } = window.PLOTSRV;
  const derived = new WeakMap();
  let profile = null,
    rawColumns = [],
    opening = false,
    selectedName = null;
  core.tableFieldLabel = function (field) {
    const labels = (state.observationProfile && state.observationProfile.labels) || (state.httpProfile && state.httpProfile.labels) || {};
    return Object.prototype.hasOwnProperty.call(labels, field)
      ? labels[field]
      : field;
  };
  async function open(spec, suggestionName = null) {
    if (opening) return;
    opening = true;
    core.mountHttpSuggestions();
    let errorMessage = null;
    try {
      await core.applyViewSpec(spec);
      selectedName = suggestionName;
    } catch (error) {
      errorMessage = "Presentation unavailable: " + error.message;
    } finally {
      opening = false;
      core.mountHttpSuggestions();
    }
    if (errorMessage)
      document.getElementById("http-suggestions-scope").textContent =
        errorMessage;
  }
  core.clearHttpSuggestionSelection = function () {
    selectedName = null;
    if (document.getElementById("http-suggestions")) core.mountHttpSuggestions();
  };
  core.prepareHttpSuggestions = function (data) {
    rawColumns = data.columns.slice();
    profile =
      data.http_profile && data.http_profile.version === 1
        ? data.http_profile
        : null;
    state.httpProfile = profile;
    const fields = Object.values((profile && profile.fields) || {});
    const allowed = new Set(fields);
    data.columns = rawColumns.concat(fields);
    for (const record of data.records) {
      if (!record.http_projection || !fields.length) continue;
      const row = Object.assign(Object.create(null), record.data),
        keys = [];
      for (const [role, key] of Object.entries(profile.fields)) {
        if (
          Object.prototype.hasOwnProperty.call(record.http_projection, role) &&
          !Object.prototype.hasOwnProperty.call(row, key)
        ) {
          row[key] = record.http_projection[role];
          keys.push(key);
        }
      }
      derived.set(row, keys);
      record.data = row;
    }
    // Only previously generated cells are removed; source keys remain untouched.
    core.expireHttpProjection = function (row, sequence) {
      let changed = false;
      for (const key of derived.get(row) || []) {
        if (
          (!allowed.has(key) || sequence < profile.first_sequence) &&
          Object.prototype.hasOwnProperty.call(row, key)
        ) {
          delete row[key];
          changed = true;
        }
      }
      return changed;
    };
    core.mountHttpSuggestions();
  };
  core.mountHttpSuggestions = function () {
    const save = document.getElementById("table-save-view-btn");
    if (!save) return;
    let area = document.getElementById("http-suggestions");
    if (!area) {
      save.closest(".ps-table-topbar")?.classList.add("ps-http-topbar");
      area = document.createElement("span");
      area.id = "http-suggestions";
      area.className = "ps-http-suggestions";
      const select = document.createElement("select");
      select.id = "http-suggestions-select";
      select.className = "ps-table-select";
      select.setAttribute("aria-label", "Suggested views");
      select.addEventListener("change", async function () {
        if (select.value === "") return;
        const chosen = ((profile && profile.recipes) || [])[
          Number(select.value)
        ];
        if (chosen) await open(chosen, chosen.name);
      });
      const raw = document.createElement("button");
      raw.type = "button";
      raw.className = "ps-btn";
      raw.id = "http-raw-view";
      raw.textContent = "Raw stream";
      raw.addEventListener("click", async function () {
        const spec = {
          version: 1,
          sourceId: config.activeViewId,
          name: "Raw stream",
          caption:
            "Original accepted records, including unknown text and tracebacks.",
          presentation: {
            search: "",
            filters: [],
            sort: [],
            group: "",
            columns: [],
            hidden: Object.values((profile && profile.fields) || {}),
            mode: "table",
            plot: { type: "bar", source: "table" },
          },
          requirements: { fields: [], plotFields: [], plotSource: "table" },
        };
        await open(spec);
      });
      area.append(select, raw);
      save.parentElement.before(area);
      const note = document.createElement("p");
      note.id = "http-suggestions-scope";
      note.className = "ps-http-scope";
      save.closest(".ps-table-toolbar")?.append(note);
      if (!note.parentElement) area.parentElement.after(note);
    }
    const recipes = (profile && profile.recipes) || [];
    const select = area.querySelector("select");
    const signature = JSON.stringify(recipes.map((r) => r.name));
    // Keep keyboard focus/open native menus stable across ordinary appends.
    if (select.dataset.signature !== signature) {
      select.replaceChildren(new Option("Suggested views", ""));
      select.options[0].disabled = true;
      recipes.forEach((recipe, index) =>
        select.add(new Option(recipe.name, String(index))),
      );
      select.dataset.signature = signature;
    }
    // This is the chosen starting presentation, even after manual edits.
    // Match by name because available recipes can change order as data arrives.
    if (!opening) {
      const selected = recipes.findIndex(recipe => recipe.name === selectedName);
      const value = selected < 0 ? "" : String(selected);
      if (select.value !== value) select.value = value;
    }
    select.disabled = opening || !recipes.length;
    area.querySelector("button").disabled = opening;
    select.title = recipes.length
      ? "Choose a starting presentation; its name stays selected when you customise the settings"
      : (profile && profile.unavailable) || "No HTTP suggestions available";
    const message = profile
      ? recipes.length
        ? profile.scope +
          " Endpoint activity shares one plot; filter an endpoint to focus. Time buckets use half-open UTC intervals."
        : profile.unavailable
      : "No HTTP suggestions available from this server.";
    const note = document.getElementById("http-suggestions-scope");
    if (note.textContent !== message) note.textContent = message;
  };
})();
