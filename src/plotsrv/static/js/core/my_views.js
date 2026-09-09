(function () {
  "use strict";
  const { core, state, config } = window.PLOTSRV;
  const contract = core.viewSpec;
  if (new URL(window.location.href).searchParams.has("my_view"))
    state.myViewBlocked = true;
  let remountSpec = null,
    blockedSpec = null,
    selectedSpec = null;
  let active = null,
    baseline = null,
    lastSchema = null,
    applying = false,
    frame = null,
    requested = false;
  function schema() {
    return {
      fields: Object.assign({}, state.tableFieldTypes),
      summary: Object.assign({}, state.tablePlotSummaryFieldTypes),
      sources: (state.tablePlotCapabilities || { sources: ["table"] }).sources,
    };
  }
  function capture(name, caption, requirements) {
    const p = Object.assign(
      core.extractTablePresentation(),
      core.extractPlotPresentation(),
    );
    const current = requirements || schema();
    const used = new Set([
      ...p.columns,
      ...p.hidden,
      ...p.sort.map((s) => s.field),
      ...p.filters.map((f) => f.field),
    ]);
    if (p.group) used.add(p.group);
    return contract.validate({
      version: 1,
      sourceId: config.activeViewId,
      name: name == null ? "Untitled" : name,
      caption: caption || "",
      presentation: p,
      requirements: {
        fields: [...used].map((name) => ({
          name,
          type: current.fields[name] || "unknown",
        })),
        plotFields: [
          ...new Set(
            contract.plotFields.map((key) => p.plot[key]).filter(Boolean),
          ),
        ].map((name) => ({
          name,
          type:
            (p.plot.source === "summary" ? current.summary : current.fields)[
              name
            ] || "unknown",
        })),
        plotSource: p.plot.source,
      },
    });
  }
  function meaningful(spec) {
    const p = JSON.parse(JSON.stringify(spec.presentation));
    // Column schema facts and inactive plot auto-selection are not user edits.
    if (p.mode === "table") p.plot = null;
    p.hidden.sort();
    p.filters.sort((a, b) =>
      JSON.stringify(a).localeCompare(JSON.stringify(b)),
    );
    return JSON.stringify(p);
  }
  function notice(message, repair) {
    const box = document.getElementById("my-view-notice");
    if (!box) return;
    box.replaceChildren();
    box.hidden = !message;
    if (!message) return;
    const copy = document.createElement("span");
    copy.textContent = message;
    box.appendChild(copy);
    if (repair) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ps-btn";
      button.textContent = "Repair presentation";
      button.addEventListener("click", function () {
        if (
          !window.confirm(
            "Apply compatible settings? Unavailable filters may be removed and more rows may be shown. The saved view will not be changed.",
          )
        )
          return;
        active = null;
        blockedSpec = selectedSpec = null;
        state.myViewBlocked = false;
        clearSelection();
        apply(repair.spec).then(() =>
          notice(
            "Compatible settings applied. Review filters and plot fields, then save as a new view. " +
              repair.notes.join(" "),
          ),
        );
      });
      box.appendChild(button);
    }
  }
  function clearSelection() {
    const url = new URL(window.location.href);
    url.searchParams.delete("my_view");
    window.history.replaceState(null, "", url);
  }
  function refresh() {
    frame = null;
    const button = document.getElementById("table-save-view-btn");
    if (!button || !baseline || applying) return;
    try {
      button.disabled =
        state.myViewBlocked || meaningful(capture()) === meaningful(baseline);
      button.textContent = "Save view";
      button.title = button.disabled
        ? "Change table or plot settings to save a presentation"
        : "Save presentation settings on this browser";
    } catch (error) {
      button.disabled = true;
      button.title = error.message;
    }
  }
  core.presentationChanged = function () {
    if (applying || frame !== null) return;
    frame = window.requestAnimationFrame(refresh);
  };
  async function apply(spec) {
    applying = true;
    const owner = state.tabulatorInstance;
    try {
      await core.applyTablePresentation(spec.presentation);
      if (state.tabulatorInstance === owner)
        core.applyPlotPresentation(spec.presentation);
    } catch (error) {
      if (state.tabulatorInstance === owner) throw error;
    } finally {
      applying = false;
      core.presentationChanged();
      if (remountSpec) core.mountPersonalViews();
    }
  }
  async function present(spec, item) {
    if (spec.sourceId !== config.activeViewId) {
      state.myViewBlocked = true;
      notice(
        "This saved presentation belongs to a different source. Open it from My views.",
      );
      return;
    }
    const result = contract.compatible(spec, schema());
    active = item;
    selectedSpec = spec;
    if (item) baseline = item.spec;
    if (result.unsafe.length) {
      blockedSpec = spec;
      state.myViewBlocked = true;
      await apply(result.spec);
      notice(
        "“" + spec.name + "” is paused. " + result.unsafe.join(" "),
        result,
      );
      return;
    }
    blockedSpec = null;
    state.myViewBlocked = false;
    await apply(result.spec);
    notice(
      (item ? "My view: " : "Presentation: ") +
        spec.name +
        (spec.caption ? " — " + spec.caption : "") +
        ". " +
        result.notes.join(" "),
    );
  }
  function select(item) {
    return present(item.spec, item);
  }
  core.applyViewSpec = function (spec) {
    requested = true;
    clearSelection();
    return present(spec, null);
  };
  core.checkPersonalViewSchema = function () {
    if (!selectedSpec || !lastSchema) return;
    const currentSchema = schema();
    if (JSON.stringify(currentSchema) === JSON.stringify(lastSchema)) return;
    try {
      const working =
        remountSpec ||
        blockedSpec ||
        capture(selectedSpec.name, selectedSpec.caption, lastSchema);
      const result = contract.compatible(working, currentSchema);
      if (result.unsafe.length) {
        blockedSpec = working;
        state.myViewBlocked = true;
        notice(
          "“" + selectedSpec.name + "” is paused. " + result.unsafe.join(" "),
          result,
        );
      } else if (result.notes.length)
        notice(
          (active ? "My view: " : "Presentation: ") +
            selectedSpec.name +
            ". " +
            result.notes.join(" "),
        );
    } catch (error) {
      state.myViewBlocked = true;
      notice(error.message);
    }
  };
  function saveDialog() {
    const opener = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.className = "ps-my-view-dialog";
    dialog.setAttribute("aria-labelledby", "my-view-dialog-title");
    const form = document.createElement("form");
    const title = document.createElement("h2");
    title.id = "my-view-dialog-title";
    title.textContent = active
      ? "Save presentation changes"
      : "Add to My views";
    form.appendChild(title);
    const explanation = document.createElement("p");
    explanation.textContent =
      "This view is saved only in your browser and is not shared with other dashboard users or sent to the server. Anyone using this browser profile can see it. It saves presentation settings for the source’s latest data. It does not save data, a historical snapshot or a stream session. Clearing browser storage removes these settings.";
    form.appendChild(explanation);
    function field(labelText, value, maximum, required) {
      const label = document.createElement("label");
      label.textContent = labelText;
      const input = document.createElement("input");
      input.name = labelText.toLowerCase();
      input.value = value;
      input.maxLength = maximum;
      input.required = required;
      label.appendChild(input);
      form.appendChild(label);
      return input;
    }
    const name = field("Name", active ? active.spec.name : "", 80, true);
    const caption = field(
      "Caption",
      active ? active.spec.caption : "",
      256,
      false,
    );
    const errorBox = document.createElement("p");
    errorBox.setAttribute("role", "alert");
    form.appendChild(errorBox);
    function close() {
      dialog.close();
      dialog.remove();
      if (opener && opener.isConnected) opener.focus();
    }
    async function save(update) {
      if (form.dataset.saving || !form.reportValidity()) return;
      form.dataset.saving = "1";
      try {
        if (state.myViewBlocked)
          throw new Error(
            "Repair the incompatible presentation before saving.",
          );
        const spec = capture(name.value.trim(), caption.value.trim());
        const item = {
          id: update
            ? active.id
            : window.crypto.randomUUID
              ? window.crypto.randomUUID()
              : Date.now().toString(36) + Math.random().toString(36).slice(2),
          spec,
        };
        await contract.change(item, false, update ? active : undefined);
        active = item;
        selectedSpec = spec;
        baseline = spec;
        requested = true;
        const url = new URL(window.location.href);
        url.searchParams.set("my_view", item.id);
        window.history.replaceState(null, "", url);
        close();
        notice("My view: " + spec.name + ". Saved on this browser.");
        refresh();
      } catch (error) {
        errorBox.textContent = error.message;
      } finally {
        delete form.dataset.saving;
      }
    }
    const buttons = document.createElement("div");
    buttons.className = "ps-my-view-dialog__actions";
    function button(label, action) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ps-btn";
      b.textContent = label;
      b.addEventListener("click", action);
      buttons.appendChild(b);
    }
    button("Cancel", close);
    if (active) button("Save as new", () => save(false));
    button(active ? "Update" : "Save view", () => save(!!active));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      save(!!active);
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close();
    });
    form.appendChild(buttons);
    dialog.appendChild(form);
    document.body.appendChild(dialog);
    dialog.showModal();
    name.focus();
  }
  core.capturePersonalBeforeRemount = function () {
    if (!baseline || !state.tabulatorInstance) return;
    try {
      remountSpec =
        blockedSpec ||
        capture(
          selectedSpec ? selectedSpec.name : "Untitled",
          selectedSpec ? selectedSpec.caption : "",
          lastSchema,
        );
    } catch (error) {
      notice(error.message);
    }
  };
  core.mountPersonalViews = function () {
    const unavailable = document.getElementById("my-view-unavailable");
    if (unavailable) unavailable.remove();
    const table = state.tabulatorInstance,
      button = document.getElementById("table-save-view-btn");
    if (!table || !button || table.initialized === false) return;
    if (!button.dataset.personalBound) {
      button.dataset.personalBound = "1";
      button.addEventListener("click", saveDialog);
    }
    if (!table._personalBound && table.on) {
      table._personalBound = true;
      ["dataSorted", "columnMoved", "columnVisibilityChanged"].forEach(
        (event) => table.on(event, core.presentationChanged),
      );
    }
    try {
      if (!baseline) baseline = capture();
    } catch (error) {
      notice(error.message);
      return;
    }
    lastSchema = schema();
    if (remountSpec && !applying) {
      const pending = remountSpec;
      remountSpec = null;
      const result = contract.compatible(pending, lastSchema);
      blockedSpec = result.unsafe.length ? pending : null;
      state.myViewBlocked = !!blockedSpec;
      apply(result.spec)
        .then(function () {
          if (result.unsafe.length)
            notice(
              "“" + pending.name + "” is paused. " + result.unsafe.join(" "),
              result,
            );
        })
        .catch((error) => {
          state.myViewBlocked = true;
          notice(error.message);
        });
    }
    if (!requested) {
      requested = true;
      const id = new URL(window.location.href).searchParams.get("my_view");
      const loaded = contract.read();
      const item = loaded.items.find((value) => value.id === id);
      if (item)
        select(item).catch((error) => {
          state.myViewBlocked = true;
          notice(error.message);
        });
      else if (id || loaded.error) {
        state.myViewBlocked = false;
        notice(
          loaded.error ||
            "This saved view is missing on this browser. Showing the ordinary source.",
        );
        apply(baseline).catch((error) => notice(error.message));
      }
    }
    refresh();
  };
  core.resetPersonalView = function () {
    if (active && !state.myViewBlocked) {
      select(active).catch((error) => notice(error.message));
      return true;
    }
    active = null;
    blockedSpec = remountSpec = selectedSpec = null;
    state.myViewBlocked = false;
    requested = true;
    clearSelection();
    notice("");
    if (core.resetPlotPresentation) core.resetPlotPresentation();
    core.presentationChanged();
  };
  core.personalViewUrl = function (item) {
    const url = new URL(window.location.href);
    url.search = "";
    url.hash = "";
    url.searchParams.set("view", item.spec.sourceId);
    url.searchParams.set("my_view", item.id);
    return url.href;
  };
  core.deletePersonalView = async function (item) {
    if (
      !window.confirm(
        "Delete “" +
          item.spec.name +
          "”? This deletes only the saved configuration on this browser. Source data is not deleted.",
      )
    )
      return false;
    try {
      await contract.change(item, true, item);
      if (active && active.id === item.id) {
        active = null;
        selectedSpec = null;
        clearSelection();
        notice("Saved configuration deleted; current working settings remain.");
        core.presentationChanged();
      }
      return true;
    } catch (error) {
      window.alert(error.message);
      return false;
    }
  };
  window.addEventListener("storage", (event) => {
    if (event.key !== null && event.key !== contract.namespace()) return;
    window.dispatchEvent(new Event("plotsrv-my-views-changed"));
    if (active)
      notice(
        "My views changed in another tab. Your working presentation is unchanged; reopen the saved view before updating it.",
      );
  });
  core.checkPersonalViewSurface = function () {
    const id = new URL(window.location.href).searchParams.get("my_view");
    if (!id || state.tabulatorInstance) return;
    let box = document.getElementById("my-view-unavailable");
    if (!box) {
      box = document.createElement("p");
      box.id = "my-view-unavailable";
      box.setAttribute("role", "status");
      const header = document.getElementById("site-header");
      if (header) header.after(box);
      else document.body.prepend(box);
    }
    box.textContent =
      "This saved presentation cannot be applied: the source has no adjustable table or plot surface. The saved configuration is unchanged; open My views to manage it.";
  };
  core.captureViewSpec = capture;
  core.applyPersonalView = select;
})();
