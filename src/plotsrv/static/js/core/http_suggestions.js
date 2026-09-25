/* Optional server-generated presentations of the existing stream source. */
(function () {
  "use strict";
  const { core, state } = window.PLOTSRV;
  const derived = new WeakMap();
  let profile = null,
    rawColumns = [],
    opening = false,
    selectedName = null;

  function supportsInterpretation() {
    const fields = profile && profile.fields;
    return !!fields && (profile.label
      ? ["time", "level", "logger", "message"].every(role => fields[role])
      : ["time", "method", "path", "status"].every(role => fields[role]));
  }

  function profileLabel() {
    return (profile && profile.label) || "HTTP access log";
  }

  function interpretationModel() {
    const available = supportsInterpretation();
    const manual = available && state.streamInterpretationOverride === "default";
    return {
      available: available,
      mode: manual ? "default" : "auto",
      manual: manual,
      label: manual ? "Default stream" : profileLabel(),
    };
  }

  function closeInterpretationMenu(details) {
    if (details) details.open = false;
  }

  core.mountStreamInterpretationControl = function (target) {
    if (!target) return;
    const host = document.getElementById("stream-interpretation-host") || target;
    const model = interpretationModel();
    const existing = host.querySelector(":scope > .ps-stream-interpretation");
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
      {mode: "auto", label: (model.manual ? "Return to auto — " : "Auto — ") + profileLabel()},
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
    else host.appendChild(wrapper);
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
    if (errorMessage && typeof core.setStatusMessage === "function") {
      core.setStatusMessage(errorMessage);
    }
  }
  core.clearHttpSuggestionSelection = function () {
    selectedName = null;
    if (document.getElementById("http-suggestions")) core.mountHttpSuggestions();
  };
  core.prepareHttpSuggestions = function (data) {
    rawColumns = data.columns.slice();
    const http = data.http_profile && data.http_profile.version === 1 &&
      data.http_profile.recipes.length ? data.http_profile : null;
    const log = data.log_profile && data.log_profile.version === 1 &&
      data.log_profile.recipes.length ? data.log_profile : null;
    profile = http || log || (data.http_profile && data.http_profile.version === 1
      ? data.http_profile : null);
    state.httpProfile = profile;
    const projectionKey = profile === log ? "log_projection" : "http_projection";
    const fields = Object.values((profile && profile.fields) || {});
    const allowed = new Set(fields);
    data.columns = rawColumns.concat(fields);
    for (const record of data.records) {
      const projection = record[projectionKey];
      if (!projection || !fields.length) continue;
      const row = Object.assign(Object.create(null), record.data),
        keys = [];
      for (const [role, key] of Object.entries(profile.fields)) {
        if (
          Object.prototype.hasOwnProperty.call(projection, role) &&
          !Object.prototype.hasOwnProperty.call(row, key)
        ) {
          row[key] = projection[role];
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
      const topbar = save.closest(".ps-table-topbar");
      topbar?.classList.add("ps-http-topbar");
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
      area.appendChild(select);
      const filters = document.getElementById("table-filters-toggle-btn");
      const columns = document.getElementById("table-columns-toggle-btn");
      const actions = save.closest(".ps-my-view-actions");
      const row = document.createElement("div");
      row.id = "stream-secondary-controls";
      row.className = "ps-stream-secondary-controls";
      const interpretation = document.createElement("span");
      interpretation.id = "stream-interpretation-host";
      interpretation.className = "ps-stream-interpretation-host";
      row.append(interpretation, area);
      if (filters) row.appendChild(filters);
      if (columns) row.appendChild(columns);
      if (actions) row.appendChild(actions);
      topbar?.appendChild(row);
    }
    const recipes = (profile && profile.recipes) || [];
    const select = area.querySelector("select");
    const signature = JSON.stringify([profileLabel(), ...recipes.map((r) => r.name)]);
    // Keep keyboard focus/open native menus stable across ordinary appends.
    if (select.dataset.signature !== signature) {
      select.replaceChildren(new Option(
        recipes.length ? "✦ Suggested views " + recipes.length : "Suggested views",
        ""
      ));
      select.options[0].disabled = true;
      const group = document.createElement("optgroup");
      group.label = "Based on " + profileLabel();
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
    select.removeAttribute("title");
  };
})();
