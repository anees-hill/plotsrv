/* Optional server-generated presentations of the existing stream source. */
(function () {
  "use strict";
  const { core, state, config } = window.PLOTSRV;
  const derived = new WeakMap();
  let profile = null,
    rawColumns = [],
    opening = false,
    selectedName = null;

  function supportsHttpInterpretation() {
    const fields = profile && profile.fields;
    return !!fields && ["time", "method", "path", "status"].every(role => fields[role]);
  }

  function interpretationModel() {
    const available = supportsHttpInterpretation();
    const manual = available && state.streamInterpretationOverride === "default";
    return {
      available: available,
      mode: manual ? "default" : "auto",
      manual: manual,
      label: manual ? "Default stream" : "HTTP access log",
    };
  }

  function closeInterpretationMenu(details) {
    if (details) details.open = false;
  }

  core.mountStreamInterpretationControl = function (target) {
    if (!target) return;
    const model = interpretationModel();
    const existing = target.querySelector(":scope > .ps-stream-interpretation");
    if (!model.available) {
      if (existing) existing.remove();
      return;
    }
    if (existing && existing.dataset.mode === model.mode) return;

    const wrapper = document.createElement("span");
    wrapper.className = "ps-stream-interpretation";
    wrapper.dataset.mode = model.mode;
    const prefix = document.createElement("span");
    prefix.className = "ps-stream-interpretation__prefix";
    prefix.textContent = model.manual ? "Chosen as" : "Detected as";
    const details = document.createElement("details");
    details.className = "ps-stream-interpretation__menu";
    const summary = document.createElement("summary");
    summary.setAttribute("aria-label", "Stream interpretation: " + model.label);
    summary.innerHTML = model.manual
      ? '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 5h12M6 12h12M6 19h12"></path></svg>'
      : '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8"></circle><path d="M4 12h16M12 4a13 13 0 0 1 0 16M12 4a13 13 0 0 0 0 16"></path></svg>';
    const current = document.createElement("span");
    current.textContent = model.label;
    const chevron = document.createElement("span");
    chevron.className = "ps-stream-interpretation__chevron";
    chevron.setAttribute("aria-hidden", "true");
    summary.append(current, chevron);
    details.appendChild(summary);
    details.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !details.open) return;
      details.open = false;
      summary.focus();
    });
    details.addEventListener("toggle", function () {
      if (!details.open) return;
      window.setTimeout(function () {
        document.addEventListener("pointerdown", function closeOnOutsideClick(event) {
          if (!details.contains(event.target)) details.open = false;
        }, {once: true});
      }, 0);
    });

    const list = document.createElement("span");
    list.className = "ps-stream-interpretation__options";
    list.setAttribute("role", "menu");
    const choices = [
      {mode: "auto", label: model.manual ? "Return to auto — HTTP access log" : "Auto — HTTP access log"},
      {mode: "default", label: "Default stream"},
    ];
    for (const choice of choices) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ps-stream-interpretation__option";
      button.dataset.mode = choice.mode;
      button.setAttribute("role", "menuitemradio");
      button.setAttribute("aria-checked", String(choice.mode === model.mode));
      const label = document.createElement("span");
      label.textContent = choice.label;
      const check = document.createElement("span");
      check.className = "ps-stream-interpretation__check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = choice.mode === model.mode ? "✓" : "";
      button.append(label, check);
      button.addEventListener("click", async function () {
        closeInterpretationMenu(details);
        if (choice.mode === model.mode) return;
        if (typeof core.applyStreamInterpretation === "function") {
          await core.applyStreamInterpretation(choice.mode);
        }
      });
      list.appendChild(button);
    }
    details.appendChild(list);
    wrapper.append(prefix, details);
    if (existing) existing.replaceWith(wrapper);
    else target.appendChild(wrapper);
  };

  core.getStreamInterpretation = interpretationModel;
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
      const filters = document.getElementById("table-filters-toggle-btn");
      if (filters) filters.before(area);
      else save.parentElement.before(area);
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
      select.replaceChildren(new Option(
        recipes.length ? "✦ Suggested views " + recipes.length : "Suggested views",
        ""
      ));
      select.options[0].disabled = true;
      const group = document.createElement("optgroup");
      group.label = "Based on HTTP access log";
      recipes.forEach((recipe, index) =>
        group.appendChild(new Option(recipe.name, String(index))),
      );
      if (recipes.length) select.appendChild(group);
      select.dataset.signature = signature;
    }
    area.classList.toggle("is-available", recipes.length > 0);
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
    note.title = message;
  };
})();
